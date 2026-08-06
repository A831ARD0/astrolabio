"""
Registro de auditoria.

Se guarda el email ademas del id: si un usuario se borra, el registro sigue
diciendo quien hizo el cambio. La auditoria no debe poder quedarse huerfana.
"""

from sqlalchemy.orm import Session

from app.modelos_db import Auditoria


def registrar(sesion: Session, *, accion: str, usuario_id: int | None = None,
              email: str | None = None, objeto_tipo: str | None = None,
              objeto_id: str | int | None = None,
              detalle: dict | None = None) -> None:
    sesion.add(Auditoria(
        usuario_id=usuario_id,
        email_usuario=email,
        accion=accion,
        objeto_tipo=objeto_tipo,
        objeto_id=str(objeto_id) if objeto_id is not None else None,
        detalle=detalle or {},
    ))
