"""
Continuar una corrida que se detuvo o falló.

Volver a correr treinta y ocho extractores porque el número veinte falló es lo que
esto evita. Pero reanudar tiene un filo: **mezcla dos momentos**, lo que se trajo a
la una y lo que se trae a las seis. Para cuarenta sucursales independientes eso da
igual; para una transformación que ya corrió con los datos viejos, no.

De ahí las reglas que se protegen aquí:

- se salta lo que ya salió bien, **pero solo cargas y flujos**;
- una **transformación se rehace siempre**, aunque hubiera salido bien;
- los pasos se reconocen por su **identidad**, no por su número: entre pausar y
  continuar el flujo puede haberse editado;
- nadie continúa dos veces la misma corrida;
- y también se continúan las **fallidas**, que es el caso frecuente.
"""

from __future__ import annotations

import itertools

import pytest

from app import flujos as mod_flujos
from app import trabajos
from app.cargas import Actor
from app.db import CrearSesion
from app.modelos_db import EstadoCarga, Flujo, FlujoEjecucion
from tests.test_flujos import (           # noqa: F401
    correr, crear_flujo, transformacion_flujo,
)

_n = itertools.count()


@pytest.fixture
def ids(cliente, cab_admin, conexion_archivos_etl, transformacion_flujo):
    """
    Cuatro datasets y una transformación que existan.

    Aquí solo tienen que EXISTIR: la carga y la transformación van simuladas, y lo
    que se prueba es el ejecutor —qué se salta y qué no—, no la ingesta.
    """
    from app.modelos_db import Conexion, Dataset

    with CrearSesion() as s:
        conexion = s.get(Dataset, conexion_archivos_etl).conexion_id
        assert s.get(Conexion, conexion) is not None
        cargas = [conexion_archivos_etl]
        for i in range(3):
            nombre = f"reanudar_ds_{i}"
            ya = s.query(Dataset).filter(Dataset.nombre == nombre).one_or_none()
            if ya is None:
                ya = Dataset(conexion_id=conexion, nombre=nombre,
                             tabla_origen="ventas.csv")
                s.add(ya)
                s.flush()
            cargas.append(ya.id)
        s.commit()
    return cargas, transformacion_flujo


def _flujo_con(pasos: list[dict]) -> int:
    """Un flujo directo en la base: aquí interesa el ejecutor, no la API."""
    with CrearSesion() as s:
        f = Flujo(nombre=f"reanudable_{next(_n)}", pasos=pasos, al_fallar="detener")
        s.add(f)
        s.commit()
        return f.id


def _correr(flujo_id: int, **kw) -> FlujoEjecucion:
    with CrearSesion() as s:
        f = s.get(Flujo, flujo_id)
        try:
            mod_flujos.ejecutar(s, f, Actor(id=None, email="p@astrolabio"), **kw)
        except mod_flujos.ErrorFlujo:
            pass
        s.commit()
    with CrearSesion() as s:
        return s.get(Flujo, flujo_id).ejecuciones[0]


def _estados(ejec: FlujoEjecucion) -> list[str]:
    return [p["estado"] for p in ejec.detalle["pasos"]]


# --------------------------------------------------------------------------- #
# Lo que se salta y lo que no
# --------------------------------------------------------------------------- #

def test_se_salta_la_carga_hecha_y_se_rehace_la_transformacion(
        cliente, cab_admin, ids, monkeypatch):
    """
    La regla que evita un número falso.

    Una carga que ya salió bien se salta —traerla otra vez no cambia nada—. Una
    transformación NO: si se saltara, se quedaría con el resultado de la una
    mientras los datasets que lee se actualizan a las seis, y eso es exactamente
    un número que parece fresco y no lo es.
    """
    cargas, trans = ids
    flujo_id = _flujo_con([
        {"tipo": "carga", "id": cargas[0], "nombre": "c1"},
        {"tipo": "transformacion", "id": trans, "nombre": "t1"},
        {"tipo": "carga", "id": cargas[1], "nombre": "c2"},
    ])

    hechas: list[str] = []
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: (hechas.append(f"carga:{ds.id}"),
                                               {"filas": 1, "modo": "completo",
                                                "ms": 1})[1])
    monkeypatch.setattr(mod_flujos, "ejecutar_transformacion",
                        lambda s, t, a, **k: (hechas.append("trans"),
                                              {"filas": 1, "ms": 1})[1])

    primera = _correr(flujo_id)
    assert _estados(primera) == ["exito", "exito", "exito"]

    # Se continúa como si la primera se hubiera pausado: se salta lo que hizo.
    hechas.clear()
    segunda = _correr(flujo_id, saltar=mod_flujos.hechos_en(primera),
                      reanuda_a=primera.id)

    assert _estados(segunda) == ["saltado", "exito", "saltado"]
    # Lo que de verdad importa: la transformación SÍ se volvió a correr, y
    # ninguna carga se repitió.
    assert hechas == ["trans"]


