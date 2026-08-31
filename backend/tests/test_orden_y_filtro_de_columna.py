"""
Ordenar y filtrar por columna, en el SERVIDOR.

Lo que esto arregla no es la comodidad de una casilla. Es que el LIMITE corta
DESPUES: una tabla de cien mil filas llega recortada a doscientas, y ordenar esas
doscientas por fecha no da la ultima factura —da la ultima de las doscientas
primeras que el motor encontro—. Mientras el recorte no se dice, la tabla se lee
como si fuera todo, y las conclusiones se sacan de una muestra que nadie eligio.

De ahi las tres cosas que se comprueban aqui:

  - el orden viaja a la consulta, asi que el recorte se queda con las filas que se
    pidieron y no con las que salieron primero;
  - el filtro tambien, asi que filtra los datos y no la muestra;
  - y el servidor pide una fila MAS de las que devuelve, para poder DECIR que hay
    mas.

Y una que no es de comodidad tampoco: ordenar o filtrar por una columna que no
esta en la consulta es un error con nombre, no un ORDER BY a ciegas. Una fila
arriba por un motivo invisible no se puede comprobar.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)

SUC = "cat_sucursal.sucursal_nombre"
MES = "dim_calendario.anio_mes"


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"orden_col_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def consultar(cliente, cab, mid, **cuerpo):
    cuerpo.setdefault("metricas", ["unidades_vendidas"])
    return cliente.post(f"/api/modelos/{mid}/consultar", headers=cab, json=cuerpo)


def previa(cliente, cab, mid, **cuerpo):
    cuerpo.setdefault("metricas", ["unidades_vendidas"])
    return cliente.post(f"/api/modelos/{mid}/vista-previa", headers=cab, json=cuerpo)


def muestra(cliente, cab, mid, **cuerpo):
    cuerpo.setdefault("entidad", "fact_venta")
    return cliente.post(f"/api/modelos/{mid}/muestra", headers=cab, json=cuerpo)


# ------------------------------------------------------------- la agregada ---

def test_sin_orden_manda_el_desglose(cliente, cab_editor, modelo):
    """Lo de siempre: ordenado por las columnas del desglose, de menor a mayor."""
    r = consultar(cliente, cab_editor, modelo, dimensiones=[SUC])
    assert r.status_code == 200, r.text
    nombres = [f[SUC] for f in r.json()["filas"]]
    assert nombres == sorted(nombres)


def test_ordenar_por_una_metrica_de_mayor_a_menor(cliente, cab_editor, modelo):
    r = consultar(cliente, cab_editor, modelo, dimensiones=[SUC],
                  orden="unidades_vendidas", descendente=True)
    assert r.status_code == 200, r.text
    cifras = [f["unidades_vendidas"] for f in r.json()["filas"]]
    assert cifras == sorted(cifras, reverse=True)
    # Y que no sea el orden alfabetico disfrazado: si coincidieran, la prueba no
    # distinguiria un ORDER BY que funciona de uno que no se aplico.
    nombres = [f[SUC] for f in r.json()["filas"]]
    assert nombres != sorted(nombres)


def test_el_orden_decide_QUE_filas_sobreviven_al_limite(cliente, cab_editor, modelo):
    """
    Lo que hace que esto valga la pena.

    Con limite 3, ordenando al reves salen OTRAS tres filas: eso es lo que no se
    puede conseguir reordenando en pantalla lo que llego.
    """
    arriba = consultar(cliente, cab_editor, modelo, dimensiones=[SUC], limite=3,
                       orden="unidades_vendidas", descendente=True)
    abajo = consultar(cliente, cab_editor, modelo, dimensiones=[SUC], limite=3,
                      orden="unidades_vendidas", descendente=False)
    assert arriba.status_code == abajo.status_code == 200
    unos = [f[SUC] for f in arriba.json()["filas"]]
    otros = [f[SUC] for f in abajo.json()["filas"]]
    assert len(unos) == len(otros) == 3
    assert set(unos) != set(otros)


def test_los_vacios_van_al_final_aunque_se_baje(cliente, cab_editor, modelo):
    """
    Misma regla que la ordenacion en pantalla: los vacios SIEMPRE al final, suba o
    baje el resto. Que una tabla ordenara distinto segun por donde se ordeno seria
    peor que no poder ordenarla.

    Los vacios se consiguen con «mostrar las filas sin cifras» y un filtro que solo
    deja una sucursal con ventas: las demas salen, y salen en blanco.
    """
    r = consultar(cliente, cab_editor, modelo, dimensiones=[SUC],
                  filas_sin_cifras=True,
                  filtros=[{"campo": "fact_venta.serie", "op": "=",
                            "valor": "AC1"}],
                  orden="unidades_vendidas", descendente=True)
    assert r.status_code == 200, r.text
    valores = [f["unidades_vendidas"] for f in r.json()["filas"]]
    assert any(v is None for v in valores), "sin vacios esta prueba no comprueba nada"
    assert any(v is not None for v in valores)
    # Ningun vacio antes de un lleno, aunque el orden sea descendente.
    vistos = [v is None for v in valores]
    assert vistos == sorted(vistos)


def test_ordenar_por_algo_que_no_se_pidio_es_un_error_con_nombre(
        cliente, cab_editor, modelo):
    r = consultar(cliente, cab_editor, modelo, dimensiones=[SUC],
                  orden="cat_marca.marca_nombre")
    assert r.status_code == 422, r.text
    texto = r.text
    assert "cat_marca.marca_nombre" in texto
    # Y que diga cuales SI hay: un «no se puede» sin la lista obliga a adivinar.
    assert SUC in texto


def test_se_puede_ordenar_por_el_mes_escondido(cliente, cab_editor, modelo):
    """
    Con una metrica de tiempo y sin columna de meses en el desglose, el resultado
    lleva `__mes_usado`: el mes contra el que se calculo. Es una columna como las
    demas y se puede ordenar por ella — y por eso hay que acordarse de que existe,
    que es lo que esta prueba vigila.
    """
    d = cliente.get(f"/api/modelos/{modelo}/definicion",
                    headers=cab_editor).json()["definicion"]
    d["metricas"].append({
        "nombre": "unidades_mes_anterior", "etiqueta": "Unidades mes anterior",
        "formato": "entero", "expresion": "MESANTERIOR([unidades_vendidas])"})
    r = previa(cliente, cab_editor, modelo, definicion=d, dimensiones=[SUC],
               metricas=["unidades_vendidas", "unidades_mes_anterior"],
               orden="__mes_usado", descendente=True)
    assert r.status_code == 200, r.text
    # No sale como columna de la tabla —se cuenta aparte, en `mes_usado`—, pero el
    # ORDER BY si la ve, y eso es lo que hay que no olvidar al validar el orden.
    assert r.json()["columnas"] == [SUC, "unidades_vendidas", "unidades_mes_anterior"]


# --------------------------------------------------------------- el recorte ---

def test_la_vista_previa_avisa_de_que_hay_mas(cliente, cab_editor, modelo):
    r = previa(cliente, cab_editor, modelo, dimensiones=[SUC], limite=2)
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["filas"]) == 2, "la fila de sobra no se devuelve, solo se cuenta"
    assert d["truncado"] is True


def test_la_vista_previa_no_avisa_cuando_cabe_todo(cliente, cab_editor, modelo):
    r = previa(cliente, cab_editor, modelo, dimensiones=[SUC], limite=500)
    assert r.status_code == 200, r.text
    assert r.json()["truncado"] is False


def test_la_muestra_tambien_avisa(cliente, cab_editor, modelo):
    r = muestra(cliente, cab_editor, modelo, limite=5)
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["filas"]) == 5
    assert d["truncado"] is True


# ---------------------------------------------------- la muestra sin agregar ---

def test_la_muestra_filtra_en_el_motor_y_no_la_muestra(cliente, cab_editor, modelo):
    """
    La prueba que separa filtrar los datos de filtrar lo que llego.

    Se filtra por las ultimas ventas y se pide un limite de cinco. Las filas que
    vuelven NO estan entre las cinco que se ven sin filtro: filtrando en pantalla
    serian inalcanzables, porque nunca habrian llegado.
    """
    ultima = muestra(cliente, cab_editor, modelo, limite=1,
                     orden="venta_id", descendente=True)
    assert ultima.status_code == 200, ultima.text
    tope = ultima.json()["filas"][0]["venta_id"]

    sin_filtro = muestra(cliente, cab_editor, modelo, limite=5)
    primeras = {f["venta_id"] for f in sin_filtro.json()["filas"]}

    r = muestra(cliente, cab_editor, modelo, limite=5, filtros=[
        {"campo": "fact_venta.venta_id", "op": ">=", "valor": tope - 3}])
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert filas, "el filtro dejo la tabla vacia: no comprueba nada"
    assert all(f["venta_id"] >= tope - 3 for f in filas)
    assert not (primeras & {f["venta_id"] for f in filas})


def test_la_muestra_ordena_al_reves(cliente, cab_editor, modelo):
    sube = muestra(cliente, cab_editor, modelo, limite=10,
                   orden="fecha_emision", descendente=False)
    baja = muestra(cliente, cab_editor, modelo, limite=10,
                   orden="fecha_emision", descendente=True)
    assert sube.status_code == baja.status_code == 200
    primeras = [f["fecha_emision"] for f in sube.json()["filas"]]
    ultimas = [f["fecha_emision"] for f in baja.json()["filas"]]
    assert primeras == sorted(primeras)
    assert ultimas == sorted(ultimas, reverse=True)
    # Las ultimas son POSTERIORES a las primeras: es la pregunta que no se podia
    # contestar, «ensename los datos mas recientes».
    assert ultimas[0] > primeras[0]


def test_la_muestra_no_filtra_por_columnas_de_otra_tabla(cliente, cab_editor, modelo):
    """
    Una puerta que no se abre: el campo tiene que ser de la entidad que se mira y
    estar visible. Si no, un filtro seria una forma de escribir SQL contra otra
    tabla desde una casilla.
    """
    r = muestra(cliente, cab_editor, modelo, limite=10, filtros=[
        {"campo": "cat_sucursal.sucursal_nombre", "op": "=", "valor": "x"}])
    assert r.status_code == 422, r.text
    assert "cat_sucursal.sucursal_nombre" in r.text


def test_la_muestra_no_ordena_por_una_columna_invisible(cliente, cab_editor, modelo):
    r = muestra(cliente, cab_editor, modelo, entidad="cat_sucursal", limite=10,
                orden="nombre_conexion")
    assert r.status_code == 422, r.text
    assert "nombre_conexion" in r.text


# ------------------------------------------------------ el comodin del LIKE ---

def test_un_por_ciento_en_el_valor_es_un_por_ciento(cliente, cab_editor, modelo):
    """
    `ILIKE` con `ESCAPE`: buscando `Nor\\%te` se busca ese texto y no «Nor
    cualquier cosa te». Sin el escape, DuckDB no casa `\\%` con nada —comprobado— y
    el filtro devolveria cero filas sin decir por que.
    """
    r = consultar(cliente, cab_editor, modelo, dimensiones=[SUC], filtros=[
        {"campo": SUC, "op": "ILIKE", "valor": "%o%"}])
    assert r.status_code == 200, r.text
    con_o = r.json()["filas"]
    assert con_o, "ninguna sucursal con una «o»: el juego de datos no sirve"

    r2 = consultar(cliente, cab_editor, modelo, dimensiones=[SUC], filtros=[
        {"campo": SUC, "op": "ILIKE", "valor": "%\\%%"}])
    assert r2.status_code == 200, r2.text
    assert r2.json()["filas"] == [], "un «%» escapado busca un «%» literal"
