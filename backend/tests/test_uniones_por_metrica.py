"""
Elegir por qué fecha se une un hecho, métrica por métrica.

Un hecho toca el calendario por más de una fecha mucho más a menudo de lo que
parece. Un contacto tiene fecha de primera visita, de asignación y de prueba de
manejo, y **cada indicador cuenta por la suya**: el tráfico de piso por la visita,
los leads asignados por la asignación.

Sólo una relación puede estar activa —si mandaran dos, cada consulta tendría dos
caminos igual de válidos y el total dependería de cuál eligiera el compilador—. Las
demás se dejan dibujadas e inactivas, y la métrica dice cuál es la suya. Es el
`USERELATIONSHIP` de DAX.

El escenario es de verdad y no un doble: se deriva un hecho con dos fechas
separadas por un mes exacto, así que la misma suma desglosada por mes tiene que
salir **corrida un mes** según por cuál se una. Si el motor ignorara la unión
pedida, los dos números saldrían iguales y la prueba fallaría.
"""

import itertools

import pytest

_siguiente = itertools.count(1)

HECHO = "ventas_dos_fechas"
MES = "dim_calendario.anio_mes"

@pytest.fixture
def hecho(cliente, cab_admin):
    """
    Un hecho con dos fechas: la real y la misma corrida UN MES.

    Un mes y no treinta días: con días, el 31 de enero se va a marzo y el
    desplazamiento deja de ser de un mes para las fechas de fin de mes. Con
    `INTERVAL 1 MONTH` cada fecha cae en el mismo día del mes siguiente, así que
    la serie sale corrida exactamente un mes y se puede afirmar cuál es cuál.
    """
    r = cliente.post("/api/transformaciones", headers=cab_admin, json={
        "definicion": {
            "nombre": HECHO,
            "origenes": [{"nombre": "v", "tipo": "tabla",
                          "referencia": "fact_venta"}],
            "pasos": [
                {"tipo": "derivar", "nombre": "fecha_visita",
                 "expresion": "fecha_emision"},
                {"tipo": "derivar", "nombre": "fecha_prueba",
                 "expresion": "fecha_emision + INTERVAL 1 MONTH"},
            ],
        }})
    # 409 = ya la creó otra prueba de este mismo módulo; el resultado ya está
    # escrito y sirve igual.
    assert r.status_code in (201, 409), r.text
    if r.status_code == 201:
        id_ = r.json()["id"]
        assert cliente.post(f"/api/transformaciones/{id_}/ejecutar",
                            headers=cab_admin).status_code == 200
    return HECHO


def definicion(por_defecto: str = "fecha_visita") -> dict:
    """
    El modelo: el hecho, el calendario, y las DOS relaciones —una activa y la
    otra dibujada pero inactiva—.
    """
    return {
        "modelo": f"uniones_{next(_siguiente)}", "version": 1,
        "entidades": [
            {"nombre": "dim_calendario", "tipo": "dimension",
             "origen": {"tabla": "dim_calendario"},
             "clave_primaria": "fecha",
             "campos": [
                 {"nombre": "fecha", "tipo": "fecha", "rol": "clave"},
                 {"nombre": "anio_mes", "tipo": "entero", "rol": "dimension",
                  "grano_tiempo": "mes"},
             ]},
            {"nombre": HECHO, "tipo": "hecho",
             "origen": {"tabla": HECHO}, "grano": ["venta_id"],
             "campos": [
                 {"nombre": "venta_id", "tipo": "entero", "rol": "clave"},
                 {"nombre": "fecha_visita", "tipo": "fecha", "rol": "clave_externa"},
                 {"nombre": "fecha_prueba", "tipo": "fecha", "rol": "clave_externa"},
                 {"nombre": "unidades", "tipo": "entero", "rol": "medida_base"},
             ]},
        ],
        "relaciones": [
            {"desde": [HECHO, "fecha_visita"], "hasta": ["dim_calendario", "fecha"],
             "cardinalidad": "muchos_a_uno",
             "activa": por_defecto == "fecha_visita"},
            {"desde": [HECHO, "fecha_prueba"], "hasta": ["dim_calendario", "fecha"],
             "cardinalidad": "muchos_a_uno",
             "activa": por_defecto == "fecha_prueba"},
        ],
        "metricas": [
            {"nombre": "por_visita", "etiqueta": "Por la visita",
             "entidad": HECHO, "expresion": "SUMA(unidades)"},
            {"nombre": "por_prueba", "etiqueta": "Por la prueba",
             "entidad": HECHO, "expresion": "SUMA(unidades)",
             "uniones": [f"{HECHO}.fecha_prueba -> dim_calendario.fecha"]},
        ],
    }


def crear(cliente, cab, d: dict) -> int:
    r = cliente.post("/api/modelos", headers=cab,
                     json={"nombre": d["modelo"], "definicion": d})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def consultar(cliente, cab, modelo_id, metricas, dimensiones):
    return cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab,
                        json={"dimensiones": dimensiones, "metricas": metricas})


# --------------------------------------------------------------------------- #

