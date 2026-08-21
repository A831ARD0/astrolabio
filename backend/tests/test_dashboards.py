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


def test_un_filtro_necesita_al_menos_un_campo(cliente, cab_admin, modelo_dash):
    cuerpo = _tablero_minimo(modelo_dash)
    cuerpo["nombre"] = "malo3"
    cuerpo["definicion"]["widgets"].append({
        "id": "f1", "tipo": "filtro", "posicion": {"x": 0, "y": 8, "ancho": 3, "alto": 6},
        "dimensiones": []})
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422


def test_un_filtro_puede_llevar_varios_campos(cliente, cab_admin, modelo_dash):
    """
    Un panel de filtros lleva los campos que quepan y se colapsan en una barra de
    desplegables — Año, Mes, Sucursal en fila, como en Qlik. La regla de "exactamente
    un campo" era de antes de que el panel supiera dibujar varios, y hacia imposible
    guardar justo la barra de filtros que la pantalla ya sabe armar.
    """
    cuerpo = _tablero_minimo(modelo_dash)
    cuerpo["nombre"] = "barra_de_filtros"
    cuerpo["definicion"]["widgets"].append({
        "id": "f1", "tipo": "filtro",
        "posicion": {"x": 0, "y": 8, "ancho": 12, "alto": 3},
        "dimensiones": ["cat_marca.marca_nombre", "cat_sucursal.sucursal_nombre",
                        "dim_calendario.anio", "dim_calendario.mes"]})
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 201, r.text
    guardado = next(w for w in r.json()["definicion"]["widgets"] if w["id"] == "f1")
    assert len(guardado["dimensiones"]) == 4
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


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
    de_una_marca = con.json()["filas"][0]["monto_venta"]

    total = cliente.post(f"/api/modelos/{modelo_dash}/consultar", headers=cab_admin,
                         json={"dimensiones": [], "metricas": ["monto_venta"]})
    assert 0 < de_una_marca < total.json()["filas"][0]["monto_venta"]


# --------------------------------------------------------------------------- #
# Hojas: un tablero es un libro
# --------------------------------------------------------------------------- #

def _con_hojas(modelo_id: int) -> dict:
    """Dos hojas y un widget en cada una."""
    cuerpo = _tablero_minimo(modelo_id)
    cuerpo["nombre"] = "Libro"
    cuerpo["definicion"]["hojas"] = [
        {"id": "h1", "nombre": "Ventas"},
        {"id": "h2", "nombre": "Inventario",
         "lienzo": {"modo": "libre", "columnas": 24, "filas": 40}},
    ]
    cuerpo["definicion"]["widgets"][0]["hoja"] = "h1"
    cuerpo["definicion"]["widgets"][1]["hoja"] = "h2"
    return cuerpo


def test_un_tablero_de_antes_de_las_hojas_se_sigue_leyendo(tablero):
    """
    Lo que ya existia no tiene `hojas` ni `hoja`. Tiene que abrirse igual, con
    todos sus widgets en la hoja implicita: si esto falla, cada tablero guardado
    hasta hoy se queda en blanco.
    """
    assert tablero["definicion"]["hojas"] == []
    assert all(w["hoja"] == "" for w in tablero["definicion"]["widgets"])


def test_cada_widget_dice_en_que_hoja_esta(cliente, cab_admin, modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_con_hojas(modelo_dash))
    assert r.status_code == 201, r.text
    d = r.json()["definicion"]
    assert [h["nombre"] for h in d["hojas"]] == ["Ventas", "Inventario"]
    assert {w["id"]: w["hoja"] for w in d["widgets"]} == {"w1": "h1", "w2": "h2"}
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


def test_el_lienzo_de_cada_hoja_se_guarda(cliente, cab_admin, modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_con_hojas(modelo_dash))
    hojas = r.json()["definicion"]["hojas"]
    assert hojas[0]["lienzo"] == {"modo": "pantalla", "columnas": 12, "filas": 12}
    assert hojas[1]["lienzo"]["modo"] == "libre"
    assert hojas[1]["lienzo"]["columnas"] == 24
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