def test_reanudar_desde_una_corrida_detenida_no_repite_lo_hecho(
        cliente, cab_admin, ids, monkeypatch):
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": c, "nombre": f"c{i}"}
                           for i, c in enumerate(cargas, start=1)])

    traidas: list[int] = []

    def carga(s, ds, a, **k):
        traidas.append(ds.id)
        return {"filas": 1, "modo": "completo", "ms": 1}

    monkeypatch.setattr(mod_flujos, "ejecutar_carga", carga)

    # Se para despues del segundo paso.
    hecho = {"n": 0}

    def parar() -> bool:
        hecho["n"] += 1
        return hecho["n"] > 2

    primera = _correr(flujo_id, parar=parar)
    assert primera.estado == EstadoCarga.cancelado
    assert _estados(primera) == ["exito", "exito", "cancelado", "cancelado"]
    assert traidas == cargas[:2]

    traidas.clear()
    segunda = _correr(flujo_id, saltar=mod_flujos.hechos_en(primera),
                      reanuda_a=primera.id)

    assert segunda.estado == EstadoCarga.exito
    assert _estados(segunda) == ["saltado", "saltado", "exito", "exito"]
    assert traidas == cargas[2:4]        # solo las que faltaban


def test_un_paso_editado_no_se_salta_por_su_numero(cliente, cab_admin, ids,
                                                   monkeypatch):
    """
    Los pasos se reconocen por lo que SON.

    Si se reanudara por posición, meter una tabla nueva en el primer sitio haría
    que «continuar en el paso 3» apuntara a otra tabla, y la que se colocó delante
    no se traería nunca.
    """
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"},
                           {"tipo": "carga", "id": cargas[1], "nombre": "c2"}])

    traidas: list[int] = []
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: (traidas.append(ds.id),
                                               {"filas": 1, "modo": "completo",
                                                "ms": 1})[1])
    primera = _correr(flujo_id)

    # Alguien mete otra tabla DELANTE mientras estaba pausado.
    with CrearSesion() as s:
        f = s.get(Flujo, flujo_id)
        f.pasos = [{"tipo": "carga", "id": cargas[2], "nombre": "nueva"}] + f.pasos
        s.commit()

    traidas.clear()
    segunda = _correr(flujo_id, saltar=mod_flujos.hechos_en(primera),
                      reanuda_a=primera.id)

    # La nueva se trae; las dos viejas se saltan. Por identidad, no por numero.
    assert _estados(segunda) == ["exito", "saltado", "saltado"]
    assert traidas == [cargas[2]]


def test_un_paso_sin_id_en_el_historial_se_vuelve_a_correr(cliente, cab_admin,
                                                           ids, monkeypatch):
    """
    Las corridas de antes de guardar el id no llevan con qué reconocerse.

    Ante la duda se repite el trabajo, que es gratis, en vez de saltarse una tabla,
    que no lo es.
    """
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"}])
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: {"filas": 1, "modo": "completo",
                                               "ms": 1})
    primera = _correr(flujo_id)

    with CrearSesion() as s:
        e = s.get(FlujoEjecucion, primera.id)
        e.detalle = {"pasos": [{"paso": 1, "tipo": "carga", "nombre": "c1",
                                "estado": "exito"}], "total": 1}
        s.commit()
        assert mod_flujos.hechos_en(e) == set()


