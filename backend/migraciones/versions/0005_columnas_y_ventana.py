"""Columnas elegidas y ventana movil de recarga.

Agrega a `dataset`:

- `columnas`: que columnas traer. **NULL = todas**, y ese es el valor por defecto
  a proposito. Congelar la lista completa al crear el dataset dejaria fuera para
  siempre las columnas que el origen agregue despues, sin avisar a nadie.
- `ventana`: ventana movil de recarga ('mes_actual', 'ultimos_dias:30'). Se
  resuelve a un rango de fechas en el momento de correr, no al guardarla.

Cada columna se agrega solo si falta, por lo mismo que en 0002: la revision 0001
usa create_all, asi que en una base nueva ya vienen puestas por los modelos.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NUEVAS: list[tuple[str, object]] = [
    ("columnas", lambda: sa.Column("columnas", sa.JSON(), nullable=True)),
    ("ventana", lambda: sa.Column("ventana", sa.String(40), nullable=True)),
]


def _columnas() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("dataset")}


def upgrade() -> None:
    existentes = _columnas()
    for nombre, fabrica in NUEVAS:
        if nombre not in existentes:
            op.add_column("dataset", fabrica())      # type: ignore[operator]


def downgrade() -> None:
    existentes = _columnas()
    with op.batch_alter_table("dataset") as lote:
        for nombre, _ in NUEVAS:
            if nombre in existentes:
                lote.drop_column(nombre)
