"""
Proyectos con secciones: el script con secciones del editor de carga.

Lo que se protege aquí es lo que de verdad puede romper:

- que **un tramo corra solo el tramo**. «Ejecutar desde la sección 12» es la razón
  de ser de todo esto: si en el camino se cuela una corrida completa, alguien
  espera veinte minutos por nada, y si se cuela al revés —corre menos de lo
  pedido— trabaja con datos viejos sin saberlo.
- que un tramo **no se pueda leer como si el proyecto entero estuviera al día**.
  Tres secciones en verde de dieciocho es exactamente la clase de pantalla que
  hace decidir con un número que no se recalculó.
- que una sección **no pueda vivir en dos proyectos**. El orden que se ve dejaría
  de ser el orden que corre, que es lo único que un proyecto tiene que garantizar.
- que las **intermedias** no ensucien la lista de orígenes de los demás, y que sí
  se ofrezcan dentro de su propio proyecto: si tampoco ahí, no se pueden encadenar.
- que borrar el proyecto **no se lleve los resultados**, y que borrar una sección
  no deje el proyecto con un paso que apunta a nada.
"""

import pytest

from app import trabajos


def crear_transformacion(cliente, cab, nombre: str, **extra) -> int:
    """Una transformación que lee de una tabla del motor, sin depender de cargas."""
    lista = cliente.get("/api/transformaciones", headers=cab).json()
    ya = next((t for t in lista if t["nombre"] == nombre), None)
    if ya:
        return ya["id"]
    r = cliente.post("/api/transformaciones", headers=cab, json={
        "definicion": {
            "nombre": nombre,
            "origenes": [{"nombre": "v", "tipo": "tabla",
                          "referencia": "fact_venta"}],
            "pasos": [{"tipo": "agrupar", "por": ["sucursal_id"], "agregados": [
                {"nombre": "n", "funcion": "cuenta", "campo": None}]}],
        },
        **extra,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def proyecto(cliente, cab_admin):
    r = cliente.post("/api/proyectos", headers=cab_admin,
                     json={"nombre": "proy_comercial",
                           "descripcion": "Ventas y servicio"})
    if r.status_code == 409:
        lista = cliente.get("/api/proyectos", headers=cab_admin).json()
        return next(p for p in lista if p["nombre"] == "proy_comercial")
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def tres_secciones(cliente, cab_admin, proyecto):
    """Un proyecto con tres secciones en orden."""
    ids = [crear_transformacion(cliente, cab_admin, f"seccion_{n}")
           for n in ("uno", "dos", "tres")]
    r = cliente.put(f"/api/proyectos/{proyecto['id']}", headers=cab_admin,
                    json={"nombre": proyecto["nombre"], "secciones": ids})
    assert r.status_code == 200, r.text
    return proyecto, ids


# --------------------------------------------------------------------------- #
# Secciones: orden y pertenencia
# --------------------------------------------------------------------------- #

def test_proyecto_nace_vacio(cliente, cab_admin, proyecto):
    """
    Un proyecto sin secciones es un estado normal: se crea y luego se le llena.

    Un flujo vacío no lo es —se guardaría algo que no hace nada y que de madrugada
    parece que corrió—, así que la misma validación tiene que contestar distinto.
    """
    assert proyecto["secciones"] == []


def test_las_secciones_conservan_el_orden(cliente, cab_admin, tres_secciones):
    p, ids = tres_secciones
    salida = cliente.get("/api/proyectos", headers=cab_admin).json()
    mio = next(x for x in salida if x["id"] == p["id"])
    assert [s["id"] for s in mio["secciones"]] == ids
    assert [s["orden"] for s in mio["secciones"]] == [1, 2, 3]


def test_reordenar_cambia_el_orden_de_corrida(cliente, cab_admin, tres_secciones):
    p, ids = tres_secciones
    r = cliente.put(f"/api/proyectos/{p['id']}", headers=cab_admin,
                    json={"nombre": p["nombre"],
                          "secciones": [ids[2], ids[0], ids[1]]})
    assert r.status_code == 200, r.text
    assert [s["id"] for s in r.json()["secciones"]] == [ids[2], ids[0], ids[1]]


def test_una_seccion_no_puede_estar_en_dos_proyectos(cliente, cab_admin,
                                                     tres_secciones):
    p, ids = tres_secciones
    otro = cliente.post("/api/proyectos", headers=cab_admin,
                        json={"nombre": "proy_otro"})
    assert otro.status_code == 201, otro.text
    r = cliente.post(f"/api/proyectos/{otro.json()['id']}/secciones/{ids[0]}",
                     headers=cab_admin)
    assert r.status_code == 422, r.text
    assert "proy_comercial" in str(r.json()["detail"])


def test_una_seccion_no_puede_estar_dos_veces(cliente, cab_admin, tres_secciones):
    p, ids = tres_secciones
    r = cliente.put(f"/api/proyectos/{p['id']}", headers=cab_admin,
                    json={"nombre": p["nombre"], "secciones": [ids[0], ids[0]]})
    assert r.status_code == 422, r.text


def test_un_proyecto_solo_lleva_transformaciones(cliente, cab_admin, proyecto):
    """
    Una extracción en un proyecto lo convertiría otra vez en un flujo, y el panel
    de secciones tendría que explicar por qué la sección 3 no es una sección.
    """
    from app.flujos import revisar_pasos
    from app.db import CrearSesion

    with CrearSesion() as sesion:
        errores = revisar_pasos(sesion, [{"tipo": "carga", "id": 1}],
                                proyecto["id"], es_proyecto=True)
    assert errores and "solo lleva transformaciones" in errores[0]


def test_quitar_una_seccion_no_la_borra(cliente, cab_admin, tres_secciones):
    p, ids = tres_secciones
    r = cliente.delete(f"/api/proyectos/{p['id']}/secciones/{ids[1]}",
                       headers=cab_admin)
    assert r.status_code == 200, r.text
    assert [s["id"] for s in r.json()["secciones"]] == [ids[0], ids[2]]

    # Sigue existiendo, ahora suelta: sacar algo de una carpeta no es tirarlo.
    sueltas = cliente.get("/api/proyectos/sueltas", headers=cab_admin).json()
    assert ids[1] in [t["id"] for t in sueltas["transformaciones"]]


def test_borrar_una_seccion_la_saca_del_proyecto(cliente, cab_admin,
                                                 tres_secciones):
    """
    Sin esto el proyecto queda con un paso que apunta a nada: la pantalla lo diría
    como huérfano, pero al guardar cualquier otro cambio la validación lo
    rechazaría y no habría forma de arreglarlo desde ahí.
    """
    p, ids = tres_secciones
    suelta = crear_transformacion(cliente, cab_admin, "seccion_efimera")
    cliente.post(f"/api/proyectos/{p['id']}/secciones/{suelta}", headers=cab_admin)

    r = cliente.delete(f"/api/transformaciones/{suelta}", headers=cab_admin)
    assert r.status_code == 204, r.text

    despues = cliente.get("/api/proyectos", headers=cab_admin).json()
    mio = next(x for x in despues if x["id"] == p["id"])
    assert suelta not in [s["id"] for s in mio["secciones"]]
    assert mio["huerfanas"] == []

    # Y el proyecto sigue guardándose sin pelear con un paso fantasma.
    assert cliente.put(f"/api/proyectos/{p['id']}", headers=cab_admin,
                       json={"nombre": p["nombre"]}).status_code == 200


def test_borrar_el_proyecto_deja_las_secciones(cliente, cab_admin, tres_secciones):
    p, ids = tres_secciones
    assert cliente.delete(f"/api/proyectos/{p['id']}",
                          headers=cab_admin).status_code == 204
    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    quedan = {t["id"] for t in lista}
    assert set(ids) <= quedan, "borrar el contenedor se llevó los resultados"


# --------------------------------------------------------------------------- #
# Intermedias
# --------------------------------------------------------------------------- #

def test_una_intermedia_no_se_ofrece_fuera_de_su_proyecto(cliente, cab_admin,
                                                          proyecto):
    """
    Andamiaje: un mapeo de códigos o una tabla de series existe para que otra
    sección lo use. Con dieciocho por sucursal, ofrecerlo a todo el mundo hace la
    lista inservible por volumen.
    """
    andamio = crear_transformacion(cliente, cab_admin, "seccion_andamio",
                                   intermedia=True, proyecto_id=proyecto["id"])

    fuera = cliente.get("/api/transformaciones/origenes", headers=cab_admin).json()
    assert "seccion_andamio" not in [t["nombre"] for t in fuera["transformaciones"]]

    dentro = cliente.get(
        f"/api/transformaciones/origenes?proyecto_id={proyecto['id']}",
        headers=cab_admin).json()
    mio = next(t for t in dentro["transformaciones"]
               if t["nombre"] == "seccion_andamio")
    assert mio["intermedia"] is True
    assert mio["seccion"] == 1, "sin el número de sección no se puede encadenar"
    assert andamio


def test_marcar_intermedia_se_guarda(cliente, cab_admin):
    id_ = crear_transformacion(cliente, cab_admin, "seccion_marcable")
    actual = cliente.get("/api/transformaciones", headers=cab_admin).json()
    definicion = next(t for t in actual if t["id"] == id_)["definicion"]

    r = cliente.put(f"/api/transformaciones/{id_}", headers=cab_admin,
                    json={"definicion": definicion, "intermedia": True})
    assert r.status_code == 200, r.text
    assert r.json()["intermedia"] is True


def test_la_transformacion_dice_de_que_proyecto_es(cliente, cab_admin,
                                                   tres_secciones):
    p, ids = tres_secciones
    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    segunda = next(t for t in lista if t["id"] == ids[1])
    assert segunda["proyecto"] == p["nombre"]
    assert segunda["orden"] == 2


# --------------------------------------------------------------------------- #
# Ejecutar un tramo
# --------------------------------------------------------------------------- #

def correr(cliente, cab, id_: int, **params) -> dict:
    """Lanza y espera. La corrida va en segundo plano: el resultado está en el historial."""
    r = cliente.post(f"/api/flujos/{id_}/ejecutar", headers=cab, params=params)
    assert r.status_code == 202, r.text
    assert trabajos.esperar(60), "el trabajo no termino a tiempo"
    h = cliente.get(f"/api/flujos/{id_}/historial", headers=cab).json()
    assert h["ejecuciones"], "la corrida no dejo historial"
    return h["ejecuciones"][0]


def test_un_tramo_corre_solo_el_tramo(cliente, cab_admin, tres_secciones):
    p, ids = tres_secciones
    ejec = correr(cliente, cab_admin, p["id"], desde_paso=2)

    estados = [x["estado"] for x in ejec["pasos"]]
    assert estados == ["no_pedido", "exito", "exito"], ejec["pasos"]


def test_no_pedido_no_es_omitido_ni_exito(cliente, cab_admin, tres_secciones):
    """
    Los tres significan cosas distintas y el historial tiene que poder decir cuál
    fue: `omitido` es «no se intentó porque algo falló antes», `exito` es «corrió»,
    y `no_pedido` es «no se le pidió que corriera».
    """
    p, ids = tres_secciones
    ejec = correr(cliente, cab_admin, p["id"], desde_paso=3)
    primeros = [x for x in ejec["pasos"] if x["paso"] in (1, 2)]
    assert all(x["estado"] == "no_pedido" for x in primeros)
    assert all("filas" not in x for x in primeros), \
        "un paso que no corrió no puede traer filas"


def test_el_tramo_queda_marcado_en_el_historial(cliente, cab_admin,
                                                tres_secciones):
    """Un tramo verde no se puede leer como «el proyecto entero está al día»."""
    p, ids = tres_secciones
    ejec = correr(cliente, cab_admin, p["id"], desde_paso=2)
    assert ejec["desde_paso"] == 2
    assert ejec["estado"] == "exito"

    completa = correr(cliente, cab_admin, p["id"])
    assert completa["desde_paso"] is None


def test_un_tramo_fuera_de_rango_no_se_lanza(cliente, cab_admin, tres_secciones):
    p, ids = tres_secciones
    r = cliente.post(f"/api/flujos/{p['id']}/ejecutar", headers=cab_admin,
                     params={"desde_paso": 9})
    assert r.status_code == 422, r.text
    assert "solo hay 3" in str(r.json()["detail"])


def test_un_tramo_no_dispara_el_correo_de_recuperado(cliente, cab_admin,
                                                     tres_secciones, monkeypatch):
    """
    Un tramo que sale bien no prueba que el proyecto se arregló: los pasos que
    fallaban pueden ser justo los que no se pidieron. Decir «recuperado» ahí cierra
    el asunto en la cabeza de quien lo lee.
    """
    from app import avisos, flujos
    from app.db import CrearSesion
    from app.modelos_db import EstadoCarga, Flujo, FlujoEjecucion

    p, ids = tres_secciones
    # Una corrida fallida anterior, para que la siguiente cuente como recuperación.
    with CrearSesion() as sesion:
        f = sesion.get(Flujo, p["id"])
        sesion.add(FlujoEjecucion(flujo_id=f.id, estado=EstadoCarga.error,
                                  origen="manual", mensaje="falló antes",
                                  detalle={"pasos": [], "total": 3}))
        sesion.commit()

    llamadas = []
    monkeypatch.setattr(avisos, "por_flujo_recuperado",
                        lambda *a, **k: llamadas.append(a))
    monkeypatch.setattr(flujos.avisos, "por_flujo_recuperado",
                        lambda *a, **k: llamadas.append(a))

    correr(cliente, cab_admin, p["id"], desde_paso=2)
    assert not llamadas, "un tramo se anunció como flujo recuperado"


def test_un_proyecto_sale_marcado_en_la_lista_de_flujos(cliente, cab_admin,
                                                        proyecto):
    """
    Comparte tabla con los flujos porque comparte ejecución. Va marcado y no
    escondido: la pantalla de flujos lo saca de su lista, pero la de tareas tiene
    que verlo, porque tiene horario y corre de madrugada como todo lo demás.
    """
    lista = cliente.get("/api/flujos", headers=cab_admin).json()
    mio = next(f for f in lista if f["id"] == proyecto["id"])
    assert mio["es_proyecto"] is True
    assert all(f["es_proyecto"] is False for f in lista if f["id"] != proyecto["id"]
               and f["nombre"] not in ("proy_otro",))
