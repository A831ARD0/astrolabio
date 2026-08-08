"""
Proyectos: un grupo ordenado de transformaciones, con secciones.

Es lo que en el editor de carga de Qlik son las secciones de un script. El problema
que resuelve no es de potencia sino de volumen: dieciocho transformaciones sueltas
más un flujo que las ordena es correcto pieza por pieza e inmanejable en conjunto —
la lista de la izquierda no dice qué va con qué, y para probar una hay que ir a otra
pantalla. Con cuarenta sucursales eso deja de escalar.

**Un proyecto es un flujo restringido a transformaciones**, no un objeto nuevo con
motor propio. Comparte la tabla `flujo` y el ejecutor de `app/flujos.py`, y por eso
hereda gratis lo que ya está probado: reintentos, cancelación entre pasos,
reanudación por identidad, historial paso a paso y los avisos por correo. Un segundo
motor «igual pero para proyectos» acabaría siendo el que se queda atrás.

Consecuencias visibles, y las tres se querían:

- Un proyecto tiene horario propio, sale en la pantalla de tareas y se detiene con el
  mismo botón que cualquier otra cosa que esté corriendo.
- Un flujo puede llamar a un proyecto como paso: el maestro trae las cuarenta
  sucursales y luego llama al proyecto que las transforma.
- Lo que ya existe no cambia. Una transformación sin proyecto sigue funcionando y
  sigue apareciendo donde aparecía.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auditoria import registrar
from app.dependencias import SesionDep, exigir_rol
from app.flujos import _nombre_de, revisar_pasos, secciones_tomadas
from app.materializar import ruta_datos_dataset
from app.modelos_db import (
    Flujo, Rol, Transformacion as TransformacionDB, Usuario, iso,
)

router = APIRouter(prefix="/api/proyectos", tags=["proyectos"])


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class Crear(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None


class Editar(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None
    #: Los ids de las transformaciones, EN ORDEN. Es la lista de secciones: el
    #: orden que se ve en la pantalla es el orden en que corren.
    secciones: list[int] | None = None


class Seccion(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    orden: int
    intermedia: bool
    filas: int
    ultima_ejecucion: str | None
    ultimo_estado: str | None
    tiene_datos: bool


class Salida(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    secciones: list[Seccion]
    cron: str | None
    zona_horaria: str
    programacion_activa: bool
    ultima_ejecucion: str | None
    ultimo_estado: str | None
    ultimo_mensaje: str | None
    #: Si la última corrida fue un tramo, desde qué sección. Hace falta decirlo: dos
    #: secciones en verde de dieciocho se leen como «el proyecto está al día», que es
    #: justo la pantalla con la que se decide sobre un número que no se recalculó.
    ultimo_tramo_desde: int | None
    #: Las secciones que el proyecto lista pero que ya no existen. Se dicen en vez
    #: de filtrarse en silencio: una sección que desaparece del panel sin
    #: explicación se busca durante media hora.
    huerfanas: list[int]


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _obtener(sesion: SesionDep, id_: int) -> Flujo:
    p = sesion.get(Flujo, id_)
    if p is None or not p.es_proyecto:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proyecto no encontrado")
    return p


def _tiene_datos(nombre: str) -> bool:
    """Si hay Parquet escrito. Un nombre raro no tumba la lista entera."""
    try:
        return ruta_datos_dataset(nombre) is not None
    except Exception:
        return False


def _salida(sesion: SesionDep, p: Flujo) -> Salida:
    ultima = p.ejecuciones[0] if p.ejecuciones else None
    secciones: list[Seccion] = []
    huerfanas: list[int] = []

    for i, paso in enumerate(p.pasos or [], start=1):
        try:
            id_ = int(paso.get("id"))
        except (TypeError, ValueError):
            continue
        t = sesion.get(TransformacionDB, id_)
        if t is None:
            huerfanas.append(id_)
            continue
        ult = t.ejecuciones[0] if t.ejecuciones else None
        secciones.append(Seccion(
            id=t.id, nombre=t.nombre, descripcion=t.descripcion, orden=i,
            intermedia=bool(t.intermedia), filas=t.filas,
            ultima_ejecucion=iso(t.ultima_ejecucion),
            ultimo_estado=ult.estado.value if ult else None,
            tiene_datos=_tiene_datos(t.nombre),
        ))

    return Salida(
        id=p.id, nombre=p.nombre, descripcion=p.descripcion, secciones=secciones,
        cron=p.cron, zona_horaria=p.zona_horaria,
        programacion_activa=p.programacion_activa,
        ultima_ejecucion=iso(p.ultima_ejecucion),
        ultimo_estado=ultima.estado.value if ultima else None,
        ultimo_mensaje=ultima.mensaje if ultima else None,
        ultimo_tramo_desde=(ultima.detalle or {}).get("desde_paso") if ultima else None,
        huerfanas=huerfanas,
    )


def _pasos_de(sesion: SesionDep, ids: list[int]) -> list[dict]:
    """La lista de ids a pasos de flujo, con el nombre puesto."""
    pasos = [{"tipo": "transformacion", "id": int(i)} for i in ids]
    for paso in pasos:
        paso["nombre"] = _nombre_de(sesion, paso)
    return pasos


def _guardar_pasos(sesion: SesionDep, p: Flujo, ids: list[int]) -> None:
    """Valida y escribe la lista de secciones. Los errores son del usuario."""
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Una sección no puede estar dos veces en el mismo proyecto: solo "
            "duplicaría el trabajo.")
    pasos = _pasos_de(sesion, ids)
    errores = revisar_pasos(sesion, pasos, p.id, es_proyecto=True)
    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": errores})
    p.pasos = pasos


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[Salida])
def listar(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    return [_salida(sesion, p) for p in sesion.scalars(
        select(Flujo).where(Flujo.es_proyecto.is_(True)).order_by(Flujo.nombre))]


@router.get("/sueltas")
def sueltas(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Las transformaciones que no son sección de ningún proyecto.

    Es lo que la pantalla ofrece para meter en uno. No se migran solas a un
    proyecto de una sección cada una: eso convertiría doscientas transformaciones
    en doscientos proyectos y el desorden sería el mismo con otro nombre.
    """
    tomadas = secciones_tomadas(sesion)
    return {"transformaciones": [
        {"id": t.id, "nombre": t.nombre, "filas": t.filas,
         "intermedia": bool(t.intermedia)}
        for t in sesion.scalars(select(TransformacionDB)
                                .order_by(TransformacionDB.nombre))
        if t.id not in tomadas
    ]}


