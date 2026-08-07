"""
Elegir columnas, y ventanas moviles de recarga.

Las ventanas se prueban con la fecha fijada. Una funcion que lee el reloj por
dentro no se puede verificar, y aqui equivocarse de un dia significa un mes que no
se recarga y nadie lo nota.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from app.ventanas import VentanaInvalida, describir, resolver
from tests.conftest import cargar, necesita_mysql

HOY = date(2026, 8, 5)      # miercoles, para que "mes actual" tenga dias antes


# --------------------------------------------------------------------------- #
# El calculo de la ventana
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("clave,esperado", [
    ("dia_anterior",           ("2026-08-04", "2026-08-05")),
    ("ultimos_7_dias",         ("2026-07-29", "2026-08-05")),
    ("ultimos_30_dias",        ("2026-07-06", "2026-08-05")),
    ("mes_actual",             ("2026-08-01", "2026-08-05")),
    ("mes_actual_y_anterior",  ("2026-07-01", "2026-08-05")),
    ("anio_actual",            ("2026-01-01", "2026-08-05")),
    ("ultimos_2_anios",        ("2025-01-01", "2026-08-05")),
    ("ultimos_dias:45",        ("2026-06-21", "2026-08-05")),
])
def test_cada_ventana_da_su_rango(clave, esperado):
    assert resolver(clave, hoy=HOY) == esperado


def test_el_mes_anterior_cruza_el_ano():
    """Enero menos un mes es diciembre del ano pasado, no el mes cero."""
    assert resolver("mes_actual_y_anterior", hoy=date(2026, 1, 9))[0] == "2025-12-01"


def test_una_ventana_inventada_no_pasa_callada():
    with pytest.raises(VentanaInvalida) as e:
        resolver("el_mes_que_viene")
    assert "mes_actual" in str(e.value)      # el error dice cuales valen


def test_la_descripcion_dice_las_fechas():
    dicho = describir("mes_actual_y_anterior", hoy=HOY)
    assert "2026-07-01" in dicho and "2026-08-05" in dicho


def test_una_zona_mal_escrita_no_tumba_la_carga():
    """Se resuelve con UTC en vez de reventar: la carga vale mas que la precision."""
    desde, hasta = resolver("mes_actual", zona="Marte/Olimpo")
    assert desde <= hasta


# --------------------------------------------------------------------------- #
# Columnas elegidas
# --------------------------------------------------------------------------- #

@necesita_mysql
def test_solo_trae_las_columnas_elegidas(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "cols_elegidas", "tabla": "cat_sucursal",
                           "columnas": ["sucursal_id", "sucursal_nombre"]})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]

    cargar(cliente, cab_admin, ds)

    from app.cargas import ruta_dataset
    con = duckdb.connect()
    cols = con.execute(
        f"SELECT * FROM read_parquet('{ruta_dataset('cols_elegidas')}/**/*.parquet') "
        f"LIMIT 1").df().columns.tolist()
    assert cols == ["sucursal_id", "sucursal_nombre"]


@necesita_mysql
def test_no_deja_dejar_fuera_la_columna_de_particion(cliente, cab_admin,
                                                    conexion_mysql):
    """
    Es el error que hay que atajar al guardar: el dataset se guardaria bien y la
    carga fallaria de madrugada diciendo que la columna no existe.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "sin_particion", "tabla": "ventas",
                           "particionar_por": "fecha_emision",
                           "columnas": ["venta_id", "monto_base"]})
    assert r.status_code == 422, r.text
    assert "partición" in r.json()["detail"]


@necesita_mysql
def test_una_columna_inexistente_se_rechaza(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "col_inventada", "tabla": "cat_sucursal",
                           "columnas": ["sucursal_id", "columna_que_no_existe"]})
    assert r.status_code == 422, r.text
    assert "columna_que_no_existe" in r.json()["detail"]


