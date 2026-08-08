"""Proyectos con secciones.

Agrega:

- `flujo.es_proyecto`: este flujo es un proyecto, es decir un grupo ordenado de
  transformaciones —lo que en Qlik es un script con secciones—. Comparte tabla con
  los flujos porque comparte ejecucion; lo que cambia es el vocabulario y que solo
  admite pasos de transformacion.
- `transformacion.intermedia`: la seccion es andamiaje. Se sigue materializando,
  pero no se ofrece como origen fuera de su proyecto ni sale en las listas de
  datos.

Las dos con valor por omision FALSO, y eso importa: **nada de lo que ya existe
cambia de comportamiento.** Los flujos siguen siendo flujos y las transformaciones
sueltas siguen visibles donde estaban.

Se agregan solo si faltan, por lo mismo que en 0002, 0005, 0007, 0008 y 0010: la
revision 0001 usa create_all, asi que en una base nueva ya vienen puestas.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

NUEVAS = (
    ("flujo", "es_proyecto"),
    ("transformacion", "intermedia"),
)


def _columnas(tabla: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(tabla)}


def upgrade() -> None:
    for tabla, columna in NUEVAS:
        if columna in _columnas(tabla):
            continue
        # `server_default` y no solo `default`: el default de SQLAlchemy lo pone
        # Python al insertar, y las filas que YA estan no pasan por ahi. Sin el
        # default del servidor quedarian en NULL, y un NULL en un booleano que
        # decide si algo se muestra se lee distinto en cada dialecto.
        op.add_column(tabla, sa.Column(columna, sa.Boolean(), nullable=False,
                                       server_default=sa.false()))


def downgrade() -> None:
    for tabla, columna in NUEVAS:
        if columna in _columnas(tabla):
            with op.batch_alter_table(tabla) as lote:
                lote.drop_column(columna)
