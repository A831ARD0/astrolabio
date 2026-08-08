"""
Renombrar una transformación.

El nombre no es una etiqueta: es **el directorio del Parquet** y **el nombre con el
que otras la leen**. Por eso estaba bloqueado, y por eso desbloquearlo sin más habría
sido peor que dejarlo: el resultado quedaría huérfano en disco y las que lo usan
apuntando a algo que ya no está.

Lo que se protege aquí:

- que **los datos se muevan** con el nombre, no que se queden en la carpeta vieja;
- que las que la leen **sigan leyéndola**, y que se diga cuáles se tocaron;
- que el **alias** de un origen no se toque —es el nombre con el que la consulta la
  llama por dentro, y cambiarlo rompería el SQL que alguien escribió a mano—;
- que un nombre **ya usado** por otra transformación o por un dataset se rechace: los
  dos escribirían en el mismo sitio;
- que una **versión de modelo** que la nombre **detenga** el renombrado. Las versiones
  son instantáneas inmutables: un tablero anclado a una versión no puede cambiar de
  significado porque alguien renombró algo.
"""

import pytest

from app.materializar import ruta_salida


def crear(cliente, cab, nombre: str, lee_de: str | None = None) -> int:
    """Una transformación que lee de una tabla del motor, o de otra transformación."""
    lista = cliente.get("/api/transformaciones", headers=cab).json()
    ya = next((t for t in lista if t["nombre"] == nombre), None)
    if ya:
        return ya["id"]
    origen = ({"nombre": "fuente", "tipo": "dataset", "referencia": lee_de}
              if lee_de else
              {"nombre": "v", "tipo": "tabla", "referencia": "fact_venta"})
    r = cliente.post("/api/transformaciones", headers=cab, json={
        "definicion": {"nombre": nombre, "origenes": [origen], "pasos": []}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def catalogo(cliente, cab_admin, request):
    """
    Una transformación ya ejecutada —con datos en disco— y otra que la lee.

    Con nombres propios de cada prueba: la base de metadatos vive toda la corrida, y
    una prueba que renombra dejaría a la siguiente chocando con el nombre nuevo. Una
    prueba que falla según el orden es peor que una que falla.
    """
    marca = request.node.name.replace("test_", "")[:24]
    base, lee = f"cat_{marca}", f"lector_{marca}"
    id_ = crear(cliente, cab_admin, base)
    assert cliente.post(f"/api/transformaciones/{id_}/ejecutar",
                        headers=cab_admin).status_code == 200
    lector = crear(cliente, cab_admin, lee, lee_de=base)
    yield id_, lector, base, lee

    # Se limpia el disco: el directorio de datasets es real, no temporal, y una
    # carpeta olvidada hace que la MISMA prueba falle la segunda vez que se corre
    # —«ya existe la carpeta»—, que es la peor forma de fallar.
    from shutil import rmtree

    for nombre in (base, f"{base}_nuevo", lee):
        carpeta = ruta_salida(nombre)
        if carpeta.is_dir():
            rmtree(carpeta, ignore_errors=True)


# --------------------------------------------------------------------------- #

def test_renombrar_mueve_los_datos(cliente, cab_admin, catalogo):
    id_, _, base, _lee = catalogo
    assert ruta_salida(base).is_dir()

    r = cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                     json={"nombre": f"{base}_nuevo"})
    assert r.status_code == 200, r.text
    assert r.json()["datos_movidos"] is True

    assert ruta_salida(f"{base}_nuevo").is_dir()
    assert not ruta_salida(base).exists(), \
        "los datos se quedaron en la carpeta vieja"


def test_las_que_la_leen_siguen_leyendola(cliente, cab_admin, catalogo):
    id_, lector, base, lee = catalogo
    r = cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                     json={"nombre": f"{base}_nuevo"})
    assert r.status_code == 200, r.text
    assert r.json()["dependientes"] == [lee], \
        "no se dijo a quién se tocó"

    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    otra = next(t for t in lista if t["id"] == lector)
    origen = otra["definicion"]["origenes"][0]
    assert origen["referencia"] == f"{base}_nuevo"
    # El ALIAS no se toca: es como la llama la consulta por dentro.
    assert origen["nombre"] == "fuente"


