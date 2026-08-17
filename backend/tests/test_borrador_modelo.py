"""
Guardar sin publicar, descartar, publicar y borrar el modelo.

La regla que se prueba una y otra vez aqui es la misma: **lo que ven los tableros
no cambia hasta que alguien publica.** Guardar cuarenta veces deja el modelo
vigente en la version en la que estaba.
"""

import itertools

import pytest

_contador = itertools.count(1)


@pytest.fixture
def modelo_id(cliente, cab_admin, yaml_modelo):
    """
    Un modelo propio por prueba, y se borra al terminar.

    No se reutiliza el `modelo_id` compartido de conftest a proposito: aqui casi
    todo PUBLICA, y una version de mas en el modelo de demostracion cambiaria por
    debajo lo que afirman las pruebas de los otros modulos. Ademas, tener que
    crear y borrar uno de verdad ejercita las dos rutas nuevas en cada prueba.
    """
    nombre = f"borrador_pruebas_{next(_contador)}"
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


def vigente(cliente, cab, modelo_id) -> int:
    return next(m for m in cliente.get("/api/modelos", headers=cab).json()
                if m["id"] == modelo_id)["version_actual"]


def con_metrica(definicion, nombre="prueba_borrador", expresion="CONTAR()"):
    """La definicion con esa metrica puesta, la hubiera ya o no."""
    entidad = next(e["nombre"] for e in definicion["entidades"]
                   if e["tipo"] == "hecho")
    otras = [m for m in definicion.get("metricas", []) if m["nombre"] != nombre]
    return {**definicion, "metricas": [
        *otras,
        {"nombre": nombre, "etiqueta": "Prueba", "entidad": entidad,
         "expresion": expresion, "formato": "entero"},
    ]}


# --------------------------------------------------------------------------- #
# Guardar sin publicar
# --------------------------------------------------------------------------- #

def test_guardar_el_borrador_no_crea_version(cliente, cab_editor, modelo_id,
                                             definicion):
    antes = vigente(cliente, cab_editor, modelo_id)
    r = cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                    json={"definicion": con_metrica(definicion)})
    assert r.status_code == 200, r.text
    assert vigente(cliente, cab_editor, modelo_id) == antes


def test_el_editor_reabre_el_borrador_y_no_lo_publicado(cliente, cab_editor,
                                                        modelo_id, definicion):
    """
    Lo que hace que guardar sirva de algo: al volver, ahi esta el trabajo. Si
    `/definicion` devolviera la version vigente, guardar y recargar se veria
    exactamente igual que no haber guardado.
    """
    cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                json={"definicion": con_metrica(definicion)})
    r = cliente.get(f"/api/modelos/{modelo_id}/definicion", headers=cab_editor)
    d = r.json()
    assert d["borrador"] is not None
    assert d["borrador"]["actualizado_por"].endswith("@pruebas.example.com")
    assert any(m["nombre"] == "prueba_borrador" for m in d["definicion"]["metricas"])


def test_el_modelo_publicado_sigue_intacto_con_borrador_encima(
        cliente, cab_editor, modelo_id, definicion):
    cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                json={"definicion": con_metrica(definicion)})
    v = vigente(cliente, cab_editor, modelo_id)
    # Pedir la version explicitamente salta el borrador: es la via del historial.
    r = cliente.get(f"/api/modelos/{modelo_id}/definicion?version={v}",
                    headers=cab_editor)
    assert r.json()["borrador"] is None
    assert not any(m["nombre"] == "prueba_borrador"
                   for m in r.json()["definicion"]["metricas"])
    # Y el catalogo, que es de lo que comen los tableros, tampoco la ve.
    campos = cliente.get(f"/api/modelos/{modelo_id}/campos", headers=cab_editor)
    assert "prueba_borrador" not in {m["clave"] for m in campos.json()["metricas"]}


def test_guardar_dos_veces_deja_un_solo_borrador(cliente, cab_editor, modelo_id,
                                                 definicion):
    for nombre in ("uno", "dos"):
        r = cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                        json={"definicion": con_metrica(definicion, nombre)})
        assert r.status_code == 200, r.text
    d = cliente.get(f"/api/modelos/{modelo_id}/definicion",
                    headers=cab_editor).json()["definicion"]
    nombres = {m["nombre"] for m in d["metricas"]}
    assert "dos" in nombres and "uno" not in nombres


def test_un_borrador_que_no_compila_no_se_guarda(cliente, cab_editor, modelo_id,
                                                 definicion):
    """
    Guardar valida igual que publicar. Un borrador roto se guardaria sin
    protestar y el error saldria dias despues, al publicar.
    """
    roto = con_metrica(definicion)
    roto["metricas"][-1]["entidad"] = "no_existe"
    r = cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                    json={"definicion": roto})
    assert r.status_code == 422, r.text
    assert cliente.get(f"/api/modelos/{modelo_id}/definicion",
                       headers=cab_editor).json()["borrador"] is None


