"""
Partir por una columna que no es fecha ya no termina en verde.

Existe por un caso real: se eligio como columna de particion un entero con forma
20260914. DuckDB no lo puede interpretar como fecha, TRY_CAST devuelve NULL, y las
140 mil filas acabaron en la particion 'sin_fecha'. La carga dijo 'exito'. A partir
de ahi la ventana movil borraba meses que no existian y volvia a pedir al origen un
rango de fechas contra una columna entera: el dataset se quedo congelado y no hubo
ninguna señal.
"""

from __future__ import annotations

from tests.conftest import cargar, necesita_mysql, ultima_carga


@necesita_mysql
def test_partir_por_un_entero_no_termina_en_verde(cliente, cab_admin, conexion_mysql):
    from app import trabajos

    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "part_entero", "tabla": "ventas",
                           "particionar_por": "venta_id"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]

    r = cliente.post(f"/api/conexiones/datasets/{ds}/cargar", headers=cab_admin,
                     params={"limite": 500})
    assert r.status_code == 202, r.text
    assert trabajos.esperar(120)

    e = ultima_carga(cliente, cab_admin, ds)
    assert e["estado"] == "error", "una carga que no feche ninguna fila no es un exito"
    assert "sin_fecha" in e["mensaje"], e["mensaje"]
    assert "venta_id" in e["mensaje"], "el mensaje tiene que decir cual columna"


@necesita_mysql
def test_una_fecha_de_verdad_sigue_pasando(cliente, cab_admin, conexion_mysql):
    """El guardia no puede estorbar al caso bueno."""
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "part_fecha_ok", "tabla": "ventas",
                           "particionar_por": "fecha_emision"})
    ds = r.json()["id"]
    e = cargar(cliente, cab_admin, ds, limite=500)
    assert e["estado"] == "exito", e
    assert e["filas_sin_particion"] == 0
    assert e["particiones"], "tiene que decir que particiones toco"
