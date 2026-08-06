"""
Gobierno: simulador de seguridad por fila y visor de auditoria.

Nota sobre la auditoria: solo se lee. No hay ruta para editarla ni para borrarla, y
es deliberado — un registro que se puede limpiar no sirve para lo unico que existe,
que es contestar "quien vio esto y cuando" cuando alguien pregunta en serio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auditoria import registrar
from app.dependencias import SesionDep, exigir_rol
from app.gobierno import contexto_de, contexto_ficticio, simular
from app.modelos_db import Auditoria, Rol, Usuario
from app.rutas.modelos import _cargar_semantico, _version_exacta, _version_vigente
from semantic.engine import Consulta, ErrorModelo

router = APIRouter(prefix="/api/gobierno", tags=["gobierno"])


# --------------------------------------------------------------------------- #
# Simulador
# --------------------------------------------------------------------------- #

class ConsultaSimulada(BaseModel):
    dimensiones: list[str] = []
    metricas: list[str] = []
    limite: int = Field(default=200, le=5000)


class PeticionSimular(BaseModel):
    modelo_id: int
    version: int | None = None
    # Uno de los dos: un usuario real, o un rol con atributos a mano.
    usuario_id: int | None = None
    rol: str | None = None
    atributos: dict[str, str] = {}
    consulta: ConsultaSimulada | None = None


@router.post("/simular")
def simular_usuario(cuerpo: PeticionSimular, sesion: SesionDep,
                    actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Que veria otra persona. Solo administrador, y queda en auditoria.

    Que quede en auditoria no es tramite: un administrador mirando los datos como
    otro usuario es precisamente el tipo de acceso por el que existe un registro.
    """
    v = (_version_exacta(sesion, cuerpo.modelo_id, cuerpo.version)
         if cuerpo.version else _version_vigente(sesion, cuerpo.modelo_id))
    modelo = _cargar_semantico(v.yaml)

    if cuerpo.usuario_id is not None:
        objetivo = sesion.get(Usuario, cuerpo.usuario_id)
        if objetivo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
        ctx = contexto_de(objetivo)
        quien: dict[str, Any] = {"usuario_id": objetivo.id, "email": objetivo.email}
    elif cuerpo.rol:
        if cuerpo.rol not in {r.value for r in Rol}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"El rol '{cuerpo.rol}' no existe")
        ctx = contexto_ficticio(cuerpo.rol, cuerpo.atributos)
        quien = {"rol": cuerpo.rol, "atributos": cuerpo.atributos}
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Hace falta un usuario o un rol con atributos para simular.")

    consulta = None
    if cuerpo.consulta and cuerpo.consulta.metricas:
        consulta = Consulta(dimensiones=cuerpo.consulta.dimensiones,
                            metricas=cuerpo.consulta.metricas,
                            limite=cuerpo.consulta.limite)

    try:
        resultado = simular(modelo, ctx, consulta)
    except ErrorModelo as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))

    registrar(sesion, accion="simulacion", usuario_id=actor.id, email=actor.email,
              objeto_tipo="modelo", objeto_id=cuerpo.modelo_id,
              detalle={"version": v.version, "como": quien,
                       "politicas": [p["politica"] for p in resultado["aplicadas"]],
                       "consulta": bool(consulta)})
    return {"version": v.version, **resultado}


# --------------------------------------------------------------------------- #
# Auditoria
# --------------------------------------------------------------------------- #

@router.get("/auditoria")
def listar_auditoria(
    sesion: SesionDep,
    _: Usuario = Depends(exigir_rol(Rol.administrador)),
    accion: str | None = None,
    email: str | None = None,
    objeto_tipo: str | None = None,
    objeto_id: str | None = None,
    dias: int | None = Query(default=None, ge=1, le=3650),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=50, ge=1, le=500),
):
    """
    El registro, filtrado y paginado.

    Se pagina en el servidor y no en el navegador porque esta tabla crece con cada
    consulta que hace cualquiera: en unas semanas son cientos de miles de filas y
    traerlas todas para filtrar en el cliente deja de funcionar sin avisar.
    """
    cond = []
    if accion:
        cond.append(Auditoria.accion == accion)
    if email:
        cond.append(Auditoria.email_usuario.ilike(f"%{email}%"))
    if objeto_tipo:
        cond.append(Auditoria.objeto_tipo == objeto_tipo)
    if objeto_id:
        cond.append(Auditoria.objeto_id == str(objeto_id))
    if dias:
        cond.append(Auditoria.creado_en
                    >= datetime.now(timezone.utc) - timedelta(days=dias))

    total = sesion.scalar(
        select(func.count()).select_from(Auditoria).where(*cond)) or 0
    filas = sesion.scalars(
        select(Auditoria).where(*cond)
        .order_by(Auditoria.id.desc())
        .offset((pagina - 1) * por_pagina).limit(por_pagina)
    )
    return {
        "total": total,
        "pagina": pagina,
        "por_pagina": por_pagina,
        "eventos": [
            {"id": a.id, "cuando": a.creado_en.isoformat(),
             "email": a.email_usuario, "usuario_id": a.usuario_id,
             "accion": a.accion, "objeto_tipo": a.objeto_tipo,
             "objeto_id": a.objeto_id, "detalle": a.detalle}
            for a in filas
        ],
    }


@router.get("/auditoria/resumen")
def resumen_auditoria(sesion: SesionDep,
                      _: Usuario = Depends(exigir_rol(Rol.administrador)),
                      dias: int = Query(default=30, ge=1, le=3650)):
    """Que acciones hay y cuantas, para poder filtrar sin adivinar los nombres."""
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    acciones = sesion.execute(
        select(Auditoria.accion, func.count())
        .where(Auditoria.creado_en >= desde)
        .group_by(Auditoria.accion).order_by(func.count().desc())
    ).all()
    personas = sesion.execute(
        select(Auditoria.email_usuario, func.count())
        .where(Auditoria.creado_en >= desde,
               Auditoria.email_usuario.is_not(None))
        .group_by(Auditoria.email_usuario).order_by(func.count().desc())
    ).all()
    return {
        "dias": dias,
        "acciones": [{"accion": a, "veces": n} for a, n in acciones],
        "personas": [{"email": e, "veces": n} for e, n in personas],
        "objetos": [
            t for (t,) in sesion.execute(
                select(Auditoria.objeto_tipo).where(
                    Auditoria.objeto_tipo.is_not(None)).distinct()
            ).all()
        ],
        # Los ingresos fallidos aparte: son la senal que se mira primero cuando se
        # sospecha de algo, y perdida entre 50,000 consultas no se ve.
        "ingresos_fallidos": sesion.scalar(
            select(func.count()).select_from(Auditoria)
            .where(Auditoria.accion == "ingreso_fallido",
                   Auditoria.creado_en >= desde)) or 0,
    }
