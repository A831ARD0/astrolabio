"""
Cifras que son una FOTO y no un flujo: el inventario de hoy, la cartera de hoy.

El problema que resuelve `ignora_periodo`, tal como sale en un informe de verdad:
una tabla con el inventario al lado de un promedio de tres meses de venta, para
sacar «meses de inventario». En cuanto entra el promedio, la tabla necesita un mes
de referencia, y la foto **no pertenece a ningun mes**: al pedirle la cifra del mes
que manda no tiene ni una fila, sale vacia, y el cociente sale cero. Toda la
columna del inventario en blanco, sin un aviso.

Con la bandera puesta, a esa metrica se le quitan las columnas y los filtros del
calendario y su cifra se REPARTE en cada periodo del desglose. Es el
`CALCULATE(..., ALL(Calendario))` de DAX.

Aqui `fact_presupuesto` hace de foto: su objetivo se declara sin periodo y se
comprueba contra la aritmetica —el total de la sucursal, entero, repetido en cada
mes— y no contra si mismo.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)

MES = "dim_calendario.anio_mes"
SUC = "cat_sucursal.sucursal_nombre"

#: La foto: el objetivo sin periodo, y el promedio de tres meses con el que se
#: cruza. La compuesta es la que fuerza un mes de referencia.
FOTO = [
    {"nombre": "foto_objetivo", "etiqueta": "Objetivo (foto)", "formato": "entero",
     "entidad": "fact_presupuesto", "expresion": "SUM(objetivo_unidades)",
     "ignora_periodo": True},
    {"nombre": "prom3", "etiqueta": "Promedio de 3 meses", "formato": "numero",
     "expresion": "PROMEDIOMESES([unidades_vendidas], 3)"},
    {"nombre": "meses_foto", "etiqueta": "Meses de foto", "formato": "numero",
     "expresion": "DIVIDIR([foto_objetivo], [prom3], 0)"},
]


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"foto_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def definicion(cliente, cab, mid: int) -> dict:
    r = cliente.get(f"/api/modelos/{mid}/definicion", headers=cab)
    assert r.status_code == 200, r.text
    return r.json()["definicion"]


def guardar(cliente, cab, mid: int, d: dict):
    return cliente.put(f"/api/modelos/{mid}/definicion", headers=cab,
                       json={"definicion": d})


def con_foto(cliente, cab, mid: int, extra=None) -> dict:
    d = definicion(cliente, cab, mid)
    d["metricas"] += [dict(m) for m in (extra if extra is not None else FOTO)]
    return d


def consultar(cliente, cab, mid: int, metricas, dimensiones, filtros=None):
    return cliente.post(f"/api/modelos/{mid}/consultar", headers=cab,
                        json={"dimensiones": dimensiones, "metricas": metricas,
                              "filtros": filtros or []})


# --------------------------------------------------------------------------- #

def test_la_foto_es_la_misma_en_todos_los_meses(cliente, cab_editor, modelo):
    """
    El total de la sucursal, entero, en cada mes. No el del mes: la cifra no es de
    ningun mes, y repartirla es justamente lo que se pide.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_foto(cliente, cab_editor, modelo)).status_code == 201

    # La verdad, aparte: el total por sucursal sin ningun desglose de tiempo.
    r = consultar(cliente, cab_editor, modelo, ["objetivo_unidades"], [SUC])
    assert r.status_code == 200, r.text
    total = {f[SUC]: f["objetivo_unidades"] for f in r.json()["filas"]}
    assert total, "la demo tiene que traer objetivos"

    r = consultar(cliente, cab_editor, modelo,
                  ["foto_objetivo", "unidades_vendidas"], [SUC, MES])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert len(filas) > 20, "hacen falta varios meses para que la prueba diga algo"
    for f in filas:
        assert f["foto_objetivo"] == total[f[SUC]], f
    # Y que no sea que todo esta vacio: la otra cifra si cambia mes a mes.
    assert len({f["unidades_vendidas"] for f in filas}) > 1