def test_la_metrica_se_une_por_la_fecha_que_pidio(cliente, cab_admin, hecho):
    """
    La comprobación de fondo. Las dos métricas son la MISMA suma sobre el MISMO
    hecho; lo único distinto es por qué fecha llegan al calendario. Como las dos
    fechas van separadas por un mes exacto, la serie tiene que salir corrida:
    lo que `por_visita` pone en enero, `por_prueba` lo pone en febrero.
    """
    modelo = crear(cliente, cab_admin, definicion())
    r = consultar(cliente, cab_admin, modelo, ["por_visita", "por_prueba"], [MES])
    assert r.status_code == 200, r.text
    filas = sorted(r.json()["filas"], key=lambda f: f[MES])
    assert len(filas) > 6

    visita = {f[MES]: f["por_visita"] for f in filas}
    prueba = {f[MES]: f["por_prueba"] for f in filas}

    def mes_siguiente(m: int) -> int:
        return m + 1 if m % 100 < 12 else (m // 100 + 1) * 100 + 1

    comparados = 0
    for mes, valor in visita.items():
        if valor is None:
            continue
        siguiente = mes_siguiente(mes)
        if siguiente not in prueba or prueba[siguiente] is None:
            continue
        comparados += 1
        assert prueba[siguiente] == valor, (
            f"lo de {mes} por la visita ({valor}) tenia que caer en "
            f"{siguiente} por la prueba, y cayo {prueba[siguiente]}")
    assert comparados > 5, "no se compararon suficientes meses"


def test_sin_pedir_nada_manda_la_activa(cliente, cab_admin, hecho):
    """
    Una métrica que no dice nada se une por la activa, como siempre. Se comprueba
    dando la vuelta al modelo: con la otra relación activa, la métrica que no pide
    nada cambia de número y la que pide la suya no.
    """
    normal = crear(cliente, cab_admin, definicion(por_defecto="fecha_visita"))
    vuelta = crear(cliente, cab_admin, definicion(por_defecto="fecha_prueba"))

    a = consultar(cliente, cab_admin, normal, ["por_visita", "por_prueba"], [MES])
    b = consultar(cliente, cab_admin, vuelta, ["por_visita", "por_prueba"], [MES])
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)

    pa = {f[MES]: f for f in a.json()["filas"]}
    pb = {f[MES]: f for f in b.json()["filas"]}
    comunes = set(pa) & set(pb)
    assert len(comunes) > 6

    # La que pide su relación da lo mismo en los dos modelos.
    assert all(pa[m]["por_prueba"] == pb[m]["por_prueba"] for m in comunes)
    # La que no pide nada sigue a la activa, así que cambia.
    assert any(pa[m]["por_visita"] != pb[m]["por_visita"] for m in comunes)


def test_dos_metricas_del_mismo_hecho_con_uniones_distintas(cliente, cab_admin,
                                                            hecho):
    """
    Las dos salen en la misma consulta, cada una por su fecha. Es lo que obliga a
    agrupar los CTE por entidad **y** por unión: con un solo CTE por entidad, la
    segunda métrica se uniría por donde se hubiera unido la primera.
    """
    modelo = crear(cliente, cab_admin, definicion())
    r = consultar(cliente, cab_admin, modelo, ["por_visita", "por_prueba"], [MES])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    distintas = [f for f in filas
                 if f["por_visita"] is not None and f["por_prueba"] is not None
                 and f["por_visita"] != f["por_prueba"]]
    assert distintas, "las dos columnas salieron iguales: se unieron igual"


def test_una_union_que_no_existe_no_se_guarda(cliente, cab_admin, hecho):
    """
    Nombrar mal una relación no falla al compilar: el grafo simplemente no cambia
    por ahí, y la métrica devuelve la cifra de la relación activa como si tal
    cosa. Por eso se para al guardar.
    """
    d = definicion()
    d["metricas"][1]["uniones"] = [f"{HECHO}.fecha_que_no_existe -> dim_calendario.fecha"]
    r = cliente.post("/api/modelos", headers=cab_admin,
                     json={"nombre": d["modelo"], "definicion": d})
    assert r.status_code == 422, r.text
    assert "no es ninguna relacion del modelo" in r.text


def test_una_union_que_no_toca_al_hecho_no_se_guarda(cliente, cab_admin, hecho):
    """Elegirla no cambiaría nada, y la cifra saldría por la activa sin avisar."""
    d = definicion()
    d["entidades"].append({
        "nombre": "otro_hecho", "tipo": "hecho",
        "origen": {"tabla": HECHO}, "grano": ["venta_id"],
        "campos": [{"nombre": "venta_id", "tipo": "entero", "rol": "clave"},
                   {"nombre": "fecha_visita", "tipo": "fecha",
                    "rol": "clave_externa"}]})
    d["relaciones"].append({
        "desde": ["otro_hecho", "fecha_visita"],
        "hasta": ["dim_calendario", "fecha"],
        "cardinalidad": "muchos_a_uno", "activa": False})
    d["metricas"][1]["uniones"] = ["otro_hecho.fecha_visita -> dim_calendario.fecha"]

    r = cliente.post("/api/modelos", headers=cab_admin,
                     json={"nombre": d["modelo"], "definicion": d})
    assert r.status_code == 422, r.text
    assert "no toca esa entidad" in r.text


def test_una_compuesta_no_elige_relaciones(cliente, cab_admin, hecho):
    """No lee ninguna tabla, así que no hay nada por donde unirla."""
    d = definicion()
    d["metricas"].append({
        "nombre": "cociente", "etiqueta": "Cociente",
        "expresion": "DIVIDIR([por_visita], [por_prueba], 0)",
        "uniones": [f"{HECHO}.fecha_prueba -> dim_calendario.fecha"]})
    r = cliente.post("/api/modelos", headers=cab_admin,
                     json={"nombre": d["modelo"], "definicion": d})
    assert r.status_code == 422, r.text
    assert "no puede elegir relaciones" in r.text
