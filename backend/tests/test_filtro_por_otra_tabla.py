"""
Acotar una métrica por una columna que vive en OTRA tabla.

Es el último hueco de `CALCULAR` y el más corriente de todos: «las ventas cuyo
canal es digital», donde el canal no está en la factura sino en el catálogo de
orígenes. En DAX se escribe `CALCULATE(SUM(Ventas[Unidades]),
'Dim_Origen'[categoria_canal] = "Digital")` y no hace falta decir nada más.

Aquí se escribe con el prefijo de la tabla —`dim_cliente.segmento_cliente`— y el
compilador une esa dimensión **dentro del CTE del hecho**, que es el único sitio
donde sirve: acotar después no puede, porque para entonces el hecho ya está
sumado.

Dos cosas que se comprueban aparte porque son las dos formas de equivocarse en
silencio:

- La dimensión se une por la IZQUIERDA. En el mismo CTE viven las demás métricas
  del hecho, y un JOIN normal les quitaría de en medio las filas cuya clave no
  casa, cambiando totales que nadie pidió filtrar.
- El prefijo MANDA. `sucursal_id` existe en el hecho y en el catálogo; una
  condición sobre la del catálogo tiene que leer la del catálogo.
"""

import itertools

import pytest

_siguiente = itertools.count(1)

SEG = "dim_cliente.segmento_cliente"


HUERFANAS = "ventas_con_huerfanas"


@pytest.fixture
def huerfanas(cliente, cab_admin):
    """
    Un hecho donde UNA DE CADA TRES ventas apunta a un cliente inexistente.

    Sin esto no hay forma de medir que la unión sea por la izquierda: en el
    modelo de demostración todas las ventas casan con su cliente, así que un JOIN
    normal y un LEFT JOIN dan el mismo número y la prueba pasaría por casualidad.
    """
    r = cliente.post("/api/transformaciones", headers=cab_admin, json={
        "definicion": {
            "nombre": HUERFANAS,
            "origenes": [{"nombre": "v", "tipo": "tabla",
                          "referencia": "fact_venta"}],
            "pasos": [
                {"tipo": "derivar", "nombre": "cliente_ref",
                 "expresion": "CASE WHEN venta_id % 3 = 0 THEN -1 "
                              "ELSE cliente_id END"},
            ],
        }})
    # 409 = ya la creó otra prueba de este módulo; el resultado ya está escrito.
    assert r.status_code in (201, 409), r.text
    if r.status_code == 201:
        assert cliente.post(f"/api/transformaciones/{r.json()['id']}/ejecutar",
                            headers=cab_admin).status_code == 200
    return HUERFANAS


def definicion(metricas: list[dict], nombre: str | None = None,
               hecho: str | None = None) -> dict:
    """
    El modelo mínimo: ventas, sus clientes, y las métricas que se prueben.

    `hecho` cambia la tabla de la que se lee sin cambiar nada más, para poder
    correr las mismas métricas contra el hecho con huérfanas.
    """
    llave = "cliente_ref" if hecho else "cliente_id"
    d = {
        "modelo": nombre or f"filtro_otra_{next(_siguiente)}", "version": 1,
        "entidades": [
            {"nombre": "dim_cliente", "tipo": "dimension",
             "origen": {"tabla": "dim_cliente"},
             "clave_primaria": "cliente_id",
             "campos": [
                 {"nombre": "cliente_id", "tipo": "entero", "rol": "clave"},
                 {"nombre": "segmento_cliente", "tipo": "texto",
                  "rol": "dimension"},
             ]},
            {"nombre": "fact_venta", "tipo": "hecho",
             "origen": {"tabla": hecho or "fact_venta"}, "grano": ["venta_id"],
             "campos": [
                 {"nombre": "venta_id", "tipo": "entero", "rol": "clave"},
                 {"nombre": llave, "tipo": "entero", "rol": "clave_externa"},
                 {"nombre": "unidades", "tipo": "entero", "rol": "medida_base"},
             ]},
        ],
        "relaciones": [
            {"desde": ["fact_venta", llave],
             "hasta": ["dim_cliente", "cliente_id"],
             "cardinalidad": "muchos_a_uno"},
        ],
        "metricas": metricas,
    }
    return d


TOTAL = {"nombre": "unidades", "etiqueta": "Unidades", "entidad": "fact_venta",
         "expresion": "SUMA(unidades)"}
