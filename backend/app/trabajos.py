"""
Lo que se lanza a mano corre en segundo plano, y hace cola.

Antes, «Ejecutar ahora» corria dentro de la peticion HTTP. Con un flujo de tres
pasos eso pasa desapercibido; con el de una sucursal de verdad —veintiocho
tablas por el puente de 32 bits— pasan minutos, y entonces se rompe de tres
formas a la vez:

- el proxy corta la conexion y la pantalla dice «Error 502», aunque el servidor
  siga trabajando;
- salirse de la pantalla deja sin forma de saber como acabo;
- dos extracciones lanzadas seguidas se pisan, cada una escribiendo el mismo
  Parquet desde su propio hilo.

Aqui las corridas a mano se registran y las hace un trabajador aparte. La
peticion contesta enseguida —«queda en cola»— y el resultado se sigue por el
historial, igual que si lo hubiera disparado el programador.

Tres reglas, y las tres se pueden defender:

1. **Por defecto, una a la vez.** El cuello de botella es el origen, no el
   servidor: cuarenta sucursales sobre el mismo Pervasive no van mas rapido por
   pedirselo todo de golpe. La cola es FIFO y se ve.

2. **Correr a la par se puede, pero se pide.** Es una decision de quien opera,
   no nuestra, y hay casos legitimos —dos sucursales en dos servidores
   distintos—. Lo que no se hace es decidirlo en silencio.

3. **El mismo flujo dos veces, no.** Eso no es una preferencia: son dos procesos
   escribiendo los mismos archivos. Se rechaza, se corra como se corra.

El registro vive en memoria a proposito. Es el estado de ESTE proceso: si el
servicio se reinicia, no hay nada corriendo, y una cola persistente solo serviria
para resucitar trabajos que ya nadie espera. Lo que si sobrevive es el historial,
que esta en la base.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.cargas import Actor
from app.db import CrearSesion

log = logging.getLogger("astrolabio.trabajos")

#: Cuantos trabajos pueden esperar turno. No es una cola de mensajes: si hay
#: cincuenta encolados, lo que hay es un error de operacion, no un atasco.
MAXIMO_EN_COLA = 100


@dataclass
class Trabajo:
    id: int
    tipo: str                     # 'flujo' | 'carga'
    objeto_id: int
    nombre: str
    actor_id: int | None
    actor_email: str
    a_la_par: bool
    encolado_en: datetime
    #: Lo que distingue una carga de otra del mismo dataset: incremental,
    #: completa, o un rango de fechas. Se pasa tal cual a `ejecutar_carga`.
    opciones: dict = field(default_factory=dict)
    iniciado_en: datetime | None = None
    estado: str = "en_cola"       # en_cola | corriendo
    #: Alguien pidio pararlo. No se corta nada a la fuerza: el ejecutor lo mira
    #: ENTRE pasos y se detiene sin dejar nada a medias. Ver `cancelar`.
    parar: bool = False

    def como_dict(self) -> dict:
        return {
            "id": self.id, "tipo": self.tipo, "objeto_id": self.objeto_id,
            "nombre": self.nombre, "estado": self.estado, "parando": self.parar,
            "a_la_par": self.a_la_par, "quien": self.actor_email,
            "encolado_en": self.encolado_en.isoformat(),
            "iniciado_en": self.iniciado_en.isoformat() if self.iniciado_en else None,
        }


class YaEnMarcha(Exception):
    """El mismo objeto ya esta corriendo o esperando turno."""


@dataclass
class _Registro:
    """Lo que hay ahora mismo. Todo acceso pasa por `candado`."""
    candado: threading.Lock = field(default_factory=threading.Lock)
    pendientes: "queue.Queue[Trabajo]" = field(default_factory=queue.Queue)
    #: id de trabajo -> Trabajo, tanto en cola como corriendo.
    vivos: dict[int, Trabajo] = field(default_factory=dict)
    siguiente_id: int = 1
    trabajador: threading.Thread | None = None


_reg = _Registro()


def _clave(tipo: str, objeto_id: int) -> tuple[str, int]:
    return (tipo, objeto_id)


def _arrancar_trabajador() -> None:
    """El hilo de la cola se crea la primera vez que hace falta, no al importar."""
    if _reg.trabajador is not None and _reg.trabajador.is_alive():
        return
    _reg.trabajador = threading.Thread(target=_atender_cola, name="trabajos",
                                       daemon=True)
    _reg.trabajador.start()


def _atender_cola() -> None:
    while True:
        t = _reg.pendientes.get()
        try:
            # Un trabajo cancelado se saco del registro mientras esperaba: sigue
            # en la cola de Python y se salta aqui.
            if _esta_vivo(t):
                _correr(t)
            else:
                log.info("Trabajo %s cancelado antes de empezar", t.id)
        finally:
            _reg.pendientes.task_done()


def _correr(t: Trabajo) -> None:
    """
    Ejecuta un trabajo con su propia sesion y se traga todo.

    Una excepcion que escape mata el hilo de la cola y deja el sistema sin
    trabajador, en silencio, hasta el siguiente reinicio.
    """
    with _reg.candado:
        t.estado = "corriendo"
        t.iniciado_en = datetime.now(timezone.utc)
    log.info("Trabajo %s: %s '%s' empieza", t.id, t.tipo, t.nombre)
    try:
        with CrearSesion() as sesion:
            if t.tipo == "carga":
                _ejecutar_carga(sesion, t)
            else:
                _ejecutar_flujo(sesion, t)
    except Exception:
        log.exception("Trabajo %s (%s '%s') murio", t.id, t.tipo, t.nombre)
    finally:
        with _reg.candado:
            _reg.vivos.pop(t.id, None)
        log.info("Trabajo %s: %s '%s' termina", t.id, t.tipo, t.nombre)


def _ejecutar_flujo(sesion, t: Trabajo) -> None:
    # Importes aqui dentro: `app.flujos` tira de media aplicacion y este modulo
    # lo importan las rutas al arrancar.
    from app.flujos import ErrorFlujo
    from app.flujos import ejecutar as ejecutar_flujo
    from app.modelos_db import Flujo

    f = sesion.get(Flujo, t.objeto_id)
    if f is None:
        log.warning("El flujo %s ya no existe", t.objeto_id)
        return
    actor = Actor(id=t.actor_id, email=t.actor_email)
    try:
        # `parar` se consulta entre pasos. Se pasa como funcion y no como valor
        # porque el valor cambia mientras el flujo corre: es justo el punto.
        r = ejecutar_flujo(sesion, f, actor, parar=lambda: t.parar)
        sesion.commit()
        log.info("Flujo '%s' completo: %d pasos en %s ms",
                 f.nombre, len(r["pasos"]), r["ms"])
    except ErrorFlujo as e:
        # Ya quedo registrado y confirmado dentro de `ejecutar`.
        log.error("Flujo '%s' fallo: %s", f.nombre, e)
    except Exception:
        sesion.rollback()
        raise


def _ejecutar_carga(sesion, t: Trabajo) -> None:
    from app.cargas import ErrorCarga, ejecutar_carga
    from app.modelos_db import Dataset

    ds = sesion.get(Dataset, t.objeto_id)
    if ds is None:
        log.warning("El dataset %s ya no existe", t.objeto_id)
        return
    try:
        r = ejecutar_carga(sesion, ds, Actor(id=t.actor_id, email=t.actor_email),
                           **t.opciones)
        sesion.commit()
        log.info("Carga de '%s' completa: %s filas en %s ms",
                 ds.nombre, r["filas"], r["ms"])
    except ErrorCarga as e:
        # Ya quedo registrada y confirmada dentro de `ejecutar_carga`.
        log.error("Carga de '%s' fallo: %s", ds.nombre, e)
    except Exception:
        sesion.rollback()
        raise


# --------------------------------------------------------------------------- #
# Lo que usan las rutas
# --------------------------------------------------------------------------- #

def encolar(tipo: str, objeto_id: int, nombre: str, actor: Actor,
            a_la_par: bool = False, opciones: dict | None = None) -> Trabajo:
    """
    Registra un trabajo y devuelve su ficha. No espera a que corra.

    `a_la_par` se salta la cola y arranca su propio hilo. Lo decide quien opera:
    ver `YaEnMarcha` para lo que no se negocia.
    """
    with _reg.candado:
        for otro in _reg.vivos.values():
            if _clave(otro.tipo, otro.objeto_id) == _clave(tipo, objeto_id):
                raise YaEnMarcha(
                    f"'{nombre}' ya esta {'corriendo' if otro.estado == 'corriendo' else 'en cola'}. "
                    f"Dos corridas de lo mismo a la vez escriben los mismos archivos.")
        if _reg.pendientes.qsize() >= MAXIMO_EN_COLA:
            raise YaEnMarcha(
                f"Hay {MAXIMO_EN_COLA} trabajos esperando turno; algo va mal. "
                f"Revisa la cola antes de encolar mas.")
        t = Trabajo(id=_reg.siguiente_id, tipo=tipo, objeto_id=objeto_id,
                    nombre=nombre, actor_id=actor.id, actor_email=actor.email,
                    a_la_par=a_la_par, opciones=dict(opciones or {}),
                    encolado_en=datetime.now(timezone.utc))
        _reg.siguiente_id += 1
        _reg.vivos[t.id] = t

    if a_la_par:
        threading.Thread(target=_correr, args=(t,), name=f"trabajo-{t.id}",
                         daemon=True).start()
    else:
        _arrancar_trabajador()
        _reg.pendientes.put(t)
    return t


def estado() -> dict:
    """Que corre y que espera, para la pantalla de tareas."""
    with _reg.candado:
        vivos = sorted(_reg.vivos.values(), key=lambda t: t.id)
    return {
        "corriendo": [t.como_dict() for t in vivos if t.estado == "corriendo"],
        "en_cola": [t.como_dict() for t in vivos if t.estado == "en_cola"],
    }


def hay_algo_corriendo() -> Trabajo | None:
    with _reg.candado:
        for t in sorted(_reg.vivos.values(), key=lambda t: t.id):
            if t.estado == "corriendo":
                return t
    return None


def esperar(segundos: float = 60) -> bool:
    """
    Bloquea hasta que no quede nada en marcha. Devuelve False si se acaba el
    tiempo.

    Existe para las pruebas: sin esto, comprobar el resultado de una corrida
    lanzada en segundo plano es una carrera, y una prueba que a veces pasa es
    peor que una que falla.
    """
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        with _reg.candado:
            if not _reg.vivos:
                return True
        time.sleep(0.02)
    return False


def cancelar(trabajo_id: int) -> str | None:
    """
    Detiene un trabajo. Devuelve que se hizo, o None si ya no habia nada.

    Tres respuestas distintas, porque son tres situaciones distintas:

    - `'sacado'` — estaba esperando turno y ya no va a correr.
    - `'parando'` — un flujo que ya arranco. **No se corta la tabla en curso**:
      se le pide parar y el ejecutor lo mira ENTRE pasos. La tabla que se esta
      trayendo se termina, y los pasos que faltan quedan como cancelados. Cortar
      a media ingesta es lo que deja un destino a medias, y ahi es peor el
      remedio: el borrado del destino ocurre ANTES de escribir, asi que una
      recarga completa interrumpida en el momento justo deja el dataset vacio.
    - `'no_se_puede'` — una carga suelta que ya arranco. No tiene pasos donde
      pararse: o se termina, o se corta a la mitad. Se dice, en vez de fingir.
    """
    with _reg.candado:
        t = _reg.vivos.get(trabajo_id)
        if t is None:
            return None
        if t.estado == "en_cola":
            # Se saca del registro; el trabajador lo salta al sacarlo de la cola
            # porque ya no esta entre los vivos.
            _reg.vivos.pop(trabajo_id, None)
            return "sacado"
        if t.tipo != "flujo":
            return "no_se_puede"
        t.parar = True
        return "parando"


def _esta_vivo(t: Trabajo) -> bool:
    with _reg.candado:
        return t.id in _reg.vivos


def limpiar_interrumpidos() -> int:
    """
    Al arrancar, cierra las ejecuciones que quedaron en 'corriendo'.

    Si el servicio se reinicio a mitad de una carga, ese renglon se queda
    'corriendo' para siempre y la pantalla de tareas miente. Nadie las va a
    terminar: este proceso acaba de nacer.
    """
    from app.modelos_db import CargaEjecucion, EstadoCarga, FlujoEjecucion
    from app.modelos_db import TransformacionEjecucion

    aviso = "Interrumpida: el servicio se reinicio mientras corria."
    total = 0
    with CrearSesion() as sesion:
        for modelo in (FlujoEjecucion, CargaEjecucion, TransformacionEjecucion):
            for e in sesion.query(modelo).filter(
                    modelo.estado == EstadoCarga.corriendo):
                e.estado = EstadoCarga.error
                e.mensaje = aviso
                total += 1
        sesion.commit()
    if total:
        log.warning("%d ejecucion(es) quedaron a medias en el reinicio", total)
    return total