@necesita_mysql
def test_cambiar_columnas_obliga_a_carga_completa(cliente, cab_admin,
                                                 conexion_mysql):
    """
    El Parquet en disco tiene las columnas viejas. Agregar un lote con otras
    columnas haria que leer el dataset fallara o devolviera nulos, asi que la marca
    se borra y la siguiente carga reescribe todo. Y se avisa.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "cambia_cols", "tabla": "cat_sucursal",
                           "columna_incremental": "sucursal_id",
                           "columnas": ["sucursal_id", "sucursal_nombre"]})
    ds = r.json()["id"]
    cargar(cliente, cab_admin, ds)

    lista = cliente.get("/api/conexiones/datasets/lista", headers=cab_admin).json()
    antes = next(d for d in lista["datasets"] if d["id"] == ds)
    assert antes["marca_maxima"] is not None

    r = cliente.patch(f"/api/conexiones/datasets/{ds}", headers=cab_admin,
                      json={"columnas": ["sucursal_id", "sucursal_nombre", "marca_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["avisos"], "cambiar columnas tiene que avisar"

    lista = cliente.get("/api/conexiones/datasets/lista", headers=cab_admin).json()
    despues = next(d for d in lista["datasets"] if d["id"] == ds)
    assert despues["marca_maxima"] is None
    assert despues["columnas"] == ["sucursal_id", "sucursal_nombre", "marca_id"]


@necesita_mysql
def test_volver_a_todas_las_columnas(cliente, cab_admin, conexion_mysql):
    """Lista vacia = todas. Sin ese centinela no habria forma de deshacer."""
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "vuelve_todas", "tabla": "cat_sucursal",
                           "columnas": ["sucursal_id"]})
    ds = r.json()["id"]
    r = cliente.patch(f"/api/conexiones/datasets/{ds}", headers=cab_admin,
                      json={"columnas": []})
    assert r.status_code == 200, r.text
    assert r.json()["columnas"] is None


@necesita_mysql
def test_la_muestra_solo_trae_lo_elegido(cliente, cab_admin, conexion_mysql):
    r = cliente.get(f"/api/conexiones/{conexion_mysql}/tablas/cat_sucursal/muestra"
                    f"?limite=3&columnas=sucursal_id,sucursal_nombre", headers=cab_admin)
    assert r.status_code == 200, r.text
    assert r.json()["columnas"] == ["sucursal_id", "sucursal_nombre"]


# --------------------------------------------------------------------------- #
# La ventana en una carga de verdad
# --------------------------------------------------------------------------- #

def test_el_catalogo_de_ventanas_esta_en_la_api(cliente, cab_admin):
    r = cliente.get("/api/conexiones/ventanas", headers=cab_admin)
    assert r.status_code == 200, r.text
    claves = [v["clave"] for v in r.json()["ventanas"]]
    assert "mes_actual_y_anterior" in claves and "ultimos_dias:N" in claves


@necesita_mysql
def test_una_ventana_sin_particion_no_se_guarda(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "ventana_sin_part", "tabla": "cat_sucursal",
                           "ventana": "mes_actual"})
    assert r.status_code == 422, r.text
    assert "partido" in r.json()["detail"]


@necesita_mysql
def test_la_ventana_convierte_la_carga_en_recarga_de_particiones(
        cliente, cab_admin, conexion_mysql):
    """
    Con ventana, la carga deja de ser incremental y pasa a reemplazar particiones.
    Es lo que hace que una fila corregida hace tres semanas se vuelva a traer: la
    carga incremental por clave nunca la volveria a mirar.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "con_ventana", "tabla": "ventas",
                           "particionar_por": "fecha_emision", "columna_incremental": "venta_id",
                           "ventana": "ultimos_2_anios"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]
    assert "del 20" in r.json()["ventana"]        # dice las fechas al guardar

    d = cargar(cliente, cab_admin, ds, limite=2000)
    assert d["modo"] == "particion"
    assert d["ventana"] == "ultimos_2_anios"
    assert d["rango"][0] < d["rango"][1]

    # Y queda en el historial: sin esto, mirando una corrida de madrugada no se
    # sabria por que solo se tocaron unas particiones.
    h = cliente.get(f"/api/conexiones/datasets/{ds}/historial", headers=cab_admin)
    assert h.json()["ejecuciones"][0]["detalle"]["ventana"] == "ultimos_2_anios"


@necesita_mysql
def test_la_carga_completa_se_salta_la_ventana(cliente, cab_admin, conexion_mysql):
    """Quien pide "volver a traer todo" quiere todo, no el mes en curso."""
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "ventana_saltada", "tabla": "ventas",
                           "particionar_por": "fecha_emision", "ventana": "mes_actual"})
    ds = r.json()["id"]
    d = cargar(cliente, cab_admin, ds, incremental="false", limite=500)
    assert d["modo"] == "completo"
    assert d["ventana"] is None
