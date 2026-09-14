"""
Un rango de recarga se estira a meses completos.

Existe por una perdida de datos silenciosa: se borraba por particiones —y la
particion minima es el mes— pero se volvia a traer por las fechas exactas del
rango. Recargar "del 15 al 20 de marzo" borraba marzo entero y devolvia seis dias.
La carga terminaba en verde.
"""

from __future__ import annotations

from datetime import date

import duckdb
import pytest

from app.conectores.base import a_meses_completos, particiones_del_rango
from tests.conftest import cargar, necesita_mysql, recargar_rango


@pytest.mark.parametrize("desde,hasta,esperado", [
    # Medio mes: se estira por los dos lados.
    ("2026-03-15", "2026-03-20", ("2026-03-01", "2026-03-31")),
    # Ya completo: no se toca.
    ("2026-03-01", "2026-03-31", ("2026-03-01", "2026-03-31")),
    # Varios meses, y febrero de un año bisiesto por su ultimo dia.
    ("2024-01-10", "2024-02-05", ("2024-01-01", "2024-02-29")),
    # Febrero normal.
    ("2026-02-10", "2026-02-11", ("2026-02-01", "2026-02-28")),
    # Diciembre: el ultimo dia no se busca en el mes 13.
    ("2025-12-05", "2025-12-06", ("2025-12-01", "2025-12-31")),
    # Cruzando el año.
    ("2025-11-20", "2026-01-04", ("2025-11-01", "2026-01-31")),
])
def test_el_rango_se_estira_a_meses(desde, hasta, esperado):
    assert a_meses_completos(desde, hasta) == esperado


def test_lo_que_se_trae_cubre_exactamente_lo_que_se_borra():
    """
    La invariante de la que dependia todo: el rango estirado tiene que cubrir las
    mismas particiones que se van a borrar, ni una mas ni una menos. Si un dia se
    cambia como se calculan las particiones, aqui se nota.
    """
    for desde, hasta in [("2026-03-15", "2026-03-20"),
                         ("2025-11-20", "2026-01-04"),
                         ("2024-01-10", "2024-02-05")]:
        d, h = a_meses_completos(desde, hasta)
        meses = particiones_del_rango(d, h)
        assert meses == particiones_del_rango(desde, hasta)
        # Y el rango estirado empieza y acaba dentro del primer y ultimo mes.
        assert date.fromisoformat(d).day == 1
        assert f"anio={date.fromisoformat(h).year}/mes={date.fromisoformat(h).month}" \
            == meses[-1]


@necesita_mysql
def test_recargar_media_marzo_no_se_lleva_la_otra_media(cliente, cab_admin,
                                                       conexion_mysql):
    """
    La prueba que lo destapo, de punta a punta. Antes del arreglo marzo pasaba de
    1689 filas a 312 y la carga decia 'exito'.
    """
    from app.cargas import ruta_dataset

    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "rango_medio_mes", "tabla": "ventas",
                           "particionar_por": "fecha_emision"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]
    cargar(cliente, cab_admin, ds)

    destino = ruta_dataset("rango_medio_mes")
    con = duckdb.connect()
    marzo = (f"SELECT COUNT(*) FROM read_parquet('{destino}/**/*.parquet', "
             f"hive_partitioning=1) WHERE anio=2026 AND mes=3")
    antes = con.execute(marzo).fetchone()[0]
    assert antes > 0, "el fixture tiene que traer marzo de 2026"

    d = recargar_rango(cliente, cab_admin, ds, "2026-03-15", "2026-03-20")
    assert d["estado"] == "exito", d

    assert con.execute(marzo).fetchone()[0] == antes, (
        "recargar medio marzo se llevo por delante el resto del mes")

    # Y el rango que quedo en el historial es el estirado, no el que se pidio: si
    # dijera el pedido, mirando una corrida nadie entenderia por que se toco el
    # dia 3.
    assert d["detalle"]["rango"] == ["2026-03-01", "2026-03-31"]