# --------------------------------------------------------------------------- #
# El plan, y quien puede continuar
# --------------------------------------------------------------------------- #

def test_el_plan_dice_que_salta_que_corre_y_que_desaparecio(cliente, cab_admin,
                                                            ids, monkeypatch):
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"},
                           {"tipo": "carga", "id": cargas[1], "nombre": "c2"}])
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: {"filas": 1, "modo": "completo",
                                               "ms": 1})
    primera = _correr(flujo_id)

    # Se quita c2 del flujo y se agrega otra.
    with CrearSesion() as s:
        f = s.get(Flujo, flujo_id)
        f.pasos = [{"tipo": "carga", "id": cargas[0], "nombre": "c1"},
                   {"tipo": "carga", "id": cargas[2], "nombre": "c3"}]
        s.commit()
        plan = mod_flujos.plan_de_reanudacion(f, s.get(FlujoEjecucion, primera.id))

    assert [p["nombre"] for p in plan["saltaria"]] == ["c1"]
    assert [p["nombre"] for p in plan["correria"]] == ["c3"]
    assert [p["nombre"] for p in plan["ausentes"]] == ["c2"]


def test_una_corrida_con_exito_no_es_reanudable(cliente, cab_admin, ids,
                                                monkeypatch):
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"}])
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: {"filas": 1, "modo": "completo",
                                               "ms": 1})
    assert not mod_flujos.reanudable(_correr(flujo_id))


def test_una_corrida_fallida_si_es_reanudable(cliente, cab_admin, ids,
                                              monkeypatch):
    """
    El caso frecuente: la sucursal veinte estaba apagada a las seis. Volver a
    correr las treinta y ocho por una es lo que esto evita.
    """
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"},
                           {"tipo": "carga", "id": cargas[1], "nombre": "c2"}])

    from app.cargas import ErrorCarga

    def carga(s, ds, a, **k):
        if ds.id == cargas[1]:
            raise ErrorCarga("la sucursal estaba apagada")
        return {"filas": 1, "modo": "completo", "ms": 1}

    monkeypatch.setattr(mod_flujos, "ejecutar_carga", carga)
    primera = _correr(flujo_id)
    assert primera.estado == EstadoCarga.error
    assert mod_flujos.reanudable(primera)
    assert mod_flujos.hechos_en(primera) == {("carga", cargas[0])}


# --------------------------------------------------------------------------- #
# La cadena, por la API
# --------------------------------------------------------------------------- #

def test_reanudar_por_la_api_encadena_las_dos_corridas(cliente, cab_admin, ids,
                                                       monkeypatch):
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"},
                           {"tipo": "carga", "id": cargas[1], "nombre": "c2"}])
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: {"filas": 1, "modo": "completo",
                                               "ms": 1})

    hecho = {"n": 0}

    def parar() -> bool:
        hecho["n"] += 1
        return hecho["n"] > 1

    primera = _correr(flujo_id, parar=parar)
    assert primera.estado == EstadoCarga.cancelado

    h = cliente.get(f"/api/flujos/{flujo_id}/historial", headers=cab_admin).json()
    fila = h["ejecuciones"][0]
    assert fila["reanudable"] is True
    assert (fila["saltaria"], fila["correria"]) == (1, 1)

    r = cliente.post(f"/api/flujos/{flujo_id}/reanudar/{primera.id}",
                     headers=cab_admin)
    assert r.status_code == 202, r.text
    assert r.json() == {**r.json(), "continua_de": primera.id,
                        "pasos": 1, "saltados": 1}
    assert trabajos.esperar(30)

    h = cliente.get(f"/api/flujos/{flujo_id}/historial", headers=cab_admin).json()
    nueva, vieja = h["ejecuciones"][0], h["ejecuciones"][1]
    assert nueva["estado"] == "exito"
    assert nueva["reanuda_a"] == primera.id
    assert vieja["reanudada_por"] == nueva["id"]
    # Y la vieja ya no se puede volver a continuar.
    assert vieja["reanudable"] is False


