"""
Una metrica que no ve el filtro de un campo: `ignora_filtros`.

El caso de verdad: un tablero con un filtro de segmento, y al lado de las ventas del
segmento elegido un total que tiene que quedarse fijo —el objetivo del mes, el
divisor de una participacion—. En Qlik es `{$<Segmento=>}`; en DAX,
`REMOVEFILTERS(Segmento)`.

Lo que se protege:
- con el filtro puesto, la metrica marcada da lo mismo que sin filtro;
- la de al lado, sin marca, si se filtra (si no, la prueba no diria nada);
- si el campo es del desglose, se sigue desglosando por el;
- una compuesta no puede llevar la marca, y un campo inventado no pasa callado.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")
_siguiente = itertools.count(1)

SUC = "cat_sucursal.sucursal_nombre"
SEG = "dim_vehiculo.segmento"

TOTAL = {"nombre": "unidades_todo_segmento", "etiqueta": "Unidades (todo segmento)",
         "formato": "entero", "entidad": "fact_venta", "expresion": "SUM(unidades)",
         "ignora_filtros": ["segmento"]}


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"sin_filtro_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _guardar(cliente, cab, mid, extra):
    d = cliente.get(f"/api/modelos/{mid}/definicion", headers=cab).json()["definicion"]
    d["metricas"] += extra
    return cliente.put(f"/api/modelos/{mid}/definicion", headers=cab, json={"definicion": d})


def _consultar(cliente, cab, mid, metricas, dims, filtros=None):
    r = cliente.post(f"/api/modelos/{mid}/consultar", headers=cab,
                     json={"dimensiones": dims, "metricas": metricas, "filtros": filtros or []})
    assert r.status_code == 200, r.text
    return r.json()["filas"]


def _un_segmento(cliente, cab, mid):
    filas = _consultar(cliente, cab, mid, ["unidades_vendidas"], [SEG])
    assert len(filas) > 1, "la demo necesita varios segmentos para que esto diga algo"
    return filas[0][SEG]


def test_con_el_filtro_puesto_da_lo_mismo_que_sin_el(cliente, cab_editor, modelo):
    assert _guardar(cliente, cab_editor, modelo, [dict(TOTAL)]).status_code == 201
    seg = _un_segmento(cliente, cab_editor, modelo)

    sin_filtro = {f[SUC]: f["unidades_vendidas"]
                  for f in _consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC])}
    filas = _consultar(cliente, cab_editor, modelo,
                       ["unidades_vendidas", "unidades_todo_segmento"], [SUC],
                       [{"campo": SEG, "op": "=", "valor": seg}])
    assert filas
    for f in filas:
        assert f["unidades_todo_segmento"] == sin_filtro[f[SUC]], f
    # La de al lado si se filtra: en alguna sucursal el segmento es solo una parte.
    assert any(f["unidades_vendidas"] < f["unidades_todo_segmento"] for f in filas)


def test_si_el_campo_es_del_desglose_se_sigue_desglosando(cliente, cab_editor, modelo):
    """Lo que se ignora es el filtro, no la columna."""
    assert _guardar(cliente, cab_editor, modelo, [dict(TOTAL)]).status_code == 201
    filas = _consultar(cliente, cab_editor, modelo,
                       ["unidades_vendidas", "unidades_todo_segmento"], [SEG])
    assert len(filas) > 1
    for f in filas:
        assert f["unidades_todo_segmento"] == f["unidades_vendidas"], f


def test_una_compuesta_no_puede_ignorar_filtros(cliente, cab_editor, modelo):
    r = _guardar(cliente, cab_editor, modelo, [
        {"nombre": "comp", "etiqueta": "Comp", "expresion": "[unidades_vendidas] * 2",
         "ignora_filtros": ["segmento"]}])
    assert r.status_code == 422
    assert "no puede ignorar" in r.text


def test_un_campo_que_no_existe_no_pasa_callado(cliente, cab_editor, modelo):
    r = _guardar(cliente, cab_editor, modelo, [dict(TOTAL, ignora_filtros=["segmentito"])])
    assert r.status_code == 422
    assert "segmentito" in r.text
