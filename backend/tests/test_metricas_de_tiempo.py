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


def test_sin_columna_de_meses_el_mes_lo_pone_el_filtro(cliente, cab_editor, modelo):
    """
    Una tabla de una fila por sucursal con «el mes anterior» al lado.

    Es como se lee un informe de verdad —y como esta armada la pagina de Power BI
    que se esta traduciendo—: el periodo lo pone el filtro de arriba, no una columna
    de meses en la tabla. Antes esto fallaba pidiendo esa columna, y agregarla
    convertia una fila por sucursal en una por sucursal y mes, que es otro informe.

    Se comprueba contra la aritmetica hecha aparte: la cifra que trae la fila tiene
    que ser EXACTAMENTE la del mes de antes, sacada de una consulta por meses.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    # La verdad, mes a mes, para una sucursal.
    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [MES, SUC])
    assert r.status_code == 200, r.text
    una = r.json()["filas"][0][SUC]
    por = {f[MES]: f["unidades_vendidas"] for f in r.json()["filas"]
           if f[SUC] == una}
    meses = sorted(por)
    assert len(meses) >= 2, "hacen falta dos meses para que haya uno anterior"
    mes, previo = meses[-1], meses[-2]

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "mes_anterior"], [SUC],
                  filtros=[{"campo": MES, "op": "=", "valor": mes}])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    fila = next(f for f in cuerpo["filas"] if f[SUC] == una)

    assert fila["unidades_vendidas"] == por[mes]
    assert fila["mes_anterior"] == por[previo]
    # Y una fila por sucursal, no una por sucursal y mes.
    assert len(cuerpo["filas"]) == len({f[SUC] for f in cuerpo["filas"]})
    # El mes que se uso se cuenta, pero no se cuela como columna de la tabla.
    assert cuerpo["mes_usado"] == mes
    assert MES not in cuerpo["columnas"]
    assert not any(c.startswith("__") for c in cuerpo["columnas"])


def test_el_mes_lo_puede_poner_un_filtro_de_año_y_mes_por_separado(
        cliente, cab_editor, modelo):
    """
    Filtrando por año y por mes en columnas distintas —no por la de «año-mes»—.

    Es como esta armado el informe que se esta traduciendo: dos filtros arriba, uno
    de año y otro con el nombre del mes, y ninguno de los dos es la columna marcada
    como mes. La primera version solo levantaba los filtros de la columna marcada,
    asi que la capa de dentro se quedaba con un unico mes y «el mes anterior» salia
    vacio, sin decir nada.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    ANIO, MES_1_12 = "dim_calendario.anio", "dim_calendario.mes"

    # La verdad, mes a mes, para una sucursal.
    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [MES, SUC])
    una = r.json()["filas"][0][SUC]
    por = {f[MES]: f["unidades_vendidas"] for f in r.json()["filas"]
           if f[SUC] == una}
    meses = sorted(por)
    # Dos meses SEGUIDOS del mismo año: es el mes de al lado lo que se compara.
    mes = next(m for m in reversed(meses) if m % 100 > 1 and m - 1 in por)
    previo = mes - 1

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "mes_anterior"], [SUC],
                  filtros=[{"campo": ANIO, "op": "=", "valor": mes // 100},
                           {"campo": MES_1_12, "op": "=", "valor": mes % 100}])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    fila = next(f for f in cuerpo["filas"] if f[SUC] == una)

    assert fila["unidades_vendidas"] == por[mes]
    assert fila["mes_anterior"] == por[previo], "el mes anterior salio vacio"
    assert cuerpo["mes_usado"] == mes
    assert len(cuerpo["filas"]) == len({f[SUC] for f in cuerpo["filas"]})