def test_un_widget_en_una_hoja_que_no_existe_se_rechaza(cliente, cab_admin,
                                                        modelo_dash):
    """
    Un widget huerfano no se dibuja en ninguna parte: existe, cuenta, y nadie lo
    ve. Es peor que un error.
    """
    cuerpo = _con_hojas(modelo_dash)
    cuerpo["definicion"]["widgets"][1]["hoja"] = "h9"
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422, r.text
    assert "h9" in r.json()["detail"]["errores"][0]


def test_ids_de_hoja_repetidos_se_rechazan(cliente, cab_admin, modelo_dash):
    cuerpo = _con_hojas(modelo_dash)
    cuerpo["definicion"]["hojas"][1]["id"] = "h1"
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422, r.text
    assert "h1" in r.json()["detail"]["errores"][0]


def test_un_widget_que_no_cabe_en_su_hoja_se_rechaza(cliente, cab_admin,
                                                     modelo_dash):
    """
    La hoja tiene 12 columnas y la caja empieza en la 8 midiendo 9. En la hoja de
    24 la misma caja si cabe: el tope es el de SU hoja, no uno fijo.
    """
    cuerpo = _con_hojas(modelo_dash)
    cuerpo["definicion"]["widgets"][0]["posicion"] = {"x": 8, "y": 0,
                                                      "ancho": 9, "alto": 4}
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422, r.text
    assert "se sale de la hoja" in r.json()["detail"]["errores"][0]

    cuerpo["definicion"]["widgets"][0]["hoja"] = "h2"        # la de 24 columnas
    ok = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert ok.status_code == 201, ok.text
    cliente.delete(f"/api/dashboards/{ok.json()['id']}", headers=cab_admin)


def test_una_hoja_de_24_columnas_acepta_una_caja_ancha(cliente, cab_admin,
                                                       modelo_dash):
    """La rejilla de 12 era un numero fijo en el esquema; ahora es de la hoja."""
    cuerpo = _con_hojas(modelo_dash)
    cuerpo["definicion"]["widgets"][1]["posicion"] = {"x": 0, "y": 0,
                                                      "ancho": 24, "alto": 8}
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 201, r.text
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


def test_una_hoja_no_puede_pedir_mas_columnas_de_las_que_se_leen(cliente,
                                                                 cab_admin,
                                                                 modelo_dash):
    cuerpo = _con_hojas(modelo_dash)
    cuerpo["definicion"]["hojas"][0]["lienzo"] = {"columnas": 60}
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# Tabla dinamica
# --------------------------------------------------------------------------- #

def _pivote(modelo_id: int, **cambios) -> dict:
    cuerpo = _tablero_minimo(modelo_id)
    cuerpo["nombre"] = "matriz"
    w = {"id": "p1", "tipo": "tabla_dinamica", "titulo": "Por modelo y mes",
         "posicion": {"x": 0, "y": 8, "ancho": 12, "alto": 9},
         "dimensiones": ["dim_vehiculo.modelo", "dim_calendario.mes"],
         "metricas": ["unidades_vendidas"],
         "pivote": "dim_calendario.mes"}
    w.update(cambios)
    cuerpo["definicion"]["widgets"].append(w)
    return cuerpo


def test_una_tabla_dinamica_se_guarda_con_su_pivote(cliente, cab_admin, modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin, json=_pivote(modelo_dash))
    assert r.status_code == 201, r.text
    w = next(x for x in r.json()["definicion"]["widgets"] if x["id"] == "p1")
    assert w["pivote"] == "dim_calendario.mes"
    assert w["dimensiones"] == ["dim_vehiculo.modelo", "dim_calendario.mes"]
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


