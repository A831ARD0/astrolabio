"""Flujos: cargas y transformaciones en cadena, con un solo horario.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _existe(tabla: str) -> bool:
    return tabla in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _existe("flujo"):
        op.create_table(
            "flujo",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nombre", sa.String(120), nullable=False, unique=True),
            sa.Column("descripcion", sa.Text(), nullable=True),
            sa.Column("pasos", sa.JSON(), nullable=True),
            sa.Column("al_fallar", sa.String(20), nullable=False,
                      server_default="detener"),
            sa.Column("cron", sa.String(120), nullable=True),
            sa.Column("zona_horaria", sa.String(64), nullable=False,
                      server_default="America/Mexico_City"),
            sa.Column("programacion_activa", sa.Boolean(), nullable=False,
                      server_default=sa.false()),
            sa.Column("ultima_ejecucion", sa.DateTime(), nullable=True),
            sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuario.id"),
                      nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=False),
        )

    if not _existe("flujo_ejecucion"):
        op.create_table(
            "flujo_ejecucion",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("flujo_id", sa.Integer(),
                      sa.ForeignKey("flujo.id", ondelete="CASCADE"), nullable=False),
            sa.Column("estado",
                      sa.Enum("corriendo", "exito", "error", name="estadocarga"),
                      nullable=False),
            sa.Column("origen", sa.String(20), nullable=False,
                      server_default="manual"),
            sa.Column("ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mensaje", sa.Text(), nullable=True),
            sa.Column("detalle", sa.JSON(), nullable=True),
            sa.Column("iniciado_por", sa.Integer(), sa.ForeignKey("usuario.id"),
                      nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_flujo_ejecucion_creado_en", "flujo_ejecucion",
                        ["creado_en"])


def downgrade() -> None:
    if _existe("flujo_ejecucion"):
        op.drop_table("flujo_ejecucion")
    if _existe("flujo"):
        op.drop_table("flujo")