ACOTADA = {"nombre": "unidades_seg", "etiqueta": "Unidades del segmento",
           "entidad": "fact_venta",
           "expresion": f"CALCULAR(SUMA(unidades), {SEG} = 'Flotilla')"}


def crear(cliente, cab, d: dict) -> int:
    r = cliente.post("/api/modelos", headers=cab,
                     json={"nombre": d["modelo"], "definicion": d})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def consultar(cliente, cab, modelo_id, metricas, dimensiones=()):
    return cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab,
                        json={"dimensiones": list(dimensiones),
                              "metricas": metricas})


@pytest.fixture
def segmentos(cliente, cab_admin):
    """Los segmentos que hay de verdad, para no afirmar sobre datos inventados."""
    modelo = crear(cliente, cab_admin, definicion([TOTAL]))
    r = consultar(cliente, cab_admin, modelo, ["unidades"], [SEG])
    assert r.status_code == 200, r.text
    return {f[SEG]: f["unidades"] for f in r.json()["filas"]}


# --------------------------------------------------------------------------- #

def test_la_condicion_acota_por_la_columna_de_la_dimension(cliente, cab_admin,
                                                           segmentos):
    """
    La comprobación de fondo. La métrica acotada tiene que dar exactamente lo que
    da el total desglosado por ese segmento — el mismo número, calculado por dos
    caminos distintos.
    """
    assert "Flotilla" in segmentos, segmentos
    modelo = crear(cliente, cab_admin, definicion([TOTAL, ACOTADA]))
    r = consultar(cliente, cab_admin, modelo, ["unidades", "unidades_seg"])
    assert r.status_code == 200, r.text
    fila = r.json()["filas"][0]
    assert fila["unidades_seg"] == segmentos["Flotilla"]
    # Y no es que haya acotado todo: el total sigue siendo mayor.
    assert fila["unidades"] > fila["unidades_seg"]


def test_el_total_del_mismo_cte_no_se_toca(cliente, cab_admin, huerfanas):
    """
    Las dos métricas comparten CTE, así que la unión que hizo falta para una NO
    puede cambiar la otra.

    Es lo que obliga a unir por la izquierda, y se mide con un hecho en el que
    UNA DE CADA TRES filas apunta a un cliente que no existe: con un JOIN normal
    ese tercio desaparecería también del total, que nadie pidió filtrar. El
    modelo de demostración no sirve para esto —todas sus ventas casan— y por eso
    el hecho se fabrica.
    """
    solo = crear(cliente, cab_admin, definicion([TOTAL], hecho=huerfanas))
    con = crear(cliente, cab_admin,
                definicion([TOTAL, ACOTADA], hecho=huerfanas))
    a = consultar(cliente, cab_admin, solo, ["unidades"]).json()["filas"][0]
    r = consultar(cliente, cab_admin, con, ["unidades", "unidades_seg"])
    b = r.json()["filas"][0]
    assert a["unidades"] == b["unidades"]
    assert "LEFT JOIN" in r.json()["sql"]
    # Y el tercio huérfano es de verdad un tercio: si fuera despreciable, la
    # comprobación de arriba pasaria por casualidad.
    assert b["unidades_seg"] < a["unidades"] * 0.5


def test_desglosada_por_otra_cosa_sigue_cuadrando(cliente, cab_admin, segmentos):
    """
    La suma de la métrica acotada por cualquier desglose tiene que seguir siendo
    el total de ese segmento. Si la unión duplicara filas, esto saldría de más.
    """
    modelo = crear(cliente, cab_admin, definicion([ACOTADA]))
    r = consultar(cliente, cab_admin, modelo, ["unidades_seg"], [SEG])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    total = sum(f["unidades_seg"] or 0 for f in filas)
    assert total == segmentos["Flotilla"]
    # Y en las demás filas la métrica no cuenta nada: el segmento no es ese.
    otras = [f for f in filas if f[SEG] != "Flotilla"]
    assert otras and all(not f["unidades_seg"] for f in otras)


