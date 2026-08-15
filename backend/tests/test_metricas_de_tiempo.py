"""
Comparar contra otro periodo: el mes anterior, el acumulado del año, el año pasado.

Estas cuatro funciones son las que traen «% Crec MoM» y compañia desde DAX. El
riesgo aqui no es que no compilen: es que devuelvan un numero **parecido al
correcto**, que nadie revisa.

Los dos sitios donde eso pasa, y que estas pruebas fijan:

  1. **Un mes sin datos.** La forma facil de escribir «el mes anterior» en SQL es
     `LAG(1)`, que significa «la fila anterior del RESULTADO». Si marzo no tiene
     ventas, el mes anterior de abril sale siendo febrero, sin aviso. Aqui el
     marco va en meses (`RANGE`), asi que abril sale **vacio** — que es la verdad.
  2. **Sumar lo que no se suma.** El acumulado del año de un conteo de clientes
     distintos contaria dos veces a quien compro en enero y en marzo. Se rechaza.

Y se comprueban contra la aritmetica hecha aparte, no contra si mismas.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)

MES = "dim_calendario.anio_mes"
SUC = "cat_sucursal.sucursal_nombre"

TIEMPO = [
    {"nombre": "mes_anterior", "etiqueta": "Mes anterior", "formato": "entero",
     "expresion": "MESANTERIOR([unidades_vendidas])"},
    {"nombre": "acum_anio", "etiqueta": "Acumulado del año", "formato": "entero",
     "expresion": "ACUMANIO([unidades_vendidas])"},
    {"nombre": "anio_anterior", "etiqueta": "Mismo mes del año pasado",
     "formato": "entero",
     "expresion": "MISMOMESANIOANTERIOR([unidades_vendidas])"},
    {"nombre": "prom3", "etiqueta": "Promedio de 3 meses", "formato": "numero",
     "expresion": "PROMEDIOMESES([unidades_vendidas], 3)"},
]


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"tiempo_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def definicion(cliente, cab, modelo_id: int) -> dict:
    r = cliente.get(f"/api/modelos/{modelo_id}/definicion", headers=cab)
    assert r.status_code == 200, r.text
    return r.json()["definicion"]


def guardar(cliente, cab, modelo_id: int, d: dict):
    return cliente.put(f"/api/modelos/{modelo_id}/definicion", headers=cab,
                       json={"definicion": d})


def con_tiempo(cliente, cab, modelo_id: int, extra: list[dict] | None = None) -> dict:
    d = definicion(cliente, cab, modelo_id)
    d["metricas"] += [dict(m) for m in (extra if extra is not None else TIEMPO)]
    return d


def consultar(cliente, cab, modelo_id: int, metricas, dimensiones, filtros=None):
    return cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab,
                        json={"dimensiones": dimensiones, "metricas": metricas,
                              "filtros": filtros or []})


def por_mes(filas: list[dict], clave: str) -> dict:
    return {f[MES]: f[clave] for f in filas}


# --------------------------------------------------------------------------- #

def test_cada_funcion_da_el_numero_correcto(cliente, cab_editor, modelo):
    """
    Contra la aritmetica, mes a mes: el mes anterior es el mes anterior, el
    acumulado es la suma desde enero, y el promedio de tres meses no incluye el
    mes de la fila.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "mes_anterior", "acum_anio",
                   "anio_anterior", "prom3"], [MES])
    assert r.status_code == 200, r.text
    filas = sorted(r.json()["filas"], key=lambda f: f[MES])
    assert len(filas) > 15, "hacen falta varios años para probar el año anterior"

    unidades = por_mes(filas, "unidades_vendidas")
    meses = [f[MES] for f in filas]

    def anterior(mes: int, cuantos: int = 1) -> int | None:
        anio, m = divmod(mes, 100)
        indice = anio * 12 + m - cuantos
        objetivo = (indice // 12) * 100 + (indice % 12)
        if objetivo % 100 == 0:                      # diciembre del año de antes
            objetivo = objetivo - 100 + 12
        return objetivo if objetivo in unidades else None

    comparadas = 0
    for f in filas:
        mes = f[MES]
        previo = anterior(mes)
        assert f["mes_anterior"] == (unidades[previo] if previo else None)

        hace_un_anio = mes - 100
        assert f["anio_anterior"] == unidades.get(hace_un_anio)

        # El acumulado: todo lo del mismo año hasta este mes, inclusive.
        esperado = sum(u for m2, u in unidades.items()
                       if m2 // 100 == mes // 100 and m2 <= mes)
        assert f["acum_anio"] == esperado

        # El promedio de tres: los TRES meses anteriores, sin el de la fila, y
        # dividido entre 3 aunque falte alguno — que es lo que hace DAX.
        atras = [anterior(mes, k) for k in (1, 2, 3)]
        suma = sum(unidades[a] for a in atras if a)
        if any(atras):
            assert f["prom3"] == pytest.approx(suma / 3)
            comparadas += 1
    assert comparadas > 10 and len(meses) == len(set(meses))


def test_un_mes_sin_datos_sale_vacio_y_no_el_de_antes(cliente, cab_editor, modelo):
    """
    La prueba que justifica todo el diseño.

    Se quita un mes del resultado con un filtro. El mes siguiente NO puede
    heredar el valor del mes anterior a ese: tiene que salir vacio. Con `LAG(1)`
    —«la fila de arriba»— esta prueba fallaria y el tablero enseñaria una
    comparacion falsa sin una sola señal de que lo es.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    completo = consultar(cliente, cab_editor, modelo,
                         ["unidades_vendidas", "mes_anterior"], [MES])
    assert completo.status_code == 200, completo.text
    meses = sorted(f[MES] for f in completo.json()["filas"])
    # Un mes de en medio, con vecinos a los dos lados dentro del mismo año.
    hueco = next(m for m in meses[2:-2] if m % 100 not in (1, 12))
    siguiente = hueco + 1

    con_hueco = consultar(
        cliente, cab_editor, modelo, ["unidades_vendidas", "mes_anterior"], [MES],
        filtros=[{"campo": MES, "op": "!=", "valor": hueco}])
    assert con_hueco.status_code == 200, con_hueco.text
    filas = {f[MES]: f for f in con_hueco.json()["filas"]}

    assert hueco not in filas, "el filtro tenia que quitar ese mes"
    antes = por_mes(completo.json()["filas"], "unidades_vendidas")[hueco - 1]
    assert filas[siguiente]["mes_anterior"] is None, (
        f"el mes {siguiente} heredo el valor de {hueco - 1} ({antes}) saltandose "
        f"el mes que falta")


def test_el_acumulado_reinicia_en_enero(cliente, cab_editor, modelo):
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "acum_anio"], [MES])
    filas = sorted(r.json()["filas"], key=lambda f: f[MES])
    eneros = [f for f in filas if f[MES] % 100 == 1]
    assert len(eneros) >= 2
    for f in eneros:
        assert f["acum_anio"] == f["unidades_vendidas"]


def test_cada_sucursal_mira_su_propio_mes_anterior(cliente, cab_editor, modelo):
    """
    Con dos dimensiones, el mes anterior de una sucursal es el suyo y no la fila
    que le toque al lado. Es lo que hace el `PARTITION BY` de las demas columnas.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "mes_anterior"], [SUC, MES])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    valores = {(f[SUC], f[MES]): f["unidades_vendidas"] for f in filas}
    assert len({s for s, _ in valores}) > 1, "hace falta mas de una sucursal"

    comparadas = 0
    for f in filas:
        previo = valores.get((f[SUC], f[MES] - 1))
        if f[MES] % 100 == 1 or previo is None:
            continue
        assert f["mes_anterior"] == previo
        comparadas += 1
    assert comparadas > 20


