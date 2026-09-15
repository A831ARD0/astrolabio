"""
No se mezclan dos formatos en el mismo destino.

La trampa que se cobro una tarde: a un dataset ya cargado plano se le puso columna
de particion. El aviso decia "la siguiente carga sera completa", pero el dataset
tenia ventana movil, la ventana gana sobre el modo, y una recarga de particiones NO
vacia el destino. Escribio carpetas anio=/mes= al lado del archivo plano de antes.
Escribir salio bien; leerlo ya no:

    Hive partition mismatch between file "..._20260914113909_ffd37f68.parquet"
    and ".../anio=2026/mes=7/lote_....parquet"

Y eso no se queda en la pantalla de cargas: el dataset deja de servir tambien para
los tableros que lo usan.
"""

from __future__ import annotations

import duckdb
import pytest

from app.conectores.base import (
    ErrorConector, PeticionIngesta, escribir_lote, revisar_formato,
)

FECHA = "TRY_CAST(\"f\" AS DATE)"


def _peticion(**kw) -> PeticionIngesta:
    return PeticionIngesta(**{"esquema": None, "tabla": "t", "destino": "d", **kw})


def _con(filas: str):
    c = duckdb.connect()
    c.execute(f"CREATE TABLE lote AS SELECT * FROM (VALUES {filas}) AS v(f, n)")
    return c


def test_un_destino_vacio_acepta_cualquier_cosa(tmp_path):
    revisar_formato(tmp_path, _peticion(particionar_por="f"))
    revisar_formato(tmp_path, _peticion())


def test_partido_sobre_plano_se_niega(tmp_path):
    """El caso exacto: estaba plano y ahora se quiere partir."""
    escribir_lote(_con("(DATE '2026-07-05', 1)"), tmp_path, _peticion(), 0.0)
    assert any(h.is_file() for h in tmp_path.iterdir())

    with pytest.raises(ErrorConector, match="Recargar completo"):
        escribir_lote(_con("(DATE '2026-07-06', 2)"), tmp_path,
                      _peticion(particionar_por="f"), 0.0)


def test_plano_sobre_partido_tambien(tmp_path):
    """Y al reves: quitar la particion de un dataset ya partido."""
    escribir_lote(_con("(DATE '2026-07-05', 1)"), tmp_path,
                  _peticion(particionar_por="f"), 0.0)
    with pytest.raises(ErrorConector, match="Recargar completo"):
        escribir_lote(_con("(DATE '2026-07-06', 2)"), tmp_path, _peticion(), 0.0)


def test_la_carga_completa_si_puede_porque_vacia(tmp_path):
    """
    La salida del atasco. Es la unica carga que vacia el destino, asi que es la
    unica a la que se le permite cambiar de formato — y lo que dice el mensaje.
    """
    escribir_lote(_con("(DATE '2026-07-05', 1)"), tmp_path, _peticion(), 0.0)
    r = escribir_lote(_con("(DATE '2026-07-06', 2)"), tmp_path,
                      _peticion(particionar_por="f", reemplazar_todo=True), 0.0)
    assert r.particiones_escritas == ["anio=2026/mes=7"]
    assert not any(h.is_file() and h.suffix == ".parquet"
                   for h in tmp_path.iterdir()), "el plano de antes tenia que irse"

    # Y lo importante: se puede leer.
    assert duckdb.connect().execute(
        f"SELECT COUNT(*) FROM read_parquet('{tmp_path}/**/*.parquet', "
        f"hive_partitioning=1)").fetchone()[0] == 1


def test_seguir_en_el_mismo_formato_no_estorba(tmp_path):
    """El guardia no puede molestar al caso de todos los dias."""
    escribir_lote(_con("(DATE '2026-07-05', 1)"), tmp_path,
                  _peticion(particionar_por="f"), 0.0)
    escribir_lote(_con("(DATE '2026-08-05', 2)"), tmp_path,
                  _peticion(particionar_por="f"), 0.0)
    assert duckdb.connect().execute(
        f"SELECT COUNT(*) FROM read_parquet('{tmp_path}/**/*.parquet', "
        f"hive_partitioning=1)").fetchone()[0] == 2


def test_un_destino_ya_mezclado_lo_dice(tmp_path):
    """Para quien ya lo tenga roto de antes: el mensaje explica como salir."""
    (tmp_path / "anio=2026").mkdir(parents=True)
    (tmp_path / "anio=2026" / "mes=7").mkdir()
    (tmp_path / "anio=2026" / "mes=7" / "lote_x.parquet").write_bytes(b"")
    (tmp_path / "suelto.parquet").write_bytes(b"")

    with pytest.raises(ErrorConector, match="mezclados"):
        revisar_formato(tmp_path, _peticion(particionar_por="f"))
