"""
Fase 6 — gobierno: politicas editables, simulador y auditoria.

Las cifras vienen del modelo de pruebas: la politica filtra cat_sucursal por
region_id, y el usuario 'norte@...' tiene region_id=3 (Veracruz), donde hay
exactamente una de las 40 sucursales. Eso hace verificable a mano lo que el
simulador reporta.
"""

import pytest

from semantic.politica import PoliticaDef, revisar_politica

CAMPOS = {"cat_sucursal": {"sucursal_id", "sucursal_nombre", "region_id"},
          "cat_region": {"region_id", "region_nombre"}}


def _pol(**kw) -> PoliticaDef:
    base = {"nombre": "p", "entidad": "cat_sucursal",
            "predicado": "region_id = {{ usuario.region_id }}",
            "aplica_a_roles": ["lector"]}
    return PoliticaDef.model_validate({**base, **kw})


# --------------------------------------------------------------------------- #
# Validacion del predicado
# --------------------------------------------------------------------------- #

def test_una_politica_correcta_no_tiene_errores_ni_avisos():
    errores, avisos = revisar_politica(_pol(), CAMPOS)
    assert errores == []
    assert avisos == []


def test_columna_inexistente_es_error():
    """
    No es un detalle: una columna mal escrita dentro de una politica no rompe la
    politica, rompe TODA consulta de la gente a la que aplica.
    """
    errores, _ = revisar_politica(_pol(predicado="estado = {{ usuario.region_id }}"),
                                  CAMPOS)
    assert errores and "estado" in errores[0]


def test_entidad_inexistente_es_error():
    errores, _ = revisar_politica(_pol(entidad="cat_marca"), CAMPOS)
    assert errores and "cat_marca" in errores[0]


@pytest.mark.parametrize("malo", [
    "region_id = (SELECT 1)",                       # subconsulta
    "region_id = 1; DROP TABLE cat_sucursal",       # dos sentencias
    "region_id = {{ tabla.otra }}",                 # sustitucion no soportada
    "region_id",                                    # no es una condicion
])
def test_predicados_rechazados(malo):
    errores, _ = revisar_politica(_pol(predicado=malo), CAMPOS)
    assert errores, f"se acepto un predicado que no debia: {malo}"


def test_una_condicion_compuesta_se_acepta():
    errores, _ = revisar_politica(_pol(
        predicado="region_id = {{ usuario.region_id }} AND sucursal_id <> 99"),
        CAMPOS)
    assert errores == []


def test_politica_sin_atributo_avisa_pero_no_bloquea():
    errores, avisos = revisar_politica(_pol(predicado="region_id = 3"), CAMPOS)
    assert errores == []
    assert any("atributo" in a for a in avisos)


def test_nombres_repetidos_son_error(cliente, cab_admin, modelo_id):
    r = cliente.put(f"/api/modelos/{modelo_id}/politicas", headers=cab_admin,
                    json={"politicas": [
                        _pol(nombre="repetida").model_dump(),
                        _pol(nombre="repetida").model_dump(),
                    ]})
    assert r.status_code == 422, r.text
    assert "repetida" in str(r.json()["detail"])


# --------------------------------------------------------------------------- #
# API de politicas
# --------------------------------------------------------------------------- #

