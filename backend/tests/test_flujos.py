"""
Flujos: cargar y transformar en cadena.

Lo que se protege: que un fallo detenga la cadena en vez de recalcular sobre datos
que no se cargaron, que el orden mal puesto se avise, y que un flujo programado deje
el mismo rastro que el botón.
"""

import pytest

from tests.conftest import necesita_mysql   # noqa: F401


def crear_flujo(cliente, cab, cuerpo: dict) -> dict:
    """
    Crea el flujo o devuelve el que ya existe con ese nombre.

    La base de metadatos vive toda la corrida, asi que crear el mismo flujo dos
    veces da 409. Reutilizarlo mantiene las pruebas independientes del orden.
    """
    r = cliente.post("/api/flujos", headers=cab, json=cuerpo)
    if r.status_code == 409:
        lista = cliente.get("/api/flujos", headers=cab).json()
        existente = next(f for f in lista if f["nombre"] == cuerpo["nombre"])
        r = cliente.put(f"/api/flujos/{existente['id']}", headers=cab, json=cuerpo)
        assert r.status_code == 200, r.text
        return r.json()
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def transformacion_flujo(cliente, cab_admin):
    """Una transformación que lee de una TABLA del motor (sin depender de cargas)."""
    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    for t in lista:
        if t["nombre"] == "resumen_flujo":
            return t["id"]
    r = cliente.post("/api/transformaciones", headers=cab_admin, json={
        "definicion": {
            "nombre": "resumen_flujo",
            "origenes": [{"nombre": "v", "tipo": "tabla", "referencia": "fact_venta"}],
            "pasos": [{"tipo": "agrupar", "por": ["sucursal_id"], "agregados": [
                {"nombre": "n", "funcion": "cuenta", "campo": None}]}],
        }})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def flujo(cliente, cab_admin, transformacion_flujo):
    return crear_flujo(cliente, cab_admin, {
        "nombre": "nocturno",
        "descripcion": "Recalcula el resumen",
        "pasos": [{"tipo": "transformacion", "id": transformacion_flujo}],
    })


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #

