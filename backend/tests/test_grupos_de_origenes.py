"""
Cada origen del panel del ETL, en el grupo que le toca.

El panel reparte lo que se puede transformar en grupos —«Tablas del motor»,
«Datos cargados», «Secciones de este proyecto»— y ese reparto NO es decoracion:
decide con que tipo se crea el origen al pulsarlo, y de ahi sale un FROM distinto.

  - Del grupo del motor sale un origen `tabla`, que se lee como `motor."nombre"`.
  - De los otros sale un origen `dataset`, que se lee con `read_parquet(...)` y
    que ademas le agrega al vuelo las etiquetas de su conexion —`id_sucursal`, la
    marca—. Con cuarenta sucursales esas columnas son la diferencia entre saber de
    que agencia es cada fila y no saberlo.

El endpoint devolvia en `tablas` TODO lo que el modelo puede nombrar: las del
motor, las cargas y los resultados, cada cosa con su procedencia, y la pantalla lo
pintaba entero bajo «Tablas del motor». De 49 entradas, 12 eran del motor.

Y no era cosmetico: la carga aparecia DOS veces, en dos grupos, con el mismo
nombre. Tomada del grupo bueno funciona; tomada del de arriba crea un origen que
apunta a una tabla que no existe en el motor, y la transformacion revienta al
ejecutarse con «Table with name X does not exist». Dos caminos con el mismo
nombre, uno bueno y otro roto, sin nada que los distinga mirando.
"""

import pytest

from tests.conftest import cargar


@pytest.fixture
def escenario(cliente, cab_admin, conexion_archivos_etl):
    """
    Una carga Y un resultado, los dos con datos.

    **La primera version de estas pruebas no traia esto y por eso no valian.** Tres
    de las cuatro pasaban igual con el defecto puesto: cuando corrian todavia no
    habia ninguna carga hecha ni ninguna transformacion ejecutada, asi que el grupo
    del motor solo tenia las doce de demostracion y no habia nada que pudiera
    colarse. Una prueba que no puede fallar no prueba nada.
    """
    cargar(cliente, cab_admin, conexion_archivos_etl)

    definicion = {
        "nombre": "resultado_para_grupos",
        "origenes": [{"nombre": "v", "tipo": "tabla", "referencia": "fact_venta"}],
        "pasos": [{"tipo": "agrupar", "por": ["sucursal_id"],
                   "agregados": [{"nombre": "n", "funcion": "cuenta"}]}],
    }
    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    tid = next((t["id"] for t in lista
                if t["nombre"] == "resultado_para_grupos"), None)
    if tid is None:
        r = cliente.post("/api/transformaciones", headers=cab_admin,
                         json={"definicion": definicion})
        assert r.status_code == 201, r.text
        tid = r.json()["id"]
    r = cliente.post(f"/api/transformaciones/{tid}/ejecutar", headers=cab_admin)
    assert r.status_code == 200, r.text
    return {"carga": "ventas_csv_etl", "resultado": "resultado_para_grupos"}


def _origenes(cliente, cab):
    r = cliente.get("/api/transformaciones/origenes", headers=cab)
    assert r.status_code == 200, r.text
    return r.json()


def test_en_el_grupo_del_motor_solo_hay_tablas_del_motor(
        cliente, cab_admin, escenario):
    """
    La prueba de fondo, y la que no se puede falsear: cada nombre de ese grupo
    tiene que poder LEERSE como tabla del motor. Comprobar solo la procedencia
    seria comprobar la etiqueta que pone el mismo codigo que se esta probando.
    """
    cuerpo = _origenes(cliente, cab_admin)
    assert cuerpo["avisos"] == []
    assert len(cuerpo["tablas"]) > 0, "el bloque del motor se cayo en silencio"

    for t in cuerpo["tablas"]:
        r = cliente.get("/api/transformaciones/columnas", headers=cab_admin,
                        params={"tipo": "tabla", "referencia": t["nombre"]})
        assert r.status_code == 200, (
            f"'{t['nombre']}' se ofrece como tabla del motor y no se puede leer "
            f"como tal: {r.text}")


def test_la_carga_y_el_resultado_salen_en_su_grupo_y_solo_en_el_suyo(
        cliente, cab_admin, escenario):
    """
    El caso concreto del defecto: el mismo nombre en dos grupos, uno de los cuales
    no existe.

    Lo que NO se puede exigir es que los tres grupos sean disjuntos en general. Una
    carga puede llamarse igual que una tabla del motor —pasa en la propia bateria de
    pruebas, con `cat_sucursal`— y entonces salir en los dos grupos es correcto: son
    dos cosas distintas con el mismo nombre, y las dos se pueden leer. Eso es un
    problema de nombres, no de grupos, y se resuelve en otro sitio.

    El defecto era otra cosa: nombres en el grupo del motor que **no estan en el
    motor**. De eso se encarga la prueba de arriba, que los lee uno por uno.
    """
    cuerpo = _origenes(cliente, cab_admin)
    motor = {t["nombre"] for t in cuerpo["tablas"]}
    cargas = {d["nombre"] for d in cuerpo["datasets"]}
    resultados = {t["nombre"] for t in cuerpo["transformaciones"]}

    assert escenario["carga"] in cargas
    assert escenario["carga"] not in motor
    assert escenario["resultado"] in resultados
    assert escenario["resultado"] not in motor


def test_tomar_la_carga_del_grupo_equivocado_es_lo_que_fallaba(
        cliente, cab_admin, escenario):
    """
    Deja constancia de POR QUE importa el grupo, y no solo de que la lista este
    limpia. Si algun dia alguien vuelve a meter las cargas en `tablas`, esta
    prueba explica lo que le va a pasar al usuario.
    """
    como_dataset = cliente.get(
        "/api/transformaciones/columnas", headers=cab_admin,
        params={"tipo": "dataset", "referencia": escenario["carga"]})
    assert como_dataset.status_code == 200, como_dataset.text
    assert len(como_dataset.json()["columnas"]) > 0

    como_tabla = cliente.get(
        "/api/transformaciones/columnas", headers=cab_admin,
        params={"tipo": "tabla", "referencia": escenario["carga"]})
    assert como_tabla.status_code == 400
    assert "does not exist" in como_tabla.json()["detail"]
