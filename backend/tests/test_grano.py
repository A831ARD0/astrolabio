"""
El grano, comprobado contra los datos.

El grano son las columnas que **juntas** identifican una fila. En una tabla de
objetivos son la sucursal y el mes: por separado los dos se repiten —cada mes
vuelven todas las sucursales— y juntos no deberían.

Es una **afirmación**, y hasta ahora nadie la comprobaba: se guardaba y ya. Si el
mes se carga dos veces, el objetivo se duplica, el porcentaje de logro sale a la
mitad y nada protesta. Esto lo dice en una consulta.

Y no es lo mismo que la clave primaria. La clave primaria es UNA columna —es por
donde se une— y aquí no existe ninguna que sirva: declarar `ID_Sucursal` como
clave primaria es afirmar que no se repite, que es falso.
"""

import itertools

import pytest

_siguiente = itertools.count(1)


@pytest.fixture
def modelo(cliente, cab_admin, yaml_modelo):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"grano_{next(_siguiente)}", "yaml": yaml_modelo})
    assert r.status_code == 201, r.text
    identificador = r.json()["id"]
    yield identificador
    cliente.delete(f"/api/modelos/{identificador}", headers=cab_admin)


def definicion(cliente, cab, modelo_id: int) -> dict:
    return cliente.get(f"/api/modelos/{modelo_id}/definicion",
                       headers=cab).json()["definicion"]


def comprobar(cliente, cab, modelo_id: int, entidad: str, d=None):
    cuerpo = {"entidad": entidad}
    if d is not None:
        cuerpo["definicion"] = d
    return cliente.post(f"/api/modelos/{modelo_id}/comprobar-grano",
                        headers=cab, json=cuerpo)


def con_grano(d: dict, entidad: str, grano: list[str]) -> dict:
    return {**d, "entidades": [
        {**e, "grano": grano} if e["nombre"] == entidad else e
        for e in d["entidades"]]}


# --------------------------------------------------------------------------- #

def test_un_grano_que_se_cumple(cliente, cab_editor, modelo):
    """
    `fact_presupuesto` tiene una fila por sucursal y mes, que es exactamente su
    grano declarado.
    """
    r = comprobar(cliente, cab_editor, modelo, "fact_presupuesto")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["grano"] == ["sucursal_id", "anio_mes"]
    assert d["filas"] > 0
    assert d["cumple"] is True
    assert d["repetidas"] == 0
    assert d["filas"] == d["combinaciones"]


def test_un_grano_que_no_se_cumple_lo_dice_con_numeros(cliente, cab_editor,
                                                       modelo):
    """
    Se declara un grano falso —solo la sucursal, cuando hay una fila por sucursal
    Y mes— y tiene que salir cuántas filas sobran. El número importa: «sobran
    tres» y «sobran cuatro mil» se arreglan de formas distintas.
    """
    d = definicion(cliente, cab_editor, modelo)
    r = comprobar(cliente, cab_editor, modelo, "fact_presupuesto",
                  con_grano(d, "fact_presupuesto", ["sucursal_id"]))
    assert r.status_code == 200, r.text
    x = r.json()
    assert x["cumple"] is False
    assert x["repetidas"] > 0
    assert x["repetidas"] == x["filas"] - x["combinaciones"]
    # Y las combinaciones son las sucursales, no las filas.
    assert x["combinaciones"] < x["filas"]


def test_se_puede_comprobar_sin_haber_guardado(cliente, cab_editor, modelo):
    """
    Es justo el momento en que uno duda: mientras declara el grano. Mandar la
    definición del navegador permite comprobarlo antes de guardar.
    """
    d = definicion(cliente, cab_editor, modelo)
    con = con_grano(d, "fact_venta", ["venta_id", "sucursal_id"])
    r = comprobar(cliente, cab_editor, modelo, "fact_venta", con)
    assert r.status_code == 200, r.text
    assert r.json()["grano"] == ["venta_id", "sucursal_id"]
    # Lo guardado sigue siendo lo de antes.
    assert definicion(cliente, cab_editor, modelo) == d


def test_sin_grano_declarado_se_explica(cliente, cab_editor, modelo):
    d = definicion(cliente, cab_editor, modelo)
    r = comprobar(cliente, cab_editor, modelo, "cat_sucursal",
                  con_grano(d, "cat_sucursal", []))
    assert r.status_code == 422, r.text
    assert "no declara grano" in r.text


def test_una_entidad_que_no_existe(cliente, cab_editor, modelo):
    r = comprobar(cliente, cab_editor, modelo, "no_existe")
    assert r.status_code == 404


def test_un_lector_no_puede(cliente, cab_lector, modelo):
    """Lee de la tabla entera: es trabajo de quien edita el modelo."""
    assert comprobar(cliente, cab_lector, modelo,
                     "fact_presupuesto").status_code == 403


def test_no_devuelve_ninguna_fila_de_datos(cliente, cab_editor, modelo):
    """
    Solo dos números. La comprobación no pasa por las políticas de seguridad
    —filtrar filas cambiaría justo lo que se está contando— así que no puede
    devolver contenido.
    """
    r = comprobar(cliente, cab_editor, modelo, "fact_presupuesto")
    assert set(r.json()) == {"entidad", "grano", "filas", "combinaciones",
                             "repetidas", "cumple", "sql"}
