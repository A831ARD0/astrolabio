"""
La cola de corridas a mano.

Lo que se protege: que lanzar un flujo conteste enseguida en vez de tener la
peticion abierta durante minutos —de ahi salia el 502 con veintiocho tablas—,
que dos corridas de lo mismo no se pisen, y que dos flujos distintos hagan cola
salvo que se pida lo contrario a proposito.
"""

from __future__ import annotations

import pytest

from app import trabajos
from tests.test_flujos import (           # noqa: F401
    crear_flujo, transformacion_flujo,
)


@pytest.fixture(autouse=True)
def cola_limpia():
    yield
    trabajos.esperar(60)


@pytest.fixture
def dos_flujos(cliente, cab_admin, transformacion_flujo):
    uno = crear_flujo(cliente, cab_admin, {
        "nombre": "cola_uno",
        "pasos": [{"tipo": "transformacion", "id": transformacion_flujo}]})
    dos = crear_flujo(cliente, cab_admin, {
        "nombre": "cola_dos",
        "pasos": [{"tipo": "transformacion", "id": transformacion_flujo}]})
    return uno["id"], dos["id"]


def test_lanzar_contesta_enseguida_y_no_trae_el_resultado(cliente, cab_admin,
                                                          dos_flujos):
    # 202 y no 200: la corrida empieza, no termina. Tenerla dentro de la
    # peticion es lo que hacia que el proxy cortara con 502.
    id_, _ = dos_flujos
    r = cliente.post(f"/api/flujos/{id_}/ejecutar", headers=cab_admin)
    assert r.status_code == 202, r.text
    d = r.json()
    assert d["trabajo_id"] > 0
    assert d["estado"] in ("en_cola", "corriendo")
    assert "pasos" in d and isinstance(d["pasos"], int)


def test_el_resultado_aparece_en_el_historial(cliente, cab_admin, dos_flujos):
    id_, _ = dos_flujos
    cliente.post(f"/api/flujos/{id_}/ejecutar", headers=cab_admin)
    assert trabajos.esperar(60)
    h = cliente.get(f"/api/flujos/{id_}/historial", headers=cab_admin).json()
    assert h["ejecuciones"][0]["estado"] == "exito"
    assert h["ejecuciones"][0]["disparo"] == "manual"


def test_el_mismo_flujo_dos_veces_se_rechaza():
    # No es una preferencia: son dos procesos escribiendo los mismos archivos.
    actor = _actor()
    trabajos.encolar("flujo", 99_001, "ficticio", actor)
    with pytest.raises(trabajos.YaEnMarcha):
        trabajos.encolar("flujo", 99_001, "ficticio", actor)
    assert trabajos.esperar(30)


def test_dos_flujos_distintos_hacen_cola():
    actor = _actor()
    a = trabajos.encolar("flujo", 99_002, "uno", actor)
    b = trabajos.encolar("flujo", 99_003, "dos", actor)
    assert a.id != b.id
    # Los dos estan vivos: uno corriendo o en cola, el otro esperando turno.
    e = trabajos.estado()
    assert len(e["corriendo"]) + len(e["en_cola"]) == 2
    assert all(not t["a_la_par"] for t in e["corriendo"] + e["en_cola"])
    assert trabajos.esperar(30)


def test_a_la_par_se_marca_como_tal():
    actor = _actor()
    t = trabajos.encolar("flujo", 99_004, "suelto", actor, a_la_par=True)
    assert t.a_la_par is True
    assert trabajos.esperar(30)


def test_la_cola_se_puede_mirar(cliente, cab_admin):
    r = cliente.get("/api/flujos/cola", headers=cab_admin)
    assert r.status_code == 200
    assert set(r.json()) == {"corriendo", "en_cola"}


def test_lo_que_ya_empezo_no_se_saca_de_la_cola(cliente, cab_admin):
    # Cortar a mitad de una ingesta deja el destino a medias y sin nadie que lo
    # cuente: se espera y se mira el historial.
    r = cliente.delete("/api/flujos/cola/999999", headers=cab_admin)
    assert r.status_code == 409


def test_un_flujo_que_ya_no_existe_no_tumba_al_trabajador():
    # El hilo de la cola es uno solo: si una excepcion escapa, el sistema se
    # queda sin trabajador en silencio hasta el siguiente reinicio.
    trabajos.encolar("flujo", 12_345_678, "borrado", _actor())
    assert trabajos.esperar(30)
    # Y sigue atendiendo lo siguiente.
    trabajos.encolar("flujo", 12_345_679, "otro", _actor())
    assert trabajos.esperar(30)


def _actor():
    from app.cargas import Actor
    return Actor(id=None, email="prueba@astrolabio")


def test_el_avance_se_ve_mientras_corre(cliente, cab_admin, transformacion_flujo):
    """
    Lo que motivo esto: veintiocho tablas escribiendose en el disco y la pantalla
    diciendo «todavia no ha corrido». El renglon de la corrida se confirmaba al
    final, asi que hasta entonces no existia para nadie mas.
    """
    from app.cargas import Actor
    from app.db import CrearSesion
    from app.flujos import ejecutar as ejecutar_flujo
    from app.modelos_db import EstadoCarga, Flujo, FlujoEjecucion

    id_ = crear_flujo(cliente, cab_admin, {
        "nombre": "con_avance",
        "pasos": [{"tipo": "transformacion", "id": transformacion_flujo}]})["id"]

    # Otra sesion, como la que atiende la peticion del navegador: solo ve lo
    # confirmado.
    with CrearSesion() as propia, CrearSesion() as mirona:
        f = propia.get(Flujo, id_)
        ejecutar_flujo(propia, f, Actor(id=None, email="prueba@astrolabio"))
        propia.commit()
        vistas = mirona.query(FlujoEjecucion).filter(
            FlujoEjecucion.flujo_id == id_).all()

    assert vistas, "la corrida no era visible desde fuera"
    ultima = vistas[-1]
    assert ultima.estado == EstadoCarga.exito
    assert ultima.detalle["total"] == 1
    assert [p["estado"] for p in ultima.detalle["pasos"]] == ["exito"]


def test_el_progreso_dice_por_que_paso_va(cliente, cab_admin, transformacion_flujo):
    from app.rutas.flujos import _progreso
    from app.modelos_db import EstadoCarga

    class _Falsa:
        estado = EstadoCarga.corriendo
        detalle = {"total": 28, "pasos": [
            {"paso": 1, "estado": "exito"}, {"paso": 2, "estado": "exito"},
            {"paso": 3, "estado": "corriendo"}]}

    assert _progreso(_Falsa()) == "3 de 28"
    # Terminada no hay nada que decir: para eso esta el resultado.
    _Falsa.estado = EstadoCarga.exito
    assert _progreso(_Falsa()) is None
