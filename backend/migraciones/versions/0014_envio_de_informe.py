"""Envio de un informe por correo, con horario.

Una tabla nueva: a quien, de que hoja, cada cuando, y de que periodo. Lo que no
guarda son los filtros de ese periodo, y es a proposito — ver la nota de
`EnvioInforme`: un informe mensual con los filtros escritos a mano mandaria el mismo
mes para siempre.

Se crea solo si falta, por lo mismo que en las anteriores: la revision 0001 usa
create_all, asi que en una base nueva ya viene puesta.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TABLA = "envio_informe"


def _existe() -> bool:
    return TABLA in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _existe():
        return
    op.create_table(
        TABLA,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dashboard_id", sa.Integer,
                  sa.ForeignKey("dashboard.id"), nullable=False),
        sa.Column("hoja", sa.String(120), nullable=True),
        sa.Column("destinatarios", sa.Text, nullable=False),
        sa.Column("asunto", sa.String(200), nullable=True),
        sa.Column("cuerpo", sa.String(10), nullable=False, server_default="pdf"),
        sa.Column("periodo", sa.String(20), nullable=False,
                  server_default="mes_anterior"),
        sa.Column("cron", sa.String(120), nullable=True),
        sa.Column("zona_horaria", sa.String(64), nullable=False,
                  server_default="America/Mexico_City"),
        sa.Column("activa", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("ultimo_envio", sa.DateTime, nullable=True),
        sa.Column("ultimo_error", sa.Text, nullable=True),
        sa.Column("ultimo_ms", sa.Integer, nullable=True),
        sa.Column("creado_por", sa.Integer, sa.ForeignKey("usuario.id"), nullable=True),
        sa.Column("creado_en", sa.DateTime, nullable=False),
        sa.Column("actualizado_en", sa.DateTime, nullable=False),
    )
    # Por tablero, que es como se listan: al abrir un tablero se preguntan los suyos.
    op.create_index("ix_envio_informe_dashboard", TABLA, ["dashboard_id"])


def downgrade() -> None:
    if not _existe():
        return
    op.drop_index("ix_envio_informe_dashboard", table_name=TABLA)
    op.drop_table(TABLA)
