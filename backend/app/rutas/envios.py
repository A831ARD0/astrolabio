"""
Envios programados de un informe por correo.

Cuelgan de un tablero: `/api/dashboards/{id}/envios`. No son un objeto suelto porque no
significan nada sin su tablero, y verlos juntos —«este tablero le llega a estas cuatro
personas el dia 2»— es lo que hace que alguien se acuerde de quitar a quien ya no esta.

Quien puede: **editor**. Un envio manda datos fuera de la aplicacion a direcciones que
alguien escribe, asi que no es una preferencia de lectura; y el informe se genera con la
sesion de quien lo creo, asi que crearlo es decidir con que permisos se va a mirar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import envios as motor
from app import informe_pdf, programador
from app.auditoria import registrar
from app.avisos import canal_listo, destinatarios as leer_destinatarios
from app.dependencias import SesionDep, UsuarioDep, exigir_rol
from app.modelos_db import Dashboard, EnvioInforme, Rol, Usuario, iso

router = APIRouter(prefix="/api/dashboards", tags=["envios"])


class EnvioEntrada(BaseModel):
    destinatarios: str = Field(min_length=3, max_length=2000)
    hoja: str | None = Field(default=None, max_length=120)
    asunto: str | None = Field(default=None, max_length=200)
    cuerpo: Literal["pdf", "imagen", "ambos"] = "pdf"
    periodo: Literal["guardado", "mes_anterior"] = "mes_anterior"
    # El dia 2 a las 7:00, que es lo que se pidio y el caso normal de un informe
    # mensual: el mes cerrado y un dia de margen para que la carga del 1 haya corrido.
    cron: str = Field(default="0 7 2 * *", max_length=120)
    zona_horaria: str = Field(default="America/Mexico_City", max_length=64)
    activa: bool = False

    @field_validator("destinatarios")
    @classmethod
    def con_algun_destinatario(cls, v: str) -> str:
        if not leer_destinatarios(v):
            raise ValueError("hace falta al menos un correo")
        for c in leer_destinatarios(v):
            if "@" not in c or c.startswith("@") or c.endswith("@"):
                raise ValueError(f"'{c}' no parece un correo")
        return v


class EnvioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dashboard_id: int
    destinatarios: str
    hoja: str | None
    asunto: str | None
    cuerpo: str
    periodo: str
    cron: str | None
    zona_horaria: str
    activa: bool
    ultimo_envio: str | None
    ultimo_error: str | None
    ultimo_ms: int | None
    #: Cuando le toca la proxima. Sale del planificador, no de la base: es lo unico que
    #: distingue «programado» de «guardado y nadie lo va a correr».
    proxima: str | None
    #: Si el correo esta configurado en el servidor, y si no, que falta. Se ensena junto
    #: al envio: uno guardado sobre un servidor de correo sin configurar se ve igual que
    #: uno que funciona, y esa confusion es la que hace que nadie reciba nada.
    correo_listo: bool
    correo_dice: str


def _salida(e: EnvioInforme) -> dict[str, Any]:
    listo, dice = canal_listo("correo")
    proxima = programador.proxima_corrida_envio(e.id)
    return {
        "id": e.id, "dashboard_id": e.dashboard_id, "destinatarios": e.destinatarios,
        "hoja": e.hoja, "asunto": e.asunto, "cuerpo": e.cuerpo, "periodo": e.periodo,
        "cron": e.cron, "zona_horaria": e.zona_horaria, "activa": e.activa,
        "ultimo_envio": iso(e.ultimo_envio), "ultimo_error": e.ultimo_error,
        "ultimo_ms": e.ultimo_ms,
        "proxima": proxima.isoformat() if proxima else None,
        "correo_listo": listo, "correo_dice": dice,
    }


def _tablero(sesion: SesionDep, dashboard_id: int) -> Dashboard:
    d = sesion.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard no encontrado")
    return d


def _envio(sesion: SesionDep, dashboard_id: int, envio_id: int) -> EnvioInforme:
    e = sesion.get(EnvioInforme, envio_id)
    if e is None or e.dashboard_id != dashboard_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Envio no encontrado")
    return e


def _comprobar_periodo(sesion: SesionDep, e: EnvioInforme) -> None:
    """
    Que el periodo se pueda resolver, AL GUARDAR.

    «El mes anterior» necesita una columna marcada como mes en el modelo. Si no la hay,
    esto falla el dia 2 a las siete de la mañana y nadie lo ve hasta que alguien
    pregunta por su informe. Se dice ahora, que hay alguien delante.
    """
    try:
        motor.filtros_del_periodo(sesion, e)
    except motor.EnvioInvalido as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err))


@router.get("/{dashboard_id}/envios", response_model=list[EnvioSalida])
def listar(dashboard_id: int, sesion: SesionDep, usuario: UsuarioDep):
    _tablero(sesion, dashboard_id)
    return [_salida(e) for e in
            sesion.query(EnvioInforme)
            .filter(EnvioInforme.dashboard_id == dashboard_id)
            .order_by(EnvioInforme.id).all()]


@router.post("/{dashboard_id}/envios", response_model=EnvioSalida, status_code=201)
def crear(dashboard_id: int, cuerpo: EnvioEntrada, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    _tablero(sesion, dashboard_id)
    e = EnvioInforme(dashboard_id=dashboard_id, creado_por=actor.id,
                     **cuerpo.model_dump())
    sesion.add(e)
    sesion.flush()
    _comprobar_periodo(sesion, e)
    sesion.commit()
    programador.aplicar_envio(e)
    registrar(sesion, accion="envio_creado", usuario_id=actor.id, email=actor.email,
              objeto_tipo="dashboard", objeto_id=dashboard_id,
              detalle={"envio": e.id, "destinatarios": e.destinatarios,
                       "cron": e.cron, "periodo": e.periodo})
    sesion.commit()
    return _salida(e)


@router.put("/{dashboard_id}/envios/{envio_id}", response_model=EnvioSalida)
def cambiar(dashboard_id: int, envio_id: int, cuerpo: EnvioEntrada, sesion: SesionDep,
            actor: Usuario = Depends(exigir_rol(Rol.editor))):
    e = _envio(sesion, dashboard_id, envio_id)
    for campo, valor in cuerpo.model_dump().items():
        setattr(e, campo, valor)
    _comprobar_periodo(sesion, e)
    sesion.commit()
    programador.aplicar_envio(e)
    registrar(sesion, accion="envio_cambiado", usuario_id=actor.id, email=actor.email,
              objeto_tipo="dashboard", objeto_id=dashboard_id,
              detalle={"envio": e.id, "destinatarios": e.destinatarios,
                       "cron": e.cron, "activa": e.activa})
    sesion.commit()
    return _salida(e)


@router.delete("/{dashboard_id}/envios/{envio_id}", status_code=204)
def quitar(dashboard_id: int, envio_id: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    e = _envio(sesion, dashboard_id, envio_id)
    programador.quitar_envio(e.id)
    sesion.delete(e)
    sesion.commit()
    registrar(sesion, accion="envio_borrado", usuario_id=actor.id, email=actor.email,
              objeto_tipo="dashboard", objeto_id=dashboard_id,
              detalle={"envio": envio_id})
    sesion.commit()


@router.post("/{dashboard_id}/envios/{envio_id}/probar")
def probar(dashboard_id: int, envio_id: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Lo manda AHORA, a los mismos destinatarios.

    A los mismos y no solo a quien pulsa: lo que se esta probando es que el correo llega
    a esa lista, y un envio de prueba que solo se manda a uno no prueba la lista. El
    asunto lleva el periodo, asi que se distingue del de verdad por la fecha.
    """
    e = _envio(sesion, dashboard_id, envio_id)
    try:
        resultado = motor.enviar(sesion, e)
    except (motor.EnvioInvalido, informe_pdf.SinNavegador,
            informe_pdf.FaltaDireccion) as err:
        e.ultimo_error = str(err)[:2000]
        sesion.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err))
    except informe_pdf.InformeFallido as err:
        e.ultimo_error = str(err)[:2000]
        sesion.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(err))
    registrar(sesion, accion="envio_probado", usuario_id=actor.id, email=actor.email,
              objeto_tipo="dashboard", objeto_id=dashboard_id,
              detalle={"envio": e.id, "ms": resultado["ms"]})
    sesion.commit()
    return {**resultado, "envio": _salida(e)}
