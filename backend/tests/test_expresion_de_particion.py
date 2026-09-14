"""
Convertir en fecha una columna que no lo es, para poder partir por ella.

Existe por los origenes antiguos, donde la fecha no es una fecha: viene como el
entero 20260914, o como texto en el formato del pais. Elegir esa columna como
particion no fallaba —dejaba las filas en la particion 'sin_fecha' y la carga
decia 'exito'— y codificar los formatos uno a uno habria sido una lista sin fin.
"""

from __future__ import annotations

import duckdb
import pytest

from app.conectores.base import PeticionIngesta, expresion_fecha
from tests.conftest import cargar, necesita_mysql, recargar_rango, ultima_carga

#: Lo que hay que escribir cuando la fecha es un entero 20260914, que es el caso
#: que destapo todo esto.
ENTERO_AAAAMMDD = "try_strptime(CAST(\"Dt Movim\" AS VARCHAR), '%Y%m%d')"


def _peticion(**kw) -> PeticionIngesta:
    base = dict(esquema=None, tabla="t", destino="d")
    return PeticionIngesta(**{**base, **kw})


def test_sin_expresion_la_columna_se_castea_tal_cual():
    p = _peticion(particionar_por="fecha_emision")
    assert expresion_fecha(p) == 'TRY_CAST(("fecha_emision") AS DATE)'


def test_con_expresion_se_usa_la_expresion():
    p = _peticion(particionar_por="Dt Movim", expresion_particion=ENTERO_AAAAMMDD)
    assert expresion_fecha(p) == f"TRY_CAST(({ENTERO_AAAAMMDD}) AS DATE)"


def test_el_try_cast_envuelve_tambien_a_la_expresion():
    """
    strptime devuelve TIMESTAMP, no DATE, y una fila suelta que no encaje no debe
    tumbar la carga entera. Las dos cosas las da el TRY_CAST de fuera.
    """
    p = _peticion(particionar_por="Dt Movim", expresion_particion=ENTERO_AAAAMMDD)
    con = duckdb.connect()
    con.execute('CREATE TABLE t AS SELECT * FROM (VALUES (20260914), (0), (NULL)) '
                'AS v("Dt Movim")')
    filas = con.execute(f"SELECT {expresion_fecha(p)} FROM t").fetchall()
    assert [f[0] for f in filas][0].isoformat() == "2026-09-14"
    assert filas[1][0] is None, "un valor imposible cae en sin_fecha, no revienta"
    assert filas[2][0] is None


@pytest.mark.parametrize("valor,expresion,esperado", [
    (20260914, "try_strptime(CAST(c AS VARCHAR), '%Y%m%d')", "2026-09-14"),
    ("14/09/2026", "try_strptime(c, '%d/%m/%Y')", "2026-09-14"),
    ("09/14/2026", "try_strptime(c, '%m/%d/%Y')", "2026-09-14"),
    (1260914, "try_strptime(CAST(c + 19000000 AS VARCHAR), '%Y%m%d')", "2026-09-14"),
])
def test_formatos_raros_que_se_pueden_escribir(valor, expresion, esperado):
    """
    La razon de que esto sea una expresion y no una lista de formatos: el mismo
    '03/04' es marzo o abril segun el pais, y hay codificaciones que no son un
    formato sino una cuenta (el entero con el siglo desplazado, de COBOL).
    """
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT ? AS c", [valor])
    r = con.execute(f"SELECT TRY_CAST(({expresion}) AS DATE) FROM t").fetchone()[0]
    assert r.isoformat() == esperado


@necesita_mysql
def test_partir_por_una_fecha_de_texto(cliente, cab_admin, conexion_mysql):
    """De punta a punta: columna de texto + expresion, y particiones de verdad."""
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "part_texto", "tabla": "ventas",
                           "particionar_por": "fecha_texto",
                           "expresion_particion": "try_strptime(\"fecha_texto\", '%Y-%m-%d')"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]

    e = cargar(cliente, cab_admin, ds, limite=2000)
    assert e["estado"] == "exito", e.get("mensaje")
    assert any(p.startswith("anio=20") for p in e["particiones"]), e["particiones"]

    # El origen trae un 1% de cadenas vacias. Con `strptime` la carga entera
    # reventaria en la primera; con `try_strptime` esas filas van a su particion y
    # las demas se fechan. Que la tolerancia exista es el punto.
    assert 0 < e["filas_sin_particion"] < e["filas"] // 10, e
    assert "anio=/mes=" in e["particiones"], "las vacias tienen que quedar aparte"