def test_un_lector_no_guarda_borradores(cliente, cab_lector, modelo_id, definicion):
    r = cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_lector,
                    json={"definicion": definicion})
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Descartar
# --------------------------------------------------------------------------- #

def test_descartar_devuelve_el_modelo_a_lo_publicado(cliente, cab_editor,
                                                     modelo_id, definicion):
    cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                json={"definicion": con_metrica(definicion)})
    r = cliente.delete(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == vigente(cliente, cab_editor, modelo_id)

    d = cliente.get(f"/api/modelos/{modelo_id}/definicion", headers=cab_editor).json()
    assert d["borrador"] is None
    assert not any(m["nombre"] == "prueba_borrador" for m in d["definicion"]["metricas"])


def test_descartar_sin_borrador_es_404(cliente, cab_editor, modelo_id):
    assert cliente.delete(f"/api/modelos/{modelo_id}/borrador",
                          headers=cab_editor).status_code == 404


# --------------------------------------------------------------------------- #
# Publicar
# --------------------------------------------------------------------------- #

def test_publicar_crea_la_version_y_cierra_el_borrador(cliente, cab_editor,
                                                       modelo_id, definicion):
    antes = vigente(cliente, cab_editor, modelo_id)
    cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                json={"definicion": con_metrica(definicion)})

    r = cliente.post(f"/api/modelos/{modelo_id}/publicar", headers=cab_editor,
                     json={"notas": "con la metrica de prueba"})
    assert r.status_code == 201, r.text
    assert r.json()["version"] == antes + 1

    d = cliente.get(f"/api/modelos/{modelo_id}/definicion", headers=cab_editor).json()
    assert d["borrador"] is None                       # ya no hay nada pendiente
    assert d["version"] == antes + 1
    assert any(m["nombre"] == "prueba_borrador" for m in d["definicion"]["metricas"])


def test_publicar_sin_borrador_no_crea_una_version_identica(cliente, cab_editor,
                                                            modelo_id):
    """
    Publicar «por si acaso» sin haber cambiado nada llenaria el historial de
    versiones iguales, que es justo lo que hace inservible un historial.
    """
    antes = vigente(cliente, cab_editor, modelo_id)
    r = cliente.post(f"/api/modelos/{modelo_id}/publicar", headers=cab_editor,
                     json={})
    assert r.status_code == 409
    assert vigente(cliente, cab_editor, modelo_id) == antes


def test_publicar_por_la_via_de_siempre_tambien_cierra_el_borrador(
        cliente, cab_editor, modelo_id, definicion):
    """
    `PUT /definicion` publica directo. Si dejara el borrador puesto, el editor
    seguiria avisando de «cambios sin publicar» identicos a lo ya publicado.
    """
    cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                json={"definicion": con_metrica(definicion)})
    r = cliente.put(f"/api/modelos/{modelo_id}/definicion", headers=cab_editor,
                    json={"definicion": con_metrica(definicion)})
    assert r.status_code == 201, r.text
    assert cliente.get(f"/api/modelos/{modelo_id}/definicion",
                       headers=cab_editor).json()["borrador"] is None


# --------------------------------------------------------------------------- #
# Borrar el modelo
#
# El fixture `modelo_id` ya crea uno propio y lo borra al terminar, asi que estas
# pruebas pueden llevarselo por delante sin dejar nada a medias: borrar dos veces
# es 404 y el fixture no lo comprueba.
# --------------------------------------------------------------------------- #

def test_borrar_se_lleva_versiones_y_borrador(cliente, cab_admin, cab_editor,
                                              modelo_id, definicion):
    cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                json={"definicion": con_metrica(definicion)})
    assert cliente.delete(f"/api/modelos/{modelo_id}",
                          headers=cab_admin).status_code == 204

    ids = {m["id"] for m in cliente.get("/api/modelos", headers=cab_admin).json()}
    assert modelo_id not in ids
    assert cliente.get(f"/api/modelos/{modelo_id}/versiones",
                       headers=cab_admin).status_code == 404


def test_no_se_borra_un_modelo_con_tableros_encima(cliente, cab_admin,
                                                   modelo_id):
    """
    Se niega y DICE cuales. Borrar en cascada seria peor: quien tira un modelo de
    prueba no espera perder ademas el tablero que otro publico sobre el.
    """
    t = cliente.post("/api/dashboards", headers=cab_admin,
                     json={"nombre": "tablero encima",
                           "modelo_id": modelo_id})
    assert t.status_code == 201, t.text

    r = cliente.delete(f"/api/modelos/{modelo_id}", headers=cab_admin)
    assert r.status_code == 409, r.text
    detalle = r.json()["detail"]
    assert [d["nombre"] for d in detalle["tableros"]] == ["tablero encima"]

    # Sin el tablero, ya se puede.
    cliente.delete(f"/api/dashboards/{t.json()['id']}", headers=cab_admin)
    assert cliente.delete(f"/api/modelos/{modelo_id}",
                          headers=cab_admin).status_code == 204


