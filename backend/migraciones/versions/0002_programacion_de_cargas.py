"""Programacion de cargas y origen de cada ejecucion.

Agrega a `dataset` su cron con zona horaria, y a `carga_ejecucion` de donde salio
la carga (manual o programada) mas su detalle.

Cada columna se agrega solo si falta. Hace falta porque la revision 0001 usa
create_all: en una base nueva las columnas ya vienen puestas por los modelos
actuales, mientras que en la base que ya existia faltan. Sin la comprobacion, una
de las dos rutas falla.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# (tabla, nombre, fabrica). La columna se construye al usarla: un objeto Column
# no se puede reutilizar entre operaciones, queda ligado a la primera tabla.
NUEVAS: list[tuple[str, str, object]] = [
    ("dataset", "cron",
     lambda: sa.Column("cron", sa.String(120), nullable=True)),
    ("dataset", "zona_horaria",
     lambda: sa.Column("zona_horaria", sa.String(64), nullable=False,
                       server_default="America/Mexico_City")),
    ("dataset", "programacion_activa",
     lambda: sa.Column("programacion_activa", sa.Boolean(), nullable=False,
                       server_default=sa.false())),
    ("carga_ejecucion", "origen",
     lambda: sa.Column("origen", sa.String(20), nullable=False,
                       server_default="manual")),
    ("carga_ejecucion", "detalle",
     lambda: sa.Column("detalle", sa.JSON(), nullable=True)),
]

TABLAS = ["dataset", "carga_ejecucion"]


def _columnas(tabla: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(tabla)}


def upgrade() -> None:
    for tabla in TABLAS:
        existentes = _columnas(tabla)
        for t, nombre, fabrica in NUEVAS:
            if t == tabla and nombre not in existentes:
                op.add_column(tabla, fabrica())      # type: ignore[operator]


def downgrade() -> None:
    for tabla in TABLAS:
        existentes = _columnas(tabla)
        with op.batch_alter_table(tabla) as lote:
            for t, nombre, _ in NUEVAS:
                if t == tabla and nombre in existentes:
                    lote.drop_column(nombre)