def test_un_filtro_de_dias_no_se_estira_al_mes_en_silencio(
        cliente, cab_editor, modelo):
    """
    Con un dia filtrado, «el mes anterior» no existe — y callarlo es lo peligroso.

    Levantar ese filtro como se levantan los de año y mes convertiria el periodo en
    el mes entero, y entonces las unidades del dia saldrian siendo las del mes: un
    numero de otra cosa, en la misma fila, sin nada que lo delate.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "mes_anterior"], [SUC],
                  filtros=[{"campo": "dim_calendario.fecha", "op": "=",
                            "valor": "2026-07-15"}])
    assert r.status_code == 422, r.text
    assert "es de dias" in r.text and "dim_calendario.anio_mes" in r.text


def test_sin_filtro_de_fecha_manda_el_ultimo_mes_con_datos(
        cliente, cab_editor, modelo):
    """
    Sin filtro de fecha, el mes lo pone el dato: el ultimo que tiene LA cifra.

    Es lo que se decidio, y trae una consecuencia que hay que poder ver: la cifra
    cambia al cargar el mes siguiente sin que nadie toque el informe. Por eso el mes
    usado viaja en la respuesta — y por eso esta prueba lo exige.
    """
    assert guardar(cliente, cab_editor, modelo,
                   con_tiempo(cliente, cab_editor, modelo)).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [MES])
    por = {f[MES]: f["unidades_vendidas"] for f in r.json()["filas"]}
    ultimo = max(por)

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_vendidas", "mes_anterior"], [])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["mes_usado"] == ultimo
    assert len(cuerpo["filas"]) == 1
    assert cuerpo["filas"][0]["unidades_vendidas"] == por[ultimo]


def test_manda_el_ultimo_mes_con_LA_CIFRA_y_no_con_cualquier_dato(
        cliente, cab_editor, modelo):
    """
    Un objetivo cargado hasta diciembre no hace que diciembre sea el mes del que
    hablar cuando lo que se compara son ventas.

    Es el caso real: la tabla de objetivos trae el año completo desde enero y las
    ventas llegan hasta donde llego la ultima carga. Con «el ultimo mes con datos» a
    secas mandaba el ultimo mes del objetivo, y la fila salia con el objetivo puesto
    y todas las columnas de venta vacias — una tabla en blanco que no dice por que.
    Manda el ultimo mes que tenga LA cifra que se compara.

    Aqui las ventas se cortan a mano con un CASE, porque en los datos de
    demostracion los dos hechos acaban el mismo mes.
    """
    d = definicion(cliente, cab_editor, modelo)
    corte = 202605
    d["metricas"] += [
        {"nombre": "unidades_cortas", "etiqueta": "Unidades (hasta el corte)",
         "entidad": "fact_venta", "formato": "entero",
         "expresion": f"SUM(CASE WHEN YEAR(fecha_emision) * 100 + "
                      f"MONTH(fecha_emision) <= {corte} THEN unidades END)"},
        {"nombre": "cortas_mes_ant", "etiqueta": "Mes anterior", "formato": "entero",
         "expresion": "MESANTERIOR([unidades_cortas])"},
    ]
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    # El objetivo llega mas lejos que las ventas cortadas: es lo que hace la prueba.
    r = consultar(cliente, cab_editor, modelo, ["objetivo_unidades"], [MES])
    assert max(f[MES] for f in r.json()["filas"]) > corte

    r = consultar(cliente, cab_editor, modelo,
                  ["unidades_cortas", "cortas_mes_ant", "objetivo_unidades"], [SUC])
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["mes_usado"] == corte
    # Y la fila trae cifra, que es el punto: no sale en blanco.
    assert any(f["unidades_cortas"] for f in cuerpo["filas"])
    assert any(f["cortas_mes_ant"] for f in cuerpo["filas"])
    # Las cifras escondidas para elegir el mes no se cuelan en la respuesta.
    assert not any(c.startswith("__") for c in cuerpo["columnas"])


def test_si_el_modelo_no_marca_ningun_mes_se_explica(cliente, cab_editor, modelo):
    """
    Sin ninguna columna marcada como mes no hay contexto del que sacar el periodo, y
    entonces «el mes anterior» no significa nada. Se dice, en vez de devolver el
    total repetido con pinta de comparacion.
    """
    d = con_tiempo(cliente, cab_editor, modelo)
    for ent in d["entidades"]:
        for campo in ent.get("campos", []):
            campo.pop("grano_tiempo", None)
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["mes_anterior"], [SUC])
    assert r.status_code == 422, r.text
    assert "grano de tiempo" in r.text
    # Y el mensaje se lee: la primera version imprimia la entidad entera —campos,
    # tipos, claves— y lo util quedaba sepultado en media pantalla de texto.
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


def test_lo_que_esta_fuera_de_la_ventana_no_tiene_que_poder_sumarse(
        cliente, cab_editor, modelo):
    """
    La revisión de «esto no se puede sumar por meses» valía para TODAS las
    dependencias en cuanto una sola ventana era ancha, y eso rechazaba fórmulas
    correctas.

    El caso es de verdad: el objetivo de utilidad por unidad es un promedio del
    propio mes, y cuando no está cargado se cae al promedio de los tres meses
    anteriores de la cifra real. Lo único que se suma en tres meses es esa cifra
    real; el objetivo se lee del mes de la fila —está en la condición, fuera de la
    ventana— así que da igual que sea un promedio. Antes la fórmula entera quedaba
    rechazada por su culpa.
    """
    d = definicion(cliente, cab_editor, modelo)
    d["metricas"] += [
        # Un promedio: NO es aditivo. Antes bastaba con nombrarlo.
        {"nombre": "obj_uti", "etiqueta": "Objetivo de utilidad",
         "entidad": "fact_presupuesto", "expresion": "PROMEDIO(objetivo_monto)",
         "formato": "moneda"},
        {"nombre": "uti_unidad", "etiqueta": "Utilidad por unidad",
         "expresion": "DIVIDIR([monto_utilidad], [unidades_vendidas], 0)",
         "formato": "moneda"},
        {"nombre": "obj_con_respaldo", "etiqueta": "Objetivo, con respaldo",
         "expresion": "SI(O(ESVACIO([obj_uti]), [obj_uti] = 0),"
                      " PROMEDIOMESES([uti_unidad], 3), [obj_uti])",
         "formato": "moneda"},
    ]
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["obj_con_respaldo", "obj_uti"],
                  [MES])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert filas
    # Y donde el objetivo existe, es el objetivo lo que sale: el respaldo no se
    # cuela cuando no hace falta.
    con_objetivo = [f for f in filas if f["obj_uti"]]
    assert con_objetivo
    assert all(f["obj_con_respaldo"] == f["obj_uti"] for f in con_objetivo)


def test_dentro_de_la_ventana_sigue_sin_poder_sumarse(cliente, cab_editor,
                                                      modelo):
    """El aviso tiene que sobrevivir al arreglo de arriba: el mismo promedio,
    ahora SÍ metido dentro de la ventana, se sigue rechazando."""
    d = definicion(cliente, cab_editor, modelo)
    d["metricas"] += [
        {"nombre": "obj_uti2", "etiqueta": "Objetivo de utilidad",
         "entidad": "fact_presupuesto", "expresion": "PROMEDIO(objetivo_monto)",
         "formato": "moneda"},
        {"nombre": "obj_uti2_3m", "etiqueta": "Objetivo, 3 meses",
         "expresion": "PROMEDIOMESES([obj_uti2], 3)", "formato": "moneda"},
    ]
    assert guardar(cliente, cab_editor, modelo, d).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["obj_uti2_3m"], [MES])
    assert r.status_code == 422, r.text
    assert "no se puede sumar" in r.text