def test_una_tabla_dinamica_con_un_solo_desglose_se_rechaza(cliente, cab_admin,
                                                            modelo_dash):
    """
    Con un desglose no hay nada que cruzar: lo que se queria era una tabla normal, y
    dibujar una matriz de una sola columna solo esconde el malentendido.
    """
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_pivote(modelo_dash,
                                  dimensiones=["dim_calendario.mes"],
                                  pivote="dim_calendario.mes"))
    assert r.status_code == 422, r.text
    assert "dos desgloses" in " ".join(r.json()["detail"]["errores"])


def test_una_tabla_dinamica_sin_metrica_se_rechaza(cliente, cab_admin, modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_pivote(modelo_dash, metricas=[]))
    assert r.status_code == 422, r.text
    assert "al menos una metrica" in " ".join(r.json()["detail"]["errores"])


def test_el_pivote_tiene_que_ser_uno_de_sus_desgloses(cliente, cab_admin,
                                                      modelo_dash):
    """
    Abrir en columnas algo que no se pidio dejaria la matriz con una sola columna
    sin decir por que.
    """
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_pivote(modelo_dash, pivote="cat_marca.marca_nombre"))
    assert r.status_code == 422, r.text
    assert "no es uno de sus desgloses" in " ".join(r.json()["detail"]["errores"])


def test_una_metrica_puede_quedarse_fuera_de_las_columnas(cliente, cab_admin,
                                                          modelo_dash):
    """
    Una cifra que no es del mes —el inventario de hoy— no puede repetirse debajo de
    cada mes: sumar esa fila daria siete veces el inventario. Se guarda cual va
    aparte, y sobrevive el viaje.
    """
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_pivote(modelo_dash,
                                  metricas=["unidades_vendidas", "objetivo_unidades"],
                                  fuera_del_pivote=["objetivo_unidades"]))
    assert r.status_code == 201, r.text
    w = next(x for x in r.json()["definicion"]["widgets"] if x["id"] == "p1")
    assert w["fuera_del_pivote"] == ["objetivo_unidades"]
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


def test_no_se_pueden_dejar_todas_fuera_de_las_columnas(cliente, cab_admin,
                                                        modelo_dash):
    """
    Sin ninguna metrica dentro no hay matriz que abrir. Se dice al guardar: un widget
    que solo sabe explicarse en pantalla se publica y se descubre despues.
    """
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_pivote(modelo_dash,
                                  fuera_del_pivote=["unidades_vendidas"]))
    assert r.status_code == 422, r.text
    assert "no queda ninguna que abrir" in " ".join(r.json()["detail"]["errores"])


def test_dejar_fuera_una_metrica_que_no_es_del_widget_se_rechaza(cliente, cab_admin,
                                                                 modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_pivote(modelo_dash, fuera_del_pivote=["monto_venta"]))
    assert r.status_code == 422, r.text
    assert "que no son metricas suyas" in " ".join(r.json()["detail"]["errores"])


def test_el_widget_puede_decir_por_donde_ordena(cliente, cab_admin, modelo_dash):
    """
    El orden de una lista es presentacion, y se decide en la hoja: cambiarlo no
    deberia costar publicar una version del modelo, que se lo cambia a todos los
    tableros. Se guarda en el widget y sobrevive el viaje.
    """
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_pivote(modelo_dash,
                                  orden_por={"dim_calendario.mes":
                                             "dim_calendario.anio_mes"}))
    assert r.status_code == 201, r.text
    w = next(x for x in r.json()["definicion"]["widgets"] if x["id"] == "p1")
    assert w["orden_por"] == {"dim_calendario.mes": "dim_calendario.anio_mes"}
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


def test_ordenar_un_desglose_que_el_widget_no_tiene_se_rechaza(cliente, cab_admin,
                                                               modelo_dash):
    """
    Suele quedar al quitar el campo y dejar su ajuste detras. No ordena nada, y una
    lista mal ordenada no se distingue de una sin ordenar.
    """
    r = cliente.post("/api/dashboards", headers=cab_admin,
                     json=_pivote(modelo_dash,
                                  orden_por={"cat_marca.marca_nombre":
                                             "cat_marca.marca_id"}))
    assert r.status_code == 422, r.text
    assert "no es uno de sus desgloses" in " ".join(r.json()["detail"]["errores"])


