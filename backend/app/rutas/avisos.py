"""
Avisos: a quién se le cuenta cuando algo falla.

La ruta que de verdad importa aquí es `POST /{id}/probar`. Un canal de avisos que
nadie probó no es cobertura: es creer que la hay, y eso es peor que no tener
avisos, porque con avisos uno deja de mirar el historial.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import avisos as srv
from app.auditoria import registrar
from app.dependencias import SesionDep, exigir_rol
from app.modelos_db import AvisoEnviado, Dataset, Flujo, ReglaAviso, Rol, Usuario

router = APIRouter(prefix="/api/avisos", tags=["avisos"])


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class Guardar(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    canal: str = "correo"
    destino: str = ""
    eventos: list[str] = []
    objeto_tipo: str | None = None
    objeto_id: int | None = None
    silencio_minutos: int = 60
    activa: bool = True


class Salida(BaseModel):
    id: int
    nombre: str
    canal: str
    destino: str
    eventos: list[str]
    objeto_tipo: str | None
    objeto_id: int | None
    objeto_nombre: str | None
    silencio_minutos: int
    activa: bool
    # Si el canal puede entregar ahora. Una regla activa sobre un canal sin
    # configurar se ve igual que una que funciona si no se dice.
    canal_listo: bool
    canal_detalle: str
    ultimo_envio: str | None
    ultimo_estado: str | None


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _nombre_objeto(sesion: SesionDep, tipo: str | None, id_: int | None) -> str | None:
    if tipo is None or id_ is None:
        return None
    if tipo == "dataset":
        ds = sesion.get(Dataset, id_)
        return ds.nombre if ds else f"(dataset {id_} borrado)"
    f = sesion.get(Flujo, id_)
    return f.nombre if f else f"(flujo {id_} borrado)"


def _salida(sesion: SesionDep, r: ReglaAviso) -> Salida:
    listo, detalle = srv.canal_listo(r.canal)
    ultimo = r.envios[0] if r.envios else None
    return Salida(
        id=r.id, nombre=r.nombre, canal=r.canal, destino=r.destino,
        eventos=r.eventos or [], objeto_tipo=r.objeto_tipo, objeto_id=r.objeto_id,
        objeto_nombre=_nombre_objeto(sesion, r.objeto_tipo, r.objeto_id),
        silencio_minutos=r.silencio_minutos, activa=r.activa,
        canal_listo=listo, canal_detalle=detalle,
        ultimo_envio=ultimo.creado_en.isoformat() if ultimo else None,
        ultimo_estado=ultimo.estado if ultimo else None,
    )


def _obtener(sesion: SesionDep, id_: int) -> ReglaAviso:
    r = sesion.get(ReglaAviso, id_)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regla de aviso no encontrada")
    return r


def _validar(sesion: SesionDep, cuerpo: Guardar) -> None:
    errores = srv.revisar(cuerpo.canal, cuerpo.destino, cuerpo.eventos,
                          cuerpo.silencio_minutos)
    if cuerpo.objeto_tipo is not None:
        if cuerpo.objeto_tipo not in ("dataset", "flujo"):
            errores.append("El alcance solo puede ser 'dataset', 'flujo' o todo.")
        elif cuerpo.objeto_id is not None:
            nombre = _nombre_objeto(sesion, cuerpo.objeto_tipo, cuerpo.objeto_id)
            if nombre is None or "borrado" in nombre:
                errores.append(
                    f"El {cuerpo.objeto_tipo} {cuerpo.objeto_id} no existe.")
    elif cuerpo.objeto_id is not None:
        errores.append("Hay un id de alcance sin decir de qué tipo es.")

    # Un evento de carga en una regla que solo mira flujos no dispara nunca. Se
    # dice al guardar y no cuando alguien note que no llegan avisos.
    tipos = {e.split("_")[0] for e in cuerpo.eventos}
    if cuerpo.objeto_tipo == "dataset" and "flujo" in tipos:
        errores.append("La regla mira un dataset, pero pide eventos de flujo.")
    if cuerpo.objeto_tipo == "flujo" and "carga" in tipos:
        errores.append("La regla mira un flujo, pero pide eventos de carga.")

    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errores": errores})


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

@router.get("/catalogo")
def catalogo(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    """Qué se puede avisar, por dónde, y sobre qué."""
    return {
        "eventos": [{"clave": k, "etiqueta": v, "requiere": srv.REQUIERE.get(k)}
                    for k, v in srv.EVENTOS.items()],
        "canales": [
            {"clave": c, "listo": srv.canal_listo(c)[0],
             "detalle": srv.canal_listo(c)[1]}
            for c in srv.CANALES
        ],
        "datasets": [{"id": d.id, "nombre": d.nombre}
                     for d in sesion.scalars(select(Dataset).order_by(Dataset.nombre))],
        "flujos": [{"id": f.id, "nombre": f.nombre}
                   for f in sesion.scalars(select(Flujo).order_by(Flujo.nombre))],
    }


@router.get("", response_model=list[Salida])
def listar(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    return [_salida(sesion, r)
            for r in sesion.scalars(select(ReglaAviso).order_by(ReglaAviso.nombre))]


@router.post("", response_model=Salida, status_code=201)
def crear(cuerpo: Guardar, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    if sesion.scalar(select(func.count()).select_from(ReglaAviso)
                     .where(ReglaAviso.nombre == cuerpo.nombre)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya existe una regla de aviso con ese nombre")
    _validar(sesion, cuerpo)
    r = ReglaAviso(**cuerpo.model_dump(), creado_por=actor.id)
    sesion.add(r)
    sesion.flush()
    registrar(sesion, accion="aviso_creado", usuario_id=actor.id, email=actor.email,
              objeto_tipo="regla_aviso", objeto_id=r.id,
              detalle={"nombre": r.nombre, "canal": r.canal,
                       "eventos": r.eventos})
    return _salida(sesion, r)


@router.put("/{id_}", response_model=Salida)
def actualizar(id_: int, cuerpo: Guardar, sesion: SesionDep,
               actor: Usuario = Depends(exigir_rol(Rol.editor))):
    r = _obtener(sesion, id_)
    _validar(sesion, cuerpo)
    for campo, valor in cuerpo.model_dump().items():
        setattr(r, campo, valor)
    registrar(sesion, accion="aviso_actualizado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="regla_aviso", objeto_id=r.id,
              detalle={"nombre": r.nombre, "canal": r.canal, "activa": r.activa})
    return _salida(sesion, r)


@router.post("/{id_}/probar")
def probar(id_: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Manda un aviso de prueba ahora mismo, salteando el silencio y los eventos.

    No devuelve 400 cuando no sale: 200 con `ok: false` y el error del canal tal
    cual. El fallo es el resultado útil de esta ruta —dice qué corregir—, no un
    error de la petición.
    """
    r = _obtener(sesion, id_)
    resultado = srv.probar(sesion, r)
    registrar(sesion, accion="aviso_probado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="regla_aviso", objeto_id=r.id,
              detalle=resultado)
    return resultado


