"""
Un flujo como paso de otro: encadenar sin horarios.

Con cuarenta sucursales, «que la siguiente empiece cuando la anterior termine» no
se puede escribir con horas: no se sabe cuánto tarda cada una, y poner cuarenta
crones a las seis de la mañana no las pone en fila —las pone a pelearse por el
mismo Pervasive—. Un flujo maestro que llame a los cuarenta sí lo dice exacto.

Lo que se protege aquí es lo que puede romper de verdad:

- que la cadena corra **en orden** y deje su propio historial en cada eslabón;
- que un fallo dentro pare al maestro, que para eso está la regla de detenerse;
- que un **ciclo** no se pueda ni guardar. «A llama a B, B llama a A» no da un
  error visible: da un servidor dando vueltas de madrugada sin nadie mirando.
"""

import pytest

from tests.test_flujos import correr, crear_flujo


@pytest.fixture
def dos_transformaciones(cliente, cab_admin):
    """Dos transformaciones independientes, para poder ver el orden."""
    salida = []
    for nombre in ("eslabon_uno", "eslabon_dos"):
        lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
        ya = next((t for t in lista if t["nombre"] == nombre), None)
        if ya:
            salida.append(ya["id"])
            continue
        r = cliente.post("/api/transformaciones", headers=cab_admin, json={
            "definicion": {
                "nombre": nombre,
                "origenes": [{"nombre": "v", "tipo": "tabla",
                              "referencia": "fact_venta"}],
                "pasos": [{"tipo": "agrupar", "por": ["sucursal_id"], "agregados": [
                    {"nombre": "n", "funcion": "cuenta", "campo": None}]}],
            }})
        assert r.status_code == 201, r.text
        salida.append(r.json()["id"])
    return salida


@pytest.fixture
def cadena(cliente, cab_admin, dos_transformaciones):
    """Dos flujos hijos y un maestro que los llama en orden."""
    uno, dos = dos_transformaciones
    a = crear_flujo(cliente, cab_admin, {
        "nombre": "hijo_a", "pasos": [{"tipo": "transformacion", "id": uno}]})
    b = crear_flujo(cliente, cab_admin, {
        "nombre": "hijo_b", "pasos": [{"tipo": "transformacion", "id": dos}]})
    maestro = crear_flujo(cliente, cab_admin, {
        "nombre": "maestro",
        "pasos": [{"tipo": "flujo", "id": a["id"]},
                  {"tipo": "flujo", "id": b["id"]}]})
    return a, b, maestro


# --------------------------------------------------------------------------- #
# Que corra en orden, y que cada eslabón cuente lo suyo
# --------------------------------------------------------------------------- #

def test_el_maestro_corre_los_hijos_en_orden(cliente, cab_admin, cadena):
    a, b, maestro = cadena
    ultima = correr(cliente, cab_admin, maestro["id"])

    assert ultima["estado"] == "exito"
    assert [p["nombre"] for p in ultima["pasos"]] == ["hijo_a", "hijo_b"]
    assert all(p["tipo"] == "flujo" for p in ultima["pasos"])
    # El resumen del paso dice cuántos pasos traía dentro: es lo que distingue
    # «corrió el hijo» de «corrió el hijo y no hizo nada».
    assert all(p["sub_pasos"] == 1 for p in ultima["pasos"])


def test_cada_hijo_deja_su_propio_historial(cliente, cab_admin, cadena):
    """
    El detalle de por qué falló un hijo está en el hijo, no en el maestro. Con
    veintiocho tablas por sucursal, meterlo todo en el maestro daría un renglón
    ilegible; separado, «abrir el que salió rojo» lleva justo al paso que falló.
    """
    a, b, maestro = cadena
    correr(cliente, cab_admin, maestro["id"])

    for hijo in (a, b):
        h = cliente.get(f"/api/flujos/{hijo['id']}/historial",
                        headers=cab_admin).json()
        assert h["ejecuciones"], f"'{hijo['nombre']}' no dejó historial propio"
        assert h["ejecuciones"][0]["estado"] == "exito"


def test_un_hijo_que_falla_detiene_al_maestro(cliente, cab_admin,
                                              dos_transformaciones):
    uno, _ = dos_transformaciones
    roto = crear_flujo(cliente, cab_admin, {
        "nombre": "hijo_roto",
        # Un dataset que no existe: el hijo falla y el maestro tiene que enterarse.
        "pasos": [{"tipo": "transformacion", "id": uno}]})
    bueno = crear_flujo(cliente, cab_admin, {
        "nombre": "hijo_despues",
        "pasos": [{"tipo": "transformacion", "id": uno}]})

    # Se rompe el hijo por debajo, después de guardarlo: apuntar a un id
    # inexistente no se puede guardar por la API, y es justo lo que se quiere
    # probar —que entre guardar y correr las cosas cambian—.
    from app.db import CrearSesion
    from app.modelos_db import Flujo

    with CrearSesion() as s:
        f = s.get(Flujo, roto["id"])
        f.pasos = [{"tipo": "transformacion", "id": 999999, "nombre": "fantasma"}]
        s.commit()

    maestro = crear_flujo(cliente, cab_admin, {
        "nombre": "maestro_con_fallo",
        "al_fallar": "detener",
        "pasos": [{"tipo": "flujo", "id": roto["id"]},
                  {"tipo": "flujo", "id": bueno["id"]}]})

    ultima = correr(cliente, cab_admin, maestro["id"])
    assert ultima["estado"] == "error"
    assert ultima["pasos"][0]["estado"] == "error"
    assert ultima["pasos"][1]["estado"] == "omitido"
    assert "hijo_roto" in (ultima["mensaje"] or "")

    # Y el que iba después no corrió: eso es lo que significa detenerse.
    h = cliente.get(f"/api/flujos/{bueno['id']}/historial",
                    headers=cab_admin).json()
    assert h["ejecuciones"] == []


