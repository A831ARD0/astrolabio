"""
Caché de consultas y precalentado.

Lo que no puede pasar: que la caché devuelva un dato viejo después de una recarga,
o que una persona vea lo que guardó otra con más permisos. Lo demás es velocidad.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from app import precalentar
from app.analitico import invalidar_vistas
from app.cache_consultas import CacheResultados, cache

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")
SUC = "cat_sucursal.sucursal_nombre"
_siguiente = itertools.count(1)


# --------------------------------------------------------------------------- #
# La caché sola
# --------------------------------------------------------------------------- #

def test_guarda_y_devuelve_una_copia():
    c = CacheResultados(1024 * 1024)
    c.guardar("k", (("t", 0),), {"filas": [1, 2]})
    a = c.obtener("k", (("t", 0),))
    a["filas"].append(3)
    assert c.obtener("k", (("t", 0),)) == {"filas": [1, 2]}, "quien la usa no la estropea"


def test_si_cambian_los_datos_ya_no_vale():
    c = CacheResultados(1024 * 1024)
    c.guardar("k", (("t", 0),), {"x": 1})
    assert c.obtener("k", (("t", 1),)) is None
    assert c.estado()["entradas"] == 0, "la entrada vieja se tira"


def test_al_llenarse_sale_la_que_nadie_pidio():
    c = CacheResultados(1000)                # caben cuatro de ~210 bytes
    for k in "abcd":
        c.guardar(k, (), {"v": "x" * 200})
    c.obtener("a", ())                       # a se usó: queda
    c.guardar("e", (), {"v": "x" * 200})
    assert c.obtener("a", ()) is not None
    assert c.obtener("b", ()) is None


def test_con_cero_megas_no_guarda_nada():
    c = CacheResultados(0)
    c.guardar("k", (), {"x": 1})
    assert c.obtener("k", ()) is None


# --------------------------------------------------------------------------- #
# Por la API
# --------------------------------------------------------------------------- #

@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"cache_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _consultar(cliente, cab, mid, filtros=None):
    return cliente.post(f"/api/modelos/{mid}/consultar", headers=cab,
                        json={"dimensiones": [SUC], "metricas": ["unidades_vendidas"],
                              "filtros": filtros or []})


def test_la_segunda_vez_sale_de_la_cache_con_lo_mismo(cliente, cab_admin, modelo):
    cache().limpiar()
    a = _consultar(cliente, cab_admin, modelo)
    b = _consultar(cliente, cab_admin, modelo)
    assert a.status_code == b.status_code == 200
    assert a.json()["desde_cache"] is False
    assert b.json()["desde_cache"] is True
    assert a.json()["filas"] == b.json()["filas"]


def test_otro_filtro_es_otra_entrada(cliente, cab_admin, modelo):
    cache().limpiar()
    _consultar(cliente, cab_admin, modelo)
    r = _consultar(cliente, cab_admin, modelo,
                   [{"campo": SUC, "op": "=", "valor": "Aurex-HP Cabo Sur"}])
    assert r.json()["desde_cache"] is False


def test_una_recarga_de_sus_tablas_la_invalida(cliente, cab_admin, modelo):
    """Lo que no puede pasar nunca: un dato viejo después de recargar."""
    cache().limpiar()
    _consultar(cliente, cab_admin, modelo)
    tablas = cliente.get(f"/api/modelos/{modelo}/definicion",
                         headers=cab_admin).json()["definicion"]["entidades"]
    invalidar_vistas(tablas[0]["origen"]["tabla"])
    assert _consultar(cliente, cab_admin, modelo).json()["desde_cache"] is False


def test_la_recarga_de_otra_tabla_no_la_invalida(cliente, cab_admin, modelo):
    cache().limpiar()
    _consultar(cliente, cab_admin, modelo)
    invalidar_vistas("una_tabla_que_este_modelo_no_lee")
    assert _consultar(cliente, cab_admin, modelo).json()["desde_cache"] is True


def test_los_filtros_del_tablero_tambien_se_guardan(cliente, cab_admin, modelo):
    cache().limpiar()
    cuerpo = {"entidad": "cat_sucursal", "campo": "sucursal_nombre", "selecciones": {}}
    a = cliente.post(f"/api/modelos/{modelo}/asociativo", headers=cab_admin, json=cuerpo)
    antes = cache().estado()["aciertos"]
    b = cliente.post(f"/api/modelos/{modelo}/asociativo", headers=cab_admin, json=cuerpo)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert cache().estado()["aciertos"] == antes + 1


def test_el_estado_y_vaciar_son_de_administrador(cliente, cab_admin, cab_lector):
    assert cliente.get("/api/gobierno/cache", headers=cab_lector).status_code == 403
    r = cliente.get("/api/gobierno/cache", headers=cab_admin)
    assert r.status_code == 200 and "cache" in r.json()
    r = cliente.delete("/api/gobierno/cache", headers=cab_admin)
    assert r.status_code == 200
    assert cache().estado()["entradas"] == 0


# --------------------------------------------------------------------------- #
# Precalentado
# --------------------------------------------------------------------------- #

def test_precalentar_repite_lo_que_se_uso_y_deja_la_cache_llena(cliente, cab_admin,
                                                                modelo):
    """
    Se consulta (queda registrada), se recargan los datos (la caché deja de valer),
    se precalienta: la siguiente petición ya sale de la caché.
    """
    cache().limpiar()
    _consultar(cliente, cab_admin, modelo)
    tablas = cliente.get(f"/api/modelos/{modelo}/definicion",
                         headers=cab_admin).json()["definicion"]["entidades"]
    invalidar_vistas(*[t["origen"]["tabla"] for t in tablas])

    r = cliente.post("/api/gobierno/cache/precalentar", headers=cab_admin)
    assert r.status_code == 200, r.text
    assert r.json()["calentadas"] >= 1
    assert _consultar(cliente, cab_admin, modelo).json()["desde_cache"] is True


def test_lo_que_nadie_usa_en_dias_se_olvida(monkeypatch):
    from datetime import datetime, timedelta, timezone

    viejo = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    reg = {"a": {"veces": 9, "ultima": viejo},
           "b": {"veces": 1, "ultima": datetime.now(timezone.utc).isoformat()}}
    precalentar._podar(reg)
    assert list(reg) == ["b"]