def test_el_nombre_propio_de_la_definicion_tambien_cambia(cliente, cab_admin,
                                                          catalogo):
    """
    Si la definición guardada siguiera diciendo el nombre viejo, el siguiente
    «Guardar» desde la pantalla se rechazaría por intentar renombrar.
    """
    id_, _, base, _lee = catalogo
    cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                 json={"nombre": f"{base}_nuevo"})

    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    mia = next(t for t in lista if t["id"] == id_)
    assert mia["nombre"] == f"{base}_nuevo"
    assert mia["definicion"]["nombre"] == f"{base}_nuevo"

    r = cliente.put(f"/api/transformaciones/{id_}", headers=cab_admin,
                    json={"definicion": mia["definicion"]})
    assert r.status_code == 200, r.text


def test_un_nombre_ya_usado_se_rechaza(cliente, cab_admin, catalogo):
    id_, _, base, lee = catalogo
    r = cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                     json={"nombre": lee})
    assert r.status_code == 409, r.text
    assert "otra transformación" in r.json()["detail"]


def test_un_nombre_que_no_sirve_de_carpeta_se_rechaza(cliente, cab_admin, catalogo):
    id_, _, base, _lee = catalogo
    r = cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                     json={"nombre": "catálogo de ventas"})
    assert r.status_code == 409, r.text
    assert "carpeta" in r.json()["detail"]


def test_renombrar_al_mismo_nombre_no_hace_nada(cliente, cab_admin, catalogo):
    id_, _, base, _lee = catalogo
    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    actual = next(t for t in lista if t["id"] == id_)["nombre"]
    r = cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                     json={"nombre": actual})
    assert r.status_code == 200, r.text
    assert r.json()["cambiado"] is False


def test_la_etiqueta_del_paso_en_el_flujo_se_actualiza(cliente, cab_admin, catalogo):
    """
    El id no cambia, así que el flujo sigue corriendo igual. Lo que cambiaría es lo
    que se lee en su historial: un paso con el nombre de antes obliga a adivinar.
    """
    from tests.test_flujos import crear_flujo

    id_, _, base, _lee = catalogo
    f = crear_flujo(cliente, cab_admin, {
        "nombre": "flujo_del_catalogo",
        "pasos": [{"tipo": "transformacion", "id": id_}]})

    r = cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                     json={"nombre": f"{base}_nuevo"})
    assert r.status_code == 200, r.text
    assert r.json()["flujos_tocados"] >= 1

    lista = cliente.get("/api/flujos", headers=cab_admin).json()
    mio = next(x for x in lista if x["id"] == f["id"])
    assert mio["pasos"][0]["nombre"] == f"{base}_nuevo"


def test_una_version_de_modelo_que_la_nombra_detiene_el_renombrado(
        cliente, cab_admin, catalogo):
    """
    Las versiones del modelo son inmutables a propósito. Renombrar callando que una
    la nombra rompería un tablero publicado, así que se para, se dice qué modelo es y
    se ofrece la salida: sacar la entidad, o crear otra transformación.

    La versión se inserta aquí y no se monta un modelo entero: lo que se comprueba es
    la decisión —hay un YAML que nombra la tabla, no se renombra—, y montar el modelo
    completo probaría el modelo, no esto.
    """
    from app.db import CrearSesion
    from app.modelos_db import Modelo, VersionModelo

    id_, _, base, _lee = catalogo
    with CrearSesion() as sesion:
        m = Modelo(nombre=f"modelo_{base}")
        sesion.add(m)
        sesion.flush()
        sesion.add(VersionModelo(
            modelo_id=m.id, version=1,
            yaml=f"entidades:\n  - nombre: x\n    origen:\n      tabla: {base}\n"))
        sesion.commit()

    r = cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                     json={"nombre": f"{base}_nuevo"})
    assert r.status_code == 409, r.text
    assert f"modelo_{base}" in r.json()["detail"]
    assert "no se reescriben" in r.json()["detail"]
    # Y no se movió nada: si el renombrado se para, se para antes de tocar el disco.
    assert ruta_salida(base).is_dir()
    assert not ruta_salida(f"{base}_nuevo").exists()


def test_los_datos_no_se_mueven_encima_de_una_carpeta_que_ya_esta(
        cliente, cab_admin, catalogo):
    """
    Una carpeta suelta en disco sin nada registrado con ese nombre. Moverse encima
    perdería lo que tenga, así que se para y se dice.
    """
    id_, _, base, _lee = catalogo
    huerfana = ruta_salida("catalogo_huerfano")
    huerfana.mkdir(parents=True, exist_ok=True)
    try:
        r = cliente.post(f"/api/transformaciones/{id_}/renombrar", headers=cab_admin,
                         json={"nombre": "catalogo_huerfano"})
        assert r.status_code == 409, r.text
        assert "ya existe la carpeta" in r.json()["detail"]
    finally:
        huerfana.rmdir()