@router.get("/historial")
def historial(sesion: SesionDep, limite: int = Query(default=60, le=300),
              _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Todo intento de aviso, incluidos los silenciados y los que fallaron.

    Los silenciados se ven a propósito: son la prueba de que hubo más fallos de
    los que llegaron al buzón, y sin ellos el silencio parece que perdió avisos.
    """
    filas = sesion.scalars(
        select(AvisoEnviado).order_by(AvisoEnviado.id.desc()).limit(limite)
    )
    nombres = {r.id: r.nombre for r in sesion.scalars(select(ReglaAviso))}
    return {"envios": [
        {"id": e.id, "regla": nombres.get(e.regla_id, f"(regla {e.regla_id})"),
         "evento": e.evento, "objeto_tipo": e.objeto_tipo, "objeto_id": e.objeto_id,
         "asunto": e.asunto, "estado": e.estado, "mensaje": e.mensaje,
         "cuando": e.creado_en.isoformat()}
        for e in filas
    ]}


@router.delete("/{id_}", status_code=204)
def borrar(id_: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    r = _obtener(sesion, id_)
    nombre = r.nombre
    sesion.delete(r)
    registrar(sesion, accion="aviso_borrado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="regla_aviso", objeto_id=id_,
              detalle={"nombre": nombre})
