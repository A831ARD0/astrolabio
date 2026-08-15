"""
Metricas compuestas: una cifra que sale de dividir dos hechos distintos.

El caso que las obliga a existir es el mas comun de un tablero comercial: el
porcentaje de logro es lo vendido entre lo presupuestado, y lo vendido esta en las
facturas mientras que el presupuesto esta en otra tabla, a otro grano. Antes de
esto no habia forma de escribirlo — una metrica se agrega desde UN hecho, y desde
el hecho de las ventas la columna del objetivo no existe—.

Lo que estas pruebas fijan, y que es donde esta el riesgo de dar un numero
plausible y equivocado:

  1. Que el cociente se calcule DESPUES de agregar cada hecho por su lado. Unir
     antes multiplicaria el objetivo del mes por el numero de facturas del mes:
     el fan trap clasico, que da un numero enorme con toda la pinta de estar bien.
  2. Que pedir la compuesta traiga UNA columna, no tres. Sus dependencias se
     calculan pero no se enseñan: quien pide el porcentaje pidio el porcentaje.
  3. Que se compruebe contra la aritmetica hecha aparte, y no contra si misma.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)

#: La misma sucursal esta en las dos tablas, asi que el desglose por sucursal es
#: el que de verdad cruza los dos hechos.
DIM = "cat_sucursal.sucursal_nombre"

LOGRO = {
    "nombre": "logro_unidades",
    "etiqueta": "% Logro Unidades",
    "expresion": "DIVIDIR([unidades_vendidas], [objetivo_unidades], 0)",
    "formato": "porcentaje",
}


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"compuestas_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def definicion(cliente, cab, modelo_id: int) -> dict:
    r = cliente.get(f"/api/modelos/{modelo_id}/definicion", headers=cab)
    assert r.status_code == 200, r.text
    return r.json()["definicion"]


def guardar(cliente, cab, modelo_id: int, d: dict):
    return cliente.put(f"/api/modelos/{modelo_id}/definicion", headers=cab,
                       json={"definicion": d})


def con_logro(cliente, cab, modelo_id: int, expresion: str | None = None) -> dict:
    """Le agrega al modelo demo la compuesta del porcentaje de logro."""
    d = definicion(cliente, cab, modelo_id)
    metrica = dict(LOGRO)
    if expresion is not None:
        metrica["expresion"] = expresion
    d["metricas"].append(metrica)
    return d


def consultar(cliente, cab, modelo_id: int, metricas: list[str],
              dimensiones: list[str] | None = None):
    return cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab,
                        json={"dimensiones": dimensiones or [],
                              "metricas": metricas})


# --------------------------------------------------------------------------- #

def test_una_compuesta_se_guarda_sin_entidad(cliente, cab_editor, modelo):
    """Sin `entidad`: es lo que la distingue de una metrica normal."""
    r = guardar(cliente, cab_editor, modelo, con_logro(cliente, cab_editor, modelo))
    assert r.status_code == 201, r.text

    guardada = next(m for m in definicion(cliente, cab_editor, modelo)["metricas"]
                    if m["nombre"] == "logro_unidades")
    assert guardada.get("entidad") is None


def test_el_cociente_cruza_los_dos_hechos(cliente, cab_editor, modelo):
    """
    La comprobacion de fondo: el porcentaje tiene que ser exactamente las unidades
    entre el objetivo, sucursal por sucursal.

    Se piden tambien las dos por separado y se hace la division aqui, en Python.
    Comparar el resultado contra si mismo no probaria nada; contra la aritmetica,
    si.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_logro(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "objetivo_unidades", "logro_unidades"],
                  [DIM])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert filas, "el demo tiene ventas y objetivos: sin filas no se prueba nada"

    comparadas = 0
    for f in filas:
        unidades = f["unidades_vendidas"]
        objetivo = f["objetivo_unidades"]
        if unidades is None or not objetivo:
            continue
        comparadas += 1
        assert f["logro_unidades"] == pytest.approx(unidades / objetivo)
    assert comparadas, "ninguna sucursal tenia venta y objetivo a la vez"


