"""Como convertir en fecha la columna de particion.

Agrega a `dataset` la columna `expresion_particion`: una expresion de DuckDB que
se evalua sobre las filas ya traidas y devuelve la fecha con la que se parte el
Parquet. NULL = la columna ya es una fecha.

Existe porque en los origenes antiguos las fechas no son fechas: vienen como
enteros con forma 20260914, o como texto en el formato del pais. Elegir una de
esas columnas no fallaba —hacia algo peor, dejarlo todo en la particion
'sin_fecha'— y la alternativa, codificar los formatos uno a uno, es una lista que
nunca acaba.

Se agrega solo si falta, por lo mismo que en las anteriores: la revision 0001 usa
create_all, asi que en una base nueva ya viene puesta.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

COLUMNA = "expresion_particion"


def _columnas() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("dataset")}


def upgrade() -> None:
    if COLUMNA not in _columnas():
        op.add_column("dataset", sa.Column(COLUMNA, sa.String(500), nullable=True))


def downgrade() -> None:
    if COLUMNA in _columnas():
        with op.batch_alter_table("dataset") as lote:
            lote.drop_column(COLUMNA)
