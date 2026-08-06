"""
Fase 4 — dashboards.

Lo que se protege: que un tablero publicado no cambie de cifra por su cuenta, que
un lector no vea borradores, y que un filtro del tablero se aplique de verdad.
"""

import pytest



@pytest.fixture
def modelo_dash(cliente, cab_admin, yaml_modelo):
    """
    Un modelo propio de estas pruebas. Se reutiliza si ya existe: la base de
    metadatos vive toda la corrida, y crear el mismo modelo dos veces da 409.
    """
    existentes = cliente.get("/api/modelos", headers=cab_admin).json()
    for m in existentes:
        if m["nombre"] == "dash_modelo":
            return m["id"]
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": "dash_modelo", "yaml": yaml_modelo})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _tablero_minimo(modelo_id: int, **extra) -> dict:
    return {
        "nombre": "Comercial",
        "modelo_id": modelo_id,
        "definicion": {
            "widgets": [
                {"id": "w1", "tipo": "kpi", "titulo": "Venta total",
                 "posicion": {"x": 0, "y": 0, "ancho": 3, "alto": 4},
                 "metricas": ["monto_venta"]},
                {"id": "w2", "tipo": "barras", "titulo": "Venta por sucursal",
                 "posicion": {"x": 3, "y": 0, "ancho": 9, "alto": 8},
                 "dimensiones": ["cat_sucursal.sucursal_nombre"],
                 "metricas": ["monto_venta"]},
            ],
            "selecciones": {},
        },
        **extra,
    }


@pytest.fixture
def tablero(cliente, cab_admin, modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_tablero_minimo(modelo_dash))
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Anclaje a una version
# --------------------------------------------------------------------------- #

def test_se_ancla_a_la_version_vigente_al_crearlo(tablero):
    # Sin numeros fijos: otras pruebas de este archivo agregan versiones, y el
    # orden de ejecucion no deberia decidir si esta pasa.
    assert tablero["version_modelo"] == tablero["version_vigente_del_modelo"]


def test_una_version_nueva_del_modelo_no_mueve_el_tablero(cliente, cab_admin,
                                                          modelo_dash, tablero,
                                                          yaml_modelo):
    """
    Lo esencial: si alguien cambia el modelo, lo publicado sigue diciendo lo que
    decia. Sin esto, una cifra certificada puede cambiar sola de un dia para otro.
    """
    anclado = tablero["version_modelo"]
    r = cliente.post(f"/api/modelos/{modelo_dash}/versiones", headers=cab_admin,
                     json={"yaml": yaml_modelo, "notas": "sin cambios reales"})
    assert r.status_code == 201
    nueva = r.json()["version"]

    d = cliente.get(f"/api/dashboards/{tablero['id']}", headers=cab_admin).json()
    assert d["version_modelo"] == anclado, "el tablero se movio solo"
    assert d["version_vigente_del_modelo"] == nueva, "deberia avisar de que hay una nueva"


def test_mover_de_version_es_explicito(cliente, cab_admin, modelo_dash, tablero,
                                       yaml_modelo):
    nueva = cliente.post(f"/api/modelos/{modelo_dash}/versiones", headers=cab_admin,
                         json={"yaml": yaml_modelo}).json()["version"]
    r = cliente.post(f"/api/dashboards/{tablero['id']}/mover-a-version"
                     f"?version={nueva}", headers=cab_admin)
    assert r.status_code == 200, r.text
    assert r.json()["version_modelo"] == nueva


def test_el_widget_consulta_la_version_del_tablero(cliente, cab_admin, modelo_dash,
                                                   tablero):
    """
    El anclaje solo sirve si las consultas lo respetan. Sin el parametro de
    version, el tablero diria 'version 1' y preguntaria por la vigente.
    """
    r = cliente.post(
        f"/api/modelos/{modelo_dash}/consultar?version={tablero['version_modelo']}",
        headers=cab_admin,
        json={"dimensiones": ["cat_sucursal.sucursal_nombre"],
              "metricas": ["monto_venta"], "limite": 10})
    assert r.status_code == 200, r.text
    assert len(r.json()["filas"]) == 10


