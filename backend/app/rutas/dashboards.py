"""
Dashboards.

Dos decisiones de fondo:

1. **Un dashboard esta anclado a una version concreta del modelo.** No al modelo
   "actual". Si alguien cambia la definicion de una metrica, lo publicado sigue
   diciendo lo que decia; el cambio se adopta al mover el ancla a proposito. Sin
   esto, una cifra certificada puede cambiar sola de un dia para otro.

2. **La definicion se guarda como JSON y no se interpreta aqui.** El backend
   valida la estructura minima (que cada widget diga que metricas y dimensiones
   pide) y nada mas. Los datos NO salen de esta capa: cada widget consulta por
   `/api/modelos/{id}/consultar`, que es el unico camino y el que aplica la
   seguridad por fila. Si un dashboard pudiera traer datos por su cuenta, seria un
   agujero en las politicas.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.auditoria import registrar
from app.dependencias import SesionDep, UsuarioDep, exigir_rol
from app.modelos_db import Dashboard, Rol, Usuario, VersionModelo

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])

TIPOS_WIDGET = ("kpi", "barras", "barras_horizontales", "lineas", "area",
                "pastel", "tabla", "filtro", "texto")


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class Posicion(BaseModel):
    """Rejilla de 12 columnas; la fila mide lo que mida `alto`."""
    x: int = Field(ge=0, le=11)
    y: int = Field(ge=0)
    ancho: int = Field(ge=1, le=12)
    alto: int = Field(ge=1, le=40)


class Widget(BaseModel):
    # extra="allow": opciones propias de cada tipo de widget (colores, formato,
    # orden) sin tener que tocar el backend cada vez que se agrega una.
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=40)
    tipo: Literal[TIPOS_WIDGET]              # type: ignore[valid-type]
    titulo: str = ""
    posicion: Posicion
    dimensiones: list[str] = []              # "entidad.campo"
    metricas: list[str] = []
    filtros: list[dict[str, Any]] = []       # propios de este widget
    rutas_elegidas: dict[str, str] = {}
    limite: int = Field(default=1000, ge=1, le=50_000)


class DefinicionDashboard(BaseModel):
    model_config = ConfigDict(extra="allow")

    widgets: list[Widget] = []
    # Selecciones con las que abre el tablero: {"entidad.campo": [valores]}
    selecciones: dict[str, list[Any]] = {}


class CrearDashboard(BaseModel):
    nombre: str = Field(min_length=1, max_length=160)
    modelo_id: int
    version: int | None = None               # None = la vigente al crearlo
    definicion: DefinicionDashboard = DefinicionDashboard()


class ActualizarDashboard(BaseModel):
    nombre: str | None = None
    definicion: DefinicionDashboard | None = None


class DashboardSalida(BaseModel):
    id: int
    nombre: str
    modelo_id: int
    modelo_nombre: str
    version_modelo: int
    version_vigente_del_modelo: int
    definicion: dict
    publicado: bool
    certificado: bool
    actualizado_en: str


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _version(sesion: SesionDep, modelo_id: int, version: int | None) -> VersionModelo:
    consulta = select(VersionModelo).where(VersionModelo.modelo_id == modelo_id)
    if version is None:
        consulta = consulta.order_by(VersionModelo.version.desc())
    else:
        consulta = consulta.where(VersionModelo.version == version)
    v = sesion.scalar(consulta.limit(1))
    if v is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"El modelo {modelo_id} no tiene "
            + (f"la version {version}" if version else "ninguna version guardada"))
    return v


def _salida(sesion: SesionDep, d: Dashboard) -> DashboardSalida:
    v = sesion.get(VersionModelo, d.version_modelo_id)
    assert v is not None                    # hay clave externa; no puede faltar
    vigente = sesion.scalar(
        select(func.max(VersionModelo.version))
        .where(VersionModelo.modelo_id == v.modelo_id))
    return DashboardSalida(
        id=d.id, nombre=d.nombre, modelo_id=v.modelo_id,
        modelo_nombre=v.modelo.nombre, version_modelo=v.version,
        version_vigente_del_modelo=int(vigente or v.version),
        definicion=d.definicion, publicado=d.publicado,
        certificado=d.certificado,
        actualizado_en=d.actualizado_en.isoformat(),
    )


def _obtener(sesion: SesionDep, dashboard_id: int) -> Dashboard:
    d = sesion.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard no encontrado")
    return d


def _revisar_widgets(definicion: DefinicionDashboard) -> None:
    """
    Lo minimo que hace falta para que un tablero se pueda dibujar. No valida
    contra el modelo: eso lo hace la consulta, que es quien sabe.
    """
    ids = [w.id for w in definicion.widgets]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": [f"ids de widget repetidos: "
                                         f"{', '.join(sorted(repetidos))}"]})
    errores = []
    for w in definicion.widgets:
        if w.tipo in ("kpi", "barras", "barras_horizontales", "lineas", "area",
                      "pastel") and not w.metricas:
            errores.append(f"El widget '{w.titulo or w.id}' ({w.tipo}) necesita "
                           f"al menos una metrica.")
        if w.tipo in ("barras", "barras_horizontales", "lineas", "area",
                      "pastel") and not w.dimensiones:
            errores.append(f"El widget '{w.titulo or w.id}' ({w.tipo}) necesita "
                           f"una dimension por la que desglosar.")
        if w.tipo == "filtro" and len(w.dimensiones) != 1:
            errores.append(f"El filtro '{w.titulo or w.id}' tiene que apuntar a "
                           f"exactamente un campo.")
        if w.tipo == "tabla" and not (w.dimensiones or w.metricas):
            errores.append(f"La tabla '{w.titulo or w.id}' esta vacia.")
    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": errores})


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[DashboardSalida])
def listar(sesion: SesionDep, usuario: UsuarioDep, solo_publicados: bool = False):
    consulta = select(Dashboard).order_by(Dashboard.nombre)
    # Un lector solo ve lo publicado: un borrador a medias no es una cifra que
    # nadie deba usar para decidir.
    if solo_publicados or usuario.rol == Rol.lector:
        consulta = consulta.where(Dashboard.publicado.is_(True))
    return [_salida(sesion, d) for d in sesion.scalars(consulta)]


@router.get("/{dashboard_id}", response_model=DashboardSalida)
def obtener(dashboard_id: int, sesion: SesionDep, usuario: UsuarioDep):
    d = _obtener(sesion, dashboard_id)
    if not d.publicado and usuario.rol == Rol.lector:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard no encontrado")
    return _salida(sesion, d)


@router.post("", response_model=DashboardSalida, status_code=201)
def crear(cuerpo: CrearDashboard, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    _revisar_widgets(cuerpo.definicion)
    v = _version(sesion, cuerpo.modelo_id, cuerpo.version)

    d = Dashboard(nombre=cuerpo.nombre, version_modelo_id=v.id,
                  definicion=cuerpo.definicion.model_dump(mode="json"),
                  creado_por=actor.id)
    sesion.add(d)
    sesion.flush()
    registrar(sesion, accion="dashboard_creado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dashboard", objeto_id=d.id,
              detalle={"nombre": d.nombre, "modelo": v.modelo.nombre,
                       "version_modelo": v.version})
    return _salida(sesion, d)


@router.put("/{dashboard_id}", response_model=DashboardSalida)
def actualizar(dashboard_id: int, cuerpo: ActualizarDashboard, sesion: SesionDep,
               actor: Usuario = Depends(exigir_rol(Rol.editor))):
    d = _obtener(sesion, dashboard_id)
    if cuerpo.definicion is not None:
        _revisar_widgets(cuerpo.definicion)
        d.definicion = cuerpo.definicion.model_dump(mode="json")
    if cuerpo.nombre is not None:
        d.nombre = cuerpo.nombre

    # Editar un tablero certificado le quita el sello: la certificacion dice
    # "esto se reviso", y lo que se reviso ya no es esto.
    perdio_sello = False
    if d.certificado:
        d.certificado = False
        perdio_sello = True

    registrar(sesion, accion="dashboard_actualizado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dashboard", objeto_id=d.id,
              detalle={"widgets": len(d.definicion.get("widgets", [])),
                       "perdio_certificacion": perdio_sello})
    return _salida(sesion, d)


@router.post("/{dashboard_id}/publicar", response_model=DashboardSalida)
def publicar(dashboard_id: int, sesion: SesionDep, publicado: bool = True,
             actor: Usuario = Depends(exigir_rol(Rol.editor))):
    d = _obtener(sesion, dashboard_id)
    d.publicado = publicado
    registrar(sesion, accion="dashboard_publicado" if publicado else "dashboard_retirado",
              usuario_id=actor.id, email=actor.email, objeto_tipo="dashboard",
              objeto_id=d.id, detalle={"nombre": d.nombre})
    return _salida(sesion, d)


@router.post("/{dashboard_id}/certificar", response_model=DashboardSalida)
def certificar(dashboard_id: int, sesion: SesionDep, certificado: bool = True,
               actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Certificar es decir "estas cifras se revisaron y se puede decidir con ellas".
    Solo un administrador, y se pierde al editar.
    """
    d = _obtener(sesion, dashboard_id)
    if certificado and not d.publicado:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "No se puede certificar un tablero sin publicar")
    d.certificado = certificado
    registrar(sesion, accion="dashboard_certificado" if certificado
              else "dashboard_descertificado",
              usuario_id=actor.id, email=actor.email, objeto_tipo="dashboard",
              objeto_id=d.id, detalle={"nombre": d.nombre})
    return _salida(sesion, d)


@router.post("/{dashboard_id}/mover-a-version", response_model=DashboardSalida)
def mover_a_version(dashboard_id: int, sesion: SesionDep, version: int,
                    actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Adopta otra version del modelo. Es un acto explicito a proposito: al cambiar
    el ancla, las cifras del tablero pueden cambiar.
    """
    d = _obtener(sesion, dashboard_id)
    actual = sesion.get(VersionModelo, d.version_modelo_id)
    assert actual is not None
    nueva = _version(sesion, actual.modelo_id, version)
    d.version_modelo_id = nueva.id
    d.certificado = False               # el sello era de las cifras anteriores
    registrar(sesion, accion="dashboard_movido_de_version", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dashboard", objeto_id=d.id,
              detalle={"de": actual.version, "a": nueva.version})
    return _salida(sesion, d)


@router.delete("/{dashboard_id}", status_code=204)
def borrar(dashboard_id: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    d = _obtener(sesion, dashboard_id)
    nombre = d.nombre
    sesion.delete(d)
    registrar(sesion, accion="dashboard_borrado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dashboard", objeto_id=dashboard_id,
              detalle={"nombre": nombre})
