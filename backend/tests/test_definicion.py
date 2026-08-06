"""
Fase 2 — la definicion del modelo como estructura editable.

Lo que se protege aqui es la ida y vuelta: la interfaz lee la definicion, la
cambia y la guarda. Si en ese viaje se pierde algo, se pierde en silencio, y el
modelo queda distinto de lo que su autor cree.
"""

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"def_{id(cliente)}", "descripcion": "Fase 2",
        "yaml": YAML_DEMO,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# Ida y vuelta
# --------------------------------------------------------------------------- #

def test_la_definicion_conserva_lo_que_el_motor_ignora():
    """
    El motor no lee 'jerarquias'. Si la interfaz guardara serializando los
    objetos del motor, la jerarquia Tiempo desapareceria al primer cambio de una
    relacion, sin aviso.
    """
    from semantic.definicion import desde_yaml

    d = desde_yaml(YAML_DEMO)
    calendario = next(e for e in d.entidades if e.nombre == "dim_calendario")
    assert calendario.model_extra.get("jerarquias"), "se perdio la jerarquia"

    # Y sobrevive el viaje completo a YAML y de vuelta.
    d2 = desde_yaml(d.a_yaml())
    cal2 = next(e for e in d2.entidades if e.nombre == "dim_calendario")
    assert cal2.model_extra["jerarquias"] == calendario.model_extra["jerarquias"]


def test_el_modelo_completo_sobrevive_la_ida_y_vuelta():
    from semantic.definicion import desde_yaml

    d = desde_yaml(YAML_DEMO)
    d2 = desde_yaml(d.a_yaml())
    assert d2.model_dump() == d.model_dump()


def test_las_politicas_no_se_tocan():
    """La seguridad por fila viaja intacta: reescribirla seria abrir un hueco."""
    from semantic.definicion import desde_yaml

    d = desde_yaml(YAML_DEMO)
    assert d.politicas
    assert desde_yaml(d.a_yaml()).politicas == d.politicas


def test_el_orden_de_las_claves_es_estable():
    """
    El YAML se versiona y se revisa en diff. Con orden alfabetico o al azar, cada
    guardado produciria un diff ilegible y nadie revisaria nada.
    """
    from semantic.definicion import desde_yaml

    texto = desde_yaml(YAML_DEMO).a_yaml()
    posiciones = [texto.index(f"\n{k}:") if texto.index(f"{k}:") else 0
                  for k in ("version", "entidades", "relaciones", "metricas")]
    assert posiciones == sorted(posiciones)
    assert texto.startswith("modelo:")


# --------------------------------------------------------------------------- #
# Validacion con mensajes utiles
# --------------------------------------------------------------------------- #

def _definicion_minima() -> dict:
    return {
        "modelo": "prueba", "version": 1,
        "entidades": [
            {"nombre": "dim_a", "tipo": "dimension", "origen": {"tabla": "cat_marca"},
             "clave_primaria": "marca_id",
             "campos": [{"nombre": "marca_id", "tipo": "entero", "rol": "clave"},
                        {"nombre": "marca_nombre", "tipo": "texto",
                         "rol": "dimension"}]},
            {"nombre": "hecho_b", "tipo": "hecho", "origen": {"tabla": "fact_venta"},
             "grano": ["venta_id"],
             "campos": [{"nombre": "venta_id", "tipo": "entero", "rol": "clave"},
                        {"nombre": "monto_base", "tipo": "decimal",
                         "rol": "medida_base"}]},
        ],
        "relaciones": [],
        "metricas": [{"nombre": "m1", "etiqueta": "M", "entidad": "hecho_b",
                      "expresion": "SUM(monto_base)"}],
    }


def test_relacion_a_entidad_inexistente_se_explica(cliente, cab_admin, modelo):
    d = _definicion_minima()
    d["relaciones"] = [{"desde": ["hecho_b", "venta_id"],
                        "hasta": ["no_existe", "x"],
                        "cardinalidad": "muchos_a_uno",
                        "direccion_filtro": "ambas"}]
    r = cliente.put(f"/api/modelos/{modelo}/definicion", headers=cab_admin,
                    json={"definicion": d})
    assert r.status_code == 422
    errores = r.json()["detail"]["errores"]
    assert any("no_existe" in e and "no existe" in e for e in errores)


