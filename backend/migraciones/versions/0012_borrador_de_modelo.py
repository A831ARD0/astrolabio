"""Borrador del modelo semantico.

Una tabla nueva, `borrador_modelo`, con el trabajo en curso sin publicar. Guardar
deja de ser lo mismo que publicar: se guarda en el borrador cuantas veces haga
falta y solo publicar crea una version inmutable.

No toca nada existente. Los modelos que ya hay siguen igual —sin borrador— y
`GET /definicion` les devuelve la version vigente como siempre.

Se crea solo si falta, por lo mismo que en 0002, 0005, 0007, 0008, 0010 y 0011:
la revision 0001 usa create_all, asi que en una base nueva ya viene puesta.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TABLA = "borrador_modelo"


def upgrade() -> None:
    if TABLA in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        TABLA,
        # La llave primaria ES el modelo: un borrador por modelo, garantizado por
        # el esquema y no por una comprobacion en la ruta que alguien pueda
        # olvidar en el siguiente endpoint que escriba.
        sa.Column("modelo_id", sa.Integer(), primary_key=True),
        sa.Column("yaml", sa.Text(), nullable=False),
        sa.Column("desde_version", sa.Integer(), nullable=False),
        sa.Column("actualizado_por", sa.Integer(), nullable=True),
        sa.Column("actualizado_en", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["modelo_id"], ["modelo.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actualizado_por"], ["usuario.id"]),
    )


def downgrade() -> None:
    if TABLA in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLA)