def test_un_editor_no_borra_modelos(cliente, cab_editor, modelo_id):
    """
    Publicar deja rastro y se puede volver atras; esto no. Es la unica operacion
    del modelo que pide administrador.
    """
    assert cliente.delete(f"/api/modelos/{modelo_id}",
                          headers=cab_editor).status_code == 403


# --------------------------------------------------------------------------- #
# Formulas por la API
# --------------------------------------------------------------------------- #

def test_el_catalogo_de_funciones_esta_disponible(cliente, cab_editor):
    r = cliente.get("/api/modelos/funciones", headers=cab_editor)
    assert r.status_code == 200, r.text
    nombres = {f["nombre"] for f in r.json()["funciones"]}
    assert {"SUMA", "DIVIDIR", "CALCULAR", "SI", "CONTARUNICOS"} <= nombres


def test_revisar_formula_señala_el_campo_mal_escrito(cliente, cab_editor, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/revisar-formula", headers=cab_editor,
                     json={"entidad": "fact_venta", "expresion": "SUMA(mnto_base)",
                           "campos": ["monto_base", "unidades"]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["hay_errores"]
    assert d["fallos"][0]["columna"] == 6
    assert "monto_base" in d["fallos"][0]["mensaje"]


def test_revisar_formula_devuelve_el_sql_cuando_esta_bien(cliente, cab_editor,
                                                          modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/revisar-formula", headers=cab_editor,
                     json={"entidad": "fact_venta",
                           "expresion": "VAR v = SUMA(monto_base)\nRETURN DIVIDIR(v, CONTAR())",
                           "campos": ["monto_base"]})
    d = r.json()
    assert not d["hay_errores"], d["fallos"]
    assert "NULLIF" in d["sql"]


def test_una_metrica_con_formula_se_consulta_de_verdad(cliente, cab_editor,
                                                       modelo_id, definicion):
    """
    De punta a punta: se define con el lenguaje nuevo, se publica y se consulta.
    Que compile no basta — tiene que devolver el numero.
    """
    entidad = next(e["nombre"] for e in definicion["entidades"]
                   if e["tipo"] == "hecho")
    nueva = {**definicion, "metricas": [
        *definicion["metricas"],
        {"nombre": "facturas_distintas", "etiqueta": "Facturas",
         "entidad": entidad, "formato": "entero",
         "expresion": "-- una por nota\nCONTARUNICOS(nr_nota)"},
    ]}
    cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                json={"definicion": nueva})
    assert cliente.post(f"/api/modelos/{modelo_id}/publicar", headers=cab_editor,
                        json={}).status_code == 201

    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_editor,
                     json={"dimensiones": [], "metricas": ["facturas_distintas"]})
    assert r.status_code == 200, r.text
    assert r.json()["filas"][0]["facturas_distintas"] > 0


def test_el_yaml_ensena_el_borrador_y_tambien_la_publicada(
        cliente, cab_editor, modelo_id, definicion):
    """
    Las dos cosas se pueden mirar, y se sabe cual se esta mirando.

    Antes esta ruta devolvia SIEMPRE la version publicada. El lienzo enseñaba el
    borrador y el YAML otra cosa, sin decirlo: con trece tablas trabajadas y una
    publicada, aqui salia una sola, y la conclusion razonable era que el YAML
    estaba roto. No lo estaba — era otro texto.
    """
    entidad = next(e["nombre"] for e in definicion["entidades"]
                   if e["tipo"] == "hecho")
    marca = "solo_en_el_borrador"
    nueva = {**definicion, "metricas": [
        *definicion["metricas"],
        {"nombre": marca, "etiqueta": "Marca", "entidad": entidad,
         "expresion": "CONTAR()", "formato": "entero"},
    ]}
    assert cliente.put(f"/api/modelos/{modelo_id}/borrador", headers=cab_editor,
                       json={"definicion": nueva}).status_code == 200

    # Sin pedir version: el borrador, y dice que lo es.
    b = cliente.get(f"/api/modelos/{modelo_id}/yaml", headers=cab_editor)
    assert b.status_code == 200, b.text
    assert b.json()["es_borrador"] is True
    assert marca in b.json()["yaml"]
    vigente = b.json()["version_vigente"]

    # Pidiendo la publicada: la publicada, y sin la marca.
    p = cliente.get(f"/api/modelos/{modelo_id}/yaml?version={vigente}",
                    headers=cab_editor)
    assert p.status_code == 200, p.text
    assert p.json()["es_borrador"] is False
    assert marca not in p.json()["yaml"]


def test_sin_borrador_el_yaml_es_la_publicada(cliente, cab_editor, modelo_id):
    r = cliente.get(f"/api/modelos/{modelo_id}/yaml", headers=cab_editor)
    assert r.status_code == 200, r.text
    assert r.json()["es_borrador"] is False
    assert r.json()["version"] == r.json()["version_vigente"]
