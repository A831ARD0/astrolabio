"""
La prueba mas importante de la Fase 0: que la seguridad por fila filtre de
verdad, no solo que exista el gancho.

El modelo trae una politica sobre cat_sucursal: region_id = {{ usuario.region_id }}.
El usuario 'norte@pruebas.example.com' tiene region_id=3 (Sur), donde hay exactamente
una sucursal: Ekos Río Blanco. Eso hace el resultado verificable a mano.
"""


def _consultar(cliente, cab, modelo_id, **cuerpo):
    return cliente.post(f"/api/modelos/{modelo_id}/consultar",
                        headers=cab, json=cuerpo)


def test_admin_ve_las_40_sucursales(cliente, cab_admin, modelo_id):
    r = _consultar(cliente, cab_admin, modelo_id,
                   dimensiones=["cat_sucursal.sucursal_nombre"],
                   metricas=["monto_venta"])
    assert r.status_code == 200, r.text
    d = r.json()
    # 36 sucursales venden autos (las 4 de HYP solo facturan servicio).
    assert len(d["filas"]) == 36
    assert d["politicas_aplicadas"] == []


def test_lector_solo_ve_su_estado(cliente, cab_lector, modelo_id):
    r = _consultar(cliente, cab_lector, modelo_id,
                   dimensiones=["cat_sucursal.sucursal_nombre"],
                   metricas=["monto_venta"])
    assert r.status_code == 200, r.text
    d = r.json()
    nombres = [f["cat_sucursal.sucursal_nombre"] for f in d["filas"]]
    assert nombres == ["Ekos Río Blanco"], nombres
    assert "rls_por_region" in d["politicas_aplicadas"]


def test_el_total_tambien_esta_filtrado(cliente, cab_admin, cab_lector, modelo_id):
    """
    El caso critico: sin desglosar por sucursal, el CTE no uniria cat_sucursal.
    La politica debe forzar el join igual, o el lector veria el total del grupo.
    """
    total_admin = _consultar(cliente, cab_admin, modelo_id,
                             metricas=["monto_venta"]).json()["filas"][0]["monto_venta"]
    r = _consultar(cliente, cab_lector, modelo_id, metricas=["monto_venta"])
    assert r.status_code == 200, r.text
    total_lector = r.json()["filas"][0]["monto_venta"]

    assert total_lector < total_admin, (
        "El lector regional esta viendo el total del grupo entero: la politica "
        "no se aplico cuando no habia desglose por sucursal."
    )
    assert r.json()["politicas_aplicadas"] == ["rls_por_region"]


def test_filtrado_al_desglosar_por_otra_dimension(cliente, cab_lector, modelo_id):
    """Aunque la dimension pedida no sea sucursal, la politica sigue aplicando."""
    r = _consultar(cliente, cab_lector, modelo_id,
                   dimensiones=["dim_calendario.anio"],
                   metricas=["unidades_vendidas"])
    assert r.status_code == 200, r.text
    assert r.json()["politicas_aplicadas"] == ["rls_por_region"]

    solo_cordoba = _consultar(cliente, cab_lector, modelo_id,
                              dimensiones=["cat_sucursal.sucursal_nombre",
                                           "dim_calendario.anio"],
                              metricas=["unidades_vendidas"]).json()["filas"]
    suma_detalle = sum(f["unidades_vendidas"] or 0 for f in solo_cordoba)
    suma_por_anio = sum(f["unidades_vendidas"] or 0 for f in r.json()["filas"])
    assert suma_detalle == suma_por_anio


def test_estado_visible_solo_el_propio(cliente, cab_lector, modelo_id):
    r = _consultar(cliente, cab_lector, modelo_id,
                   dimensiones=["cat_region.region_nombre"],
                   metricas=["monto_venta"])
    assert r.status_code == 200, r.text
    nombres = [f["cat_region.region_nombre"] for f in r.json()["filas"]]
    assert nombres == ["Sur"], nombres


def test_falla_cerrado_si_falta_el_atributo(cliente, cab_incompleto, modelo_id):
    """
    Sin el atributo que la politica necesita, NO se entregan datos. Falla
    cerrado: es la unica opcion segura.
    """
    r = _consultar(cliente, cab_incompleto, modelo_id, metricas=["monto_venta"])
    assert r.status_code == 403, r.text
    assert "region_id" in r.json()["detail"]


def test_estados_asociativos_tambien_filtrados(cliente, cab_lector, cab_admin,
                                               modelo_id):
    """
    La existencia misma de una sucursal es informacion: no debe aparecer ni como
    'excluida' en un panel de filtros.
    """
    cuerpo = {"entidad": "cat_sucursal", "campo": "sucursal_nombre",
              "selecciones": {}}
    ra = cliente.post(f"/api/modelos/{modelo_id}/asociativo",
                      headers=cab_admin, json=cuerpo)
    rl = cliente.post(f"/api/modelos/{modelo_id}/asociativo",
                      headers=cab_lector, json=cuerpo)
    assert ra.status_code == rl.status_code == 200, rl.text

    todos_admin = sum(len(v) for v in ra.json().values())
    del_lector = rl.json()
    todos_lector = sum(len(v) for v in del_lector.values())

    assert todos_admin == 40
    assert todos_lector == 1, del_lector
    assert del_lector["posible"] == ["Ekos Río Blanco"]


def test_el_sql_no_se_expone_al_lector(cliente, cab_lector, cab_editor, modelo_id):
    lector = _consultar(cliente, cab_lector, modelo_id, metricas=["monto_venta"])
    editor = _consultar(cliente, cab_editor, modelo_id, metricas=["monto_venta"])
    assert lector.json()["sql"] is None
    assert editor.json()["sql"] is not None


def test_los_valores_van_ligados_no_interpolados(cliente, cab_editor, modelo_id):
    """Un valor de filtro con comilla no debe romper ni alterar el SQL."""
    r = _consultar(cliente, cab_editor, modelo_id,
                   dimensiones=["cat_sucursal.sucursal_nombre"],
                   metricas=["monto_venta"],
                   filtros=[{"campo": "cat_sucursal.sucursal_nombre",
                             "op": "=", "valor": "' OR 1=1 --"}])
    assert r.status_code == 200, r.text
    assert r.json()["filas"] == []          # no existe: 0 filas, no todas
    assert "OR 1=1" not in (r.json()["sql"] or "")
