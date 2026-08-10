"""
Tablas de medidas: cajones que el usuario inventa para ordenar sus metricas.

Es la «tabla de medidas» de Power BI, y como alli **solo organiza**. Ese es el punto
delicado y lo que estas pruebas fijan: la entidad de una metrica sigue siendo de donde
se calcula —lo que decide el FROM del SQL— y la tabla de medidas es solo donde se
muestra. Si algun dia una de las dos se comiera a la otra, la cifra cambiaria de
significado por haber movido una metrica de cajon, que es exactamente lo que no puede
pasar.

Se protege tambien que no exista una tabla de medidas llamada igual que una entidad
—dos cosas distintas con el mismo nombre en el mismo panel es no saber que se mira— y
que las metricas de antes, sin cajon, sigan valiendo.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"medidas_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def definicion(con_tabla: bool = True) -> dict:
    d = {
        "modelo": "prueba", "version": 1,
        "entidades": [
            {"nombre": "hecho_b", "tipo": "hecho",
             "origen": {"tabla": "fact_venta"}, "grano": ["venta_id"],
             "campos": [{"nombre": "venta_id", "tipo": "entero", "rol": "clave"},
                        {"nombre": "monto_base", "tipo": "decimal",
                         "rol": "medida_base"}]},
        ],
        "relaciones": [],
        "metricas": [{"nombre": "venta", "etiqueta": "Venta", "entidad": "hecho_b",
                      "expresion": "SUMA(monto_base)"}],
    }
    if con_tabla:
        d["tablas_medidas"] = [{"nombre": "KPIs de venta",
                                "descripcion": "Lo que mira comercial"}]
        d["metricas"][0]["tabla_medidas"] = "KPIs de venta"
    return d


def guardar(cliente, cab, modelo_id: int, d: dict):
    return cliente.put(f"/api/modelos/{modelo_id}/definicion", headers=cab,
                       json={"definicion": d})


# --------------------------------------------------------------------------- #
# Guardar y leer
# --------------------------------------------------------------------------- #

def test_una_tabla_de_medidas_se_guarda_y_vuelve(cliente, cab_admin, modelo):
    assert guardar(cliente, cab_admin, modelo, definicion()).status_code == 201

    d = cliente.get(f"/api/modelos/{modelo}/definicion",
                    headers=cab_admin).json()["definicion"]
    assert d["tablas_medidas"] == [{"nombre": "KPIs de venta",
                                    "descripcion": "Lo que mira comercial"}]
    assert d["metricas"][0]["tabla_medidas"] == "KPIs de venta"


def test_el_hecho_sigue_decidiendo_de_donde_se_calcula(cliente, cab_admin, modelo):
    """
    Lo que esta prueba impide: que mover una metrica de cajon le cambie la cifra.
    La consulta tiene que dar lo mismo con tabla de medidas y sin ella.

    Se compara con tolerancia y no con igualdad: la metrica suma medio millon de
    DOUBLE y DuckDB agrega en paralelo, asi que el orden de la suma —y con el los
    ultimos bits— puede cambiar entre dos consultas identicas. Exigir igualdad exacta
    hacia fallar la prueba una vez de cada tantas, que es la peor forma de fallar.
    """
    assert guardar(cliente, cab_admin, modelo, definicion(con_tabla=False)).status_code == 201
    sin = cliente.post(f"/api/modelos/{modelo}/consultar", headers=cab_admin,
                       json={"dimensiones": [], "metricas": ["venta"]})
    assert sin.status_code == 200, sin.text

    assert guardar(cliente, cab_admin, modelo, definicion()).status_code == 201
    con = cliente.post(f"/api/modelos/{modelo}/consultar", headers=cab_admin,
                       json={"dimensiones": [], "metricas": ["venta"]})
    assert con.status_code == 200, con.text
    assert con.json()["filas"][0]["venta"] == pytest.approx(
        sin.json()["filas"][0]["venta"], rel=1e-9)
    # Y el FROM sigue siendo el del hecho, no el del cajon.
    assert "fact_venta" in con.json()["sql"]


def test_una_metrica_sin_cajon_sigue_valiendo(cliente, cab_admin, modelo):
    r = guardar(cliente, cab_admin, modelo, definicion(con_tabla=False))
    assert r.status_code == 201, r.text
    d = cliente.get(f"/api/modelos/{modelo}/definicion",
                    headers=cab_admin).json()["definicion"]
    assert d["metricas"][0].get("tabla_medidas") is None


def test_la_tabla_de_medidas_sobrevive_el_viaje_a_yaml():
    from semantic.definicion import Definicion, desde_yaml

    d = Definicion.model_validate(definicion())
    ida = desde_yaml(d.a_yaml())
    assert [t.nombre for t in ida.tablas_medidas] == ["KPIs de venta"]
    assert ida.metricas[0].tabla_medidas == "KPIs de venta"
    # Y va despues de las entidades, que es donde se lee.
    texto = d.a_yaml()
    assert texto.index("entidades:") < texto.index("tablas_medidas:")
    assert texto.index("tablas_medidas:") < texto.index("metricas:")


# --------------------------------------------------------------------------- #
# Lo que se rechaza
# --------------------------------------------------------------------------- #

def test_un_cajon_que_no_existe_se_explica(cliente, cab_admin, modelo):
    d = definicion(con_tabla=False)
    d["metricas"][0]["tabla_medidas"] = "no_existe"
    r = guardar(cliente, cab_admin, modelo, d)
    assert r.status_code == 422
    assert any("no_existe" in e for e in r.json()["detail"]["errores"])


def test_dos_cajones_con_el_mismo_nombre_se_rechazan(cliente, cab_admin, modelo):
    d = definicion()
    d["tablas_medidas"].append({"nombre": "KPIs de venta"})
    r = guardar(cliente, cab_admin, modelo, d)
    assert r.status_code == 422
    assert any("dos tablas de medidas" in e for e in r.json()["detail"]["errores"])


def test_un_cajon_no_puede_llamarse_como_una_entidad(cliente, cab_admin, modelo):
    d = definicion()
    d["tablas_medidas"] = [{"nombre": "hecho_b"}]
    d["metricas"][0]["tabla_medidas"] = "hecho_b"
    r = guardar(cliente, cab_admin, modelo, d)
    assert r.status_code == 422
    assert any("a la vez una entidad" in e for e in r.json()["detail"]["errores"])