def test_version_inexistente_da_404(cliente, cab_admin, modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_tablero_minimo(modelo_dash, version=99))
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Validacion de widgets
# --------------------------------------------------------------------------- #

def test_un_grafico_sin_metrica_se_rechaza(cliente, cab_admin, modelo_dash):
    cuerpo = _tablero_minimo(modelo_dash)
    cuerpo["nombre"] = "malo"
    cuerpo["definicion"]["widgets"][1]["metricas"] = []
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422
    assert "metrica" in " ".join(r.json()["detail"]["errores"])


def test_un_grafico_sin_dimension_se_rechaza(cliente, cab_admin, modelo_dash):
    cuerpo = _tablero_minimo(modelo_dash)
    cuerpo["nombre"] = "malo2"
    cuerpo["definicion"]["widgets"][1]["dimensiones"] = []
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422
    assert "dimension" in " ".join(r.json()["detail"]["errores"])


def test_un_filtro_debe_apuntar_a_un_solo_campo(cliente, cab_admin, modelo_dash):
    cuerpo = _tablero_minimo(modelo_dash)
    cuerpo["nombre"] = "malo3"
    cuerpo["definicion"]["widgets"].append({
        "id": "f1", "tipo": "filtro", "posicion": {"x": 0, "y": 8, "ancho": 3, "alto": 6},
        "dimensiones": ["cat_marca.marca_nombre", "cat_region.region_nombre"]})
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422


def test_ids_de_widget_repetidos_se_rechazan(cliente, cab_admin, modelo_dash):
    cuerpo = _tablero_minimo(modelo_dash)
    cuerpo["nombre"] = "malo4"
    cuerpo["definicion"]["widgets"][1]["id"] = "w1"
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422
    assert "repetidos" in " ".join(r.json()["detail"]["errores"])


def test_las_opciones_propias_del_widget_se_conservan(cliente, cab_admin, tablero):
    """
    Cada tipo de widget tiene opciones suyas (colores, formato, orden). El backend
    no las conoce y no debe borrarlas.
    """
    d = cliente.get(f"/api/dashboards/{tablero['id']}", headers=cab_admin).json()
    d["definicion"]["widgets"][0]["formato"] = "moneda"
    d["definicion"]["widgets"][0]["comparar_con"] = "objetivo_unidades"
    r = cliente.put(f"/api/dashboards/{tablero['id']}", headers=cab_admin,
                    json={"definicion": d["definicion"]})
    assert r.status_code == 200, r.text
    w = r.json()["definicion"]["widgets"][0]
    assert w["formato"] == "moneda"
    assert w["comparar_con"] == "objetivo_unidades"


# --------------------------------------------------------------------------- #
# Publicacion y certificacion
# --------------------------------------------------------------------------- #

def test_un_lector_no_ve_borradores(cliente, cab_lector, cab_admin, tablero):
    assert tablero["publicado"] is False
    lista = cliente.get("/api/dashboards", headers=cab_lector).json()
    assert all(d["id"] != tablero["id"] for d in lista)
    assert cliente.get(f"/api/dashboards/{tablero['id']}",
                       headers=cab_lector).status_code == 404

    cliente.post(f"/api/dashboards/{tablero['id']}/publicar", headers=cab_admin)
    assert cliente.get(f"/api/dashboards/{tablero['id']}",
                       headers=cab_lector).status_code == 200


def test_no_se_certifica_lo_que_no_esta_publicado(cliente, cab_admin, tablero):
    r = cliente.post(f"/api/dashboards/{tablero['id']}/certificar", headers=cab_admin)
    assert r.status_code == 400


