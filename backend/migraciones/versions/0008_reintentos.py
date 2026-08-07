"""Reintentos por paso en los flujos.

Agrega a `flujo`:

- `reintentos`: cuantas veces se vuelve a intentar un paso antes de darlo por
  fallido. **Cero por omision**: reintentar sin que nadie lo pida esconde un
  origen que va mal.
- `espera_reintento_seg`: cuanto se espera entre intentos.

Se agregan solo si faltan, por lo mismo que en 0002, 0005 y 0007: la revision
0001 usa create_all, asi que en una base nueva ya vienen puestas por los modelos.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

NUEVAS: list[tuple[str, object]] = [
    ("reintentos",
     lambda: sa.Column("reintentos", sa.Integer(), nullable=True)),
    ("espera_reintento_seg",
     lambda: sa.Column("espera_reintento_seg", sa.Integer(), nullable=True)),
]

POR_OMISION = {"reintentos": 0, "espera_reintento_seg": 60}


def _columnas() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("flujo")}


def upgrade() -> None:
    existentes = _columnas()
    for nombre, fabrica in NUEVAS:
        if nombre not in existentes:
            op.add_column("flujo", fabrica())      # type: ignore[operator]
            op.execute(f"UPDATE flujo SET {nombre} = {POR_OMISION[nombre]} "
                       f"WHERE {nombre} IS NULL")


def downgrade() -> None:
    existentes = _columnas()
    with op.batch_alter_table("flujo") as lote:
        for nombre, _ in NUEVAS:
            if nombre in existentes:
                lote.drop_column(nombre)