def test_relacion_a_campo_inexistente_se_explica(cliente, cab_admin, modelo):
    d = _definicion_minima()
    d["relaciones"] = [{"desde": ["hecho_b", "columna_fantasma"],
                        "hasta": ["dim_a", "marca_id"],
                        "cardinalidad": "muchos_a_uno",
                        "direccion_filtro": "ambas"}]
    r = cliente.put(f"/api/modelos/{modelo}/definicion", headers=cab_admin,
                    json={"definicion": d})
    assert r.status_code == 422
    assert any("columna_fantasma" in e for e in r.json()["detail"]["errores"])


def test_clave_primaria_que_no_es_campo_se_explica(cliente, cab_admin, modelo):
    d = _definicion_minima()
    d["entidades"][0]["clave_primaria"] = "no_es_campo"
    r = cliente.put(f"/api/modelos/{modelo}/definicion", headers=cab_admin,
                    json={"definicion": d})
    assert r.status_code == 422
    assert any("clave primaria" in e for e in r.json()["detail"]["errores"])


def test_metrica_repetida_se_explica(cliente, cab_admin, modelo):
    d = _definicion_minima()
    d["metricas"].append({"nombre": "m1", "etiqueta": "Otra",
                          "entidad": "hecho_b", "expresion": "SUM(monto_base)"})
    r = cliente.put(f"/api/modelos/{modelo}/definicion", headers=cab_admin,
                    json={"definicion": d})
    assert r.status_code == 422
    assert any("mas de una metrica" in e for e in r.json()["detail"]["errores"])


def test_rol_de_campo_invalido_se_rechaza(cliente, cab_admin, modelo):
    d = _definicion_minima()
    d["entidades"][0]["campos"][0]["rol"] = "lo_que_sea"
    r = cliente.put(f"/api/modelos/{modelo}/definicion", headers=cab_admin,
                    json={"definicion": d})
    assert r.status_code == 422


def test_una_definicion_correcta_crea_version_nueva(cliente, cab_admin, modelo):
    """Guardar nunca sobreescribe: la version anterior sigue ahi."""
    r = cliente.put(f"/api/modelos/{modelo}/definicion", headers=cab_admin,
                    json={"definicion": _definicion_minima(),
                          "notas": "modelo minimo"})
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 2

    v = cliente.get(f"/api/modelos/{modelo}/versiones", headers=cab_admin).json()
    assert [x["version"] for x in v["versiones"]] == [2, 1]
    assert v["versiones"][0]["entidades"] == 2
    assert v["versiones"][0]["metricas"] == 1

    # La version 1 sigue siendo legible tal como se guardo.
    r = cliente.get(f"/api/modelos/{modelo}/definicion?version=1", headers=cab_admin)
    assert r.status_code == 200
    assert r.json()["es_vigente"] is False
    assert len(r.json()["definicion"]["entidades"]) > 2


def test_la_disposicion_del_lienzo_viaja_con_el_modelo(cliente, cab_admin, modelo):
    """
    Abrir el modelo en otra maquina debe verse igual. Por eso la posicion de cada
    nodo va dentro de la version, no en el navegador.
    """
    d = _definicion_minima()
    d["disposicion"] = {"dim_a": {"x": 120.0, "y": 40.0},
                        "hecho_b": {"x": 480.0, "y": 260.0}}
    r = cliente.put(f"/api/modelos/{modelo}/definicion", headers=cab_admin,
                    json={"definicion": d})
    assert r.status_code == 201, r.text

    leido = cliente.get(f"/api/modelos/{modelo}/definicion",
                        headers=cab_admin).json()["definicion"]
    assert leido["disposicion"]["hecho_b"] == {"x": 480.0, "y": 260.0}


# --------------------------------------------------------------------------- #
# Rutas y ambiguedad
# --------------------------------------------------------------------------- #