def test_ejecutar_un_flujo_corre_sus_pasos(cliente, cab_admin, flujo):
    r = cliente.post(f"/api/flujos/{flujo['id']}/ejecutar", headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["estado"] == "exito"
    assert len(d["pasos"]) == 1
    assert d["pasos"][0]["estado"] == "exito"
    assert d["pasos"][0]["filas"] > 0


def test_cada_paso_deja_su_propio_historial(cliente, cab_admin, flujo,
                                            transformacion_flujo):
    """
    El flujo no reemplaza el historial de cada pieza: lo alimenta. Un paso corrido
    por el flujo y el mismo paso a mano tienen que ser comparables.
    """
    cliente.post(f"/api/flujos/{flujo['id']}/ejecutar", headers=cab_admin)
    h = cliente.get(f"/api/transformaciones/{transformacion_flujo}/historial",
                    headers=cab_admin).json()
    assert h["ejecuciones"], "la transformación no registró su ejecución"
    assert h["ejecuciones"][0]["estado"] == "exito"


def test_el_flujo_guarda_el_resultado_de_cada_paso(cliente, cab_admin, flujo):
    cliente.post(f"/api/flujos/{flujo['id']}/ejecutar", headers=cab_admin)
    h = cliente.get(f"/api/flujos/{flujo['id']}/historial", headers=cab_admin).json()
    ultima = h["ejecuciones"][0]
    assert ultima["estado"] == "exito"
    assert ultima["disparo"] == "manual"
    assert ultima["pasos"][0]["nombre"] == "resumen_flujo"


def test_al_fallar_se_detiene_y_los_demas_quedan_omitidos(cliente, cab_admin,
                                                          transformacion_flujo):
    """
    La regla del diseño: si un paso falla, no se sigue. Recalcular sobre datos que
    no se cargaron produce un número que parece fresco y no lo es.

    Los pasos que no se intentaron quedan como 'omitido': un hueco en el historial
    se leería como "corrió y no hizo nada".
    """
    mala = cliente.post("/api/transformaciones", headers=cab_admin, json={
        "definicion": {
            "nombre": "rompe_el_flujo",
            "origenes": [{"nombre": "v", "tipo": "tabla",
                          "referencia": "fact_venta"}],
            "pasos": [{"tipo": "filtrar", "condiciones": [
                {"campo": "columna_inexistente", "op": "=", "valor": 1}]}],
        }}).json()["id"]

    id_ = crear_flujo(cliente, cab_admin, {
        "nombre": "con_fallo",
        "pasos": [
            {"tipo": "transformacion", "id": mala},
            {"tipo": "transformacion", "id": transformacion_flujo},
        ]})["id"]

    r = cliente.post(f"/api/flujos/{id_}/ejecutar", headers=cab_admin)
    assert r.status_code == 400
    pasos = r.json()["detail"]["pasos"]
    assert pasos[0]["estado"] == "error"
    assert pasos[1]["estado"] == "omitido", "el segundo paso no debió intentarse"


def test_con_continuar_los_demas_pasos_si_corren(cliente, cab_admin,
                                                 transformacion_flujo):
    mala = cliente.get("/api/transformaciones", headers=cab_admin).json()
    id_mala = next(t["id"] for t in mala if t["nombre"] == "rompe_el_flujo")

    id_ = crear_flujo(cliente, cab_admin, {
        "nombre": "continua",
        "al_fallar": "continuar",
        "pasos": [
            {"tipo": "transformacion", "id": id_mala},
            {"tipo": "transformacion", "id": transformacion_flujo},
        ]})["id"]

    r = cliente.post(f"/api/flujos/{id_}/ejecutar", headers=cab_admin)
    assert r.status_code == 400            # el flujo falló, aunque siguiera
    pasos = r.json()["detail"]["pasos"]
    assert pasos[0]["estado"] == "error"
    assert pasos[1]["estado"] == "exito"


# --------------------------------------------------------------------------- #
# Orden y linaje
# --------------------------------------------------------------------------- #

@pytest.fixture
def cadena(cliente, cab_admin, conexion_archivos_etl):
    """
    Un dataset de archivo con datos, y una transformación que lee de él. Es la
    cadena real que este flujo tiene que ordenar: cargar y luego recalcular.
    """
    cliente.post(f"/api/conexiones/datasets/{conexion_archivos_etl}/cargar",
                 headers=cab_admin)

    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    existente = next((t["id"] for t in lista if t["nombre"] == "sobre_csv"), None)
    if existente is None:
        r = cliente.post("/api/transformaciones", headers=cab_admin, json={
            "definicion": {
                "nombre": "sobre_csv",
                "origenes": [{"nombre": "csv", "tipo": "dataset",
                              "referencia": "ventas_csv_etl"}],
                "pasos": [{"tipo": "limitar", "n": 100}],
            }})
        assert r.status_code == 201, r.text
        existente = r.json()["id"]
    return {"dataset": conexion_archivos_etl, "transformacion": existente}


def test_avisa_si_la_transformacion_va_antes_de_su_carga(cliente, cab_admin, cadena):
    """
    El error frecuente: recalcular antes de cargar. Tal como está, el flujo
    trabajaría con los datos de ayer sin decirlo.
    """
    avisos = crear_flujo(cliente, cab_admin, {
        "nombre": "mal_ordenado",
        "pasos": [
            {"tipo": "transformacion", "id": cadena["transformacion"]},
            {"tipo": "carga", "id": cadena["dataset"]},
        ]})["avisos"]
    assert any("DESPUÉS" in a for a in avisos), avisos


def test_no_avisa_cuando_el_orden_es_correcto(cliente, cab_admin, cadena):
    f = crear_flujo(cliente, cab_admin, {
        "nombre": "bien_ordenado",
        "pasos": [
            {"tipo": "carga", "id": cadena["dataset"]},
            {"tipo": "transformacion", "id": cadena["transformacion"]},
        ]})
    assert f["avisos"] == []


def test_sugerir_orden_pone_la_carga_antes(cliente, cab_admin, cadena):
    """
    Pidiendo solo la transformación, la propuesta agrega la carga de lo que lee y
    la pone antes.
    """
    r = cliente.post("/api/flujos/sugerir-orden", headers=cab_admin, json={
        "nombre": "propuesta",
        "pasos": [{"tipo": "transformacion", "id": cadena["transformacion"]}]})
    assert r.status_code == 200, r.text
    pasos = r.json()["pasos"]
    assert [p["tipo"] for p in pasos] == ["carga", "transformacion"]
    assert pasos[0]["nombre"] == "ventas_csv_etl"
    assert r.json()["avisos"] == []


def test_avisa_si_lee_de_algo_que_el_flujo_no_actualiza(cliente, cab_admin, cadena):
    avisos = crear_flujo(cliente, cab_admin, {
        "nombre": "solo_transformacion",
        "pasos": [{"tipo": "transformacion", "id": cadena["transformacion"]}]})["avisos"]
    assert any("no actualiza" in a for a in avisos), avisos


def test_un_paso_repetido_se_rechaza(cliente, cab_admin, transformacion_flujo):
    r = cliente.post("/api/flujos", headers=cab_admin, json={
        "nombre": "repetido",
        "pasos": [
            {"tipo": "transformacion", "id": transformacion_flujo},
            {"tipo": "transformacion", "id": transformacion_flujo},
        ]})
    assert r.status_code == 422
    assert "repetido" in " ".join(r.json()["detail"]["errores"])


def test_un_paso_a_algo_inexistente_se_rechaza(cliente, cab_admin):
    r = cliente.post("/api/flujos", headers=cab_admin, json={
        "nombre": "fantasma",
        "pasos": [{"tipo": "carga", "id": 99999}]})
    assert r.status_code == 422
    assert "no existe" in " ".join(r.json()["detail"]["errores"])


def test_un_flujo_sin_pasos_se_rechaza(cliente, cab_admin):
    r = cliente.post("/api/flujos", headers=cab_admin, json={
        "nombre": "vacio", "pasos": []})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Programación
# --------------------------------------------------------------------------- #

def test_programar_un_flujo(cliente, cab_admin, flujo):
    r = cliente.put(f"/api/flujos/{flujo['id']}/programacion", headers=cab_admin,
                    json={"cron": "0 6 * * *"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["programacion_activa"] is True
    assert d["proxima_corrida"] is not None

    from app import programador

    assert programador.proxima_corrida_flujo(flujo["id"]) is not None


def test_el_cron_invalido_se_rechaza(cliente, cab_admin, flujo):
    r = cliente.put(f"/api/flujos/{flujo['id']}/programacion", headers=cab_admin,
                    json={"cron": "cada rato"})
    assert r.status_code == 422


def test_el_flujo_programado_deja_el_mismo_rastro(cliente, cab_admin, flujo):
    """
    Lo importante del diseño: el programador llama al mismo servicio que el botón.
    Lo único que cambia es quién lo disparó.
    """
    from app import programador

    cliente.put(f"/api/flujos/{flujo['id']}/programacion", headers=cab_admin,
                json={"cron": "0 6 * * *"})
    programador.correr_flujo(flujo["id"])

    h = cliente.get(f"/api/flujos/{flujo['id']}/historial", headers=cab_admin).json()
    ultima = h["ejecuciones"][0]
    assert ultima["estado"] == "exito"
    assert ultima["disparo"] == "programado"
    assert ultima["pasos"][0]["estado"] == "exito"


def test_un_flujo_en_pausa_no_corre(cliente, cab_admin, flujo):
    from app import programador

    cliente.put(f"/api/flujos/{flujo['id']}/programacion", headers=cab_admin,
                json={"cron": "0 6 * * *", "activa": False})
    antes = cliente.get(f"/api/flujos/{flujo['id']}/historial",
                        headers=cab_admin).json()["ejecuciones"]
    programador.correr_flujo(flujo["id"])
    despues = cliente.get(f"/api/flujos/{flujo['id']}/historial",
                          headers=cab_admin).json()["ejecuciones"]
    assert len(antes) == len(despues)


def test_un_fallo_no_apaga_el_programador(cliente, cab_admin):
    """Si la excepción escapara, APScheduler apagaría el trabajo en silencio."""
    from app import programador

    lista = cliente.get("/api/flujos", headers=cab_admin).json()
    id_ = next(f["id"] for f in lista if f["nombre"] == "con_fallo")
    cliente.put(f"/api/flujos/{id_}/programacion", headers=cab_admin,
                json={"cron": "0 6 * * *"})

    programador.correr_flujo(id_)          # no debe lanzar

    h = cliente.get(f"/api/flujos/{id_}/historial", headers=cab_admin).json()
    assert h["ejecuciones"][0]["estado"] == "error"


def test_borrar_el_flujo_quita_su_programacion(cliente, cab_admin,
                                               transformacion_flujo):
    from app import programador

    id_ = crear_flujo(cliente, cab_admin, {
        "nombre": "temporal",
        "pasos": [{"tipo": "transformacion", "id": transformacion_flujo}]})["id"]
    cliente.put(f"/api/flujos/{id_}/programacion", headers=cab_admin,
                json={"cron": "0 6 * * *"})
    assert cliente.delete(f"/api/flujos/{id_}", headers=cab_admin).status_code == 204
    assert programador.proxima_corrida_flujo(id_) is None


def test_el_lector_no_toca_los_flujos(cliente, cab_lector):
    assert cliente.get("/api/flujos", headers=cab_lector).status_code == 403
