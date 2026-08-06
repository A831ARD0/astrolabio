"""Avisos de fallo: reglas y registro de envios.

Dos tablas nuevas:

- `regla_aviso`: a quien avisar, por que canal, de que eventos y con cuanto
  silencio entre repeticiones.
- `aviso_enviado`: cada intento, incluidos los silenciados y los que fallaron. Es
  la tabla que contesta "creia que estaba avisando".

Se crean solo si faltan, por lo mismo que en 0002 y 0005: la revision 0001 usa
create_all, asi que en una base nueva ya vienen puestas por los modelos.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _tablas() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existentes = _tablas()

    if "regla_aviso" not in existentes:
        op.create_table(
            "regla_aviso",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nombre", sa.String(120), nullable=False, unique=True),
            sa.Column("canal", sa.String(20), nullable=False,
                      server_default="correo"),
            sa.Column("destino", sa.Text(), nullable=False),
            sa.Column("eventos", sa.JSON(), nullable=True),
            sa.Column("objeto_tipo", sa.String(20), nullable=True),
            sa.Column("objeto_id", sa.Integer(), nullable=True),
            sa.Column("silencio_minutos", sa.Integer(), nullable=False,
                      server_default="60"),
            sa.Column("activa", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuario.id"),
                      nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
        )

    if "aviso_enviado" not in existentes:
        op.create_table(
            "aviso_enviado",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("regla_id", sa.Integer(),
                      sa.ForeignKey("regla_aviso.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("evento", sa.String(40), nullable=False),
            sa.Column("objeto_tipo", sa.String(20), nullable=True),
            sa.Column("objeto_id", sa.Integer(), nullable=True),
            sa.Column("asunto", sa.Text(), nullable=False),
            sa.Column("estado", sa.String(20), nullable=False,
                      server_default="enviado"),
            sa.Column("mensaje", sa.Text(), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_aviso_enviado_creado_en", "aviso_enviado", ["creado_en"])


def downgrade() -> None:
    existentes = _tablas()
    if "aviso_enviado" in existentes:
        op.drop_table("aviso_enviado")
    if "regla_aviso" in existentes:
        op.drop_table("regla_aviso")