def test_las_rutas_explican_la_ambiguedad(cliente, cab_admin, modelo):
    """
    fact_venta llega a cat_marca por dos caminos: la marca de la agencia y la
    marca del vehiculo. El lienzo tiene que poder mostrar cuales son, no solo
    avisar de que hay un problema.
    """
    r = cliente.get(f"/api/modelos/{modelo}/rutas"
                    f"?desde=fact_venta&hasta=cat_marca", headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ambigua"] is True
    assert len(d["agregacion"]) == 2
    assert {tuple(r) for r in d["agregacion"]} == {
        ("fact_venta", "cat_sucursal", "cat_marca"),
        ("fact_venta", "dim_vehiculo", "cat_marca"),
    }


def test_una_ruta_sin_ambiguedad_es_unica(cliente, cab_admin, modelo):
    r = cliente.get(f"/api/modelos/{modelo}/rutas"
                    f"?desde=fact_venta&hasta=cat_region", headers=cab_admin)
    d = r.json()
    assert d["ambigua"] is False
    assert d["agregacion"] == [["fact_venta", "cat_sucursal", "cat_region"]]


def test_entidad_inexistente_en_rutas_da_404(cliente, cab_admin, modelo):
    r = cliente.get(f"/api/modelos/{modelo}/rutas?desde=fact_venta&hasta=nada",
                    headers=cab_admin)
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Probar una expresion antes de guardarla
# --------------------------------------------------------------------------- #

def test_probar_metrica_devuelve_el_numero(cliente, cab_admin, modelo):
    """Ver el numero antes de guardar es lo que evita publicar algo plausible
    y equivocado."""
    r = cliente.post(f"/api/modelos/{modelo}/probar-metrica", headers=cab_admin,
                     json={"entidad": "fact_venta",
                           "expresion": "SUM(monto_base)",
                           "dimensiones": ["cat_sucursal.sucursal_nombre"],
                           "limite": 5})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["filas"]) == 5
    assert "__prueba__" in d["columnas"]
    assert "SUM" in d["sql"]


def test_probar_metrica_con_columna_inexistente_avisa(cliente, cab_admin, modelo):
    r = cliente.post(f"/api/modelos/{modelo}/probar-metrica", headers=cab_admin,
                     json={"entidad": "fact_venta",
                           "expresion": "SUM(columna_que_no_existe)"})
    assert r.status_code == 422
    assert "no se pudo ejecutar" in r.json()["detail"]


def test_probar_metrica_no_guarda_nada(cliente, cab_admin, modelo):
    antes = cliente.get(f"/api/modelos/{modelo}/versiones",
                        headers=cab_admin).json()["versiones"]
    cliente.post(f"/api/modelos/{modelo}/probar-metrica", headers=cab_admin,
                 json={"entidad": "fact_venta", "expresion": "SUM(unidades)"})
    despues = cliente.get(f"/api/modelos/{modelo}/versiones",
                          headers=cab_admin).json()["versiones"]
    assert antes == despues


def test_el_lector_no_puede_probar_expresiones(cliente, cab_lector, modelo):
    """Probar una expresion ejecuta SQL arbitrario sobre el modelo: es de editor."""
    r = cliente.post(f"/api/modelos/{modelo}/probar-metrica", headers=cab_lector,
                     json={"entidad": "fact_venta", "expresion": "SUM(unidades)"})
    assert r.status_code == 403


def test_el_lector_no_ve_el_yaml(cliente, cab_lector, modelo):
    assert cliente.get(f"/api/modelos/{modelo}/yaml",
                       headers=cab_lector).status_code == 403


# --------------------------------------------------------------------------- #
# Catalogo de tablas
# --------------------------------------------------------------------------- #

def test_el_catalogo_lista_las_tablas(cliente, cab_admin):
    r = cliente.get("/api/catalogo/tablas", headers=cab_admin)
    assert r.status_code == 200, r.text
    tablas = {t["nombre"]: t["filas"] for t in r.json()["tablas"]}
    assert {"fact_venta", "cat_sucursal", "dim_calendario"} <= set(tablas)
    assert tablas["fact_venta"] > 0


def test_el_catalogo_sugiere_el_rol_de_cada_columna(cliente, cab_admin):
    """
    Es una sugerencia editable, no una decision: acertar 'sucursal_id' es facil,
    pero si 'monto_objetivo' es medida o dimension lo sabe la persona.
    """
    r = cliente.get("/api/catalogo/tablas/fact_venta", headers=cab_admin)
    assert r.status_code == 200, r.text
    cols = {c["nombre"]: c for c in r.json()["columnas"]}
    assert cols["sucursal_id"]["rol_sugerido"] == "clave_externa"
    assert cols["monto_base"]["rol_sugerido"] == "medida_base"
    assert cols["monto_base"]["tipo"] == "decimal"
    assert cols["fecha_emision"]["tipo"] == "fecha"


def test_tabla_inexistente_en_el_catalogo_da_404(cliente, cab_admin):
    assert cliente.get("/api/catalogo/tablas/no_existe",
                       headers=cab_admin).status_code == 404


def test_el_lector_no_ve_el_catalogo(cliente, cab_lector):
    assert cliente.get("/api/catalogo/tablas",
                       headers=cab_lector).status_code == 403
