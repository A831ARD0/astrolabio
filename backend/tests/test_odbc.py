"""
Conector ODBC, contra el MySQL local.

La prueba que de verdad importa es `test_odbc_trae_lo_mismo_que_el_nativo`: la
misma tabla traida por los dos caminos y comparada con EXCEPT en los dos
sentidos. Un conector nuevo puede parecer que funciona —conecta, lista tablas,
escribe un Parquet con el numero de filas correcto— y estar convirtiendo un
DECIMAL en texto o perdiendo la hora de un DATETIME. Contar filas no lo detecta;
comparar contenido, si.
"""

from __future__ import annotations

import duckdb
import pytest

from app.conectores import ErrorConector, crear
from app.conectores.base import PeticionIngesta
from tests.conftest import BASE_MYSQL, config_odbc, necesita_odbc

# Tabla de prueba: mediana, con fecha y con decimales, que es la combinacion
# donde los tipos se pierden.
TABLA = "ventas"
FECHA = "fecha_emision"
CLAVE = "venta_id"
FILAS = 5_000


def _odbc():
    return crear("odbc", config_odbc())


def _pet(**kw) -> PeticionIngesta:
    return PeticionIngesta(esquema=None, tabla=TABLA, destino="gm",
                           particionar_por=FECHA, columna_incremental=CLAVE, **kw)


def _leer(ruta) -> duckdb.DuckDBPyRelation:
    return f"read_parquet('{ruta}/**/*.parquet', hive_partitioning=true)"


# --------------------------------------------------------------------------- #
# Conexion e introspeccion
# --------------------------------------------------------------------------- #

@necesita_odbc
def test_probar_dice_el_motor_y_como_lo_trata(cliente, cab_admin, conexion_odbc):
    r = cliente.post(f"/api/conexiones/{conexion_odbc}/probar", headers=cab_admin)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["ok"] is True
    # Que el conector diga si trata la base como catalogo o como esquema no es
    # curiosidad: es la diferencia entre listar tablas y no listar nada, y con
    # el driver va a ser lo primero que haya que mirar.
    assert cuerpo["detalle"]["usa"] == "catalogo"
    assert "MySQL" in cuerpo["detalle"]["motor"]
    assert cuerpo["detalle"]["identificadores"] == "`…`"


@necesita_odbc
def test_listar_y_describir_por_odbc(cliente, cab_admin, conexion_odbc):
    r = cliente.get(f"/api/conexiones/{conexion_odbc}/tablas", headers=cab_admin)
    assert r.status_code == 200, r.text
    nombres = [t["nombre"] for t in r.json()["tablas"]]
    assert TABLA in nombres

    r = cliente.get(f"/api/conexiones/{conexion_odbc}/tablas/{TABLA}",
                    headers=cab_admin)
    assert r.status_code == 200, r.text
    cols = {c["nombre"]: c for c in r.json()["columnas"]}
    assert CLAVE in cols and FECHA in cols
    assert cols[CLAVE]["es_clave"] is True      # sale de cursor.primaryKeys
    assert r.json()["filas"] > 1000             # COUNT(*) real, no estimado


@necesita_odbc
def test_muestra_sin_limit_en_el_sql(cliente, cab_admin, conexion_odbc):
    """No hay LIMIT portable: se deja de leer. El resultado debe ser el mismo."""
    r = cliente.get(f"/api/conexiones/{conexion_odbc}/tablas/{TABLA}/muestra"
                    f"?limite=7", headers=cab_admin)
    assert r.status_code == 200, r.text
    assert len(r.json()["filas"]) == 7


@necesita_odbc
def test_esquemas_cae_al_catalogo_cuando_el_driver_no_admite_esquemas():
    """
    El driver de MariaDB responde "Schemas are not supported" a la enumeracion
    por esquema. El conector tiene que caer al catalogo, no quedarse en blanco.
    """
    assert BASE_MYSQL in _odbc().listar_esquemas()


# --------------------------------------------------------------------------- #
# Ingesta
# --------------------------------------------------------------------------- #

