"""
La forma de la fecha en el origen: de ella salen la conversión para partir el
Parquet y el filtro que se manda al origen en una recarga por ventana.

Lo que importa probar es que las dos cosas digan lo mismo: si el filtro del origen
deja fuera una fila que la conversión mete en el rango, la recarga la pierde en
silencio (borra su mes y no la vuelve a traer).
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from app import formato_fecha as ff
from app.conectores.base import PeticionIngesta, expresion_fecha
from tests.conftest import (cargar, config_odbc, necesita_mysql, necesita_odbc,
                            recargar_rango)


# --------------------------------------------------------------------------- #
# Validar
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("formato", [
    "texto:%Y%m%d", "texto:%d/%m/%Y", "texto:%Y-%m-%d %H:%M:%S", "numero:%Y%m%d",
    "numero:%Y%m", "dias:1899-12-30=0", "dias:1970-01-01=719163",
])
def test_formatos_validos(formato):
    assert ff.validar(formato) == formato


@pytest.mark.parametrize("formato,dice", [
    ("fecha:%Y", "desconocido"),
    ("texto:", "desconocido"),
    ("texto:sin directivas", "directiva"),
    ("texto:%m/%d", "año"),
    ("numero:%Y-%m-%d", "separadores"),
    ("dias:1899-12-30", "AAAA-MM-DD=n"),
    ("dias:2026-02-30=0", "no es una fecha"),
])
def test_formatos_invalidos_dicen_por_que(formato, dice):
    with pytest.raises(ff.FormatoInvalido, match=dice):
        ff.validar(formato)


def test_vacio_es_sin_formato():
    assert ff.validar("") is None and ff.validar(None) is None


# --------------------------------------------------------------------------- #
# Convertir
# --------------------------------------------------------------------------- #

def _convertir(formato, valores):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (c VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [[v] for v in valores])
    p = PeticionIngesta(esquema=None, tabla="t", destino="d", particionar_por="c",
                        formato_fecha=formato)
    return [r[0] for r in con.execute(f"SELECT {expresion_fecha(p)} FROM t").fetchall()]


@pytest.mark.parametrize("formato,valores,esperado", [
    ("texto:%Y%m%d", ["20260715", "20260715   ", "", None, "basura"],
     ["2026-07-15", "2026-07-15", None, None, None]),
    ("texto:%d/%m/%Y", ["15/07/2026"], ["2026-07-15"]),
    ("numero:%Y%m%d", ["20260715", "20260715.0", "0"], ["2026-07-15", "2026-07-15", None]),
    ("numero:%Y%m", ["202607"], ["2026-07-01"]),
    ("dias:1899-12-30=0", ["46218"], ["2026-07-15"]),
    ("dias:1970-01-01=719163", ["739812", "0", "99999999999"],
     ["2026-07-15", None, None]),
])
def test_cada_forma_convierte_y_tolera_basura(formato, valores, esperado):
    r = _convertir(formato, valores)
    assert [x.isoformat() if x else None for x in r] == esperado


# --------------------------------------------------------------------------- #
# Filtrar en el origen
# --------------------------------------------------------------------------- #

def test_limites_de_texto_y_numero():
    assert ff.limites("texto:%Y%m%d", "2026-07-01", "2026-11-30") == (
        "'20260701'", "'20261201'")
    assert ff.limites("texto:%Y-%m-%d", "2026-07-01", "2026-07-31") == (
        "'2026-07-01'", "'2026-08-01'")
    assert ff.limites("numero:%Y%m", "2026-07-01", "2026-11-30") == ("202607", "202612")
    assert ff.limites("numero:%Y", "2026-07-01", "2026-11-30") == ("2026", "2027")


def test_limites_de_dias():
    assert ff.limites("dias:1970-01-01=719163", "1970-01-01", "1970-01-31") == (
        "719163", "719194")
    assert ff.limites("dias:1899-12-30=0", "2026-07-15", "2026-07-15") == (
        "46218", "46219")


@pytest.mark.parametrize("formato", ["texto:%d/%m/%Y", "texto:%m%d%Y", "texto:%y%m%d"])
def test_si_comparar_no_es_ordenar_fechas_no_se_filtra_en_el_origen(formato):
    """'01/08/2026' < '31/07/2026' como texto: filtrar así perdería filas."""
    assert ff.limites(formato, "2026-07-01", "2026-07-31") is None


@pytest.mark.parametrize("formato", [
    "texto:%Y%m%d", "texto:%Y-%m-%d %H:%M:%S", "numero:%Y%m%d", "numero:%Y%m",
    "numero:%Y", "dias:1899-12-30=0", "dias:1970-01-01=719163",
])
def test_el_filtro_del_origen_y_la_conversion_dicen_lo_mismo(formato):
    """
    Para cada día de dos años: si la conversión lo pone dentro del rango, el filtro
    del origen tiene que dejarlo pasar. Puede dejar pasar de más (se recorta al
    escribir), nunca de menos.
    """
    desde, hasta = "2026-07-01", "2026-11-30"
    lo, hi = ff.limites(formato, desde, hasta)
    tipo, resto = formato.split(":", 1)
    d = date(2025, 12, 1)
    while d < date(2027, 2, 1):
        if tipo == "dias":
            ref, n = resto.split("=")
            valor = n and str(int(n) + (d - date.fromisoformat(ref)).days)
            pasa = int(lo) <= int(valor) < int(hi)
        elif tipo == "numero":
            valor = d.strftime(resto)
            pasa = int(lo) <= int(valor) < int(hi)
        else:
            valor = d.strftime(resto)
            pasa = lo.strip("'") <= valor < hi.strip("'")
        dentro = date.fromisoformat(desde) <= d <= date.fromisoformat(hasta)
        assert pasa or not dentro, f"{formato}: {d} está en el rango y el origen lo deja fuera"
        d += timedelta(days=1)


# --------------------------------------------------------------------------- #
# Migración: las expresiones de antes pasan solas a formato
# --------------------------------------------------------------------------- #

def _migracion():
    ruta = Path(__file__).parents[1] / "migraciones/versions/0016_formato_de_fecha.py"
    spec = importlib.util.spec_from_file_location("m0016", ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.mark.parametrize("expresion,columna,formato", [
    ("try_strptime(\"Dt Emissao\", '%Y%m%d')", "Dt Emissao", "texto:%Y%m%d"),
    ("try_strptime(CAST(\"Dt Movim\" AS VARCHAR), '%Y%m%d')", "Dt Movim", "texto:%Y%m%d"),
    ("strptime(\"f\", '%d/%m/%Y')", "f", "texto:%d/%m/%Y"),
    ('CASE WHEN CAST("Dt Emissao" AS BIGINT) BETWEEN 693596 AND 766645 THEN '
     "DATE '1970-01-01' + to_days(CAST(\"Dt Emissao\" AS INTEGER) - 719163) END",
     "Dt Emissao", "dias:1970-01-01=719163"),
    ("try_strptime(\"otra\", '%Y%m%d')", "Dt Emissao", None),
    ("try_strptime(CAST(c + 19000000 AS VARCHAR), '%Y%m%d')", "c", None),
])
def test_la_migracion_reconoce_las_formas_comunes(expresion, columna, formato):
    assert _migracion().deducir(expresion, columna) == formato


@pytest.mark.parametrize("expresion,columna,valores", [
    ("try_strptime(\"c\", '%Y%m%d')", "c", ["20260715", "20251231", ""]),
    ('CASE WHEN CAST("c" AS BIGINT) BETWEEN 693596 AND 766645 THEN '
     "DATE '1970-01-01' + to_days(CAST(\"c\" AS INTEGER) - 719163) END",
     "c", ["739812", "693596", "766645"]),
])
def test_lo_migrado_da_las_mismas_fechas(expresion, columna, valores):
    """Si no, el Parquet que ya está en disco quedaría partido de otra forma."""
    con = duckdb.connect()
    con.execute("CREATE TABLE t (c VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [[v] for v in valores])
    antes = con.execute(f"SELECT TRY_CAST(({expresion}) AS DATE) FROM t").fetchall()
    formato = _migracion().deducir(expresion, columna)
    assert _convertir(formato, valores) == [a[0] for a in antes]


# --------------------------------------------------------------------------- #
# De punta a punta, por ODBC
# --------------------------------------------------------------------------- #

@necesita_mysql
def test_formato_y_expresion_no_van_juntos(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "ff_doble", "tabla": "ventas",
                           "particionar_por": "fecha_texto",
                           "formato_fecha": "texto:%Y-%m-%d",
                           "expresion_particion": "try_strptime(\"fecha_texto\", '%Y-%m-%d')"})
    assert r.status_code == 422, r.text
    assert "una sola forma" in r.json()["detail"]


@necesita_mysql
def test_formato_sin_particion_no_vale(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "ff_sin", "tabla": "ventas",
                           "formato_fecha": "texto:%Y-%m-%d"})
    assert r.status_code == 422, r.text
    assert "Partir por" in r.json()["detail"]


@necesita_mysql
def test_un_formato_que_no_feche_nada_no_se_guarda(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "ff_mal", "tabla": "ventas",
                           "particionar_por": "fecha_texto",
                           "formato_fecha": "texto:%d/%m/%Y"})
    assert r.status_code == 422, r.text
    assert "Ninguna de las" in r.json()["detail"]


@necesita_mysql
def test_el_formato_se_guarda_y_se_lista(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "ff_lista", "tabla": "ventas",
                           "particionar_por": "fecha_texto",
                           "formato_fecha": "texto:%Y-%m-%d"})
    assert r.status_code == 201, r.text
    lista = cliente.get("/api/conexiones/datasets/lista", headers=cab_admin).json()
    ds = next(d for d in lista["datasets"] if d["nombre"] == "ff_lista")
    assert ds["formato_fecha"] == "texto:%Y-%m-%d"
    assert ds["expresion_particion"] is None
    r = cliente.get("/api/conexiones/formatos-fecha", headers=cab_admin)
    assert {f["clave"] for f in r.json()["formatos"]} == {"texto", "numero", "dias"}


@necesita_odbc
def test_por_odbc_el_rango_se_filtra_en_el_origen_y_trae_lo_mismo(tmp_path):
    """
    La misma recarga de un mes, con el filtro en el origen (formato) y recortando
    al escribir (expresión): mismo contenido. Y con el formato, el origen manda
    solo ese mes.
    """
    from app.conectores import crear

    odbc = crear("odbc", config_odbc())
    leidas = []
    original = odbc.ingestar

    def contar(p, ruta):
        r = original(p, ruta)
        leidas.append(r.filas)
        return r

    comun = dict(esquema=None, tabla="ventas", destino="ff", particionar_por="fecha_texto",
                 rango_desde="2020-04-01", rango_hasta="2020-04-30")
    con = duckdb.connect()
    a, b = tmp_path / "formato", tmp_path / "expresion"
    contar(PeticionIngesta(formato_fecha="texto:%Y-%m-%d", **comun), str(a))
    contar(PeticionIngesta(
        expresion_particion="try_strptime(\"fecha_texto\", '%Y-%m-%d')", **comun), str(b))
    leer = "SELECT * EXCLUDE (anio, mes) FROM read_parquet('{}/**/*.parquet', hive_partitioning=1)"
    diferencia = con.execute(
        f"SELECT COUNT(*) FROM (({leer.format(a)}) EXCEPT ({leer.format(b)})) x").fetchone()[0]
    diferencia += con.execute(
        f"SELECT COUNT(*) FROM (({leer.format(b)}) EXCEPT ({leer.format(a)})) x").fetchone()[0]
    assert diferencia == 0
    assert leidas[0] == leidas[1] > 0
