"""
Flujos: cargar y transformar en cadena.

El ejecutor llama a los MISMOS servicios que los botones —`cargas.ejecutar_carga` y
`transformar.ejecutar`—, así que cada paso deja su propia entrada en su propio
historial además del resumen del flujo. Un paso ejecutado por el flujo y el mismo
paso ejecutado a mano son indistinguibles en el registro salvo por el campo que dice
quién lo disparó, que es justo lo que interesa.

La regla al fallar es **detenerse**. Seguir recalculando una transformación cuando la
carga de la que depende no ocurrió produce un número que parece fresco y no lo es —y
esa es la clase de error que nadie detecta hasta que alguien decide con él.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import avisos
from app.auditoria import registrar
from app.cargas import Actor, ErrorCarga, ejecutar_carga
from app.modelos_db import (
    Dataset, EstadoCarga, Flujo, FlujoEjecucion,
    Transformacion as TransformacionDB,
)
from app.transformar import ErrorEjecucion, definicion_de
from app.transformar import ejecutar as ejecutar_transformacion

log = logging.getLogger("astrolabio.flujos")

TIPOS_PASO = ("carga", "transformacion", "flujo")

#: Cuantos flujos se pueden anidar. No hay razon para bajar mas: con cuarenta
#: sucursales basta un maestro que llame a los cuarenta, y un arbol de cinco
#: niveles ya nadie lo puede seguir. El limite es una red, no un diseno.
PROFUNDIDAD_MAXIMA = 5


class ErrorFlujo(Exception):
    """El flujo no se completó. Ya quedó registrado."""


# --------------------------------------------------------------------------- #
# Validación del orden
# --------------------------------------------------------------------------- #

def alcanzables(sesion: Session, raiz: int) -> set[int]:
    """
    Todos los flujos a los que se llega desde `raiz`, él incluido.

    Sirve para lo único que un flujo dentro de otro puede romper: el ciclo. «A
    llama a B, B llama a A» no da un error visible —da un servidor que se queda
    dando vueltas hasta quedarse sin pila, de madrugada y sin nadie mirando—, así
    que se corta al guardar, que es cuando hay alguien delante a quien decírselo.
    """
    vistos: set[int] = set()
    pila = [raiz]
    while pila:
        actual = pila.pop()
        if actual in vistos:
            continue
        vistos.add(actual)
        f = sesion.get(Flujo, actual)
        if f is None:
            continue
        for p in f.pasos or []:
            if p.get("tipo") == "flujo":
                try:
                    pila.append(int(p["id"]))
                except (TypeError, ValueError):
                    pass
    return vistos


def quien_llama(sesion: Session) -> dict[int, list[str]]:
    """
    Para cada flujo, los flujos que lo tienen como paso.

    La pantalla de tareas decia «a mano» de los treinta y ocho extractores, y era
    falso: los llama el maestro cada noche. Una tarea que corre sola y en la
    pantalla parece manual es justo lo que hace perder el hilo.
    """
    mapa: dict[int, list[str]] = {}
    for f in sesion.scalars(select(Flujo).order_by(Flujo.nombre)):
        for p in f.pasos or []:
            if p.get("tipo") == "flujo":
                try:
                    mapa.setdefault(int(p["id"]), []).append(f.nombre)
                except (TypeError, ValueError):
                    pass
    return mapa


def _profundidad(sesion: Session, flujo_id: int, nivel: int = 0) -> int:
    """Cuántos niveles de flujos cuelgan de este. Asume que no hay ciclos."""
    if nivel >= PROFUNDIDAD_MAXIMA:
        return nivel
    f = sesion.get(Flujo, flujo_id)
    hondo = nivel
    for p in (f.pasos or []) if f else []:
        if p.get("tipo") == "flujo":
            try:
                hondo = max(hondo, _profundidad(sesion, int(p["id"]), nivel + 1))
            except (TypeError, ValueError):
                pass
    return hondo


def revisar_pasos(sesion: Session, pasos: list[dict],
                  flujo_id: int | None = None) -> list[str]:
    """
    Errores que impiden guardar el flujo: pasos mal formados o que apuntan a algo
    que no existe.

    `flujo_id` es el flujo que se está guardando —None si es nuevo—. Hace falta
    para el paso de tipo `flujo`: sin saber quién soy no se puede ver si me estoy
    llamando a mí mismo.
    """
    errores: list[str] = []
    if not pasos:
        return ["El flujo no tiene ningún paso."]

    vistos: set[tuple[str, int]] = set()
    for i, p in enumerate(pasos, start=1):
        tipo = p.get("tipo")
        if tipo not in TIPOS_PASO:
            errores.append(f"Paso {i}: tipo '{tipo}' desconocido.")
            continue
        try:
            id_ = int(p.get("id"))
        except (TypeError, ValueError):
            errores.append(f"Paso {i}: falta el identificador.")
            continue

        clave = (tipo, id_)
        if clave in vistos:
            errores.append(
                f"Paso {i}: repetido. Ejecutar lo mismo dos veces en el mismo "
                f"flujo solo duplica el trabajo.")
        vistos.add(clave)

        if tipo == "carga":
            if sesion.get(Dataset, id_) is None:
                errores.append(f"Paso {i}: el dataset {id_} ya no existe.")
        elif tipo == "flujo":
            sub = sesion.get(Flujo, id_)
            if sub is None:
                errores.append(f"Paso {i}: el flujo {id_} ya no existe.")
            elif flujo_id is not None and id_ == flujo_id:
                errores.append(
                    f"Paso {i}: un flujo no puede llamarse a sí mismo.")
            elif flujo_id is not None and flujo_id in alcanzables(sesion, id_):
                errores.append(
                    f"Paso {i}: '{sub.nombre}' vuelve a este flujo, directa o "
                    f"indirectamente. Eso no tiene final.")
            elif _profundidad(sesion, id_) + 1 > PROFUNDIDAD_MAXIMA:
                errores.append(
                    f"Paso {i}: '{sub.nombre}' anida más de {PROFUNDIDAD_MAXIMA} "
                    f"niveles de flujos. A esa altura ya nadie sabe qué corre.")
        elif sesion.get(TransformacionDB, id_) is None:
            errores.append(f"Paso {i}: la transformación {id_} ya no existe.")
    return errores


def revisar_orden(sesion: Session, pasos: list[dict]) -> list[str]:
    """
    Avisos —no errores— sobre el orden, deducidos del linaje.

    Son avisos y no errores porque hay casos legítimos: una transformación puede
    leer de un dataset que se carga en otro flujo, o de una tabla que no se carga
    nunca. Bloquear eso sería adivinar. Pero el caso de verdad frecuente —el paso
    que recalcula ANTES de cargar lo que lee— sí hay que decirlo.
    """
    avisos: list[str] = []

    # Posición en la que cada nombre queda disponible.
    disponible_en: dict[str, int] = {}
    for i, p in enumerate(pasos):
        for nombre in _produce(sesion, p):
            disponible_en[nombre] = i

    for i, p in enumerate(pasos):
        if p.get("tipo") != "transformacion":
            continue
        t = sesion.get(TransformacionDB, int(p["id"]))
        if t is None:
            continue
        try:
            lee = definicion_de(t)
        except Exception:
            continue

        for o in lee.origenes:
            if o.tipo != "dataset":
                continue                     # las tablas del motor están siempre
            posicion = disponible_en.get(o.referencia)
            if posicion is None:
                avisos.append(
                    f"Paso {i + 1} ({t.nombre}) lee de '{o.referencia}', que este "
                    f"flujo no actualiza. Se usará lo que haya de la última vez.")
            elif posicion > i:
                avisos.append(
                    f"Paso {i + 1} ({t.nombre}) lee de '{o.referencia}', que se "
                    f"actualiza en el paso {posicion + 1}, DESPUÉS. Tal como está, "
                    f"trabajará con los datos anteriores.")
    return avisos


def _nombre_de(sesion: Session, paso: dict) -> str | None:
    try:
        id_ = int(paso.get("id"))
    except (TypeError, ValueError):
        return None
    if paso.get("tipo") == "carga":
        ds = sesion.get(Dataset, id_)
        return ds.nombre if ds else None
    if paso.get("tipo") == "flujo":
        f = sesion.get(Flujo, id_)
        return f.nombre if f else None
    t = sesion.get(TransformacionDB, id_)
    return t.nombre if t else None


def _produce(sesion: Session, paso: dict, nivel: int = 0) -> list[str]:
    """
    Qué queda actualizado después de este paso.

    Para una carga o una transformación es su propio nombre. Para un flujo, todo
    lo que ese flujo actualiza —y lo que actualicen los suyos—: si no, el maestro
    que primero llama a los cuarenta extractores y luego recalcula avisaría de que
    la transformación lee de algo «que este flujo no actualiza», que es falso.
    """
    if paso.get("tipo") != "flujo":
        nombre = _nombre_de(sesion, paso)
        return [nombre] if nombre else []
    if nivel >= PROFUNDIDAD_MAXIMA:
        return []
    try:
        sub = sesion.get(Flujo, int(paso.get("id")))
    except (TypeError, ValueError):
        return []
    if sub is None:
        return []
    return [n for p in sub.pasos or [] for n in _produce(sesion, p, nivel + 1)]


def sugerir_orden(sesion: Session, pasos: list[dict]) -> list[dict]:
    """
    Reordena los pasos para que cada transformación vaya después de lo que lee, y
    agrega las cargas que faltan de los datasets que las transformaciones necesitan.

    Es una propuesta que el usuario revisa, no un cambio automático: puede haber
    razones para el orden que tenía.
    """
    datasets = {d.nombre: d for d in sesion.scalars(select(Dataset))}
    trans = {t.nombre: t for t in sesion.scalars(select(TransformacionDB))}

    # Qué lee cada transformación (solo lo que este proyecto materializa).
    def lee(nombre: str) -> list[str]:
        t = trans.get(nombre)
        if t is None:
            return []
        try:
            return [o.referencia for o in definicion_de(t).origenes
                    if o.tipo == "dataset"]
        except Exception:
            return []

    # Un flujo dentro de otro no se reordena: lo que trae dentro no se puede
    # deducir desde aqui sin abrirlo, y moverlo cambiaria el sentido del maestro.
    # Se deja como esta y se dice por que, en vez de proponer algo peor.
    if any(p.get("tipo") == "flujo" for p in pasos):
        return list(pasos)

    pedidos: list[str] = []
    for p in pasos:
        nombre = _nombre_de(sesion, p)
        if nombre:
            pedidos.append(nombre)

    orden: list[str] = []
    visitando: set[str] = set()

    def colocar(nombre: str) -> None:
        if nombre in orden or nombre in visitando:
            return                            # ya está, o hay un ciclo
        visitando.add(nombre)
        for dependencia in lee(nombre):
            if dependencia in trans or dependencia in datasets:
                colocar(dependencia)
        visitando.discard(nombre)
        if nombre not in orden:
            orden.append(nombre)

    for nombre in pedidos:
        colocar(nombre)

    salida: list[dict] = []
    for nombre in orden:
        if nombre in trans:
            salida.append({"tipo": "transformacion", "id": trans[nombre].id,
                           "nombre": nombre})
        elif nombre in datasets:
            salida.append({"tipo": "carga", "id": datasets[nombre].id,
                           "nombre": nombre})
    return salida


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #

def ejecutar(sesion: Session, flujo: Flujo, actor: Actor,
             _cadena: frozenset[int] = frozenset(),
             _llamado_por: str | None = None) -> dict[str, Any]:
    """
    Corre el flujo entero. Devuelve el resumen; lanza `ErrorFlujo` si algún paso
    falló y la política es detenerse.

    `_cadena` son los flujos que ya están corriendo por encima de este, para que
    un paso de tipo `flujo` no vuelva a uno de ellos. Al guardar ya se comprueba,
    pero entre guardar y correr pueden pasar semanas y dos ediciones; esto es lo
    que impide que un ciclo llegue a la madrugada.
    """
    cadena = frozenset(_cadena) | {flujo.id}
    total = len(flujo.pasos or [])
    # Va en cada version del detalle, no solo en la primera: `_apuntar` lo
    # reescribe entero en cada paso.
    contexto = {"llamado_por": _llamado_por} if _llamado_por else {}
    ejec = FlujoEjecucion(flujo_id=flujo.id, estado=EstadoCarga.corriendo,
                          origen=actor.origen, iniciado_por=actor.id,
                          detalle={"pasos": [], "total": total, **contexto})
    sesion.add(ejec)
    sesion.flush()

    # Como acabo la vez anterior: es lo que distingue "sigue roto" de "ya se
    # arreglo", y solo se puede leer antes de escribir el resultado de esta.
    venia_fallando = sesion.scalar(
        select(FlujoEjecucion.estado)
        .where(FlujoEjecucion.flujo_id == flujo.id, FlujoEjecucion.id < ejec.id,
               FlujoEjecucion.estado != EstadoCarga.corriendo)
        .order_by(FlujoEjecucion.id.desc()).limit(1)
    ) == EstadoCarga.error

    # Confirmar YA, antes del primer paso. Sin esto, la corrida no existe para
    # nadie mas hasta que termina: veintiocho tablas escribiendose en el disco y
    # la pantalla diciendo "todavia no ha corrido". Lo que se ve es lo que esta
    # confirmado.
    sesion.commit()

    t0 = time.perf_counter()
    resultados: list[dict[str, Any]] = []
    fallo: str | None = None

    def _apuntar(en_curso: dict[str, Any] | None = None) -> None:
        """
        Deja el avance en la base y lo confirma.

        Se llama antes y despues de cada paso: antes con el paso marcado como
        'corriendo' —para saber en cual va— y despues con su resultado. Es una
        escritura pequena por paso; al lado de traer una tabla entera no se nota,
        y es la diferencia entre ver avanzar la noche y mirar una pantalla muda.
        """
        ejec.detalle = {"pasos": resultados + ([en_curso] if en_curso else []),
                        "total": total, **contexto}
        sesion.commit()

    # Cuantas veces se vuelve a intentar un paso, y cuanto se espera. Con cuarenta
    # sucursales, que una este apagada a las seis de la manana pasa seguido, y
    # eso a los dos minutos ya no esta. Cero por omision: la primera vez que algo
    # falla hay que verlo.
    reintentos = max(0, int(flujo.reintentos or 0))
    espera = max(0, int(flujo.espera_reintento_seg or 0))

    for i, paso in enumerate(flujo.pasos or [], start=1):
        nombre = paso.get("nombre") or _nombre_de(sesion, paso) or "?"
        inicio = time.perf_counter()
        ultimo_error: Exception | None = None
        salio: dict[str, Any] | None = None

        for intento in range(1, reintentos + 2):
            _apuntar({"paso": i, "tipo": paso.get("tipo"), "nombre": nombre,
                      "estado": "corriendo",
                      **({"intento": intento} if intento > 1 else {})})
            try:
                if paso.get("tipo") == "carga":
                    ds = sesion.get(Dataset, int(paso["id"]))
                    if ds is None:
                        raise ErrorFlujo(f"el dataset {paso['id']} ya no existe")
                    r = ejecutar_carga(sesion, ds, actor)
                    salio = {"paso": i, "tipo": "carga", "nombre": nombre,
                             "estado": "exito", "filas": r["filas"],
                             "modo": r["modo"], "ms": r["ms"]}
                elif paso.get("tipo") == "flujo":
                    # Un flujo dentro de otro: es la forma de encadenar. El
                    # subflujo se ejecuta entero —con SUS reintentos y SU regla
                    # al fallar— y deja su propia entrada en su propio historial,
                    # que es donde se mira cuál de sus pasos falló. Aquí solo
                    # queda el resumen.
                    sub = sesion.get(Flujo, int(paso["id"]))
                    if sub is None:
                        raise ErrorFlujo(f"el flujo {paso['id']} ya no existe")
                    if sub.id in cadena:
                        raise ErrorFlujo(
                            f"'{sub.nombre}' vuelve a un flujo que ya está "
                            f"corriendo; se corta aquí")
                    # El subflujo deja constancia de que no lo lanzo una
                    # persona: lo llamo este flujo. Sin eso, su historial dice
                    # «manual» y no hay forma de reconstruir quien disparo que.
                    de_aqui = Actor(id=actor.id, email=actor.email, origen="flujo")
                    r = ejecutar(sesion, sub, de_aqui, _cadena=cadena,
                                 _llamado_por=flujo.nombre)
                    salio = {"paso": i, "tipo": "flujo", "nombre": nombre,
                             "estado": "exito",
                             "filas": sum(int(p.get("filas") or 0)
                                          for p in r["pasos"]),
                             "sub_pasos": len(r["pasos"]), "ms": r["ms"]}
                else:
                    t = sesion.get(TransformacionDB, int(paso["id"]))
                    if t is None:
                        raise ErrorFlujo(
                            f"la transformación {paso['id']} ya no existe")
                    r = ejecutar_transformacion(sesion, t, actor)
                    salio = {"paso": i, "tipo": "transformacion",
                             "nombre": nombre, "estado": "exito",
                             "filas": r["filas"], "ms": r["ms"]}
                # Un exito al tercer intento NO es lo mismo que un exito: queda
                # anotado, o el origen que va mal se esconde detras del reintento.
                if intento > 1:
                    salio["intentos"] = intento
                break
            except (ErrorCarga, ErrorEjecucion, ErrorFlujo) as e:
                ultimo_error = e
                if intento <= reintentos:
                    log.warning("Flujo '%s' paso %s (%s) fallo en el intento %s "
                                "de %s: %s. Reintenta en %ss",
                                flujo.nombre, i, nombre, intento,
                                reintentos + 1, e, espera)
                    if espera:
                        time.sleep(espera)

        if salio is not None:
            resultados.append(salio)
        else:
            e = ultimo_error
            resultados.append({
                "paso": i, "tipo": paso.get("tipo"), "nombre": nombre,
                "estado": "error", "mensaje": str(e),
                "ms": round((time.perf_counter() - inicio) * 1000, 1),
                **({"intentos": reintentos + 1} if reintentos else {}),
            })
            fallo = (f"paso {i} ({nombre}): {e}"
                     + (f" — tras {reintentos + 1} intentos" if reintentos else ""))
            if flujo.al_fallar == "detener":
                # Los pasos que no se llegaron a intentar se anotan como omitidos:
                # un hueco en el historial se lee como "corrió y no hizo nada".
                for j, restante in enumerate(
                        (flujo.pasos or [])[i:], start=i + 1):
                    resultados.append({
                        "paso": j, "tipo": restante.get("tipo"),
                        "nombre": restante.get("nombre"), "estado": "omitido",
                    })
                _apuntar()
                break
        _apuntar()

    ms = round((time.perf_counter() - t0) * 1000, 1)
    ejec.ms = int(ms)
    ejec.detalle = {"pasos": resultados, "total": total, **contexto}
    ejec.estado = EstadoCarga.error if fallo else EstadoCarga.exito
    ejec.mensaje = fallo
    flujo.ultima_ejecucion = datetime.now(timezone.utc)

    registrar(sesion, accion="flujo_fallido" if fallo else "flujo_ejecutado",
              usuario_id=actor.id, email=actor.email, objeto_tipo="flujo",
              objeto_id=flujo.id,
              detalle={"nombre": flujo.nombre, "disparo": actor.origen,
                       "pasos": len(resultados), "ms": ms, "error": fallo})

    # El aviso del flujo no reemplaza el de cada carga: son dos preguntas
    # distintas —"salio bien la noche" y "cual paso la arruino"— y quien atiende
    # la primera no siempre es quien arregla la segunda. El silencio de la regla
    # es lo que evita que eso se vuelva ruido.
    if fallo:
        avisos.por_flujo_fallido(sesion, flujo, fallo, actor.origen, resultados)
    elif venia_fallando:
        avisos.por_flujo_recuperado(sesion, flujo, len(resultados), actor.origen)

    resumen = {
        "estado": "error" if fallo else "exito",
        "ms": ms, "pasos": resultados, "mensaje": fallo,
    }
    if fallo:
        # Confirmar antes de lanzar: si no, el rollback se lleva el historial del
        # flujo justo cuando más se necesita.
        sesion.commit()
        raise ErrorFlujo(fallo)
    return resumen