@necesita_odbc
def test_odbc_trae_lo_mismo_que_el_nativo(tmp_path):
    cfg = config_odbc()
    nativo = crear("mysql", {k: v for k, v in cfg.items() if k != "driver"})

    por_odbc = _odbc().ingestar(
        _pet(reemplazar_todo=True, limite=FILAS), str(tmp_path / "odbc"))
    por_nativo = nativo.ingestar(
        _pet(reemplazar_todo=True, limite=FILAS), str(tmp_path / "nativo"))

    assert por_odbc.filas == por_nativo.filas == FILAS
    assert por_odbc.particiones_escritas == por_nativo.particiones_escritas

    con = duckdb.connect()
    a, b = _leer(tmp_path / "odbc"), _leer(tmp_path / "nativo")
    sobran = con.execute(
        f"SELECT COUNT(*) FROM ((SELECT * FROM {a}) EXCEPT (SELECT * FROM {b}))"
    ).fetchone()[0]
    faltan = con.execute(
        f"SELECT COUNT(*) FROM ((SELECT * FROM {b}) EXCEPT (SELECT * FROM {a}))"
    ).fetchone()[0]
    assert (sobran, faltan) == (0, 0)


@necesita_odbc
def test_los_tipos_los_declara_el_origen(tmp_path):
    """
    Un DECIMAL debe llegar como DECIMAL y una fecha como DATE. Si los tipos se
    dedujeran de los datos, una columna de dinero acabaria como texto o con una
    precision que no le cabe.
    """
    _odbc().ingestar(_pet(reemplazar_todo=True, limite=200), str(tmp_path / "d"))
    con = duckdb.connect()
    tipos = dict(con.execute(
        f"DESCRIBE SELECT * FROM {_leer(tmp_path / 'd')}"
    ).df()[["column_name", "column_type"]].values)
    assert tipos[FECHA] == "DATE"
    assert tipos[CLAVE] == "BIGINT"
    assert any(t.startswith("DECIMAL") for t in tipos.values())


@necesita_odbc
def test_solo_las_columnas_elegidas(tmp_path):
    r = _odbc().ingestar(
        _pet(reemplazar_todo=True, limite=100, columnas=[CLAVE, FECHA, "monto_base"]),
        str(tmp_path / "c"))
    assert r.filas == 100
    con = duckdb.connect()
    cols = con.execute(f"SELECT * FROM {_leer(tmp_path / 'c')} LIMIT 1").df().columns
    # anio y mes las agrega el particionado, no el origen.
    assert set(cols) == {CLAVE, FECHA, "monto_base", "anio", "mes"}


@necesita_odbc
def test_incremental_no_repite(tmp_path):
    primera = _odbc().ingestar(
        _pet(reemplazar_todo=True, limite=300), str(tmp_path / "i"))
    assert primera.marca_maxima is not None

    segunda = _odbc().ingestar(
        _pet(desde=primera.marca_maxima, limite=300), str(tmp_path / "i"))
    con = duckdb.connect()
    total = con.execute(f"SELECT COUNT(*) FROM {_leer(tmp_path / 'i')}").fetchone()[0]
    assert total == primera.filas + segunda.filas


@necesita_odbc
def test_columna_inexistente_avisa_antes_de_mover_datos(tmp_path):
    with pytest.raises(ErrorConector) as e:
        _odbc().ingestar(
            PeticionIngesta(esquema=None, tabla=TABLA, destino="gm",
                            particionar_por="fecha_que_no_existe"),
            str(tmp_path / "x"))
    assert "no existe" in str(e.value)
    assert not (tmp_path / "x").exists() or not list((tmp_path / "x").rglob("*.parquet"))


# --------------------------------------------------------------------------- #
# Configuracion y secretos
# --------------------------------------------------------------------------- #

def test_sin_dsn_ni_driver_dice_que_falta():
    con = crear("odbc", {"database": "x"})
    r = con.probar()
    assert r.ok is False
    assert "DSN" in r.mensaje


def test_la_cadena_completa_no_devuelve_la_contrasena():
    """
    Es el unico sitio de la aplicacion donde un secreto viaja mezclado con la
    configuracion: dentro de la cadena ODBC. Tiene que salir enmascarado.
    """
    con = crear("odbc", {"cadena": "DRIVER={X};SERVER=s;UID=u;PWD=secreto123"})
    publica = con.config_publica()
    assert "secreto123" not in str(publica)
    assert "PWD=***" in publica["cadena"]


def test_el_endpoint_dice_que_hay_instalado(cliente, cab_admin):
    r = cliente.get("/api/conexiones/odbc/instalado", headers=cab_admin)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["disponible"] is True          # pyodbc esta en requirements
    assert isinstance(cuerpo["drivers"], list)