def test_editar_quita_la_certificacion(cliente, cab_admin, tablero):
    """
    Certificar dice "esto se reviso". Si se edita, lo que se reviso ya no es esto.
    """
    cliente.post(f"/api/dashboards/{tablero['id']}/publicar", headers=cab_admin)
    r = cliente.post(f"/api/dashboards/{tablero['id']}/certificar", headers=cab_admin)
    assert r.json()["certificado"] is True

    d = cliente.get(f"/api/dashboards/{tablero['id']}", headers=cab_admin).json()
    d["definicion"]["widgets"][0]["titulo"] = "Otro titulo"
    r = cliente.put(f"/api/dashboards/{tablero['id']}", headers=cab_admin,
                    json={"definicion": d["definicion"]})
    assert r.json()["certificado"] is False


def test_mover_de_version_quita_la_certificacion(cliente, cab_admin, modelo_dash,
                                                 tablero, yaml_modelo):
    cliente.post(f"/api/dashboards/{tablero['id']}/publicar", headers=cab_admin)
    cliente.post(f"/api/dashboards/{tablero['id']}/certificar", headers=cab_admin)
    nueva = cliente.post(f"/api/modelos/{modelo_dash}/versiones", headers=cab_admin,
                         json={"yaml": yaml_modelo}).json()["version"]
    r = cliente.post(f"/api/dashboards/{tablero['id']}/mover-a-version"
                     f"?version={nueva}", headers=cab_admin)
    assert r.json()["certificado"] is False


def test_un_editor_no_puede_certificar(cliente, cab_editor, cab_admin, tablero):
    cliente.post(f"/api/dashboards/{tablero['id']}/publicar", headers=cab_admin)
    r = cliente.post(f"/api/dashboards/{tablero['id']}/certificar", headers=cab_editor)
    assert r.status_code == 403


def test_un_lector_no_puede_editar(cliente, cab_lector, tablero):
    r = cliente.put(f"/api/dashboards/{tablero['id']}", headers=cab_lector,
                    json={"nombre": "mio"})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Estados asociativos — lo que hace que el tablero se sienta como Qlik
# --------------------------------------------------------------------------- #

def test_los_cuatro_estados_asociativos(cliente, cab_admin, modelo_dash):
    """
    Al elegir una marca, las sucursales se reparten en posibles y excluidas; las
    otras marcas quedan 'alternativas', no 'excluidas'. Esa distincion es lo que
    separa una imitacion de un motor asociativo de verdad.
    """
    seleccion = {"cat_marca.marca_nombre": ["Dalia"]}

    r = cliente.post(f"/api/modelos/{modelo_dash}/asociativo", headers=cab_admin,
                     json={"entidad": "cat_sucursal", "campo": "sucursal_nombre",
                           "selecciones": seleccion})
    assert r.status_code == 200, r.text
    suc = r.json()
    assert suc["posible"], "alguna sucursal deberia quedar posible"
    assert suc["excluido"], "alguna sucursal deberia quedar excluida"
    assert suc["seleccionado"] == []

    r = cliente.post(f"/api/modelos/{modelo_dash}/asociativo", headers=cab_admin,
                     json={"entidad": "cat_marca", "campo": "marca_nombre",
                           "selecciones": seleccion})
    marca = r.json()
    assert marca["seleccionado"] == ["Dalia"]
    # Las demas marcas son ALTERNATIVAS: se podrian elegir. No excluidas.
    assert marca["alternativo"], "las otras marcas deberian ser alternativas"
    assert marca["excluido"] == []


def test_los_estados_respetan_la_version_del_tablero(cliente, cab_admin, modelo_dash,
                                                     tablero):
    r = cliente.post(
        f"/api/modelos/{modelo_dash}/asociativo?version={tablero['version_modelo']}",
        headers=cab_admin,
        json={"entidad": "cat_marca", "campo": "marca_nombre", "selecciones": {}})
    assert r.status_code == 200, r.text
    assert r.json()["posible"]