def test_la_tabla_dinamica_consulta_igual_que_las_demas(cliente, cab_admin,
                                                        modelo_dash):
    """
    El cruce se hace en el navegador: el servidor devuelve las filas planas, con las
    dos dimensiones y la metrica. Es lo que hace que una tabla dinamica pase por la
    misma seguridad por fila y el mismo Excel que todo lo demas.
    """
    r = cliente.post(f"/api/modelos/{modelo_dash}/consultar", headers=cab_admin,
                     json={"dimensiones": ["dim_vehiculo.segmento",
                                           "dim_calendario.mes"],
                           "metricas": ["unidades_vendidas"]})
    assert r.status_code == 200, r.text
    cols = r.json()["columnas"]
    assert cols == ["dim_vehiculo.segmento", "dim_calendario.mes",
                    "unidades_vendidas"], cols
    # Una fila por combinacion, no una por mes ni una por segmento.
    filas = r.json()["filas"]
    combos = {(f["dim_vehiculo.segmento"], f["dim_calendario.mes"]) for f in filas}
    assert len(combos) == len(filas), "el motor ya agrupo: no hay combos repetidos"
    assert len({c[1] for c in combos}) > 1, "hace falta mas de un mes para cruzar"


# --------------------------------------------------------------------------- #
# Semaforos
# --------------------------------------------------------------------------- #

def _con_semaforo(modelo_id: int, sem: dict, metricas=None) -> dict:
    cuerpo = _tablero_minimo(modelo_id)
    cuerpo["nombre"] = "semaforos"
    cuerpo["definicion"]["widgets"].append({
        "id": "s1", "tipo": "tabla", "titulo": "Logro",
        "posicion": {"x": 0, "y": 8, "ancho": 12, "alto": 6},
        "dimensiones": ["cat_sucursal.sucursal_nombre"],
        "metricas": metricas if metricas is not None
        else ["unidades_vendidas", "objetivo_unidades"],
        "semaforos": sem})
    return cuerpo


def test_un_semaforo_se_guarda_con_su_direccion(cliente, cab_admin, modelo_dash):
    """
    La direccion es el dato que no se puede adivinar: los dias en inventario suben
    y eso esta mal.
    """
    r = cliente.post("/api/dashboards", headers=cab_admin, json=_con_semaforo(
        modelo_dash,
        {"unidades_vendidas": {"comparar": "metrica",
                               "metrica": "objetivo_unidades",
                               "bueno": "mayor", "mostrar": "ambos"}}))
    assert r.status_code == 201, r.text
    w = next(x for x in r.json()["definicion"]["widgets"] if x["id"] == "s1")
    assert w["semaforos"]["unidades_vendidas"]["bueno"] == "mayor"
    assert w["semaforos"]["unidades_vendidas"]["metrica"] == "objetivo_unidades"
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


def test_un_semaforo_contra_un_objetivo_fijo_se_guarda(cliente, cab_admin,
                                                       modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin, json=_con_semaforo(
        modelo_dash,
        {"unidades_vendidas": {"comparar": "valor", "objetivo": 45,
                               "bueno": "menor", "mostrar": "flecha"}}))
    assert r.status_code == 201, r.text
    w = next(x for x in r.json()["definicion"]["widgets"] if x["id"] == "s1")
    assert w["semaforos"]["unidades_vendidas"]["objetivo"] == 45
    assert w["semaforos"]["unidades_vendidas"]["bueno"] == "menor"
    cliente.delete(f"/api/dashboards/{r.json()['id']}", headers=cab_admin)


