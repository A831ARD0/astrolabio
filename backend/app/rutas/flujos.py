"""
Flujos: qué se carga y qué se recalcula, en orden y a una hora.

Un flujo es la respuesta a "cada día a las 6, trae las ventas y recalcula el
resumen por sucursal". Reúne en un solo sitio lo que antes eran cargas programadas
por separado y transformaciones ejecutadas a mano.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import programador, trabajos
from app.auditoria import registrar
from app.cargas import Actor
from app.dependencias import SesionDep, exigir_rol
from app.flujos import revisar_orden, revisar_pasos, sugerir_orden
from app.modelos_db import EstadoCarga, Flujo, Rol, Usuario, iso

router = APIRouter(prefix="/api/flujos", tags=["flujos"])


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class PasoFlujo(BaseModel):
    tipo: str
    id: int
    nombre: str | None = None


class Guardar(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None
    pasos: list[PasoFlujo] = []
    al_fallar: str = "detener"
    # Cuantas veces se reintenta UN PASO antes de darlo por fallido. Cero por
    # omision: reintentar sin que nadie lo pida esconde un origen que va mal.
    reintentos: int = Field(default=0, ge=0, le=10)
    espera_reintento_seg: int = Field(default=60, ge=0, le=3600)


class Programacion(BaseModel):
    cron: str = Field(description="5 campos: minuto hora dia mes dia_semana")
    zona_horaria: str = "America/Mexico_City"
    activa: bool = True


class Salida(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    pasos: list[dict]
    al_fallar: str
    reintentos: int
    espera_reintento_seg: int
    cron: str | None
    zona_horaria: str
    programacion_activa: bool
    proxima_corrida: str | None
    ultima_ejecucion: str | None
    ultimo_estado: str | None
    # Cuanto tardo y que dijo la ultima corrida. Van en la lista y no solo en el
    # historial porque la pantalla de tareas tiene que responder "como salio"
    # sin abrir cada flujo.
    ultima_ms: int | None
    ultimo_mensaje: str | None
    # "7 de 28" mientras corre. Con veintiocho tablas, saber que sigue viva no
    # basta: hace falta saber por donde va.
    progreso: str | None
    avisos: list[str]


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _salida(sesion: SesionDep, f: Flujo) -> Salida:
    ultima = f.ejecuciones[0] if f.ejecuciones else None
    proxima = programador.proxima_corrida_flujo(f.id)
    return Salida(
        id=f.id, nombre=f.nombre, descripcion=f.descripcion,
        pasos=f.pasos or [], al_fallar=f.al_fallar,
        reintentos=f.reintentos or 0,
        espera_reintento_seg=f.espera_reintento_seg or 0, cron=f.cron,
        zona_horaria=f.zona_horaria, programacion_activa=f.programacion_activa,
        proxima_corrida=proxima.isoformat() if proxima else None,
        ultima_ejecucion=iso(f.ultima_ejecucion),
        ultimo_estado=ultima.estado.value if ultima else None,
        ultima_ms=ultima.ms if ultima else None,
        ultimo_mensaje=ultima.mensaje if ultima else None,
        progreso=_progreso(ultima),
        # Los avisos se recalculan al leer: el orden puede quedar mal por un
        # cambio en otra parte (una transformación que ahora lee de otro dataset),
        # no solo al guardar el flujo.
        avisos=revisar_orden(sesion, f.pasos or []),
    )


def _progreso(ultima) -> str | None:
    """Por que paso va, mientras corre. Fuera de eso no hay nada que decir."""
    if ultima is None or ultima.estado != EstadoCarga.corriendo:
        return None
    d = ultima.detalle or {}
    pasos = d.get("pasos") or []
    total = d.get("total") or len(pasos)
    hechos = sum(1 for p in pasos if p.get("estado") != "corriendo")
    return f"{min(hechos + 1, total)} de {total}" if total else None


def _obtener(sesion: SesionDep, id_: int) -> Flujo:
    f = sesion.get(Flujo, id_)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flujo no encontrado")
    return f


def _validar(sesion: SesionDep, cuerpo: Guardar) -> list[dict]:
    if cuerpo.al_fallar not in ("detener", "continuar"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "al_fallar debe ser 'detener' o 'continuar'")
    pasos = [p.model_dump(mode="json") for p in cuerpo.pasos]
    errores = revisar_pasos(sesion, pasos)
    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": errores})
    # El nombre de cada paso se guarda junto al id para que el historial siga
    # siendo legible aunque después se borre el dataset.
    from app.flujos import _nombre_de

    for p in pasos:
        p["nombre"] = _nombre_de(sesion, p) or p.get("nombre")
    return pasos


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[Salida])
def listar(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    return [_salida(sesion, f)
            for f in sesion.scalars(select(Flujo).order_by(Flujo.nombre))]


@router.get("/disponibles")
def disponibles(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    """Lo que se puede poner como paso: datasets con carga, y transformaciones."""
    from app.modelos_db import Dataset, Transformacion as TransformacionDB

    return {
        "cargas": [
            {"id": d.id, "nombre": d.nombre, "tabla": d.tabla_origen,
             "cron_propio": d.cron}
            for d in sesion.scalars(select(Dataset).order_by(Dataset.nombre))
        ],
        "transformaciones": [
            {"id": t.id, "nombre": t.nombre, "lee_de": t.lee_de or {}}
            for t in sesion.scalars(select(TransformacionDB)
                                    .order_by(TransformacionDB.nombre))
        ],
    }


@router.post("/sugerir-orden")
def sugerir(cuerpo: Guardar, sesion: SesionDep,
            _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Propone el orden correcto a partir del linaje, agregando las cargas que hagan
    falta. Es una propuesta que se revisa, no un cambio: puede haber razones para
    el orden que tenía.
    """
    pasos = [p.model_dump(mode="json") for p in cuerpo.pasos]
    propuesta = sugerir_orden(sesion, pasos)
    return {"pasos": propuesta, "avisos": revisar_orden(sesion, propuesta)}


