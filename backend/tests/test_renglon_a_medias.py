"""
Una ejecucion no se queda en 'corriendo' para siempre.

El renglon se confirma ANTES de empezar, a proposito: con la transaccion abierta
durante toda la ingesta, SQLite deja fuera a cualquier otro escritor y crear un
flujo mientras corria una extraccion daba Error 500. El precio es que un
`rollback` ya no se lleva ese renglon: si algo revienta por un camino que nadie
previo, se queda 'corriendo' con el servicio vivo, la pantalla dice que sigue
trabajando y lo unico que lo arreglaba era reiniciar.
"""

from __future__ import annotations

import pytest

from app import trabajos
from app.db import CrearSesion
from app.modelos_db import CargaEjecucion, Dataset, EstadoCarga


@pytest.fixture()
def dataset_con_renglon(cliente, cab_admin, conexion_archivos_etl):
    """Un dataset con una ejecucion abierta, como la deja una carga que empieza."""
    with CrearSesion() as sesion:
        ds = sesion.query(Dataset).first()
        assert ds is not None, "el fixture tiene que dejar algun dataset"
        e = CargaEjecucion(dataset_id=ds.id, estado=EstadoCarga.corriendo,
                           modo="completo", origen="manual")
        sesion.add(e)
        sesion.commit()
        return ds.id, e.id


def test_se_cierra_con_el_motivo(dataset_con_renglon):
    ds_id, e_id = dataset_con_renglon
    assert trabajos.cerrar_a_medias("carga", ds_id, "se rompio algo") == 1

    with CrearSesion() as sesion:
        e = sesion.get(CargaEjecucion, e_id)
        assert e.estado == EstadoCarga.error
        assert e.mensaje == "se rompio algo", "sin motivo, el error no dice nada"


def test_no_toca_las_que_ya_terminaron(dataset_con_renglon):
    """Reescribir un exito con un error seria peor que el problema."""
    ds_id, e_id = dataset_con_renglon
    with CrearSesion() as sesion:
        e = sesion.get(CargaEjecucion, e_id)
        e.estado = EstadoCarga.exito
        sesion.commit()

    assert trabajos.cerrar_a_medias("carga", ds_id, "no deberia aplicarse") == 0
    with CrearSesion() as sesion:
        assert sesion.get(CargaEjecucion, e_id).estado == EstadoCarga.exito


def test_no_toca_las_de_otro_dataset(dataset_con_renglon):
    ds_id, e_id = dataset_con_renglon
    assert trabajos.cerrar_a_medias("carga", ds_id + 999, "otro") == 0
    with CrearSesion() as sesion:
        assert sesion.get(CargaEjecucion, e_id).estado == EstadoCarga.corriendo


def test_un_trabajo_que_revienta_deja_el_renglon_cerrado(dataset_con_renglon,
                                                         monkeypatch):
    """
    De punta a punta, que es lo que importa: el ejecutor se traga la excepcion
    para no matar el hilo de la cola, y antes tiene que cerrar el renglon.
    """
    from datetime import datetime, timezone

    ds_id, e_id = dataset_con_renglon

    def revienta(_sesion, _t):
        raise RuntimeError("el driver se cayo")

    monkeypatch.setattr(trabajos, "_ejecutar_carga", revienta)
    t = trabajos.Trabajo(
        id=7_777, tipo="carga", objeto_id=ds_id, nombre="x", actor_id=None,
        actor_email="x@y", a_la_par=False, encolado_en=datetime.now(timezone.utc))
    with trabajos._reg.candado:
        trabajos._reg.vivos[t.id] = t

    trabajos._correr(t)          # no relanza: el hilo de la cola sobrevive

    with CrearSesion() as sesion:
        e = sesion.get(CargaEjecucion, e_id)
        assert e.estado == EstadoCarga.error
        assert "RuntimeError" in e.mensaje
        assert "el driver se cayo" in e.mensaje