def test_sin_una_columna_de_meses_se_explica(cliente, cab_editor, modelo):
    """
    «El mes anterior» de un total sin meses no existe. Devolver el total repetido
    seria dar algo que parece una comparacion.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["mes_anterior"], [SUC])
    assert r.status_code == 422, r.text
    assert "columna de meses" in r.text
    # Y tiene que decir CUAL agregar, con su nombre y nada mas: la primera
    # version imprimia la entidad entera —campos, tipos, claves— y el mensaje
    # util quedaba sepultado en media pantalla de texto.
    assert "dim_calendario.anio_mes" in r.text
    assert "Campo(" not in r.text and "Entidad(" not in r.text


def test_no_se_acumula_lo_que_no_se_puede_sumar(cliente, cab_editor, modelo):
    """
    El mismo cliente comprando en enero y en marzo es UN cliente. Acumular un
    conteo de valores distintos lo contaria dos veces, y el numero saldria alto
    y creible.
    """
    d = definicion(cliente, cab_editor, modelo)
    d["metricas"] += [
        {"nombre": "clientes", "etiqueta": "Clientes", "entidad": "fact_venta",
         "expresion": "CONTARUNICOS(cliente_id)", "formato": "entero"},
        {"nombre": "clientes_acum", "etiqueta": "Clientes acumulados",
         "expresion": "ACUMANIO([clientes])", "formato": "entero"},
        {"nombre": "clientes_mes_ant", "etiqueta": "Clientes el mes pasado",
         "expresion": "MESANTERIOR([clientes])", "formato": "entero"},
    ]
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    malo = consultar(cliente, cab_editor, modelo, ["clientes_acum"], [MES])
    assert malo.status_code == 422, malo.text
    assert "no se puede sumar" in malo.text

    # Un solo mes si vale: sumar un valor suelto es ese valor.
    bien = consultar(cliente, cab_editor, modelo,
                     ["clientes", "clientes_mes_ant"], [MES])
    assert bien.status_code == 200, bien.text
    filas = sorted(bien.json()["filas"], key=lambda f: f[MES])
    clientes = por_mes(filas, "clientes")
    for f in filas[1:]:
        if f[MES] - 1 in clientes:
            assert f["clientes_mes_ant"] == clientes[f[MES] - 1]


def test_el_acumulado_del_anio_pasado(cliente, cab_editor, modelo):
    """
    `SAMEPERIODLASTYEAR(DATESYTD(...))` de DAX: una función de tiempo dentro de
    otra.

    No cabe en una sola ventana. Para marzo habría que sumar tres meses del año
    pasado y para noviembre once, así que el marco tendría que ensancharse fila a
    fila — y entonces ya no es un marco. Se calcula en DOS capas: abajo el
    acumulado de cada mes, y encima el desplazamiento de doce.

    Se comprueba contra el acumulado del mismo mes del año anterior, que es lo
    que tiene que dar exactamente.
    """
    d = con_tiempo(cliente, cab_editor, modelo)
    d["metricas"].append({
        "nombre": "acum_anio_pasado", "etiqueta": "Acumulado del año pasado",
        "expresion": "MISMOMESANIOANTERIOR([acum_anio])", "formato": "entero"})
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["acum_anio", "acum_anio_pasado"], [MES])
    assert r.status_code == 200, r.text
    filas = sorted(r.json()["filas"], key=lambda f: f[MES])
    acum = por_mes(filas, "acum_anio")

    comparadas = 0
    for f in filas:
        hace_un_anio = f[MES] - 100
        assert f["acum_anio_pasado"] == acum.get(hace_un_anio)
        comparadas += hace_un_anio in acum
    assert comparadas > 10, "hacen falta dos años para que esto pruebe algo"


def test_el_acumulado_del_anio_pasado_escrito_de_una_vez(cliente, cab_editor,
                                                         modelo):
    """Lo mismo, sin métrica intermedia: la de dentro también se resuelve sola."""
    d = con_tiempo(cliente, cab_editor, modelo)
    d["metricas"].append({
        "nombre": "acum_pasado_directo", "etiqueta": "Acum. año pasado",
        "expresion": "MISMOMESANIOANTERIOR(ACUMANIO([unidades_vendidas]))",
        "formato": "entero"})
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["acum_anio", "acum_pasado_directo"], [MES])
    assert r.status_code == 200, r.text
    filas = sorted(r.json()["filas"], key=lambda f: f[MES])
    acum = por_mes(filas, "acum_anio")
    for f in filas:
        assert f["acum_pasado_directo"] == acum.get(f[MES] - 100)


def test_no_se_acumula_el_anio_pasado_de_lo_que_no_se_suma(cliente, cab_editor,
                                                           modelo):
    """
    La capa de abajo también suma meses, así que le toca la misma revisión. Sin
    esto, meter la ventana en dos pasos era la forma de saltarse el control.
    """
    d = definicion(cliente, cab_editor, modelo)
    d["metricas"] += [
        {"nombre": "clientes", "etiqueta": "Clientes", "entidad": "fact_venta",
         "expresion": "CONTARUNICOS(cliente_id)", "formato": "entero"},
        {"nombre": "clientes_acum_pasado", "etiqueta": "Clientes, año pasado",
         "expresion": "MISMOMESANIOANTERIOR(ACUMANIO([clientes]))",
         "formato": "entero"},
    ]
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["clientes_acum_pasado"], [MES])
    assert r.status_code == 422, r.text
    assert "no se puede sumar" in r.text


def test_la_ventana_se_aplica_a_cada_cifra_y_no_al_cociente(cliente, cab_editor,
                                                            modelo):
    """
    `PROMEDIOMESES(DIVIDIR(a, b), 3)` tiene que ser la utilidad de tres meses
    entre las unidades de tres meses, no el promedio de tres cocientes. Son dos
    numeros distintos y el primero es el que significa en DAX.
    """
    d = definicion(cliente, cab_editor, modelo)
    d["metricas"] += [
        {"nombre": "uti_prom", "etiqueta": "Utilidad por unidad",
         "expresion": "DIVIDIR([monto_utilidad], [unidades_vendidas], 0)",
         "formato": "moneda"},
        {"nombre": "uti_prom_3m", "etiqueta": "Utilidad por unidad, 3 meses",
         "expresion": "PROMEDIOMESES([uti_prom], 3)", "formato": "moneda"},
        {"nombre": "uti_3m", "etiqueta": "Utilidad de 3 meses",
         "expresion": "PROMEDIOMESES([monto_utilidad], 3)", "formato": "moneda"},
        {"nombre": "unid_3m", "etiqueta": "Unidades de 3 meses",
         "expresion": "PROMEDIOMESES([unidades_vendidas], 3)", "formato": "numero"},
    ]
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["uti_prom_3m", "uti_3m", "unid_3m"], [MES])
    assert r.status_code == 200, r.text
    comparadas = 0
    for f in r.json()["filas"]:
        if not f["unid_3m"]:
            continue
        comparadas += 1
        # El /3 se cancela arriba y abajo: queda utilidad total / unidades total.
        assert f["uti_prom_3m"] == pytest.approx(f["uti_3m"] / f["unid_3m"] / 3)
    assert comparadas > 10
