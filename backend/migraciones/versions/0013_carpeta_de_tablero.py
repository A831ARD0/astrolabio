"""Carpeta de un tablero.

Una columna nueva en `dashboard`: en que carpeta del estante se guarda. Es **solo
para ordenar** y no decide quien ve que — eso lo siguen decidiendo el rol y el
publicado/certificado. Por eso va en su propia columna y no dentro de `definicion`:
mover un tablero de carpeta no es cambiar lo que dice, y si viviera en la definicion
lo dejaria sin certificar cada vez que alguien reordena el estante.

Vacia = sin carpeta. Los tableros que ya hay quedan asi y siguen saliendo igual.

Se anade solo si falta, por lo mismo que en 0002, 0005, 0007, 0008, 0010, 0011 y
0012: la revision 0001 usa create_all, asi que en una base nueva ya viene puesta.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TABLA = "dashboard"
COLUMNA = "carpeta"


def _tiene_columna() -> bool:
    insp = sa.inspect(op.get_bind())
    if TABLA not in insp.get_table_names():
        return True                      # no hay nada que migrar
    return COLUMNA in {c["name"] for c in insp.get_columns(TABLA)}


def upgrade() -> None:
    if _tiene_columna():
        return
    # `server_default` y no solo `default`: sin el, las filas que ya existen se
    # quedarian en NULL y habria que tratar NULL y "" como lo mismo en cada
    # consulta. Con el, "sin carpeta" es un unico valor.
    op.add_column(
        TABLA,
        sa.Column(COLUMNA, sa.String(120), nullable=False, server_default=""),
    )


def downgrade() -> None:
    if not _tiene_columna():
        return
    op.drop_column(TABLA, COLUMNA)
