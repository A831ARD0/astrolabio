"""
«Si no hay dato, cero»: una bandera por metrica, y por que hace falta.

El problema no es que una celda salga vacia — eso es hasta correcto. El problema es
que el vacio se **contagia a la operacion de al lado**:

    SI(stock > promedio, stock - promedio, 0)

con el promedio vacio no da falso: da NULO, y la rama se va al «si no» sin que nadie
lo pida. Asi que una familia que no vendio NADA en tres meses —la que tiene todo su
inventario de excedente— salia con excedente cero. La cifra mas alta posible saliendo
como la mas baja, sin un aviso.

Es opcional porque las dos lecturas son ciertas segun la metrica: en un objetivo,
vacio y cero son distintos —«no se ha cargado» contra «el objetivo es cero»— y taparlo
esconde una carga que falta.

Aqui `fact_presupuesto` hace de inventario, con sucursales que tienen objetivo y
ninguna venta: son las filas donde el promedio sale vacio.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)

SUC = "cat_sucursal.sucursal_nombre"
MES = "dim_calendario.anio_mes"


def base(cero_en_promedio: bool) -> list[dict]:
    return [
        {"nombre": "foto", "etiqueta": "Inventario", "formato": "entero",
         "entidad": "fact_presupuesto", "expresion": "SUM(objetivo_unidades)"},
        {"nombre": "prom3", "etiqueta": "Prom 3M", "formato": "numero",
         "expresion": "PROMEDIOMESES([unidades_vendidas], 3)",
         "sin_dato_cero": cero_en_promedio},
        {"nombre": "excedente", "etiqueta": "Excedente", "formato": "numero",
         "expresion": "SI([foto] > [prom3], [foto] - [prom3], 0)"},
    ]


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"cero_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def guardar(cliente, cab, mid: int, metricas: list[dict], foto=True):
    r = cliente.get(f"/api/modelos/{mid}/definicion", headers=cab)
    d = r.json()["definicion"]
    if foto:
        for e in d["entidades"]:
            if e["nombre"] == "fact_presupuesto":
                e["ignora_periodo"] = True
    d["metricas"] += [dict(m) for m in metricas]
    return cliente.put(f"/api/modelos/{mid}/definicion", headers=cab,
                       json={"definicion": d})


def consultar(cliente, cab, mid: int, metricas, dimensiones, filtros=None):
    return cliente.post(f"/api/modelos/{mid}/consultar", headers=cab,
                        json={"dimensiones": dimensiones, "metricas": metricas,
                              "filtros": filtros or []})


# --------------------------------------------------------------------------- #

def test_sin_la_bandera_el_vacio_se_contagia(cliente, cab_editor, modelo):
    """
    La foto existe, el promedio no, y el excedente sale CERO en vez de la foto
    entera. Es el fallo, escrito como prueba para que no vuelva sin avisar.
    """
    assert guardar(cliente, cab_editor, modelo, base(False)).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["foto", "prom3", "excedente"], [SUC])
    assert r.status_code == 200, r.text
    sin_promedio = [f for f in r.json()["filas"] if f["prom3"] is None]
    assert sin_promedio, "la demo tiene que traer sucursales sin ventas"
    for f in sin_promedio:
        assert f["foto"], f
        assert f["excedente"] == 0, f


def test_con_la_bandera_el_excedente_es_la_foto_entera(cliente, cab_editor, modelo):
    """
    Sin ventas en tres meses, el excedente es todo el inventario. Y donde SI hay
    promedio, la cifra no cambia: la bandera solo llena los huecos.
    """
    assert guardar(cliente, cab_editor, modelo, base(True)).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["foto", "prom3", "excedente"], [SUC])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]

    huecos = [f for f in filas if f["prom3"] == 0]
    assert huecos, "las que no tenian promedio ahora valen cero"
    for f in huecos:
        assert f["excedente"] == pytest.approx(f["foto"]), f

    con_dato = [f for f in filas if f["prom3"]]
    assert con_dato
    for f in con_dato:
        esperado = f["foto"] - f["prom3"] if f["foto"] > f["prom3"] else 0
        assert f["excedente"] == pytest.approx(esperado), f


def test_la_metrica_marcada_se_muestra_como_cero(cliente, cab_editor, modelo):
    """
    Tambien al mostrarla, no solo dentro de otra formula: una celda vacia y un cero
    se leen distinto, y quien marco la bandera dijo que ahi no hay «no se sabe».
    """
    assert guardar(cliente, cab_editor, modelo, base(True)).status_code == 201

    # Con la foto al lado: es la que trae las sucursales donde el promedio faltaria.
    r = consultar(cliente, cab_editor, modelo, ["foto", "prom3"], [SUC])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert len(filas) > 20, "hacen falta sucursales sin ventas para que diga algo"
    assert all(f["prom3"] is not None for f in filas), \
        [f for f in filas if f["prom3"] is None][:3]


def test_el_cero_inventado_no_decide_el_ultimo_mes_con_datos(cliente, cab_editor,
                                                             modelo):
    """
    El mes que manda se elige con la cifra CRUDA. Si un cero inventado contara como
    dato, el mes que manda seria el ultimo del calendario y las ventas saldrian en
    blanco — justo la fila que esto venia a arreglar.
    """
    assert guardar(cliente, cab_editor, modelo,
                   base(True) + [
                       {"nombre": "vtas", "etiqueta": "Ventas", "formato": "entero",
                        "expresion": "[unidades_vendidas]", "sin_dato_cero": True}],
                   ).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [MES])
    ultimo = max(f[MES] for f in r.json()["filas"] if f["unidades_vendidas"])

    r = consultar(cliente, cab_editor, modelo, ["vtas", "prom3"], [SUC])
    assert r.status_code == 200, r.text
    assert r.json()["mes_usado"] == ultimo, r.json().get("mes_usado")


def test_sin_marcar_nada_el_sql_no_cambia(cliente, cab_editor, modelo):
    """
    La bandera no puede tocar a quien no la puso: los tableros que ya cuadran tienen
    que seguir dando lo mismo, hasta en el vacio.
    """
    assert guardar(cliente, cab_editor, modelo, base(False)).status_code == 201
    # Con la foto al lado, que es la que trae las sucursales sin ninguna venta: sin
    # ella el desglose no tiene una sola fila donde el promedio pueda faltar.
    r = consultar(cliente, cab_editor, modelo, ["foto", "prom3"], [SUC])
    assert any(f["prom3"] is None for f in r.json()["filas"]), \
        "sin la bandera, lo que no tiene dato sigue vacio"