def test_leer_politicas_trae_lo_necesario_para_editarlas(cliente, cab_admin,
                                                         modelo_id):
    r = cliente.get(f"/api/modelos/{modelo_id}/politicas", headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert [p["nombre"] for p in d["politicas"]] == ["rls_por_region"]
    entidades = {e["nombre"] for e in d["entidades"]}
    assert "cat_sucursal" in entidades
    assert "region_id" in next(e["campos"] for e in d["entidades"]
                               if e["nombre"] == "cat_sucursal")
    # administrador no aparece: no se le pueden aplicar politicas.
    assert "administrador" not in d["roles"]


def test_la_cobertura_senala_a_quien_le_falta_el_atributo(cliente, cab_admin,
                                                          modelo_id):
    """
    El cruce que evita el 403 sorpresa: hay un lector sin region_id, y la interfaz
    tiene que poder decirlo antes de que esa persona llame por telefono.
    """
    d = cliente.get(f"/api/modelos/{modelo_id}/politicas",
                    headers=cab_admin).json()
    cob = next(c for c in d["cobertura"] if c["politica"] == "rls_por_region")
    assert cob["atributos"] == ["region_id"]
    faltos = [x["email"] for x in cob["sin_atributo"]]
    assert "incompleto@pruebas.example.com" in faltos
    assert "norte@pruebas.example.com" not in faltos


def test_un_lector_no_puede_ver_las_politicas(cliente, cab_lector, modelo_id):
    r = cliente.get(f"/api/modelos/{modelo_id}/politicas", headers=cab_lector)
    assert r.status_code == 403


def test_guardar_politicas_crea_version_nueva(cliente, cab_admin, modelo_id):
    antes = cliente.get(f"/api/modelos/{modelo_id}/politicas",
                        headers=cab_admin).json()
    r = cliente.put(f"/api/modelos/{modelo_id}/politicas", headers=cab_admin,
                    json={"politicas": antes["politicas"] + [
                        _pol(nombre="rls_extra", entidad="cat_region",
                             predicado="region_id = {{ usuario.region_id }}"
                             ).model_dump()],
                        "notas": "prueba"})
    assert r.status_code == 201, r.text
    assert r.json()["version"] == antes["version"] + 1

    # Y el modelo sigue completo: guardar politicas no puede perder entidades.
    d = cliente.get(f"/api/modelos/{modelo_id}/definicion",
                    headers=cab_admin).json()
    assert len(d["definicion"]["entidades"]) >= 4
    assert len(d["definicion"]["politicas"]) == 2

    # Se deja como estaba, que el resto de las pruebas cuenta con una sola.
    cliente.put(f"/api/modelos/{modelo_id}/politicas", headers=cab_admin,
                json={"politicas": antes["politicas"]})


def test_quitar_todas_las_politicas_es_posible_y_queda_en_auditoria(
        cliente, cab_admin, modelo_id):
    antes = cliente.get(f"/api/modelos/{modelo_id}/politicas",
                        headers=cab_admin).json()
    r = cliente.put(f"/api/modelos/{modelo_id}/politicas", headers=cab_admin,
                    json={"politicas": []})
    assert r.status_code == 201, r.text
    assert cliente.get(f"/api/modelos/{modelo_id}/politicas",
                       headers=cab_admin).json()["politicas"] == []

    ev = cliente.get("/api/gobierno/auditoria?accion=politicas_guardadas",
                     headers=cab_admin).json()["eventos"]
    # El "antes" queda registrado: sin el no se puede saber que se quito.
    assert ev[0]["detalle"]["antes"] == ["rls_por_region"]

    cliente.put(f"/api/modelos/{modelo_id}/politicas", headers=cab_admin,
                json={"politicas": antes["politicas"]})


# --------------------------------------------------------------------------- #
# Simulador
# --------------------------------------------------------------------------- #

def _usuario_id(cliente, cab_admin, email: str) -> int:
    for u in cliente.get("/api/auth/usuarios", headers=cab_admin).json():
        if u["email"] == email:
            return u["id"]
    raise AssertionError(f"no existe {email}")


def test_simular_un_lector_dice_cuantas_filas_ve(cliente, cab_admin, modelo_id):
    uid = _usuario_id(cliente, cab_admin, "norte@pruebas.example.com")
    r = cliente.post("/api/gobierno/simular", headers=cab_admin,
                     json={"modelo_id": modelo_id, "usuario_id": uid})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["error"] is None
    assert [p["politica"] for p in d["aplicadas"]] == ["rls_por_region"]

    ent = next(e for e in d["entidades"] if e["entidad"] == "cat_sucursal")
    assert ent["filas_totales"] == 40
    assert ent["filas_visibles"] == 1
    assert ent["muestra"] == ["Ekos Río Blanco"]
    # El valor del atributo se ve: es lo que explica el porque del filtro.
    assert ent["valores"] == ["3"]


def test_simular_un_administrador_dice_que_no_le_aplica(cliente, cab_admin,
                                                        modelo_id):
    uid = _usuario_id(cliente, cab_admin, "admin@pruebas.example.com")
    d = cliente.post("/api/gobierno/simular", headers=cab_admin,
                     json={"modelo_id": modelo_id, "usuario_id": uid}).json()
    assert d["aplicadas"] == []
    assert d["es_administrador"] is True
    assert any("administrador" in o["motivo"] for o in d["omitidas"])


def test_simular_muestra_el_fallo_cerrado_igual_que_lo_veria_la_persona(
        cliente, cab_admin, modelo_id):
    uid = _usuario_id(cliente, cab_admin, "incompleto@pruebas.example.com")
    d = cliente.post("/api/gobierno/simular", headers=cab_admin,
                     json={"modelo_id": modelo_id, "usuario_id": uid}).json()
    assert d["error"] and "region_id" in d["error"]
    # Y no se cuenta nada: falla cerrado tambien en la simulacion.
    assert d["entidades"] == []


def test_la_comparacion_con_y_sin_politicas_es_el_producto(cliente, cab_admin,
                                                           modelo_id):
    """
    Un numero solo no dice si la politica filtra. La comparacion si.
    """
    uid = _usuario_id(cliente, cab_admin, "norte@pruebas.example.com")
    d = cliente.post("/api/gobierno/simular", headers=cab_admin, json={
        "modelo_id": modelo_id, "usuario_id": uid,
        "consulta": {"dimensiones": ["cat_sucursal.sucursal_nombre"],
                     "metricas": ["monto_venta"]},
    }).json()
    c = d["consulta"]
    assert c["cuenta"] == 1
    assert c["cuenta_sin_politicas"] == 36
    assert [f["cat_sucursal.sucursal_nombre"] for f in c["filas"]] == ["Ekos Río Blanco"]


def test_simular_un_rol_ficticio_sin_crear_a_nadie(cliente, cab_admin, modelo_id):
    r = cliente.post("/api/gobierno/simular", headers=cab_admin, json={
        "modelo_id": modelo_id, "rol": "lector",
        "atributos": {"region_id": "2"},          # 16 de las 40 sucursales
    })
    assert r.status_code == 200, r.text
    ent = next(e for e in r.json()["entidades"] if e["entidad"] == "cat_sucursal")
    assert ent["filas_visibles"] == 16
    assert ent["filas_totales"] == 40


def test_simular_exige_usuario_o_rol(cliente, cab_admin, modelo_id):
    r = cliente.post("/api/gobierno/simular", headers=cab_admin,
                     json={"modelo_id": modelo_id})
    assert r.status_code == 422


def test_solo_un_administrador_puede_simular(cliente, cab_editor, modelo_id):
    r = cliente.post("/api/gobierno/simular", headers=cab_editor,
                     json={"modelo_id": modelo_id, "rol": "lector"})
    assert r.status_code == 403


def test_la_simulacion_queda_en_auditoria(cliente, cab_admin, modelo_id):
    """Un administrador viendo datos como otra persona es justo lo que se audita."""
    uid = _usuario_id(cliente, cab_admin, "norte@pruebas.example.com")
    cliente.post("/api/gobierno/simular", headers=cab_admin,
                 json={"modelo_id": modelo_id, "usuario_id": uid})
    ev = cliente.get("/api/gobierno/auditoria?accion=simulacion",
                     headers=cab_admin).json()["eventos"]
    assert ev, "la simulacion no dejo rastro"
    assert ev[0]["detalle"]["como"]["email"] == "norte@pruebas.example.com"


# --------------------------------------------------------------------------- #
# Usuarios
# --------------------------------------------------------------------------- #

def _crear(cliente, cab_admin, email: str, **kw) -> dict:
    cuerpo = {"email": email, "nombre": "Prueba", "contrasena": "contrasena-larga-1",
              "rol": "lector", **kw}
    r = cliente.post("/api/auth/usuarios", headers=cab_admin, json=cuerpo)
    if r.status_code == 409:
        return next(u for u in cliente.get("/api/auth/usuarios",
                                           headers=cab_admin).json()
                    if u["email"] == email)
    assert r.status_code == 201, r.text
    return r.json()


def test_editar_usuario_cambia_rol_y_atributos(cliente, cab_admin):
    u = _crear(cliente, cab_admin, "editable@pruebas.example.com",
               atributos={"region_id": "3"})
    r = cliente.patch(f"/api/auth/usuarios/{u['id']}", headers=cab_admin,
                      json={"rol": "editor", "atributos": {"region_id": "9"}})
    assert r.status_code == 200, r.text
    assert r.json()["rol"] == "editor"
    assert r.json()["atributos"] == {"region_id": "9"}


def test_los_atributos_se_reemplazan_no_se_mezclan(cliente, cab_admin):
    """Si se mezclaran, no habria forma de quitar un atributo."""
    u = _crear(cliente, cab_admin, "reemplazo@pruebas.example.com",
               atributos={"region_id": "3", "marca_id": "1"})
    r = cliente.patch(f"/api/auth/usuarios/{u['id']}", headers=cab_admin,
                      json={"atributos": {"region_id": "3"}})
    assert r.json()["atributos"] == {"region_id": "3"}


def test_una_clave_de_atributo_que_no_sirve_en_una_politica_se_rechaza(
        cliente, cab_admin):
    u = _crear(cliente, cab_admin, "clavemala@pruebas.example.com")
    r = cliente.patch(f"/api/auth/usuarios/{u['id']}", headers=cab_admin,
                      json={"atributos": {"Estado ID": "3"}})
    assert r.status_code == 422, r.text
    assert "region_id" in r.json()["detail"]


def test_el_cambio_guarda_el_antes_y_el_despues(cliente, cab_admin):
    """
    Sin el valor anterior no se puede reconstruir que veia esa persona el mes
    pasado, que es la pregunta que se hace despues.
    """
    u = _crear(cliente, cab_admin, "historial@pruebas.example.com",
               atributos={"region_id": "3"})
    cliente.patch(f"/api/auth/usuarios/{u['id']}", headers=cab_admin,
                  json={"atributos": {"region_id": "9"}})
    ev = cliente.get(f"/api/gobierno/auditoria?accion=usuario_editado"
                     f"&objeto_id={u['id']}", headers=cab_admin).json()["eventos"]
    assert ev[0]["detalle"]["cambios"]["atributos"] == [
        {"region_id": "3"}, {"region_id": "9"}]


def test_no_se_puede_quedar_sin_administradores(cliente, cab_admin):
    """
    Un clic sin vuelta atras: el ultimo administrador que se quita el rol deja el
    sistema sin nadie que pueda administrarlo.
    """
    yo = cliente.get("/api/auth/yo", headers=cab_admin).json()
    r = cliente.patch(f"/api/auth/usuarios/{yo['id']}", headers=cab_admin,
                      json={"rol": "lector"})
    assert r.status_code == 409, r.text
    assert "administrador" in r.json()["detail"]

    r = cliente.patch(f"/api/auth/usuarios/{yo['id']}", headers=cab_admin,
                      json={"activo": False})
    assert r.status_code == 409

    # Con otro administrador activo, si se puede.
    otro = _crear(cliente, cab_admin, "admin2@pruebas.example.com",
                  rol="administrador")
    r = cliente.patch(f"/api/auth/usuarios/{otro['id']}", headers=cab_admin,
                      json={"activo": False})
    assert r.status_code == 200, r.text


def test_un_usuario_desactivado_no_entra(cliente, cab_admin):
    u = _crear(cliente, cab_admin, "fuera@pruebas.example.com")
    cliente.patch(f"/api/auth/usuarios/{u['id']}", headers=cab_admin,
                  json={"activo": False})
    r = cliente.post("/api/auth/token", data={"username": u["email"],
                                              "password": "contrasena-larga-1"})
    assert r.status_code == 403


def test_cambiar_la_propia_contrasena_exige_la_actual(cliente, cab_admin):
    u = _crear(cliente, cab_admin, "cambio@pruebas.example.com")
    tok = cliente.post("/api/auth/token", data={
        "username": u["email"], "password": "contrasena-larga-1"}).json()
    cab = {"Authorization": f"Bearer {tok['access_token']}"}

    r = cliente.post("/api/auth/cambiar-contrasena", headers=cab,
                     json={"actual": "la-equivocada", "nueva": "nueva-larga-1234"})
    assert r.status_code == 403

    r = cliente.post("/api/auth/cambiar-contrasena", headers=cab,
                     json={"actual": "contrasena-larga-1",
                           "nueva": "nueva-larga-1234"})
    assert r.status_code == 204, r.text
    assert cliente.post("/api/auth/token", data={
        "username": u["email"], "password": "nueva-larga-1234"}).status_code == 200


def test_un_administrador_restablece_sin_conocer_la_anterior(cliente, cab_admin):
    u = _crear(cliente, cab_admin, "restablecer@pruebas.example.com")
    r = cliente.post(f"/api/auth/usuarios/{u['id']}/contrasena", headers=cab_admin,
                     json={"nueva": "puesta-por-admin-1"})
    assert r.status_code == 204, r.text
    assert cliente.post("/api/auth/token", data={
        "username": u["email"], "password": "puesta-por-admin-1"}).status_code == 200


def test_un_lector_no_administra_usuarios(cliente, cab_lector):
    assert cliente.get("/api/auth/usuarios",
                       headers=cab_lector).status_code == 403
    assert cliente.patch("/api/auth/usuarios/1", headers=cab_lector,
                         json={"nombre": "x"}).status_code == 403


# --------------------------------------------------------------------------- #
# Auditoria
# --------------------------------------------------------------------------- #

def test_la_auditoria_se_filtra_y_se_pagina(cliente, cab_admin):
    r = cliente.get("/api/gobierno/auditoria?por_pagina=5", headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["eventos"]) <= 5
    assert d["total"] >= len(d["eventos"])
    # Lo mas reciente primero: un registro que empieza por el año pasado no se lee.
    ids = [e["id"] for e in d["eventos"]]
    assert ids == sorted(ids, reverse=True)


def test_filtrar_por_accion_y_por_persona(cliente, cab_admin):
    d = cliente.get("/api/gobierno/auditoria?accion=ingreso",
                    headers=cab_admin).json()
    assert d["eventos"] and all(e["accion"] == "ingreso" for e in d["eventos"])

    d = cliente.get("/api/gobierno/auditoria?email=admin@pruebas",
                    headers=cab_admin).json()
    assert all("admin@pruebas" in (e["email"] or "") for e in d["eventos"])


def test_el_resumen_cuenta_los_ingresos_fallidos_aparte(cliente, cab_admin):
    cliente.post("/api/auth/token", data={"username": "nadie@pruebas.example.com",
                                          "password": "x"})
    d = cliente.get("/api/gobierno/auditoria/resumen", headers=cab_admin).json()
    assert d["ingresos_fallidos"] >= 1
    assert any(a["accion"] == "ingreso" for a in d["acciones"])


def test_un_lector_no_ve_la_auditoria(cliente, cab_lector):
    assert cliente.get("/api/gobierno/auditoria",
                       headers=cab_lector).status_code == 403


def test_la_auditoria_no_se_puede_borrar(cliente, cab_admin):
    """No es un olvido: un registro que se puede limpiar no sirve de registro."""
    for metodo in (cliente.delete, cliente.put):
        r = metodo("/api/gobierno/auditoria")
        assert r.status_code in (404, 405), r.status_code