def test_el_prefijo_manda_sobre_una_columna_que_existe_en_las_dos(cliente,
                                                                  cab_admin):
    """
    `cliente_id` está en el hecho Y en la dimensión. Una condición sobre la de la
    dimensión tiene que leer la de la dimensión: si el compilador la resolviera
    contra el hecho el número saldría igual —son iguales cuando la unión casa— y
    distinto en cuanto no casa, que es justo cuando importa.
    """
    d = definicion([{"nombre": "por_dimension", "etiqueta": "x",
                     "entidad": "fact_venta",
                     "expresion": "CALCULAR(SUMA(unidades), "
                                  "dim_cliente.cliente_id = 1)"}])
    d["entidades"][0]["campos"].append(
        {"nombre": "cliente_id_x", "tipo": "entero", "rol": "clave"})
    modelo = crear(cliente, cab_admin, d)
    r = consultar(cliente, cab_admin, modelo, ["por_dimension"])
    assert r.status_code == 200, r.text
    sql = r.json()["sql"]
    # El alias de la dimensión es el que va en la condición, no el del hecho.
    alias_dim = sql.split('"dim_cliente" AS ')[1].split()[0]
    alias_hecho = sql.split('"fact_venta" AS ')[1].split()[0]
    assert f'"{alias_dim}"."cliente_id" = 1' in sql
    assert f'"{alias_hecho}"."cliente_id" = 1' not in sql


def test_una_tabla_sin_camino_se_dice_al_guardar(cliente, cab_admin):
    """
    Nombrar una tabla con la que el hecho no se relaciona no puede fallar en el
    tablero de alguien: el diagnóstico lo dice antes.
    """
    d = definicion([{"nombre": "suelta", "etiqueta": "x",
                     "entidad": "fact_venta",
                     "expresion": "CALCULAR(SUMA(unidades), "
                                  "dim_cliente.segmento_cliente = 'Flotilla')"}])
    d["relaciones"] = []
    modelo = crear(cliente, cab_admin, d)
    r = cliente.get(f"/api/modelos/{modelo}/diagnostico", headers=cab_admin)
    assert r.status_code == 200, r.text
    tipos = [p["tipo"] for p in r.json()["problemas"]]
    assert "condicion_sin_camino" in tipos
    fallo = next(p for p in r.json()["problemas"]
                 if p["tipo"] == "condicion_sin_camino")
    assert "dim_cliente" in fallo["mensaje"]
    assert fallo["gravedad"] == "critico"


def test_una_columna_que_no_existe_en_esa_tabla(cliente, cab_admin, modelo_id):
    """
    El mensaje tiene que hablar de la tabla que se nombró, no de la del hecho:
    «no es un campo de esta entidad» sería exactamente lo contrario de lo que
    pasa.
    """
    r = cliente.post(f"/api/modelos/{modelo_id}/revisar-formula",
                     headers=cab_admin, json={
                         "entidad": "fact_venta",
                         "expresion": "CALCULAR(SUMA(unidades), "
                                      "dim_cliente.segmentto = 'x')"})
    assert r.status_code == 200, r.text
    fallos = r.json()["fallos"]
    assert r.json()["hay_errores"] is True
    assert any("dim_cliente" in f["mensaje"] and "segmento_cliente" in f["mensaje"]
               for f in fallos), fallos


def test_una_tabla_que_no_esta_en_el_modelo(cliente, cab_admin, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/revisar-formula",
                     headers=cab_admin, json={
                         "entidad": "fact_venta",
                         "expresion": "CALCULAR(SUMA(unidades), "
                                      "dim_clientte.segmento_cliente = 'x')"})
    assert r.status_code == 200, r.text
    fallos = r.json()["fallos"]
    assert any("no es una tabla de este modelo" in f["mensaje"] and
               "dim_cliente" in f["mensaje"] for f in fallos), fallos


def test_el_navegador_puede_revisar_contra_lo_que_tiene_en_pantalla(
        cliente, cab_admin, modelo_id):
    """
    Quien escribe la fórmula puede estar nombrando una tabla que acaba de crear y
    todavía no ha guardado. Se revisa contra lo que manda el navegador.
    """
    r = cliente.post(f"/api/modelos/{modelo_id}/revisar-formula",
                     headers=cab_admin, json={
                         "entidad": "hecho_nuevo",
                         "expresion": "CALCULAR(SUMA(unidades), "
                                      "dim_nueva.canal = 'Digital')",
                         "campos": ["unidades"],
                         "campos_por_entidad": {"hecho_nuevo": ["unidades"],
                                                "dim_nueva": ["canal"]}})
    assert r.status_code == 200, r.text
    assert r.json()["hay_errores"] is False, r.json()["fallos"]