@necesita_mysql
def test_una_expresion_que_no_feche_nada_no_se_guarda(cliente, cab_admin,
                                                      conexion_mysql):
    """
    Se prueba contra filas de verdad ANTES de guardar. Sin esto, el error se
    descubre en la carga de las 6 de la manana y lo que se ve es un dataset vacio.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "expr_mala", "tabla": "ventas",
                           "particionar_por": "fecha_texto",
                           # El formato esta al reves para estos datos.
                           "expresion_particion": "try_strptime(\"fecha_texto\", '%d/%m/%Y')"})
    assert r.status_code == 422, r.text
    detalle = r.json()["detail"]
    assert "Ninguna" in detalle, detalle
    assert "fecha_texto" in detalle, "tiene que decir que columna"
    assert "-" in detalle.split("son así:")[1], "y ensenar los valores crudos"


@necesita_mysql
def test_una_expresion_que_no_compila_lo_dice(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "expr_rota", "tabla": "ventas",
                           "particionar_por": "fecha_texto",
                           "expresion_particion": "try_strptime(no_existe, '%Y')"})
    assert r.status_code == 422, r.text
    assert "no se pudo evaluar" in r.json()["detail"]


@necesita_mysql
def test_la_expresion_sin_columna_de_particion_no_vale(cliente, cab_admin,
                                                       conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "expr_sin_col", "tabla": "ventas",
                           "expresion_particion": "try_strptime(\"fecha_texto\", '%Y-%m-%d')"})
    assert r.status_code == 422, r.text
    assert "Partir por" in r.json()["detail"]


@necesita_mysql
def test_cambiar_la_expresion_obliga_a_carga_completa(cliente, cab_admin,
                                                      conexion_mysql):
    """
    La expresion cambia la fecha de CADA fila, asi que las mismas filas se mudan de
    particion. Dejar lo viejo donde estaba las duplicaria en dos meses distintos.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "expr_cambia", "tabla": "ventas",
                           "particionar_por": "fecha_texto",
                           "columna_incremental": "venta_id",
                           "expresion_particion": "try_strptime(\"fecha_texto\", '%Y-%m-%d')"})
    ds = r.json()["id"]
    cargar(cliente, cab_admin, ds, limite=500)

    lista = cliente.get("/api/conexiones/datasets/lista", headers=cab_admin).json()
    assert next(d for d in lista["datasets"] if d["id"] == ds)["marca_maxima"]

    r = cliente.patch(f"/api/conexiones/datasets/{ds}", headers=cab_admin,
                      json={"expresion_particion":
                            "try_strptime(SUBSTR(\"fecha_texto\", 1, 10), '%Y-%m-%d')"})
    assert r.status_code == 200, r.text
    assert any("completa" in a for a in r.json()["avisos"]), r.json()

    lista = cliente.get("/api/conexiones/datasets/lista", headers=cab_admin).json()
    assert next(d for d in lista["datasets"]
                if d["id"] == ds)["marca_maxima"] is None


@necesita_mysql
def test_el_rango_recorta_aunque_el_origen_no_filtre(cliente, cab_admin,
                                                    conexion_mysql):
    """
    El peligro de no filtrar en el origen: llega la tabla entera, y si se
    escribiera tal cual, las filas de fuera del rango se sumarian a sus
    particiones —que no se borraron— y quedarian por duplicado. El recorte se
    hace al escribir.
    """
    from app.cargas import ruta_dataset

    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "expr_rango", "tabla": "ventas",
                           "particionar_por": "fecha_texto",
                           "expresion_particion": "try_strptime(\"fecha_texto\", '%Y-%m-%d')"})
    ds = r.json()["id"]
    cargar(cliente, cab_admin, ds)

    con = duckdb.connect()
    destino = ruta_dataset("expr_rango")
    total = (f"SELECT COUNT(*) FROM read_parquet('{destino}/**/*.parquet', "
             f"hive_partitioning=1)")
    antes = con.execute(total).fetchone()[0]

    e = recargar_rango(cliente, cab_admin, ds, "2020-04-01", "2020-04-30")
    assert e["estado"] == "exito", e
    assert con.execute(total).fetchone()[0] == antes, (
        "recargar abril duplico filas de otros meses")


def test_el_recorte_al_escribir_no_deja_entrar_filas_de_fuera(tmp_path):
    """
    El camino de ODBC, donde el origen NO filtra: llega la tabla entera y el
    recorte lo hace el escritor. Sin el, las filas de fuera del rango se sumarian
    a sus particiones —que no se borraron, porque no estaban en el rango— y
    quedarian duplicadas.

    Se prueba contra `escribir_lote` y no por la API, porque por MySQL el filtro
    sí viaja al origen y el recorte nunca se llega a ejercitar: una prueba que
    pasa con el recorte desactivado no prueba nada.
    """
    from app.conectores.base import escribir_lote

    con = duckdb.connect()
    con.execute("""
        CREATE TABLE lote AS SELECT * FROM (VALUES
            (20260315, 'dentro'),
            (20260320, 'dentro'),
            (20260415, 'fuera: abril'),
            (20260215, 'fuera: febrero'),
            (0,        'sin fecha')
        ) AS v("Dt Movim", nota)
    """)
    p = PeticionIngesta(
        esquema=None, tabla="t", destino="d", particionar_por="Dt Movim",
        expresion_particion="try_strptime(CAST(\"Dt Movim\" AS VARCHAR), '%Y%m%d')",
        rango_desde="2026-03-01", rango_hasta="2026-03-31")

    r = escribir_lote(con, tmp_path, p, 0.0)

    assert r.particiones_escritas == ["anio=2026/mes=3"]
    escritas = duckdb.connect().execute(
        f"SELECT nota FROM read_parquet('{tmp_path}/**/*.parquet')").fetchall()
    assert sorted(n for (n,) in escritas) == ["dentro", "dentro"], escritas
    assert r.filas == 2, "el conteo tiene que ser el de lo escrito, no el de lo leido"
