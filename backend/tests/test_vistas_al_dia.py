"""
Que una transformacion vuelva a correr y el catalogo lo note.

Los datasets y los resultados viven en Parquet, y para poder consultarlos como
tabla se les pone una vista temporal encima. Esa vista se recuerda POR HILO para
no volver a crearla en cada consulta — y ese recuerdo era el problema: se daba por
buena para siempre.

El caso real: una transformacion devolvia `fecha_factura` como texto, se le
anadio un `cast(... as date)` y se volvio a ejecutar. La vista seguia declarando
VARCHAR, asi que:

  - el catalogo contestaba 500 con «Contents of view were altered: types don't
    match! Expected [VARCHAR], but found [DATE]», y
  - el modelo seguia diciendo que la columna era texto, con todo lo que eso
    arrastra: el aviso de tipos que no casan al unir con el calendario y las
    funciones de fecha que no se ofrecen en las formulas.

Duraba hasta reiniciar el proceso. Sin error visible en el sitio donde se causo.
"""

import pytest


@pytest.fixture
def transformacion(cliente, cab_admin):
    """Una transformacion SQL que se pueda reescribir a voluntad."""
    creadas = []

    def _crear(sql: str) -> int:
        r = cliente.post("/api/transformaciones", headers=cab_admin, json={
            "definicion": {"nombre": "prueba_tipos", "origenes": [],
                           "pasos": [], "sql": sql},
        })
        assert r.status_code == 201, r.text
        creadas.append(r.json()["id"])
        return r.json()["id"]

    yield _crear

    for id_ in creadas:
        cliente.delete(f"/api/transformaciones/{id_}", headers=cab_admin)


def _tipos(cliente, cab) -> dict[str, str]:
    r = cliente.get("/api/catalogo/tablas/prueba_tipos", headers=cab)
    assert r.status_code == 200, r.text
    return {c["nombre"]: c["tipo"] for c in r.json()["columnas"]}


def test_el_catalogo_ve_el_tipo_nuevo_sin_reiniciar(cliente, cab_admin, transformacion):
    """
    Lo que el usuario hace: cast, volver a ejecutar, mirar. Las tres cosas en la
    misma sesion del proceso, que es donde fallaba.
    """
    id_ = transformacion("SELECT '2026-01-05' AS fecha_factura, 100.0 AS importe")
    assert cliente.post(f"/api/transformaciones/{id_}/ejecutar",
                        headers=cab_admin).status_code == 200
    # Se mira ANTES de cambiar: es lo que crea la vista con el tipo viejo, y sin
    # esa mirada previa el fallo no se reproduce.
    assert _tipos(cliente, cab_admin)["fecha_factura"] == "texto"

    cliente.put(f"/api/transformaciones/{id_}", headers=cab_admin, json={
        "definicion": {"nombre": "prueba_tipos", "origenes": [], "pasos": [],
                       "sql": "SELECT cast('2026-01-05' AS DATE) AS fecha_factura, "
                              "100.0 AS importe"},
    })
    assert cliente.post(f"/api/transformaciones/{id_}/ejecutar",
                        headers=cab_admin).status_code == 200

    assert _tipos(cliente, cab_admin)["fecha_factura"] == "fecha"


def test_una_columna_nueva_aparece_al_volver_a_ejecutar(cliente, cab_admin,
                                                        transformacion):
    """No solo el tipo: la lista de columnas tambien se quedaba congelada."""
    id_ = transformacion("SELECT 1 AS a")
    cliente.post(f"/api/transformaciones/{id_}/ejecutar", headers=cab_admin)
    assert set(_tipos(cliente, cab_admin)) == {"a"}

    cliente.put(f"/api/transformaciones/{id_}", headers=cab_admin, json={
        "definicion": {"nombre": "prueba_tipos", "origenes": [], "pasos": [],
                       "sql": "SELECT 1 AS a, 'x' AS b"},
    })
    cliente.post(f"/api/transformaciones/{id_}/ejecutar", headers=cab_admin)

    assert set(_tipos(cliente, cab_admin)) == {"a", "b"}


def test_consultar_despues_del_cambio_no_revienta(cliente, cab_admin, transformacion):
    """
    La otra cara: no basta con que el catalogo lo cuente bien, la consulta tiene
    que poder ejecutarse. Era un 500 del motor, no un aviso.
    """
    from app.analitico import conexion, registrar_vistas

    id_ = transformacion("SELECT '2026-01-05' AS f")
    cliente.post(f"/api/transformaciones/{id_}/ejecutar", headers=cab_admin)
    registrar_vistas(["prueba_tipos"])
    conexion().execute("SELECT * FROM prueba_tipos").fetchall()

    cliente.put(f"/api/transformaciones/{id_}", headers=cab_admin, json={
        "definicion": {"nombre": "prueba_tipos", "origenes": [], "pasos": [],
                       "sql": "SELECT cast('2026-01-05' AS DATE) AS f"},
    })
    cliente.post(f"/api/transformaciones/{id_}/ejecutar", headers=cab_admin)

    registrar_vistas(["prueba_tipos"])
    filas = conexion().execute("SELECT * FROM prueba_tipos").fetchall()
    assert len(filas) == 1
