"""La cadena de continuaciones entre corridas de un flujo.

Agrega a `flujo_ejecucion`:

- `reanuda_a_id`: la corrida que esta continua.
- `reanudada_por_id`: la corrida que continuo a esta.

Los dos lados y no uno solo: el primero para leer el historial hacia atras
—«corrida #43, continua de la #41»—, el segundo para poder rechazar que dos
personas continuen la misma corrida pausada.

Se agregan solo si faltan, por lo mismo que en 0002, 0005, 0007 y 0008: la
revision 0001 usa create_all, asi que en una base nueva ya vienen puestas.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

NUEVAS = ("reanuda_a_id", "reanudada_por_id")


def _columnas() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("flujo_ejecucion")}


def upgrade() -> None:
    existentes = _columnas()
    for nombre in NUEVAS:
        if nombre not in existentes:
            # Sin ForeignKey explicita: en SQLite agregar una clave ajena a una
            # tabla que ya existe obliga a recrearla, y aqui no hace falta —el
            # valor es un id de esta misma tabla y lo escribe un solo sitio.
            op.add_column("flujo_ejecucion",
                          sa.Column(nombre, sa.Integer(), nullable=True))


def downgrade() -> None:
    existentes = _columnas()
    with op.batch_alter_table("flujo_ejecucion") as lote:
        for nombre in NUEVAS:
            if nombre in existentes:
                lote.drop_column(nombre)
