"""
Etiquetas de conexion: la constante de cada sucursal.

Es el equivalente de la variable por sucursal de un script de Qlik. Cuarenta
agencias con el mismo sistema dan cuarenta veces la misma tabla, y una vez
apiladas no hay forma de saber de cual venia cada fila: la etiqueta es ese dato.

Dos cosas que se protegen aqui y que valen mas que la funcionalidad en si:

- Las etiquetas se agregan al LEER, no se escriben en el Parquet. Corregir el
  numero de una sucursal no puede obligar a volver a extraer sus tablas.
- Apilar «la misma tabla de todas las conexiones» se DETIENE si a alguna le
  faltan datos, en vez de devolver un total al que le faltan sucursales sin que
  nadie lo note.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from app.materializar import _catalogo_de_datasets, previsualizar
from semantic.transformacion import Transformacion


def _carpeta(nombre: str, filas: list[tuple]) -> Path:
    d = Path(tempfile.mkdtemp(prefix=f"astro_{nombre}_"))
    with open(d / "datos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cliente", "monto"])
        w.writerows(filas)
    return d


@pytest.fixture
def dos_sucursales(cliente, cab_admin):
    """
    Dos conexiones de archivo con la MISMA tabla —'datos.csv'— y un dataset
    cargado en cada una. Es la forma de cuarenta sucursales, en pequeno.
    """
    hechas = []
    for nombre, filas, etiquetas in [
        ("suc_norte", [("Ana", 100), ("Beto", 200)], {"id_sucursal": 1}),
        ("suc_sur", [("Cira", 300)], {"id_sucursal": 2}),
    ]:
        lista = cliente.get("/api/conexiones", headers=cab_admin).json()
        con = next((c["id"] for c in lista if c["nombre"] == nombre), None)
        if con is None:
            r = cliente.post("/api/conexiones", headers=cab_admin, json={
                "nombre": nombre, "tipo": "archivo",
                "config": {"ruta_base": str(_carpeta(nombre, filas))}})
            assert r.status_code == 201, r.text
            con = r.json()["id"]

        ds_nombre = f"{nombre}__datos"
        datasets = cliente.get("/api/conexiones/datasets/lista",
                               headers=cab_admin).json()["datasets"]
        if not any(d["nombre"] == ds_nombre for d in datasets):
            r = cliente.post(f"/api/conexiones/{con}/datasets", headers=cab_admin,
                             json={"nombre": ds_nombre, "tabla": "datos.csv"})
            assert r.status_code == 201, r.text
            ds = r.json()["id"]
            assert cliente.post(
                f"/api/conexiones/datasets/{ds}/cargar",
                headers=cab_admin).status_code == 200

        hechas.append((con, ds_nombre, etiquetas))

    cliente.put("/api/conexiones/etiquetas", headers=cab_admin, json={
        "cambios": [{"conexion_id": c, "etiquetas": e} for c, _, e in hechas]})
    return {n: (c, e) for c, n, e in hechas}


# --------------------------------------------------------------------------- #
# Guardar
# --------------------------------------------------------------------------- #

def test_las_etiquetas_salen_en_la_lista(cliente, cab_admin, dos_sucursales):
    lista = cliente.get("/api/conexiones", headers=cab_admin).json()
    norte = next(c for c in lista if c["nombre"] == "suc_norte")
    assert norte["etiquetas"] == {"id_sucursal": 1}


def test_una_etiqueta_tiene_que_servir_de_nombre_de_columna(cliente, cab_admin,
                                                            dos_sucursales):
    con, _ = dos_sucursales["suc_norte__datos"]
    r = cliente.put("/api/conexiones/etiquetas", headers=cab_admin, json={
        "cambios": [{"conexion_id": con, "etiquetas": {"id sucursal": 1}}]})
    assert r.status_code == 422
    assert "nombre de columna" in r.text


def test_un_valor_vacio_no_pone_la_columna(cliente, cab_admin, dos_sucursales):
    # Una columna de cadenas vacias se lee como dato y no lo es.
    con, _ = dos_sucursales["suc_norte__datos"]
    cliente.put("/api/conexiones/etiquetas", headers=cab_admin, json={
        "cambios": [{"conexion_id": con,
                     "etiquetas": {"id_sucursal": 1, "marca": "   "}}]})
    lista = cliente.get("/api/conexiones", headers=cab_admin).json()
    norte = next(c for c in lista if c["nombre"] == "suc_norte")
    assert norte["etiquetas"] == {"id_sucursal": 1}


def test_se_guardan_varias_conexiones_de_una_vez(cliente, cab_admin,
                                                 dos_sucursales):
    ids = [c for c, _ in dos_sucursales.values()]
    r = cliente.put("/api/conexiones/etiquetas", headers=cab_admin, json={
        "cambios": [{"conexion_id": i, "etiquetas": {"id_sucursal": 9, "pais": "MX"}}
                    for i in ids]})
    assert r.status_code == 200, r.text
    assert r.json()["cambiadas"] == 2


# --------------------------------------------------------------------------- #
# Leer
# --------------------------------------------------------------------------- #

def test_la_etiqueta_sale_como_columna_al_leer(dos_sucursales):
    d = Transformacion.model_validate({
        "nombre": "prueba_etiqueta",
        "origenes": [{"nombre": "x", "tipo": "dataset",
                      "referencia": "suc_norte__datos"}],
        "pasos": [],
    })
    r = previsualizar(d, con_conteos=False)
    assert "id_sucursal" in r.columnas
    assert {f["id_sucursal"] for f in r.filas} == {1}


def test_la_etiqueta_no_se_escribe_en_el_parquet(dos_sucursales):
    """
    Lo que hace que corregir un numero no cueste una re-extraccion: el archivo
    no la lleva, se agrega al leer.
    """
    import duckdb

    from app.materializar import ruta_datos_dataset

    ruta = ruta_datos_dataset("suc_norte__datos")
    cols = [d[0] for d in duckdb.sql(
        f"SELECT * FROM read_parquet('{ruta}') LIMIT 0").description]
    assert "id_sucursal" not in cols


def test_apilar_la_misma_tabla_de_todas_las_conexiones(dos_sucursales):
    d = Transformacion.model_validate({
        "nombre": "prueba_apilado",
        "origenes": [{"nombre": "todo", "tipo": "tabla_en_conexiones",
                      "referencia": "datos.csv"}],
        "pasos": [],
    })
    r = previsualizar(d, con_conteos=False)
    # Las tres filas de las dos sucursales, cada una con su etiqueta.
    assert len(r.filas) == 3
    assert sorted(f["id_sucursal"] for f in r.filas) == [1, 1, 2]


def test_el_catalogo_agrupa_los_datasets_por_su_tabla(dos_sucursales):
    _, por_tabla = _catalogo_de_datasets()
    assert set(por_tabla["datos.csv"]) >= {"suc_norte__datos", "suc_sur__datos"}


def test_una_etiqueta_que_choca_con_una_columna_se_avisa(cliente, cab_admin,
                                                         dos_sucursales):
    from semantic.transformacion import ErrorTransformacion

    con, _ = dos_sucursales["suc_norte__datos"]
    cliente.put("/api/conexiones/etiquetas", headers=cab_admin, json={
        "cambios": [{"conexion_id": con, "etiquetas": {"cliente": "X"}}]})

    d = Transformacion.model_validate({
        "nombre": "prueba_choque",
        "origenes": [{"nombre": "x", "tipo": "dataset",
                      "referencia": "suc_norte__datos"}],
        "pasos": [],
    })
    with pytest.raises(ErrorTransformacion) as e:
        previsualizar(d, con_conteos=False)
    assert "cliente" in str(e.value)

    # Dejarlo como estaba para las demas pruebas.
    cliente.put("/api/conexiones/etiquetas", headers=cab_admin, json={
        "cambios": [{"conexion_id": con, "etiquetas": {"id_sucursal": 1}}]})


def test_si_a_una_sucursal_le_faltan_datos_se_detiene(cliente, cab_admin,
                                                      dos_sucursales):
    """
    La regla del proyecto, otra vez: un total al que le faltan sucursales parece
    fresco y no lo es. Se para y se dice cual falta.
    """
    from semantic.transformacion import ErrorTransformacion

    lista = cliente.get("/api/conexiones", headers=cab_admin).json()
    con = next(c["id"] for c in lista if c["nombre"] == "suc_norte")
    r = cliente.post(f"/api/conexiones/{con}/datasets", headers=cab_admin,
                     json={"nombre": "suc_norte__sin_cargar", "tabla": "datos.csv"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]
    try:
        d = Transformacion.model_validate({
            "nombre": "prueba_incompleto",
            "origenes": [{"nombre": "todo", "tipo": "tabla_en_conexiones",
                          "referencia": "datos.csv"}],
            "pasos": [],
        })
        with pytest.raises(ErrorTransformacion) as e:
            previsualizar(d, con_conteos=False)
        assert "suc_norte__sin_cargar" in str(e.value)
    finally:
        cliente.delete(f"/api/conexiones/datasets/{ds}", headers=cab_admin)


def test_el_linaje_apunta_a_todos_los_datasets_apilados(cliente, cab_admin,
                                                        dos_sucursales):
    """
    Sin esto, un flujo no sabria que hay que cargar las cuarenta ANTES de
    recalcular, y el orden automatico quedaria mal.
    """
    from app.db import CrearSesion
    from app.transformar import linaje

    d = Transformacion.model_validate({
        "nombre": "prueba_linaje",
        "origenes": [{"nombre": "todo", "tipo": "tabla_en_conexiones",
                      "referencia": "datos.csv"}],
        "pasos": [],
    })
    with CrearSesion() as sesion:
        lee = linaje(sesion, d)
    assert set(lee["datasets"]) >= {"suc_norte__datos", "suc_sur__datos"}
