"""La forma de la fecha de partición en el origen.

Agrega a `dataset` la columna `formato_fecha`: 'texto:%Y%m%d', 'numero:%Y%m',
'dias:1899-12-30=0'… Con una expresión libre de DuckDB la fecha se podía convertir
al escribir, pero no filtrar en el origen, así que una recarga por ventana traía la
tabla entera. Con la forma declarada se puede hacer las dos cosas.

Los datasets que ya tenían una expresión de las formas comunes —strptime de una
columna con un formato, o días contados con `DATE '…' + (columna - n)`— pasan solos
a `formato_fecha`, y se les quita la expresión: dan las mismas fechas, así que el
Parquet en disco sigue sirviendo y no hace falta recargarlos. Las demás expresiones
se quedan como están.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import re
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

COLUMNA = "formato_fecha"

_STRPTIME = re.compile(
    r"""^\s*(?:try_)?strptime\(\s*(?:trim\(\s*)?(?:CAST\(\s*)?"([^"]+)"(?:\s+AS\s+VARCHAR\s*\))?(?:\s*\))?\s*,\s*'([^']+)'\s*\)\s*$""",
    re.I)
_DIAS = re.compile(
    r"""^\s*CASE\s+WHEN\s+CAST\(\s*"([^"]+)"\s+AS\s+BIGINT\s*\)\s+BETWEEN\s+-?\d+\s+AND\s+-?\d+\s+"""
    r"""THEN\s+DATE\s+'(\d{4}-\d{2}-\d{2})'\s*\+\s*to_days\(\s*CAST\(\s*"\1"\s+AS\s+INTEGER\s*\)\s*-\s*(-?\d+)\s*\)\s*END\s*$""",
    re.I | re.S)


def deducir(expresion: str | None, columna: str | None) -> str | None:
    """El formato equivalente a una expresión de las formas comunes, o None."""
    if not expresion or not columna:
        return None
    if (m := _STRPTIME.match(expresion)) and m.group(1) == columna:
        return f"texto:{m.group(2)}"
    if (m := _DIAS.match(expresion)) and m.group(1) == columna:
        return f"dias:{m.group(2)}={int(m.group(3))}"
    return None


def _columnas() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("dataset")}


def upgrade() -> None:
    if COLUMNA not in _columnas():
        op.add_column("dataset", sa.Column(COLUMNA, sa.String(60), nullable=True))
    con = op.get_bind()
    filas = con.execute(sa.text(
        "SELECT id, particionar_por, expresion_particion FROM dataset "
        "WHERE expresion_particion IS NOT NULL AND formato_fecha IS NULL")).fetchall()
    for id_, columna, expresion in filas:
        formato = deducir(expresion, columna)
        if formato and len(formato) <= 60:
            con.execute(sa.text(
                "UPDATE dataset SET formato_fecha = :f, expresion_particion = NULL "
                "WHERE id = :i"), {"f": formato, "i": id_})


def downgrade() -> None:
    if COLUMNA in _columnas():
        # Sin la columna, el formato se perderia: se deja escrito como expresion,
        # que da las mismas fechas (aunque ya sin el filtro en el origen).
        from app import formato_fecha

        con = op.get_bind()
        filas = con.execute(sa.text(
            "SELECT id, particionar_por, formato_fecha FROM dataset "
            "WHERE formato_fecha IS NOT NULL")).fetchall()
        for id_, columna, formato in filas:
            con.execute(sa.text(
                "UPDATE dataset SET expresion_particion = :e WHERE id = :i"),
                {"e": formato_fecha.expresion(formato, '"' + columna.replace('"', '""') + '"'),
                 "i": id_})
        with op.batch_alter_table("dataset") as lote:
            lote.drop_column(COLUMNA)
