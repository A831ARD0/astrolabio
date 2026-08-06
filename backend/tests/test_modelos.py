"""Modelo semantico via API: versionado inmutable, diagnostico, consultas."""


def test_diagnostico_reporta_los_problemas_reales(cliente, cab_admin, modelo_id):
    r = cliente.get(f"/api/modelos/{modelo_id}/diagnostico", headers=cab_admin)
    assert r.status_code == 200, r.text
    problemas = r.json()["problemas"]
    tipos = {p["tipo"] for p in problemas}
    assert "tabla_huerfana" in tipos
    assert "ruta_ambigua" in tipos
    # Sin falsas alarmas: los hechos son terminales, no puentes.
    assert len(problemas) == 4, [p["entidad"] for p in problemas]


def test_catalogo_de_campos(cliente, cab_admin, modelo_id):
    r = cliente.get(f"/api/modelos/{modelo_id}/campos", headers=cab_admin)
    assert r.status_code == 200
    d = r.json()
    claves = {m["clave"] for m in d["metricas"]}
    assert {"monto_venta", "monto_utilidad", "objetivo_unidades"} <= claves
    # nombre_conexion esta marcado visible:false y no debe salir.
    dims = {x["clave"] for x in d["dimensiones"]}
    assert "cat_sucursal.nombre_conexion" not in dims


def test_version_nueva_no_sobreescribe(cliente, cab_editor, modelo_id, yaml_modelo):
    antes = next(m for m in cliente.get("/api/modelos", headers=cab_editor).json()
                 if m["id"] == modelo_id)["version_actual"]
    r = cliente.post(f"/api/modelos/{modelo_id}/versiones", headers=cab_editor,
                     json={"yaml": yaml_modelo, "notas": "sin cambios reales"})
    assert r.status_code == 201, r.text
    assert r.json()["version"] == antes + 1


def test_lector_no_puede_crear_versiones(cliente, cab_lector, modelo_id, yaml_modelo):
    r = cliente.post(f"/api/modelos/{modelo_id}/versiones", headers=cab_lector,
                     json={"yaml": yaml_modelo})
    assert r.status_code == 403


def test_yaml_invalido_se_rechaza(cliente, cab_editor, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/versiones", headers=cab_editor,
                     json={"yaml": "esto: [no es un modelo"})
    assert r.status_code == 422


def test_ambiguedad_devuelve_422_con_las_rutas(cliente, cab_editor, modelo_id):
    """El usuario debe recibir las opciones, no un numero adivinado."""
    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_editor,
                     json={"dimensiones": ["cat_marca.marca_nombre"],
                           "metricas": ["monto_venta"]})
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["error"] == "RutaAmbigua"
    assert len(d["rutas"]) == 2


def test_ruta_elegida_si_compila(cliente, cab_editor, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_editor,
                     json={"dimensiones": ["cat_marca.marca_nombre"],
                           "metricas": ["monto_venta"],
                           "rutas_elegidas": {
                               "fact_venta->cat_marca":
                                   "fact_venta → cat_sucursal → cat_marca"}})
    assert r.status_code == 200, r.text
    assert len(r.json()["filas"]) == 9


def test_metrica_no_desglosable_avisa(cliente, cab_editor, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_editor,
                     json={"dimensiones": ["dim_vehiculo.modelo"],
                           "metricas": ["objetivo_unidades"]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error"] == "SinRuta"


def test_metrica_inexistente(cliente, cab_editor, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_editor,
                     json={"metricas": ["no_existe"]})
    assert r.status_code == 422


def test_fan_trap_no_infla_via_api(cliente, cab_admin, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_admin,
                     json={"dimensiones": ["cat_sucursal.sucursal_nombre"],
                           "metricas": ["unidades_vendidas", "objetivo_unidades"]})
    assert r.status_code == 200, r.text
    fila = next(f for f in r.json()["filas"]
                if f["cat_sucursal.sucursal_nombre"] == "Aurex Valle Alto")
    # Verdad de campo: 127 meses x 38 unidades.
    assert fila["objetivo_unidades"] == 4826


def test_limite_maximo(cliente, cab_admin, modelo_id):
    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_admin,
                     json={"metricas": ["monto_venta"], "limite": 999_999})
    assert r.status_code == 422        # excede el tope permitido


def test_auditoria_registra_las_consultas(cliente, cab_admin, modelo_id):
    from sqlalchemy import select

    from app.db import CrearSesion
    from app.modelos_db import Auditoria

    cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_admin,
                 json={"metricas": ["monto_venta"]})
    with CrearSesion() as s:
        acciones = set(s.scalars(select(Auditoria.accion)))
    assert {"ingreso", "consulta", "modelo_creado"} <= acciones


# --------------------------------------------------------------------------- #
# Filtros — el bug que un tablero convertiria en cifra equivocada
# --------------------------------------------------------------------------- #

def test_un_filtro_sobre_entidad_ajena_al_desglose_si_filtra(cliente, cab_admin,
                                                             modelo_id):
    """
    Se desglosa por sucursal y se filtra por la MARCA DEL VEHICULO: cat_marca no
    aparece en las dimensiones, asi que la consulta no la habria unido.

    Antes de arreglarlo el filtro se ignoraba en silencio y devolvia el total sin
    filtrar. Un tablero que filtra por marca y muestra el total de todas las
    marcas es peor que uno que no filtra: nadie lo nota.
    """
    base = {"dimensiones": ["cat_sucursal.sucursal_nombre"],
            "metricas": ["unidades_vendidas"], "limite": 5000}
    sin = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_admin,
                       json=base).json()

    con = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_admin, json={
        **base,
        "filtros": [{"campo": "cat_marca.marca_nombre", "op": "=", "valor": "Dalia"}],
        # cat_marca es ambigua desde fact_venta: hay que decir por donde.
        "rutas_elegidas": {
            "fact_venta->cat_marca": "fact_venta → dim_vehiculo → cat_marca"},
    }).json()

    total = lambda d: sum(f["unidades_vendidas"] or 0 for f in d["filas"])  # noqa: E731
    assert total(con) > 0, "el filtro dejo la consulta vacia"
    assert total(con) < total(sin), "el filtro no se aplico"
    assert "cat_marca" in con["sql"], "falta el join a la entidad del filtro"


def test_un_filtro_sin_ruta_falla_en_vez_de_ignorarse(cliente, cab_admin, modelo_id):
    """
    tbl_encuesta_clima esta aislada: no hay ruta desde fact_venta. Filtrar por
    ella no puede devolver un numero, tiene que avisar.
    """
    r = cliente.post(f"/api/modelos/{modelo_id}/consultar", headers=cab_admin, json={
        "dimensiones": ["cat_sucursal.sucursal_nombre"],
        "metricas": ["unidades_vendidas"],
        "filtros": [{"campo": "tbl_encuesta_clima.anio", "op": "=", "valor": 2025}],
    })
    assert r.status_code == 422, r.text
