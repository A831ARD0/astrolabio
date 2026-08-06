"""Dependencias de FastAPI: usuario actual, exigir rol, contexto de politicas."""

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import obtener_sesion
from app.modelos_db import Rol, Usuario
from app.politicas import ContextoUsuario
from app.seguridad import leer_token

esquema_oauth = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

SesionDep = Annotated[Session, Depends(obtener_sesion)]


def usuario_actual(
    token: Annotated[str, Depends(esquema_oauth)],
    sesion: SesionDep,
) -> Usuario:
    no_autorizado = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales invalidas o token expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        carga = leer_token(token)
        email = carga.get("sub")
    except jwt.PyJWTError:
        raise no_autorizado
    if not email:
        raise no_autorizado

    usuario = sesion.scalar(select(Usuario).where(Usuario.email == email))
    if usuario is None or not usuario.activo:
        raise no_autorizado
    return usuario


UsuarioDep = Annotated[Usuario, Depends(usuario_actual)]


def exigir_rol(*roles: Rol):
    """
    Uso: `_: None = Depends(exigir_rol(Rol.administrador))`

    El rol administrador pasa siempre: no hace falta enumerarlo en cada ruta.
    """
    permitidos = set(roles) | {Rol.administrador}

    def verificador(usuario: UsuarioDep) -> Usuario:
        if usuario.rol not in permitidos:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tu rol ({usuario.rol.value}) no permite esta accion. "
                       f"Se requiere: {', '.join(r.value for r in sorted(permitidos, key=lambda x: x.value))}",
            )
        return usuario

    return verificador


def contexto_politicas(usuario: UsuarioDep) -> ContextoUsuario:
    """Traduce el usuario de la BD al contexto que usa la capa de politicas."""
    return ContextoUsuario(
        usuario_id=usuario.id,
        email=usuario.email,
        rol=usuario.rol.value,
        atributos=usuario.dict_atributos,
    )


ContextoDep = Annotated[ContextoUsuario, Depends(contexto_politicas)]
