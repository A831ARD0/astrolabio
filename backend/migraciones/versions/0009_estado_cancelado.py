"""El estado `cancelado` en las ejecuciones.

Una corrida que alguien detuvo no es un fallo: no debe salir en rojo ni disparar
el aviso de fallo. Necesita su propio estado.

En SQLite no hay nada que hacer: `Enum` se guarda como `VARCHAR(9)` sin
restriccion, y 'cancelado' mide justo nueve. En MySQL o PostgreSQL el tipo es un
ENUM de verdad y hay que agregarle el valor, o el INSERT falla.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

TABLAS = ("carga_ejecucion", "flujo_ejecucion", "transformacion_ejecucion")
VALORES = ("corriendo", "exito", "error", "cancelado")


def _tipo() -> sa.Enum:
    return sa.Enum(*VALORES, name="estadocarga")


def upgrade() -> None:
    dialecto = op.get_bind().dialect.name
    if dialecto == "sqlite":
        return                      # VARCHAR sin restriccion: ya lo admite
    if dialecto == "postgresql":
        # ALTER TYPE ... ADD VALUE no se puede dentro de una transaccion en
        # versiones viejas; IF NOT EXISTS lo hace repetible.
        op.execute("ALTER TYPE estadocarga ADD VALUE IF NOT EXISTS 'cancelado'")
        return
    for tabla in TABLAS:
        op.alter_column(tabla, "estado", type_=_tipo(), existing_nullable=False)


def downgrade() -> None:
    dialecto = op.get_bind().dialect.name
    if dialecto in ("sqlite", "postgresql"):
        # En Postgres no se quita un valor de un ENUM sin recrear el tipo, y no
        # vale la pena: un valor de mas no molesta a nadie.
        return
    for tabla in TABLAS:
        # Lo cancelado pasa a error: es lo unico que el tipo viejo sabe decir.
        op.execute(f"UPDATE {tabla} SET estado = 'error' WHERE estado = 'cancelado'")
        op.alter_column(tabla, "estado",
                        type_=sa.Enum("corriendo", "exito", "error",
                                      name="estadocarga"),
                        existing_nullable=False)