@router.post("", response_model=Salida, status_code=201)
def crear(cuerpo: Crear, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    if sesion.scalar(select(func.count()).select_from(Flujo)
                     .where(Flujo.nombre == cuerpo.nombre)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ya hay un flujo o un proyecto con ese nombre. Comparten el mismo "
            "espacio de nombres porque comparten la ejecución.")
    p = Flujo(nombre=cuerpo.nombre, descripcion=cuerpo.descripcion, pasos=[],
              es_proyecto=True, creado_por=actor.id)
    sesion.add(p)
    sesion.flush()
    registrar(sesion, accion="proyecto_creado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=p.id,
              detalle={"nombre": p.nombre})
    return _salida(sesion, p)


@router.put("/{id_}", response_model=Salida)
def actualizar(id_: int, cuerpo: Editar, sesion: SesionDep,
               actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """Renombra, redescribe y reordena. `secciones` ausente deja el orden como está."""
    p = _obtener(sesion, id_)
    if cuerpo.nombre != p.nombre and sesion.scalar(
            select(func.count()).select_from(Flujo)
            .where(Flujo.nombre == cuerpo.nombre, Flujo.id != p.id)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya hay un flujo o un proyecto con ese nombre.")
    p.nombre = cuerpo.nombre
    p.descripcion = cuerpo.descripcion
    if cuerpo.secciones is not None:
        _guardar_pasos(sesion, p, cuerpo.secciones)
    registrar(sesion, accion="proyecto_actualizado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=p.id,
              detalle={"nombre": p.nombre, "secciones": len(p.pasos or [])})
    return _salida(sesion, p)


@router.post("/{id_}/secciones/{transformacion_id}", response_model=Salida)
def agregar(id_: int, transformacion_id: int, sesion: SesionDep,
            actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """Mete una transformación existente al final del proyecto."""
    p = _obtener(sesion, id_)
    t = sesion.get(TransformacionDB, transformacion_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Esa transformación ya no existe.")

    ids = [int(x["id"]) for x in (p.pasos or []) if x.get("id") is not None]
    if t.id in ids:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"'{t.nombre}' ya es sección de este proyecto.")
    _guardar_pasos(sesion, p, ids + [t.id])
    registrar(sesion, accion="proyecto_seccion_agregada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=p.id,
              detalle={"proyecto": p.nombre, "seccion": t.nombre})
    return _salida(sesion, p)


@router.delete("/{id_}/secciones/{transformacion_id}", response_model=Salida)
def quitar(id_: int, transformacion_id: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Saca la sección del proyecto. **No borra la transformación ni sus datos**: la
    deja suelta. Sacar algo de una carpeta no es tirarlo.
    """
    p = _obtener(sesion, id_)
    ids = [int(x["id"]) for x in (p.pasos or []) if x.get("id") is not None]
    if transformacion_id not in ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Esa sección no es de este proyecto.")
    _guardar_pasos(sesion, p, [i for i in ids if i != transformacion_id])
    registrar(sesion, accion="proyecto_seccion_quitada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=p.id,
              detalle={"proyecto": p.nombre, "transformacion_id": transformacion_id})
    return _salida(sesion, p)


@router.delete("/{id_}", status_code=204)
def borrar(id_: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Borra el proyecto y su horario. Las secciones quedan sueltas, con sus datos.

    Borrar el contenedor no puede llevarse dieciocho resultados que pueden estar
    alimentando un tablero. Para eso hay que borrar cada transformación.
    """
    from app import programador

    p = _obtener(sesion, id_)
    nombre, cuantas = p.nombre, len(p.pasos or [])
    sesion.delete(p)
    sesion.commit()
    programador.quitar_flujo(id_)
    registrar(sesion, accion="proyecto_borrado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="flujo", objeto_id=id_,
              detalle={"nombre": nombre, "secciones_liberadas": cuantas})