def test_la_seguridad_por_fila_tambien_aplica_a_los_estados(cliente, cab_lector,
                                                            modelo_dash):
    """
    Si un usuario no puede ver una sucursal, esa sucursal no debe aparecer ni como
    'excluida' en un panel de filtros: su existencia misma es informacion.
    """
    r = cliente.post(f"/api/modelos/{modelo_dash}/asociativo", headers=cab_lector,
                     json={"entidad": "cat_sucursal", "campo": "sucursal_nombre",
                           "selecciones": {}})
    assert r.status_code == 200, r.text
    todos = sum(len(v) for v in r.json().values())
    assert todos == 1, f"el lector regional solo deberia ver 1 sucursal, vio {todos}"


# --------------------------------------------------------------------------- #
# Borrado
# --------------------------------------------------------------------------- #

def test_borrar_un_tablero(cliente, cab_admin, tablero):
    assert cliente.delete(f"/api/dashboards/{tablero['id']}",
                          headers=cab_admin).status_code == 204
    assert cliente.get(f"/api/dashboards/{tablero['id']}",
                       headers=cab_admin).status_code == 404


def test_el_borrado_queda_en_auditoria(cliente, cab_admin, tablero):
    from sqlalchemy import select

    from app.db import CrearSesion
    from app.modelos_db import Auditoria

    cliente.delete(f"/api/dashboards/{tablero['id']}", headers=cab_admin)
    with CrearSesion() as s:
        acciones = set(s.scalars(select(Auditoria.accion)))
    assert {"dashboard_creado", "dashboard_borrado"} <= acciones




def test_las_claves_propias_del_tablero_se_conservan(cliente, cab_admin, tablero):
    """
    El tablero guarda cosas que el backend no interpreta, como el camino elegido
    para una ambiguedad de rutas. Si se borraran al guardar, la cifra volveria a
    ser irreproducible cada vez que alguien abre el tablero.
    """
    d = cliente.get(f"/api/dashboards/{tablero['id']}", headers=cab_admin).json()
    definicion = {
        **d["definicion"],
        "rutas_elegidas": {
            "fact_venta->cat_marca": "fact_venta → cat_sucursal → cat_marca"},
    }
    r = cliente.put(f"/api/dashboards/{tablero['id']}", headers=cab_admin,
                    json={"definicion": definicion})
    assert r.status_code == 200, r.text
    assert r.json()["definicion"]["rutas_elegidas"] == {
        "fact_venta->cat_marca": "fact_venta → cat_sucursal → cat_marca"}


def test_el_camino_elegido_hace_que_el_filtro_ambiguo_funcione(cliente, cab_admin,
                                                               modelo_dash):
    """
    Filtrar por marca desde fact_venta es ambiguo (la marca de la agencia o la del
    vehiculo). Sin elegir camino tiene que fallar; eligiendolo, tiene que dar un
    numero menor que el total.
    """
    base = {"dimensiones": [], "metricas": ["monto_venta"],
            "filtros": [{"campo": "cat_marca.marca_nombre", "op": "IN",
                         "valor": ["Dalia"]}]}

    sin = cliente.post(f"/api/modelos/{modelo_dash}/consultar", headers=cab_admin,
                       json=base)
    assert sin.status_code == 422, "sin elegir camino no puede devolver un numero"
    assert len(sin.json()["detail"]["rutas"]) == 2, "debe decir cuales son"

    con = cliente.post(f"/api/modelos/{modelo_dash}/consultar", headers=cab_admin,
                       json={**base, "rutas_elegidas": {
                           "fact_venta->cat_marca":
                               "fact_venta → cat_sucursal → cat_marca"}})
    assert con.status_code == 200, con.text
    kia = con.json()["filas"][0]["monto_venta"]

    total = cliente.post(f"/api/modelos/{modelo_dash}/consultar", headers=cab_admin,
                         json={"dimensiones": [], "metricas": ["monto_venta"]})
    assert 0 < kia < total.json()["filas"][0]["monto_venta"]
