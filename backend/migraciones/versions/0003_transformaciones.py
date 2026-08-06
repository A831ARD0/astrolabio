"""Transformaciones y su historial.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _existe(tabla: str) -> bool:
    return tabla in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    # Igual que en 0002: la revision 0001 crea el esquema con los modelos
    # actuales, asi que en una base nueva estas tablas ya vienen puestas.
    if not _existe("transformacion"):
        op.create_table(
            "transformacion",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nombre", sa.String(120), nullable=False, unique=True),
            sa.Column("descripcion", sa.Text(), nullable=True),
            sa.Column("definicion", sa.JSON(), nullable=True),
            sa.Column("lee_de", sa.JSON(), nullable=True),
            sa.Column("filas", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bytes_parquet", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("ultima_ejecucion", sa.DateTime(), nullable=True),
            sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuario.id"),
                      nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=False),
            sa.Column("actualizado_en", sa.DateTime(), nullable=False),
        )

    if not _existe("transformacion_ejecucion"):
        op.create_table(
            "transformacion_ejecucion",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("transformacion_id", sa.Integer(),
                      sa.ForeignKey("transformacion.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("estado",
                      sa.Enum("corriendo", "exito", "error", name="estadocarga"),
                      nullable=False),
            sa.Column("filas", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bytes_escritos", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mensaje", sa.Text(), nullable=True),
            sa.Column("sql", sa.Text(), nullable=True),
            sa.Column("iniciado_por", sa.Integer(), sa.ForeignKey("usuario.id"),
                      nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_transformacion_ejecucion_creado_en",
                        "transformacion_ejecucion", ["creado_en"])


def downgrade() -> None:
    if _existe("transformacion_ejecucion"):
        op.drop_table("transformacion_ejecucion")
    if _existe("transformacion"):
        op.drop_table("transformacion")
