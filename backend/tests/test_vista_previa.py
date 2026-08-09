"""
Ver el resultado antes de publicar.

El ciclo de escribir un modelo termina en un numero, no en un YAML validado. Lo
que se prueba aqui es que ese numero se puede ver **sobre lo que se tiene en
pantalla**: metricas escritas hace un minuto, sin guardar y sin publicar. Si para
mirar el resultado hubiera que publicar, publicar dejaria de significar «esto ya
esta bien» para significar «a ver que sale».
"""

import itertools
from pathlib import Path

import pytest

from app.politicas import PredicadoAplicado
from semantic.engine import Compilador
from semantic.engine import Modelo as ModeloSemantico

_contador = itertools.count(1)

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def modelo_id(cliente, cab_admin, yaml_modelo):
    """Un modelo propio y desechable, para no versionar el de demostracion."""
    nombre = f"vista_previa_pruebas_{next(_contador)}"
    r = cliente.post("/api/modelos", headers=cab_admin,
                     json={"nombre": nombre, "yaml": yaml_modelo})
    assert r.status_code == 201, r.text
    identificador = r.json()["id"]
    yield identificador
    cliente.delete(f"/api/modelos/{identificador}", headers=cab_admin)


@pytest.fixture
def definicion(cliente, cab_admin, modelo_id):
    return cliente.get(f"/api/modelos/{modelo_id}/definicion",
                       headers=cab_admin).json()["definicion"]


def con_metrica(definicion, nombre, expresion, entidad="fact_venta"):
    otras = [m for m in definicion.get("metricas", []) if m["nombre"] != nombre]
    return {**definicion, "metricas": [
        *otras,
        {"nombre": nombre, "etiqueta": nombre, "entidad": entidad,
         "expresion": expresion, "formato": "numero"},
    ]}


# --------------------------------------------------------------------------- #
# Vista previa
# --------------------------------------------------------------------------- #

def test_una_metrica_que_no_esta_guardada_ya_da_su_numero(
        cliente, cab_editor, modelo_id, definicion):
    """El caso entero: se escribe, y se ve, sin haber guardado nada."""
    d = con_metrica(definicion, "recien_escrita", "SUMA(monto_base)")
    r = cliente.post(f"/api/modelos/{modelo_id}/vista-previa", headers=cab_editor,
                     json={"definicion": d, "metricas": ["recien_escrita"]})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["columnas"] == ["recien_escrita"]
    assert len(cuerpo["filas"]) == 1
    assert cuerpo["filas"][0]["recien_escrita"] > 0
    assert "SUM" in cuerpo["sql"]


def test_la_vista_previa_no_publica_nada(cliente, cab_editor, cab_admin,
                                         modelo_id, definicion):
    antes = next(m for m in cliente.get("/api/modelos", headers=cab_admin).json()
                 if m["id"] == modelo_id)["version_actual"]
    cliente.post(f"/api/modelos/{modelo_id}/vista-previa", headers=cab_editor,
                 json={"definicion": con_metrica(definicion, "x", "CONTAR()"),
                       "metricas": ["x"]})
    despues = next(m for m in cliente.get("/api/modelos", headers=cab_admin).json()
                   if m["id"] == modelo_id)["version_actual"]
    assert despues == antes


def test_desglosada_por_una_dimension(cliente, cab_editor, modelo_id, definicion):
    d = con_metrica(definicion, "venta", "SUMA(monto_base)")
    r = cliente.post(f"/api/modelos/{modelo_id}/vista-previa", headers=cab_editor,
                     json={"definicion": d, "metricas": ["venta"],
                           "dimensiones": ["cat_sucursal.sucursal_nombre"],
                           "limite": 5})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["columnas"] == ["cat_sucursal.sucursal_nombre", "venta"]
    assert 1 <= len(cuerpo["filas"]) <= 5


def test_varias_metricas_de_golpe(cliente, cab_editor, modelo_id, definicion):
    """Lo que distingue esto de `probar-metrica`: el modelo entero funcionando."""
    d = con_metrica(definicion, "venta", "SUMA(monto_base)")
    d = con_metrica(d, "costo", "SUMA(monto_costo)")
    d = con_metrica(d, "margen", "DIVIDIR([venta] - [costo], [venta])")
    r = cliente.post(f"/api/modelos/{modelo_id}/vista-previa", headers=cab_editor,
                     json={"definicion": d,
                           "metricas": ["venta", "costo", "margen"]})
    assert r.status_code == 200, r.text
    fila = r.json()["filas"][0]
    assert fila["margen"] == pytest.approx(
        (fila["venta"] - fila["costo"]) / fila["venta"])


def test_sin_definicion_se_usa_el_borrador_guardado(cliente, cab_editor,
                                                    modelo_id, definicion):
    d = con_metrica(definicion, "solo_en_borrador", "CONTAR()")
    assert cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                       json={"definicion": d}).status_code == 200
    r = cliente.post(f"/api/modelos/{modelo_id}/vista-previa", headers=cab_editor,
                     json={"metricas": ["solo_en_borrador"]})
    assert r.status_code == 200, r.text
    assert r.json()["filas"][0]["solo_en_borrador"] > 0


def test_una_formula_rota_se_explica_y_no_revienta(cliente, cab_editor,
                                                   modelo_id, definicion):
    d = con_metrica(definicion, "rota", "SUMA(columna_que_no_existe)")
    r = cliente.post(f"/api/modelos/{modelo_id}/vista-previa", headers=cab_editor,
                     json={"definicion": d, "metricas": ["rota"]})
    assert r.status_code == 422
    assert "columna_que_no_existe" in r.text


