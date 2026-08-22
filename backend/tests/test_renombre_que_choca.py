"""
Un renombre cuyo destino ya existe NO se hace, y nadie lo dice.

`SELECT * EXCLUDE (Id_DB), Id_DB AS Id_Sucursal` sobre una tabla que ya traia
`Id_Sucursal` no falla: DuckDB desambigua y la nueva acaba llamandose `Id_Sucursal_1`.
El renombre no surtio efecto, la columna que uno cree haber creado apunta a otro dato,
y todo sigue funcionando — hasta que un cambio ajeno quita la original, el renombre por
fin se hace, y las cifras cambian de sitio sin que nada señale la causa.

Paso de verdad: un catalogo de sucursales que sirvio un identificador durante meses y
empezo a servir otro al cambiar el origen principal, dejando media docena de widgets en
blanco.
"""

import pytest


def previa(cliente, cab, definicion: dict):
    return cliente.post("/api/transformaciones/previsualizar", headers=cab,
                        json={"definicion": definicion})


def _con_renombre(destino: str) -> dict:
    return {
        "nombre": "choque",
        "origenes": [{"nombre": "v", "tipo": "tabla", "referencia": "cat_sucursal"}],
        "pasos": [{"tipo": "renombrar", "cambios": {"marca_id": destino}}],
    }


def test_un_renombre_que_choca_con_otra_columna_se_rechaza(cliente, cab_admin):
    """
    `cat_sucursal` ya tiene `region_id`; renombrar `marca_id` a eso no lo haria.
    """
    r = previa(cliente, cab_admin, _con_renombre("region_id"))
    assert r.status_code == 422, r.text
    detalle = str(r.json()["detail"])
    assert "ya hay una columna llamada" in detalle
    assert "region_id" in detalle


def test_el_choque_no_distingue_mayusculas(cliente, cab_admin):
    """
    Para el motor `Region_Id` y `region_id` son la misma columna, asi que el aviso
    tiene que saltar igual. Es como se colo el caso real: `Id_DB → ID_Sucursal` contra
    una `Id_Sucursal` que ya estaba.
    """
    r = previa(cliente, cab_admin, _con_renombre("REGION_ID"))
    assert r.status_code == 422, r.text
    assert "ya hay una columna llamada" in str(r.json()["detail"])


def test_un_renombre_normal_sigue_pasando(cliente, cab_admin):
    """El aviso no puede estorbar a quien renombra a un nombre libre."""
    r = previa(cliente, cab_admin, _con_renombre("id_de_marca"))
    assert r.status_code == 200, r.text
    assert "id_de_marca" in r.json()["columnas"]
    assert "marca_id" not in r.json()["columnas"]


def test_tampoco_se_puede_ejecutar(cliente, cab_admin):
    """
    Previsualizar y ejecutar son dos caminos: si solo se comprueba uno, el resultado
    malo se escribe igual y lo usa el modelo. Y se comprueba ANTES de escribir el
    Parquet, no despues.
    """
    r = cliente.post("/api/transformaciones", headers=cab_admin,
                     json={"definicion": _con_renombre("region_id")})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    try:
        r = cliente.post(f"/api/transformaciones/{tid}/ejecutar", headers=cab_admin)
        # 400 y no 422: ejecutar lo envuelve como «la transformación falló», que es lo
        # que hace con cualquier motivo por el que no pudo escribir.
        assert r.status_code == 400, r.text
        assert "ya hay una columna llamada" in str(r.json()["detail"])
    finally:
        cliente.delete(f"/api/transformaciones/{tid}", headers=cab_admin)


def test_intercambiar_dos_nombres_sigue_valiendo(cliente, cab_admin):
    """
    Renombrar A→B y B→A a la vez es legitimo: las dos se van con el EXCLUDE, asi que
    ninguna de las dos estorba a la otra. Un aviso que lo prohibiera seria un aviso
    equivocado.
    """
    r = previa(cliente, cab_admin, {
        "nombre": "intercambio",
        "origenes": [{"nombre": "v", "tipo": "tabla", "referencia": "cat_sucursal"}],
        "pasos": [{"tipo": "renombrar",
                   "cambios": {"marca_id": "region_id", "region_id": "marca_id"}}],
    })
    assert r.status_code == 200, r.text
    assert set(["marca_id", "region_id"]) <= set(r.json()["columnas"])
