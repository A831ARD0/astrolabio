"""
Cuantas filas lleva una carga en marcha.

Antes solo decia "Corriendo…", y con tres minutos de espera contra un origen
lento eso no distingue trabajar de estar atorado. Se cuenta lo unico que se puede
saber: filas traidas. No hay porcentaje porque no hay total —el origen no dice
cuantas va a devolver sin contarlas antes— y una barra que se inventa el total
miente justo cuando mas se la mira.
"""

from __future__ import annotations

from app import trabajos
from app.conectores.base import PeticionIngesta, avisar_avance


def _peticion(**kw) -> PeticionIngesta:
    return PeticionIngesta(**{"esquema": None, "tabla": "t", "destino": "d", **kw})


def test_sin_nadie_escuchando_no_pasa_nada():
    avisar_avance(_peticion(), 10)      # no revienta


def test_el_aviso_llega():
    visto = []
    avisar_avance(_peticion(avisar=visto.append), 20_000)
    assert visto == [20_000]


def test_un_aviso_que_revienta_no_tumba_la_carga():
    """
    Lo importante de todo esto: informar es un adorno. Un fallo aqui no puede
    tirar una ingesta de tres minutos que ya va por la mitad.
    """
    def explota(_n):
        raise RuntimeError("se cayo el registro")

    avisar_avance(_peticion(avisar=explota), 40_000)


def test_se_anota_y_se_consulta_por_objeto():
    from datetime import datetime, timezone

    t = trabajos.Trabajo(
        id=9_001, tipo="carga", objeto_id=77, nombre="ds", actor_id=None,
        actor_email="x@y", a_la_par=False, encolado_en=datetime.now(timezone.utc))
    t.estado = "corriendo"
    with trabajos._reg.candado:
        trabajos._reg.vivos[t.id] = t
    try:
        assert trabajos.avance_de("carga", 77) == 0
        trabajos.anotar_avance(t.id, 60_000)
        assert trabajos.avance_de("carga", 77) == 60_000
        assert t.como_dict()["traidas"] == 60_000

        # De otro objeto, o de otro tipo, no es.
        assert trabajos.avance_de("carga", 78) is None
        assert trabajos.avance_de("flujo", 77) is None
    finally:
        with trabajos._reg.candado:
            trabajos._reg.vivos.pop(t.id, None)


def test_un_trabajo_en_cola_todavia_no_tiene_avance():
    """En cola no ha traido nada, y decir 0 haria pensar que ya empezo."""
    from datetime import datetime, timezone

    t = trabajos.Trabajo(
        id=9_002, tipo="carga", objeto_id=78, nombre="ds", actor_id=None,
        actor_email="x@y", a_la_par=False, encolado_en=datetime.now(timezone.utc))
    with trabajos._reg.candado:
        trabajos._reg.vivos[t.id] = t
    try:
        assert trabajos.avance_de("carga", 78) is None
    finally:
        with trabajos._reg.candado:
            trabajos._reg.vivos.pop(t.id, None)


def test_anotar_sobre_un_trabajo_que_ya_termino_no_revienta():
    """La carrera real: el ultimo bloque avisa cuando el trabajo ya se retiro."""
    trabajos.anotar_avance(9_999, 1)