@router.post("", response_model=Salida, status_code=201)
def crear(cuerpo: Guardar, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    if sesion.scalar(select(func.count()).select_from(Flujo)
                     .where(Flujo.nombre == cuerpo.nombre)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya existe un flujo con ese nombre")
    pasos = _validar(sesion, cuerpo)

    f = Flujo(nombre=cuerpo.nombre, descripcion=cuerpo.descripcion, pasos=pasos,
              al_fallar=cuerpo.al_fallar, reintentos=cuerpo.reintentos,
              espera_reintento_seg=cuerpo.espera_reintento_seg,
              creado_por=actor.id)
    sesion.add(f)
    sesion.flush()
    registrar(sesion, accion="flujo_creado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=f.id,
              detalle={"nombre": f.nombre, "pasos": len(pasos)})
    return _salida(sesion, f)


@router.put("/{id_}", response_model=Salida)
def actualizar(id_: int, cuerpo: Guardar, sesion: SesionDep,
               actor: Usuario = Depends(exigir_rol(Rol.editor))):
    f = _obtener(sesion, id_)
    pasos = _validar(sesion, cuerpo)
    f.nombre = cuerpo.nombre
    f.descripcion = cuerpo.descripcion
    f.pasos = pasos
    f.al_fallar = cuerpo.al_fallar
    f.reintentos = cuerpo.reintentos
    f.espera_reintento_seg = cuerpo.espera_reintento_seg
    registrar(sesion, accion="flujo_actualizado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=f.id,
              detalle={"nombre": f.nombre, "pasos": len(pasos)})
    return _salida(sesion, f)


@router.post("/{id_}/ejecutar", status_code=status.HTTP_202_ACCEPTED)
def ejecutar(id_: int, sesion: SesionDep, a_la_par: bool = False,
             actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Lanza el flujo en segundo plano y contesta enseguida.

    No lo corre dentro de la petición a propósito. Veintiocho tablas por el
    puente tardan minutos: el proxy corta con un 502 aunque el servidor siga
    trabajando, y salirse de la pantalla dejaba sin forma de saber cómo acabó.
    Ahora la corrida se sigue por el historial, igual que las programadas.

    `a_la_par=false` (lo normal) hace cola: el cuello de botella es el origen, y
    cuarenta sucursales sobre el mismo Pervasive no van más rápido por pedírselo
    todo de golpe. `a_la_par=true` arranca ya, y lo decide quien opera.
    """
    f = _obtener(sesion, id_)
    ocupado = trabajos.hay_algo_corriendo()
    try:
        t = trabajos.encolar("flujo", f.id, f.nombre,
                             Actor(id=actor.id, email=actor.email),
                             a_la_par=a_la_par)
    except trabajos.YaEnMarcha as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    registrar(sesion, accion="flujo_lanzado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=f.id,
              detalle={"nombre": f.nombre, "a_la_par": a_la_par})
    return {
        "trabajo_id": t.id,
        "estado": t.estado,
        "pasos": len(f.pasos or []),
        # Qué había corriendo cuando se lanzó: es lo que la pantalla necesita
        # para decir "espera turno detrás de X" sin volver a preguntar.
        "esperando_a": ocupado.nombre if ocupado and not a_la_par else None,
    }


@router.get("/cola")
def cola(_: Usuario = Depends(exigir_rol(Rol.editor))):
    """Qué corre ahora mismo y qué espera turno."""
    return trabajos.estado()


@router.delete("/cola/{trabajo_id}", status_code=204)
def sacar_de_la_cola(trabajo_id: int,
                     _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Saca de la cola algo que todavía no empezó.

    Lo que ya arrancó no se corta: a mitad de una ingesta, cortar deja el destino
    a medias y sin nadie que lo cuente.
    """
    if not trabajos.cancelar(trabajo_id):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ese trabajo ya empezó o ya terminó; no se puede sacar "
                            "de la cola.")


@router.get("/{id_}/historial")
def historial(id_: int, sesion: SesionDep,
              _: Usuario = Depends(exigir_rol(Rol.editor))):
    f = _obtener(sesion, id_)
    return {"ejecuciones": [
        {"id": e.id, "estado": e.estado.value, "disparo": e.origen, "ms": e.ms,
         "mensaje": e.mensaje, "pasos": (e.detalle or {}).get("pasos", []),
         "total": (e.detalle or {}).get("total"),
         "cuando": iso(e.creado_en)}
        for e in f.ejecuciones[:30]
    ]}


@router.put("/{id_}/programacion", response_model=Salida)
def programar(id_: int, cuerpo: Programacion, sesion: SesionDep,
              actor: Usuario = Depends(exigir_rol(Rol.editor))):
    f = _obtener(sesion, id_)
    try:
        programador.validar_cron(cuerpo.cron, cuerpo.zona_horaria)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))

    f.cron = cuerpo.cron
    f.zona_horaria = cuerpo.zona_horaria
    f.programacion_activa = cuerpo.activa
    # Confirmar antes de tocar el programador: su jobstore escribe en la misma
    # base y dos escritores sobre el mismo SQLite se bloquean entre sí.
    sesion.commit()
    programador.aplicar_flujo(f)

    registrar(sesion, accion="flujo_programado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=f.id,
              detalle={"cron": f.cron, "zona": f.zona_horaria,
                       "activa": f.programacion_activa})
    return _salida(sesion, f)


@router.delete("/{id_}/programacion", status_code=204)
def desprogramar(id_: int, sesion: SesionDep,
                 actor: Usuario = Depends(exigir_rol(Rol.editor))):
    f = _obtener(sesion, id_)
    f.cron = None
    f.programacion_activa = False
    sesion.commit()
    programador.quitar_flujo(f.id)
    registrar(sesion, accion="flujo_desprogramado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=f.id,
              detalle={"nombre": f.nombre})


@router.delete("/{id_}", status_code=204)
def borrar(id_: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    f = _obtener(sesion, id_)
    nombre = f.nombre
    sesion.delete(f)
    sesion.commit()
    programador.quitar_flujo(id_)
    registrar(sesion, accion="flujo_borrado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=id_,
              detalle={"nombre": nombre})