def test_un_semaforo_sobre_una_metrica_que_no_esta_se_rechaza(cliente, cab_admin,
                                                              modelo_dash):
    """
    No pintar nada es indistinguible de "va bien", que es el peor fallo posible en
    un semaforo.
    """
    r = cliente.post("/api/dashboards", headers=cab_admin, json=_con_semaforo(
        modelo_dash,
        {"monto_utilidad": {"comparar": "valor", "objetivo": 0,
                            "bueno": "mayor", "mostrar": "ambos"}}))
    assert r.status_code == 422, r.text
    assert "no es una de sus metricas" in " ".join(r.json()["detail"]["errores"])


def test_un_semaforo_que_compara_contra_una_metrica_ausente_se_rechaza(
        cliente, cab_admin, modelo_dash):
    r = cliente.post("/api/dashboards", headers=cab_admin, json=_con_semaforo(
        modelo_dash,
        {"unidades_vendidas": {"comparar": "metrica", "metrica": "monto_venta",
                               "bueno": "mayor", "mostrar": "ambos"}},
        metricas=["unidades_vendidas"]))
    assert r.status_code == 422, r.text
    assert "no es una metrica de este widget" in " ".join(
        r.json()["detail"]["errores"])


# --------------------------------------------------------------------------- #
# Carpetas del estante
# --------------------------------------------------------------------------- #

def test_un_tablero_sin_carpeta_sale_con_la_carpeta_vacia(tablero):
    """Lo que ya existia no tiene carpeta, y "sin carpeta" es un unico valor."""
    assert tablero["carpeta"] == ""


def test_se_puede_crear_en_una_carpeta_y_moverlo(cliente, cab_admin, modelo_dash):
    cuerpo = _tablero_minimo(modelo_dash, carpeta="  Ventas  ")
    cuerpo["nombre"] = "en_carpeta"
    r = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo)
    assert r.status_code == 201, r.text
    # Se recorta: "Ventas " y "Ventas" serian dos carpetas distintas en la pantalla.
    assert r.json()["carpeta"] == "Ventas"
    tid = r.json()["id"]

    m = cliente.put(f"/api/dashboards/{tid}", headers=cab_admin,
                    json={"carpeta": "Postventa"})
    assert m.status_code == 200, m.text
    assert m.json()["carpeta"] == "Postventa"

    fuera = cliente.put(f"/api/dashboards/{tid}", headers=cab_admin,
                        json={"carpeta": ""})
    assert fuera.json()["carpeta"] == ""
    cliente.delete(f"/api/dashboards/{tid}", headers=cab_admin)


def test_mover_de_carpeta_no_quita_la_certificacion(cliente, cab_admin, tablero):
    """
    Lo importante de que la carpeta viva en su propia columna. Si reordenar el
    estante descertificara, el sello dejaria de significar nada porque nadie podria
    mantenerlo puesto.
    """
    tid = tablero["id"]
    cliente.post(f"/api/dashboards/{tid}/publicar", headers=cab_admin)
    cert = cliente.post(f"/api/dashboards/{tid}/certificar", headers=cab_admin)
    assert cert.json()["certificado"] is True

    r = cliente.put(f"/api/dashboards/{tid}", headers=cab_admin,
                    json={"carpeta": "Direccion"})
    assert r.status_code == 200, r.text
    assert r.json()["carpeta"] == "Direccion"
    assert r.json()["certificado"] is True, "mover de carpeta no toca ninguna cifra"

    # Renombrar tampoco: tampoco cambia una cifra.
    n = cliente.put(f"/api/dashboards/{tid}", headers=cab_admin,
                    json={"nombre": "Comercial (2026)"})
    assert n.json()["certificado"] is True

    # Cambiar la definicion, si.
    d = dict(tablero["definicion"])
    d["widgets"] = [dict(w) for w in d["widgets"]]
    d["widgets"][0]["titulo"] = "Otro titulo"
    e = cliente.put(f"/api/dashboards/{tid}", headers=cab_admin, json={"definicion": d})
    assert e.json()["certificado"] is False, "cambiar las cifras si quita el sello"