def test_nadie_continua_dos_veces_la_misma_corrida(cliente, cab_admin, ids,
                                                   monkeypatch):
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"},
                           {"tipo": "carga", "id": cargas[1], "nombre": "c2"}])
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: {"filas": 1, "modo": "completo",
                                               "ms": 1})
    hecho = {"n": 0}
    primera = _correr(flujo_id,
                      parar=lambda: (hecho.__setitem__("n", hecho["n"] + 1)
                                     or hecho["n"] > 1))
    assert primera.estado == EstadoCarga.cancelado

    assert cliente.post(f"/api/flujos/{flujo_id}/reanudar/{primera.id}",
                        headers=cab_admin).status_code == 202
    assert trabajos.esperar(30)

    r = cliente.post(f"/api/flujos/{flujo_id}/reanudar/{primera.id}",
                     headers=cab_admin)
    assert r.status_code == 409
    assert "ya la continuo" in r.json()["detail"]


def test_no_se_reanuda_una_corrida_que_salio_entera(cliente, cab_admin, ids,
                                                    monkeypatch):
    cargas, _ = ids
    flujo_id = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"}])
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: {"filas": 1, "modo": "completo",
                                               "ms": 1})
    ejec = _correr(flujo_id)

    r = cliente.post(f"/api/flujos/{flujo_id}/reanudar/{ejec.id}",
                     headers=cab_admin)
    assert r.status_code == 409
    assert "no hay nada que continuar" in r.json()["detail"]


def test_no_se_reanuda_una_corrida_de_otro_flujo(cliente, cab_admin, ids,
                                                 monkeypatch):
    cargas, _ = ids
    uno = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "c1"}])
    otro = _flujo_con([{"tipo": "carga", "id": cargas[1], "nombre": "c2"}])
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: {"filas": 1, "modo": "completo",
                                               "ms": 1})
    ejec = _correr(uno)

    r = cliente.post(f"/api/flujos/{otro}/reanudar/{ejec.id}", headers=cab_admin)
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Los hijos se reanudan solos
# --------------------------------------------------------------------------- #

def test_reanudar_un_maestro_re_entra_en_el_hijo_a_medias(cliente, cab_admin,
                                                          ids, monkeypatch):
    """
    Lo que hace esto útil con treinta y ocho por veintiocho.

    Reanudar el maestro no vuelve a traer mil sesenta y cuatro tablas: vuelve a
    entrar en el hijo que se quedó a medias y sigue donde estaba.
    """
    cargas, _ = ids
    hijo_a = _flujo_con([{"tipo": "carga", "id": cargas[0], "nombre": "a1"},
                         {"tipo": "carga", "id": cargas[1], "nombre": "a2"}])
    hijo_b = _flujo_con([{"tipo": "carga", "id": cargas[2], "nombre": "b1"}])
    maestro = _flujo_con([{"tipo": "flujo", "id": hijo_a, "nombre": "hijo_a"},
                          {"tipo": "flujo", "id": hijo_b, "nombre": "hijo_b"}])

    traidas: list[int] = []
    monkeypatch.setattr(mod_flujos, "ejecutar_carga",
                        lambda s, ds, a, **k: (traidas.append(ds.id),
                                               {"filas": 1, "modo": "completo",
                                                "ms": 1})[1])

    # Se para tras la primera tabla del primer hijo.
    hecho = {"n": 0}

    def parar() -> bool:
        hecho["n"] += 1
        return hecho["n"] > 2      # maestro paso 1 + hijo_a paso 1

    primera = _correr(maestro, parar=parar)
    assert primera.estado == EstadoCarga.cancelado
    assert traidas == [cargas[0]]

    traidas.clear()
    segunda = _correr(maestro, saltar=mod_flujos.hechos_en(primera),
                      reanuda_a=primera.id)

    assert segunda.estado == EstadoCarga.exito
    # No se trajo otra vez la tabla que hijo_a ya tenia.
    assert traidas == [cargas[1], cargas[2]]
    with CrearSesion() as s:
        dentro = s.get(Flujo, hijo_a).ejecuciones[0]
        assert _estados(dentro) == ["saltado", "exito"]
