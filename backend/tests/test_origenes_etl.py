"""
El panel de origenes del ETL.

Es la lista de la que se parte para transformar cualquier cosa, y su modo de
fallar es traicionero: los bloques se calculan por separado para que un dataset
con un nombre raro no tumbe la lista entera, asi que cuando uno de ellos revienta
la peticion sigue contestando 200 y la pantalla se queda con media lista. Solo el
aviso lo delata.

Por eso se prueba aqui que `avisos` venga VACIO, y no solo que la peticion
conteste. La version anterior le pasaba el usuario a la funcion del catalogo
donde va la sesion —`tablas_catalogo(_)`— y el bloque del motor caia siempre con
«'Usuario' object has no attribute 'scalars'»: nada rojo, ningun 500, y las
tablas del motor simplemente no estaban.
"""


def test_las_tablas_del_motor_salen_en_la_lista(cliente, cab_admin):
    r = cliente.get("/api/transformaciones/origenes", headers=cab_admin)
    assert r.status_code == 200
    cuerpo = r.json()

    # Lo importante: ningun bloque se cayo por el camino.
    assert cuerpo["avisos"] == []
    # Y el del motor trajo algo. El modelo de demostracion carga sus tablas, asi
    # que una lista vacia aqui significa que el bloque fallo en silencio.
    assert len(cuerpo["tablas"]) > 0


def test_ningun_aviso_menciona_un_fallo_de_programacion(cliente, cab_admin):
    """
    Los avisos son para lo que el usuario puede arreglar —un nombre de dataset
    que no sirve como ruta—, no para errores nuestros. Un `AttributeError`
    llegando a la pantalla no es un aviso: es un fallo disfrazado de aviso.
    """
    avisos = cliente.get("/api/transformaciones/origenes",
                         headers=cab_admin).json()["avisos"]
    for a in avisos:
        assert "has no attribute" not in a, a
        assert "object is not" not in a, a
