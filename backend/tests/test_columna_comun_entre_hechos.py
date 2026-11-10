"""
Una columna que tienen varios hechos se lee de cada uno.

Las ventas y los servicios traen los dos `vehiculo_id`. Pedir el desglose por
`fact_venta.vehiculo_id` junto a una cifra de servicio no puede significar «unir
cada servicio con cada venta»: eso repite las cifras y casi nunca tiene un solo
camino. Significa lo mismo que en Qlik, donde el campo es uno solo: cada hecho
desglosado por SU vehículo.

Se comprueba contra la cifra pedida por la columna del propio hecho, no contra si
misma.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")
_siguiente = itertools.count(1)

SERV = "venta_mano_obra"
VENTA = "unidades_vendidas"


@pytest.fixture
def mid(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"comun_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _consultar(cliente, cab, mid, dims, metricas, filtros=None):
    r = cliente.post(f"/api/modelos/{mid}/consultar", headers=cab,
                     json={"dimensiones": dims, "metricas": metricas, "filtros": filtros or []})
    assert r.status_code == 200, r.text
    return r.json()["filas"]


def test_el_desglose_por_la_columna_de_otro_hecho_usa_la_propia(cliente, cab_admin, mid):
    propia = {f["fact_servicio.vehiculo_id"]: f[SERV]
              for f in _consultar(cliente, cab_admin, mid, ["fact_servicio.vehiculo_id"], [SERV])}
    assert len(propia) > 3, "la demo tiene que traer servicios de varios vehículos"

    filas = _consultar(cliente, cab_admin, mid, ["fact_venta.vehiculo_id"], [VENTA, SERV])
    servicio = {f["fact_venta.vehiculo_id"]: f[SERV] for f in filas if f.get(SERV)}
    assert len(servicio) > 3
    for k, v in servicio.items():
        # la suma en otro orden cambia el último decimal del flotante
        assert v == pytest.approx(propia[k]), k


def test_un_filtro_sobre_la_columna_de_otro_hecho_tambien(cliente, cab_admin, mid):
    propia = _consultar(cliente, cab_admin, mid, ["fact_servicio.vehiculo_id"], [SERV])
    vehiculo = propia[0]["fact_servicio.vehiculo_id"]
    esperado = propia[0][SERV]
    filas = _consultar(cliente, cab_admin, mid, [], [SERV],
                       [{"campo": "fact_venta.vehiculo_id", "op": "=", "valor": vehiculo}])
    assert filas[0][SERV] == pytest.approx(esperado)