def test_sin_metricas_dice_que_para_eso_esta_la_muestra(cliente, cab_editor,
                                                        modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/vista-previa", headers=cab_editor,
                     json={"dimensiones": ["cat_sucursal.sucursal_nombre"]})
    assert r.status_code == 422
    assert "muestra" in r.text


def test_el_lector_no_puede_ejecutar_el_modelo_sin_publicar(cliente, cab_lector,
                                                            modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/vista-previa", headers=cab_lector,
                     json={"metricas": ["monto_venta"]})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Muestra de filas
# --------------------------------------------------------------------------- #

def test_la_muestra_devuelve_filas_crudas(cliente, cab_editor, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/muestra", headers=cab_editor,
                     json={"entidad": "fact_venta", "limite": 7})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert len(cuerpo["filas"]) == 7
    # Sin agregar: las columnas son las del modelo, tal cual.
    assert "monto_base" in cuerpo["columnas"]
    assert "venta_id" in cuerpo["columnas"]
    assert "GROUP BY" not in cuerpo["sql"]


def test_la_muestra_avisa_de_las_columnas_personales(cliente, cab_editor,
                                                     modelo_id):
    """Enseñar el dato es correcto aqui; enseñarlo sin decir lo que es, no."""
    r = cliente.post(f"/api/modelos/{modelo_id}/muestra", headers=cab_editor,
                     json={"entidad": "dim_cliente", "limite": 3})
    assert r.status_code == 200, r.text
    assert r.json()["pii"] == ["cliente_nombre"]


def test_la_muestra_ve_una_entidad_que_solo_esta_en_pantalla(
        cliente, cab_editor, modelo_id, definicion):
    """
    Se le cambia el nombre a una entidad sin guardar y la muestra la encuentra:
    es la prueba de que lee la definicion que manda el navegador y no la vigente.
    """
    d = {**definicion, "entidades": [
        {**e, "nombre": "recien_renombrada"} if e["nombre"] == "cat_marca" else e
        for e in definicion["entidades"]
    ], "relaciones": [
        {**r,
         "desde": ["recien_renombrada" if r["desde"][0] == "cat_marca"
                   else r["desde"][0], r["desde"][1]],
         "hasta": ["recien_renombrada" if r["hasta"][0] == "cat_marca"
                   else r["hasta"][0], r["hasta"][1]]}
        for r in definicion.get("relaciones", [])
    ]}
    r = cliente.post(f"/api/modelos/{modelo_id}/muestra", headers=cab_editor,
                     json={"definicion": d, "entidad": "recien_renombrada",
                           "limite": 3})
    assert r.status_code == 200, r.text
    assert len(r.json()["filas"]) > 0


def test_la_muestra_de_una_entidad_inexistente_es_404(cliente, cab_editor,
                                                      modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/muestra", headers=cab_editor,
                     json={"entidad": "no_existe"})
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Seguridad por fila en la muestra
# --------------------------------------------------------------------------- #
#
# Se compila el SQL directamente en vez de pedirlo por HTTP porque el modelo de
# demostracion solo protege al rol lector, y la muestra es de editor para
# arriba: por la ruta no hay forma de que un predicado llegue nunca. Y esto es
# justo lo que no puede quedarse sin prueba — una muestra que se saltara las
# politicas seria la puerta trasera para ver lo que tapan.

@pytest.fixture(scope="module")
def modelo_semantico():
    return ModeloSemantico(RAIZ / "demo" / "modelo_demo.yaml")


def test_la_muestra_aplica_el_predicado_de_su_propia_entidad(modelo_semantico):
    pred = PredicadoAplicado(entidad="cat_sucursal", sql="region_id = ?",
                             parametros=[3], politica="rls_por_region")
    c = Compilador(modelo_semantico).compilar_muestra("cat_sucursal", 10, [pred])
    assert "WHERE" in c.sql
    assert '"region_id" = ?' in c.sql
    assert c.parametros == [3]


def test_la_muestra_une_para_aplicar_un_predicado_de_otra_entidad(modelo_semantico):
    """
    Se pide una muestra de ventas y quien mira solo puede ver una region. La
    region no esta en fact_venta: esta en cat_sucursal. Si el predicado se
    ignorara por no ser de la entidad pedida, la muestra enseñaria ventas de
    sucursales que esa persona no puede ver.
    """
    pred = PredicadoAplicado(entidad="cat_sucursal", sql="region_id = ?",
                             parametros=[3], politica="rls_por_region")
    c = Compilador(modelo_semantico).compilar_muestra("fact_venta", 10, [pred])
    assert "JOIN" in c.sql
    assert '"region_id" = ?' in c.sql
    # DISTINCT porque ese JOIN puede repetir filas de la tabla que se muestra.
    assert c.sql.startswith("SELECT DISTINCT")


def test_sin_politicas_la_muestra_no_une_nada(modelo_semantico):
    c = Compilador(modelo_semantico).compilar_muestra("fact_venta", 10, [])
    assert "JOIN" not in c.sql
    assert "DISTINCT" not in c.sql
    assert c.parametros == []


def test_el_lector_no_ve_filas_crudas(cliente, cab_lector, modelo_id):
    """
    La muestra salta el modelo y lee la tabla. Que sea de editor para arriba no
    es burocracia: es el unico sitio de la aplicacion donde se ven filas sin
    pasar por una metrica.
    """
    r = cliente.post(f"/api/modelos/{modelo_id}/muestra", headers=cab_lector,
                     json={"entidad": "fact_venta"})
    assert r.status_code == 403
