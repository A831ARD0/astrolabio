"""
Cuando una tabla sale vacia, por que sale vacia.

Vacio se ve igual en pantalla venga de donde venga, y viene de sitios que se
arreglan en sitios distintos:

  1. la tabla no se ha cargado,
  2. la union no encuentra pareja —un codigo que en un lado es texto con ceros
     delante y en el otro un entero—,
  3. una politica de seguridad tapa todo,
  4. los filtros no dejan nada.

«Sin datos para la seleccion actual» a secas manda a buscar a ciegas por los cuatro.
Estas pruebas fijan que la respuesta diga cual de los cuatro es.
"""

import itertools
from pathlib import Path

import duckdb
import pytest

import app.analitico as analitico
from app.politicas import ContextoUsuario
from semantic.engine import Consulta, Modelo

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)

SUC = "cat_sucursal.sucursal_nombre"


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"vacio_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def definicion(cliente, cab, modelo_id: int) -> dict:
    return cliente.get(f"/api/modelos/{modelo_id}/definicion",
                       headers=cab).json()["definicion"]


def guardar(cliente, cab, modelo_id: int, d: dict):
    return cliente.put(f"/api/modelos/{modelo_id}/definicion", headers=cab,
                       json={"definicion": d})


def consultar(cliente, cab, modelo_id: int, metricas, dimensiones, filtros=None):
    return cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab,
                        json={"dimensiones": dimensiones, "metricas": metricas,
                              "filtros": filtros or []})


def test_con_filas_no_se_explica_nada(cliente, cab_editor, modelo):
    """Lo primero: esto no aparece cuando hay datos, ni cuesta las tres consultas."""
    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC])
    assert r.status_code == 200, r.text
    assert r.json()["filas"]
    assert r.json()["vacio_porque"] is None


def test_los_filtros_que_no_dejan_nada_lo_dicen(cliente, cab_editor, modelo):
    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC],
                  filtros=[{"campo": SUC, "op": "=", "valor": "no existe"}])
    assert r.status_code == 200, r.text
    assert r.json()["filas"] == []
    assert "filtros" in r.json()["vacio_porque"]


def test_una_politica_que_tapa_todo_lo_dice(cliente, cab_lector, cab_admin, modelo):
    """
    Un lector al que la politica no le deja ver ninguna sucursal. Sin decirlo, el
    tablero parece roto y lo que esta es cerrado — y son dos conversaciones muy
    distintas con quien lo reporta.
    """
    d = definicion(cliente, cab_admin, modelo)
    d["politicas"].append({"nombre": "ninguna_sucursal", "entidad": "cat_sucursal",
                           "predicado": "sucursal_nombre = 'no existe'",
                           "aplica_a_roles": ["lector"]})
    assert guardar(cliente, cab_admin, modelo, d).status_code == 201

    r = consultar(cliente, cab_lector, modelo, ["unidades_vendidas"], [SUC])
    assert r.status_code == 200, r.text
    assert r.json()["filas"] == []
    assert "politicas" in r.json()["vacio_porque"]


# --------------------------------------------------------------------------- #
# Las dos causas que estan en los datos, contra una base hecha a mano: en la de
# demostracion no hay ninguna tabla vacia ni dos columnas que no casen.
# --------------------------------------------------------------------------- #

MINIMO = """
modelo: minimo
version: 1
entidades:
  - nombre: sucursales
    tipo: dimension
    origen: {tabla: sucursales}
    clave_primaria: sucursal_id
    campos:
      - {nombre: sucursal_id, tipo: entero, rol: clave}
      - {nombre: nombre, tipo: texto, rol: dimension}
  - nombre: ventas
    tipo: hecho
    origen: {tabla: ventas}
    campos:
      - {nombre: sucursal_id, tipo: entero, rol: clave_externa}
      - {nombre: unidades, tipo: entero, rol: medida_base}
relaciones:
  - desde: [ventas, sucursal_id]
    hasta: [sucursales, sucursal_id]
    cardinalidad: muchos_a_uno
metricas:
  - nombre: unidades
    etiqueta: Unidades
    entidad: ventas
    expresion: SUM(unidades)
    formato: entero
"""

ADMIN = ContextoUsuario(usuario_id=1, email="a@b.c", rol="administrador")


def base(monkeypatch, filas_ventas: list[tuple[int, int]]):
    con = duckdb.connect()
    con.execute("CREATE TABLE sucursales(sucursal_id INTEGER, nombre VARCHAR)")
    con.execute("INSERT INTO sucursales VALUES (1, 'Norte'), (2, 'Sur')")
    con.execute("CREATE TABLE ventas(sucursal_id INTEGER, unidades INTEGER)")
    for f in filas_ventas:
        con.execute("INSERT INTO ventas VALUES (?, ?)", list(f))
    monkeypatch.setattr(analitico, "conexion", lambda: con)
    return con


def preguntar(tmp_path) -> tuple[Modelo, Consulta]:
    ruta = tmp_path / "minimo.yaml"
    ruta.write_text(MINIMO, encoding="utf-8")
    return Modelo(ruta), Consulta(dimensiones=["sucursales.nombre"],
                                  metricas=["unidades"])


def test_una_tabla_sin_cargar_lo_dice(monkeypatch, tmp_path):
    """
    El caso del primer dia: el modelo esta dibujado y la carga todavia no ha
    corrido. Sin decirlo se revisa el modelo, que es el sitio equivocado.
    """
    base(monkeypatch, [])
    m, c = preguntar(tmp_path)
    res = analitico.ejecutar_consulta(m, c, ADMIN)
    assert res.filas == []
    assert res.vacio_porque is not None
    assert "ventas" in res.vacio_porque and "vacia" in res.vacio_porque


def test_una_union_que_no_casa_lo_dice_y_dice_por_donde(monkeypatch, tmp_path):
    """
    Las dos tablas tienen filas y ninguna encuentra a la otra. Es el mas caro de los
    cuatro, porque no se parece a un error: se parece a «no hubo ventas».

    Y tiene que decir POR DONDE se une, que es el dato con el que se revisa: sin eso
    hay que ir al lienzo a buscar cual de las uniones es la que no casa.
    """
    base(monkeypatch, [(99, 3), (98, 5)])          # ninguna sucursal 98 ni 99
    m, c = preguntar(tmp_path)
    res = analitico.ejecutar_consulta(m, c, ADMIN)
    assert res.filas == []
    assert "no encuentra pareja" in res.vacio_porque
    assert "ventas.sucursal_id → sucursales.sucursal_id" in res.vacio_porque


def test_con_filas_de_verdad_no_se_explica_nada(monkeypatch, tmp_path):
    """La misma base, con una fila que si casa: no hay nada que explicar."""
    base(monkeypatch, [(1, 7)])
    m, c = preguntar(tmp_path)
    res = analitico.ejecutar_consulta(m, c, ADMIN)
    assert [f["unidades"] for f in res.filas] == [7]
    assert res.vacio_porque is None