def test_sin_la_bandera_la_cifra_es_la_del_mes(cliente, cab_editor, modelo):
    """
    El contraste: la misma metrica sin la bandera se parte por mes. Sin esto, la
    prueba de arriba pasaria igual si la bandera no hiciera nada.
    """
    d = con_foto(cliente, cab_editor, modelo)
    for m in d["metricas"]:
        if m["nombre"] == "foto_objetivo":
            m["ignora_periodo"] = False
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["foto_objetivo"], [SUC, MES])
    assert r.status_code == 200, r.text
    por_suc: dict[str, set] = {}
    for f in r.json()["filas"]:
        por_suc.setdefault(f[SUC], set()).add(f["foto_objetivo"])
    assert any(len(v) > 1 for v in por_suc.values()), \
        "sin la bandera el objetivo tiene que cambiar de mes a mes"


def test_la_foto_sale_al_lado_de_una_comparacion_mensual(cliente, cab_editor,
                                                         modelo):
    """
    El caso que lo motivo: una tabla por sucursal, SIN columna de meses, con la
    foto y un promedio de tres meses. El mes lo pone el contexto, y antes de esto
    la foto salia vacia porque ese mes no tiene filas suyas.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_foto(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["objetivo_unidades"], [SUC])
    total = {f[SUC]: f["objetivo_unidades"] for f in r.json()["filas"]}

    r = consultar(cliente, cab_editor, modelo,
                  ["foto_objetivo", "prom3", "meses_foto"], [SUC])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert filas
    for f in filas:
        assert f["foto_objetivo"] == total[f[SUC]], f
        # Y el cociente cuadra con sus dos partes, que es lo que se queria leer.
        if f["prom3"]:
            assert f["meses_foto"] == pytest.approx(
                f["foto_objetivo"] / f["prom3"]), f
    assert any(f["meses_foto"] for f in filas), \
        "el cociente no puede salir cero en todas las filas"


def test_el_filtro_de_fechas_no_la_toca(cliente, cab_editor, modelo):
    """
    Filtrar un mes acota lo que se compara, no la foto: hay ciento veinte unidades
    en el patio, y son las mismas se mire el informe de julio o el de marzo.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_foto(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["objetivo_unidades"], [SUC])
    total = {f[SUC]: f["objetivo_unidades"] for f in r.json()["filas"]}

    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [MES])
    meses = sorted(f[MES] for f in r.json()["filas"])
    alguno = meses[len(meses) // 2]

    r = consultar(cliente, cab_editor, modelo,
                  ["foto_objetivo", "unidades_vendidas"], [SUC],
                  [{"campo": MES, "op": "=", "valor": alguno}])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert filas
    for f in filas:
        assert f["foto_objetivo"] == total[f[SUC]], f


def test_la_foto_no_decide_cual_es_el_ultimo_mes_con_datos(tmp_path):
    """
    El mes que manda lo pone la cifra que se compara, no la foto.

    Una foto tiene cifra en TODOS los meses del desglose —se reparte—, asi que si
    contara para elegir el mes, el mes que manda seria el ultimo que tuviera foto y
    las ventas de ese mes podrian salir en blanco. La regla es «el ultimo mes con la
    cifra comparada», y una foto no es una cifra comparada.

    Se mira el SQL y no las filas: en la demo el objetivo y la venta llegan hasta el
    mismo mes, asi que ninguna fila distinguiria una regla de la otra. La invariante
    esta en el compilador, y ahi se comprueba.
    """
    import yaml as _yaml
    from semantic.engine import Compilador, Consulta
    from semantic.engine import Modelo as ModeloSemantico

    d = _yaml.safe_load(YAML_DEMO)
    d["metricas"] += [dict(m) for m in FOTO]
    ruta = tmp_path / "modelo.yaml"
    ruta.write_text(_yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")

    sql = Compilador(ModeloSemantico(ruta)).compilar(
        Consulta(dimensiones=[SUC], metricas=["meses_foto"])).sql

    manda = sql[sql.index("mes_que_manda"):]
    assert "__base_unidades_vendidas" in manda, manda
    assert "__base_foto_objetivo" not in manda, manda


def test_una_compuesta_no_puede_ignorar_el_periodo(cliente, cab_editor, modelo):
    """
    No lee ninguna tabla, asi que no hay filtro que quitarle. Se dice al guardar,
    con el sitio donde si va la bandera.
    """
    d = con_foto(cliente, cab_editor, modelo)
    for m in d["metricas"]:
        if m["nombre"] == "meses_foto":
            m["ignora_periodo"] = True
    r = guardar(cliente, cab_editor, modelo, d)
    assert r.status_code == 422, r.text
    assert "no puede ignorar el periodo" in r.text
    assert "las metricas que combina" in r.text


def test_una_foto_sin_relacion_al_calendario_tambien_sale(cliente, cab_editor,
                                                          modelo):
    """
    El otro modo de fallar, y el mas comun en una tabla de inventario: la foto no se
    relaciona con el calendario en absoluto. Sin la bandera la consulta no tiene por
    donde unirse y falla; con ella no necesita ese camino, porque no lo recorre.
    """
    d = con_foto(cliente, cab_editor, modelo)
    d["relaciones"] = [r for r in d["relaciones"]
                       if not (r["desde"][0] == "fact_presupuesto"
                               and r["hasta"][0] == "dim_calendario")]
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["foto_objetivo"], [SUC, MES])
    assert r.status_code == 200, r.text
    assert r.json()["filas"]

    # Y sin la bandera, la misma consulta dice que no hay camino.
    for m in d["metricas"]:
        if m["nombre"] == "foto_objetivo":
            m["ignora_periodo"] = False
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201
    r = consultar(cliente, cab_editor, modelo, ["foto_objetivo"], [SUC, MES])
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# La bandera en la TABLA, que es donde suele ir: un inventario trae ocho metricas
# —el total, los tramos de antiguedad, los dias— y todas son la misma foto. Que
# haya que marcarlas una por una es la forma de que se olvide una y esa columna se
# quede en blanco sin decir nada.
# --------------------------------------------------------------------------- #

#: Tres metricas del mismo hecho, NINGUNA marcada. Lo dice la tabla.
VARIAS = [
    {"nombre": "foto_a", "etiqueta": "Foto A", "formato": "entero",
     "entidad": "fact_presupuesto", "expresion": "SUM(objetivo_unidades)"},
    {"nombre": "foto_b", "etiqueta": "Foto B", "formato": "moneda",
     "entidad": "fact_presupuesto", "expresion": "SUM(objetivo_monto)"},
    {"nombre": "foto_c", "etiqueta": "Foto C", "formato": "entero",
     "entidad": "fact_presupuesto",
     "expresion": "CALCULAR(SUMA(objetivo_unidades), objetivo_unidades > 0)"},
    {"nombre": "prom3", "etiqueta": "Promedio de 3 meses", "formato": "numero",
     "expresion": "PROMEDIOMESES([unidades_vendidas], 3)"},
]


def con_tabla_foto(cliente, cab, mid: int) -> dict:
    d = definicion(cliente, cab, mid)
    d["metricas"] += [dict(m) for m in VARIAS]
    for e in d["entidades"]:
        if e["nombre"] == "fact_presupuesto":
            e["ignora_periodo"] = True
    return d


def test_marcar_la_tabla_las_alcanza_a_todas(cliente, cab_editor, modelo):
    """
    Las tres salen, y ninguna lleva la bandera puesta: la lleva su hecho. Es el
    caso que motivo esto — se marco una metrica de ocho y las otras siete se
    quedaron en blanco.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tabla_foto(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["foto_a", "foto_b", "foto_c"],
                  [SUC])
    total = {f[SUC]: (f["foto_a"], f["foto_b"], f["foto_c"])
             for f in r.json()["filas"]}

    # Con la comparacion mensual al lado, que es lo que fuerza un mes de referencia.
    r = consultar(cliente, cab_editor, modelo,
                  ["foto_a", "foto_b", "foto_c", "prom3"], [SUC])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert filas
    for f in filas:
        assert (f["foto_a"], f["foto_b"], f["foto_c"]) == total[f[SUC]], f
        assert f["foto_a"] is not None and f["foto_c"] is not None, f


def test_la_metrica_puede_marcarse_aunque_la_tabla_no(cliente, cab_editor, modelo):
    """
    Las dos banderas suman, no se estorban: un hecho mixto marca la metrica suelta.
    Es la de antes, que sigue valiendo.
    """
    d = definicion(cliente, cab_editor, modelo)
    d["metricas"] += [dict(m) for m in VARIAS]
    for m in d["metricas"]:
        if m["nombre"] == "foto_a":
            m["ignora_periodo"] = True
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["foto_a", "foto_b", "prom3"],
                  [SUC, MES])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    por_suc_a: dict[str, set] = {}
    por_suc_b: dict[str, set] = {}
    for f in filas:
        por_suc_a.setdefault(f[SUC], set()).add(f["foto_a"])
        por_suc_b.setdefault(f[SUC], set()).add(f["foto_b"])
    assert all(len(v) == 1 for v in por_suc_a.values()), "foto_a es la foto"
    assert any(len(v) > 1 for v in por_suc_b.values()), "foto_b no lo es"


def test_una_dimension_no_puede_ignorar_el_periodo(cliente, cab_editor, modelo):
    """
    De una dimension no sale ninguna cifra, asi que decirle que el periodo no le
    aplica no quiere decir nada. Se dice al guardar, con el sitio donde si va.
    """
    d = definicion(cliente, cab_editor, modelo)
    for e in d["entidades"]:
        if e["nombre"] == "dim_calendario":
            e["ignora_periodo"] = True
    r = guardar(cliente, cab_editor, modelo, d)
    assert r.status_code == 422, r.text
    assert "no puede ignorar el periodo" in r.text


def test_una_compuesta_hereda_por_sus_partes(cliente, cab_editor, modelo):
    """
    «Meses de inventario» es la foto dividida entre un promedio de tres meses. La
    compuesta no lleva bandera —no puede— y aun asi sale con la cifra entera de la
    foto, porque la suya la lleva por su tabla. Es lo que hace que marcar el hecho
    baste de verdad.
    """
    d = con_tabla_foto(cliente, cab_editor, modelo)
    d["metricas"].append(
        {"nombre": "meses_foto", "etiqueta": "Meses de foto", "formato": "numero",
         "expresion": "DIVIDIR([foto_a], [prom3], 0)"})
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    # La verdad, aparte: la foto entera y el promedio, cada uno pedido por su lado.
    r = consultar(cliente, cab_editor, modelo, ["foto_a"], [SUC])
    foto = {f[SUC]: f["foto_a"] for f in r.json()["filas"]}
    r = consultar(cliente, cab_editor, modelo, ["prom3"], [SUC])
    prom = {f[SUC]: f["prom3"] for f in r.json()["filas"]}

    r = consultar(cliente, cab_editor, modelo, ["meses_foto"], [SUC])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert filas
    # Una sucursal con foto y sin ventas tambien sale —la foto existe para ella— y
    # entonces no hay promedio contra el que dividir. Se comprueban las que si.
    comparadas = 0
    for f in filas:
        suc = f[SUC]
        if not prom.get(suc):
            continue
        assert f["meses_foto"] == pytest.approx(foto[suc] / prom[suc]), f
        comparadas += 1
    assert comparadas > 5, comparadas