def test_el_objetivo_no_se_multiplica_por_las_facturas(cliente, cab_editor, modelo):
    """
    El fan trap, que es lo que hace falsa la forma ingenua de hacer esto.

    Unir facturas con objetivos antes de agregar repetiria el objetivo del mes una
    vez por factura. Como el demo tiene muchas mas facturas que objetivos, eso se
    nota: el objetivo saldria inflado y el logro, ridiculamente chico. Se fija que
    el objetivo que ve la compuesta es EL MISMO que cuando se pide sola.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_logro(cliente, cab_editor, modelo)).status_code == 201

    sola = consultar(cliente, cab_editor, modelo, ["objetivo_unidades"], [DIM])
    junta = consultar(cliente, cab_editor, modelo,
                      ["objetivo_unidades", "logro_unidades"], [DIM])
    assert sola.status_code == 200 and junta.status_code == 200

    por_sucursal = {f[DIM]: f["objetivo_unidades"] for f in sola.json()["filas"]}
    for f in junta.json()["filas"]:
        assert f["objetivo_unidades"] == por_sucursal[f[DIM]]


def test_pedir_la_compuesta_devuelve_una_sola_columna(cliente, cab_editor, modelo):
    """Sus dependencias se calculan por dentro; no se cuelan en el resultado."""
    assert guardar(cliente, cab_editor, modelo,
                   con_logro(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["logro_unidades"], [DIM])
    assert r.status_code == 200, r.text
    fila = r.json()["filas"][0]
    assert set(fila) == {DIM, "logro_unidades"}


def test_tambien_sin_desglose(cliente, cab_editor, modelo):
    """Sin dimensiones el compilador toma otro camino, y tiene que dar lo mismo."""
    assert guardar(cliente, cab_editor, modelo,
                   con_logro(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "objetivo_unidades", "logro_unidades"])
    assert r.status_code == 200, r.text
    f = r.json()["filas"][0]
    assert f["logro_unidades"] == pytest.approx(
        f["unidades_vendidas"] / f["objetivo_unidades"])


def test_una_compuesta_puede_apoyarse_en_otra(cliente, cab_editor, modelo):
    d = con_logro(cliente, cab_editor, modelo)
    d["metricas"].append({
        "nombre": "logro_topado", "etiqueta": "% Logro topado al 100",
        "expresion": "SI([logro_unidades] > 1, 1, [logro_unidades])",
        "formato": "porcentaje",
    })
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["logro_unidades", "logro_topado"], [DIM])
    assert r.status_code == 200, r.text
    for f in r.json()["filas"]:
        assert f["logro_topado"] == pytest.approx(min(f["logro_unidades"], 1))


def test_una_compuesta_no_puede_nombrar_una_columna(cliente, cab_editor, modelo):
    """
    No es una restriccion de estilo: no hay ninguna tabla de la que sacarla.

    Y tiene que decirlo al GUARDAR. Dejarla pasar significa que el error sale en
    el primer tablero que la use, cuando quien la escribio ya no esta mirando.
    """
    d = con_logro(cliente, cab_editor, modelo,
                  expresion="DIVIDIR(unidades, [objetivo_unidades])")
    r = guardar(cliente, cab_editor, modelo, d)
    assert r.status_code == 422, r.text
    assert "unidades" in r.text


def test_una_compuesta_no_puede_volver_a_agregar(cliente, cab_editor, modelo):
    d = con_logro(cliente, cab_editor, modelo,
                  expresion="SUMA([unidades_vendidas])")
    r = guardar(cliente, cab_editor, modelo, d)
    assert r.status_code == 422, r.text
    assert "agregar" in r.text


def test_dos_compuestas_que_se_llaman_entre_si_no_se_guardan(
        cliente, cab_editor, modelo):
    """Sin esto la consulta se comeria la pila en vez de decir que pasa."""
    d = definicion(cliente, cab_editor, modelo)
    d["metricas"] += [
        {"nombre": "ida", "etiqueta": "Ida", "expresion": "[vuelta] + 1"},
        {"nombre": "vuelta", "etiqueta": "Vuelta", "expresion": "[ida] + 1"},
    ]
    r = guardar(cliente, cab_editor, modelo, d)
    assert r.status_code == 422, r.text
    assert "sin final" in r.text


def test_se_revisa_mientras_se_escribe(cliente, cab_editor, modelo):
    """
    La ruta que subraya en rojo. Sin entidad, y con las metricas que hay EN LA
    PANTALLA: se esta escribiendo sobre un borrador que el servidor no ha visto.
    """
    r = cliente.post(f"/api/modelos/{modelo}/revisar-formula", headers=cab_editor,
                     json={"expresion": "DIVIDIR([a], [b], 0)",
                           "metricas_del_modelo": {"a": None, "b": None}})
    assert r.status_code == 200, r.text
    assert r.json()["fallos"] == []
    assert '"a"' in r.json()["sql"]

    malo = cliente.post(f"/api/modelos/{modelo}/revisar-formula", headers=cab_editor,
                        json={"expresion": "DIVIDIR([a], [no_esta], 0)",
                              "metricas_del_modelo": {"a": None, "b": None}})
    assert malo.status_code == 200, malo.text
    assert malo.json()["hay_errores"]


def test_se_puede_probar_antes_de_guardarla(cliente, cab_editor, modelo):
    """
    Ver el numero antes de guardar. Es el paso que separa una formula correcta de
    una que dice lo que se queria decir, y una compuesta lo necesita mas que
    ninguna: el cociente de dos hechos es donde de verdad se cuelan los errores.
    """
    r = cliente.post(f"/api/modelos/{modelo}/probar-metrica", headers=cab_editor,
                     json={"expresion": LOGRO["expresion"],
                           "dimensiones": [DIM], "limite": 5})
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert filas and all(f["__prueba__"] is not None for f in filas)


def test_las_metricas_de_antes_siguen_igual(cliente, cab_editor, modelo):
    """
    `entidad` paso de obligatoria a opcional. Un modelo guardado antes no lleva
    nada distinto escrito, y tiene que seguir dando el mismo numero.
    """
    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [DIM])
    assert r.status_code == 200, r.text
    assert r.json()["filas"]
