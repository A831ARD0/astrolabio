"""Esquema base.

Primera revision. Existe para poder adoptar Alembic sobre una base que YA tiene
datos: se apoya en `create_all(checkfirst=True)`, asi que

  - en una base nueva crea todo el esquema,
  - en la base que ya existe no toca nada.

Las revisiones siguientes si son explicitas (add_column, etc.). Esta es la unica
que se permite ser declarativa, y solo porque su trabajo es marcar el punto de
partida.

Revision ID: 0001
Revises: None
"""

from __future__ import annotations

from alembic import op

from app.modelos_db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Deliberadamente vacio: la vuelta atras de "existe el esquema" es borrar la
    # base entera, y eso no debe pasar por un comando de migracion.
    pass
