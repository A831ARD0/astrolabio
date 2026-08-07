"""Etiquetas de conexion: la constante por sucursal.

Agrega a `conexion` la columna `etiquetas` (JSON): {"id_sucursal": 3}. Son
constantes de la conexion entera que salen como columna al leer cualquiera de
sus datasets, para poder distinguir de que sucursal viene cada fila una vez que
cuarenta tablas iguales estan juntas.

Se agrega solo si falta, por lo mismo que en 0002 y 0005: la revision 0001 usa
create_all, asi que en una base nueva ya viene puesta por los modelos.

El valor por defecto es un objeto vacio y no NULL: quien lee espera un
diccionario, y un NULL obligaria a comprobarlo en cada sitio.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _columnas() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("conexion")}


def upgrade() -> None:
    if "etiquetas" not in _columnas():
        op.add_column("conexion",
                      sa.Column("etiquetas", sa.JSON(), nullable=True))
        op.execute("UPDATE conexion SET etiquetas = '{}' WHERE etiquetas IS NULL")


def downgrade() -> None:
    if "etiquetas" in _columnas():
        with op.batch_alter_table("conexion") as lote:
            lote.drop_column("etiquetas")