# --------------------------------------------------------------------------- #
# Lo que no se puede guardar
# --------------------------------------------------------------------------- #

def test_un_flujo_no_puede_llamarse_a_si_mismo(cliente, cab_admin,
                                               dos_transformaciones):
    uno, _ = dos_transformaciones
    f = crear_flujo(cliente, cab_admin, {
        "nombre": "el_narciso", "pasos": [{"tipo": "transformacion", "id": uno}]})

    r = cliente.put(f"/api/flujos/{f['id']}", headers=cab_admin, json={
        "nombre": "el_narciso", "pasos": [{"tipo": "flujo", "id": f["id"]}]})
    assert r.status_code == 422
    assert "sí mismo" in str(r.json()["detail"])


def test_un_ciclo_indirecto_tampoco(cliente, cab_admin, cadena):
    """A → B ya está; intentar B → A tiene que rebotar al guardar."""
    a, b, maestro = cadena
    # maestro llama a A y a B. Que A llame al maestro cierra el ciclo.
    r = cliente.put(f"/api/flujos/{a['id']}", headers=cab_admin, json={
        "nombre": "hijo_a", "pasos": [{"tipo": "flujo", "id": maestro["id"]}]})
    assert r.status_code == 422
    assert "vuelve a este flujo" in str(r.json()["detail"])


def test_el_flujo_que_no_existe_no_se_puede_encadenar(cliente, cab_admin):
    r = cliente.post("/api/flujos", headers=cab_admin, json={
        "nombre": "apunta_al_vacio", "pasos": [{"tipo": "flujo", "id": 999999}]})
    assert r.status_code == 422
    assert "ya no existe" in str(r.json()["detail"])


def test_un_ciclo_que_se_cuela_se_corta_al_correr(cliente, cab_admin, cadena):
    """
    La comprobación al guardar es la buena; esta es la red.

    Entre guardar y correr pueden pasar semanas y dos ediciones —o una escritura
    directa en la base, como aquí—. Si un ciclo llega a la madrugada, tiene que
    morir con un error en el historial, no con el servidor sin pila.
    """
    a, _, maestro = cadena
    from app.db import CrearSesion
    from app.modelos_db import Flujo

    with CrearSesion() as s:
        f = s.get(Flujo, a["id"])
        f.pasos = [{"tipo": "flujo", "id": maestro["id"], "nombre": "maestro"}]
        s.commit()

    ultima = correr(cliente, cab_admin, maestro["id"])
    assert ultima["estado"] == "error"
    assert "vuelve a un flujo que ya está corriendo" in (ultima["mensaje"] or "")


# --------------------------------------------------------------------------- #
# Lo que la pantalla necesita
# --------------------------------------------------------------------------- #

def test_los_flujos_salen_entre_lo_que_se_puede_encadenar(cliente, cab_admin,
                                                          cadena):
    a, _, _ = cadena
    d = cliente.get("/api/flujos/disponibles", headers=cab_admin).json()
    assert any(f["id"] == a["id"] and f["pasos"] == 1 for f in d["flujos"])


def test_ordenar_solo_no_se_come_los_flujos(cliente, cab_admin, cadena):
    """
    «Ordenar solo» reordena por linaje, y de un flujo no puede saber qué trae
    dentro sin abrirlo. Antes esto devolvía la lista sin los pasos de tipo flujo
    —los borraba en silencio—. Ahora la deja igual y lo dice.
    """
    a, b, maestro = cadena
    r = cliente.post("/api/flujos/sugerir-orden", headers=cab_admin, json={
        "nombre": "maestro", "al_fallar": "detener", "reintentos": 0,
        "espera_reintento_seg": 60,
        "pasos": [{"tipo": "flujo", "id": a["id"]},
                  {"tipo": "flujo", "id": b["id"]}]})
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()["pasos"]] == [a["id"], b["id"]]
    assert any("no se reordenan" in x for x in r.json()["avisos"])


# --------------------------------------------------------------------------- #
# Rastrear quién disparó qué
# --------------------------------------------------------------------------- #

def test_el_hijo_sabe_quien_lo_llama(cliente, cab_admin, cadena):
    """
    Sin esto, la pantalla de tareas decía «a mano» de los treinta y ocho
    extractores. Es falso —los llama el maestro cada noche— y hace imposible ver
    si una sucursal se quedó fuera de la cadena o corre y nadie lo sabe.
    """
    a, b, maestro = cadena
    lista = cliente.get("/api/flujos", headers=cab_admin).json()
    por_id = {f["id"]: f for f in lista}

    assert por_id[a["id"]]["llamado_por"] == ["maestro"]
    assert por_id[b["id"]]["llamado_por"] == ["maestro"]
    # Al maestro no lo llama nadie: es la raíz.
    assert por_id[maestro["id"]]["llamado_por"] == []


def test_la_corrida_del_hijo_dice_desde_donde(cliente, cab_admin, cadena):
    a, _, maestro = cadena
    correr(cliente, cab_admin, maestro["id"])

    hijo = cliente.get(f"/api/flujos/{a['id']}/historial",
                       headers=cab_admin).json()["ejecuciones"][0]
    assert hijo["disparo"] == "flujo"
    assert hijo["llamado_por"] == "maestro"

    # Y el maestro, que sí lo lanzó una persona, sigue diciendo «manual».
    arriba = cliente.get(f"/api/flujos/{maestro['id']}/historial",
                         headers=cab_admin).json()["ejecuciones"][0]
    assert arriba["disparo"] == "manual"
    assert arriba["llamado_por"] is None