def test_la_carpeta_no_decide_quien_ve_que(cliente, cab_lector, cab_admin,
                                           modelo_dash):
    """
    La carpeta **solo ordena**. Quien ve que lo siguen decidiendo el rol y el
    publicado: un tablero sin publicar en una carpeta con nombre serio sigue siendo
    invisible para un lector, y uno publicado sigue siendo visible aunque este en
    una carpeta que se llame "Direccion".
    """
    cuerpo = _tablero_minimo(modelo_dash, carpeta="Direccion")
    cuerpo["nombre"] = "carpeta_no_es_permiso"
    tid = cliente.post("/api/dashboards", headers=cab_admin, json=cuerpo).json()["id"]

    assert cliente.get(f"/api/dashboards/{tid}", headers=cab_lector).status_code == 404

    cliente.post(f"/api/dashboards/{tid}/publicar", headers=cab_admin)
    visto = cliente.get(f"/api/dashboards/{tid}", headers=cab_lector)
    assert visto.status_code == 200, "publicado se ve, este en la carpeta que este"
    assert visto.json()["carpeta"] == "Direccion"
    cliente.delete(f"/api/dashboards/{tid}", headers=cab_admin)


def test_el_estante_sale_ordenado_por_carpeta(cliente, cab_admin, modelo_dash):
    creados = []
    for nombre, carpeta in [("zb", "Ventas"), ("za", "Ventas"), ("zc", "Postventa")]:
        cuerpo = _tablero_minimo(modelo_dash, carpeta=carpeta)
        cuerpo["nombre"] = nombre
        creados.append(cliente.post("/api/dashboards", headers=cab_admin,
                                    json=cuerpo).json()["id"])

    todos = cliente.get("/api/dashboards", headers=cab_admin).json()
    mios = [(d["carpeta"], d["nombre"]) for d in todos if d["nombre"].startswith("z")]
    assert mios == [("Postventa", "zc"), ("Ventas", "za"), ("Ventas", "zb")], mios

    for tid in creados:
        cliente.delete(f"/api/dashboards/{tid}", headers=cab_admin)


# --------------------------------------------------------------------------- #
# El limite dice cuando corta
#
# Una tabla recortada que no dice que lo esta se lee como completa. Es peor que un
# error: un error se ve y se arregla, y esto se firma.
# --------------------------------------------------------------------------- #


def _consultar(cliente, cab, modelo_id, **extra):
    cuerpo = {"dimensiones": ["cat_sucursal.sucursal_nombre"],
              "metricas": ["monto_venta"], **extra}
    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab, json=cuerpo)
    assert r.status_code == 200, r.text
    return r.json()


def test_una_consulta_que_cabe_no_dice_que_se_corto(cliente, cab_admin, modelo_dash):
    entero = _consultar(cliente, cab_admin, modelo_dash, limite=5000)
    assert entero["truncado"] is False
    assert len(entero["filas"]) > 1, "hace falta mas de una fila para la prueba"


def test_una_consulta_recortada_lo_dice_y_devuelve_justo_el_limite(
        cliente, cab_admin, modelo_dash):
    entero = _consultar(cliente, cab_admin, modelo_dash, limite=5000)
    n = len(entero["filas"])

    corto = _consultar(cliente, cab_admin, modelo_dash, limite=n - 1)
    assert corto["truncado"] is True, "dejo filas fuera y no lo dijo"
    assert len(corto["filas"]) == n - 1, "el limite es el limite, ni una mas"


def test_el_limite_exacto_no_se_confunde_con_un_recorte(cliente, cab_admin,
                                                        modelo_dash):
    """
    El caso que separa contar de saber: pedir exactamente las filas que hay.
    Contando las que vuelven, esto es indistinguible de un recorte; por eso se
    pide una fila mas de la que se ensena.
    """
    entero = _consultar(cliente, cab_admin, modelo_dash, limite=5000)
    n = len(entero["filas"])

    justo = _consultar(cliente, cab_admin, modelo_dash, limite=n)
    assert len(justo["filas"]) == n
    assert justo["truncado"] is False, "caben justas: no se corto nada"
