"""
La cola de corridas a mano.

Lo que se protege: que lanzar un flujo conteste enseguida en vez de tener la
peticion abierta durante minutos —de ahi salia el 502 con veintiocho tablas—,
que dos corridas de lo mismo no se pisen, y que dos flujos distintos hagan cola
salvo que se pida lo contrario a proposito.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text as sa_text

from app import trabajos
from tests.test_flujos import (           # noqa: F401
    correr,
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


# --------------------------------------------------------------------------- #
# Reintentos
# --------------------------------------------------------------------------- #

def test_un_paso_que_falla_se_reintenta(cliente, cab_admin,
                                        conexion_archivos_etl, monkeypatch):
    """
    El caso real: la sucursal esta apagada a las seis de la manana y a los dos
    minutos ya no lo esta. Antes el flujo se detenia y no lo volvia a intentar.
    """
    from app.conectores import archivos

    id_ = crear_flujo(cliente, cab_admin, {
        "nombre": "con_reintentos",
        "reintentos": 2,
        "espera_reintento_seg": 0,
        "pasos": [{"tipo": "carga", "id": conexion_archivos_etl}]})["id"]

    intentos = {"n": 0}
    original = archivos.ConectorArchivos.ingestar

    def falla_las_dos_primeras(self, p, ruta_destino):
        intentos["n"] += 1
        if intentos["n"] <= 2:
            raise RuntimeError("la sucursal no contesta")
        return original(self, p, ruta_destino)

    monkeypatch.setattr(archivos.ConectorArchivos, "ingestar",
                        falla_las_dos_primeras)

    d = correr(cliente, cab_admin, id_)
    assert intentos["n"] == 3
    assert d["estado"] == "exito"
    # Un exito al tercer intento NO es lo mismo que un exito: queda anotado, o
    # el origen que va mal se esconde detras del reintento.
    assert d["pasos"][0]["intentos"] == 3


def test_agotados_los_reintentos_falla_y_lo_dice(cliente, cab_admin,
                                                 conexion_archivos_etl,
                                                 monkeypatch):
    from app.conectores import archivos

    id_ = crear_flujo(cliente, cab_admin, {
        "nombre": "reintentos_agotados",
        "reintentos": 1,
        "espera_reintento_seg": 0,
        "pasos": [{"tipo": "carga", "id": conexion_archivos_etl}]})["id"]

    def siempre_falla(self, p, ruta_destino):
        raise RuntimeError("la sucursal no contesta")

    monkeypatch.setattr(archivos.ConectorArchivos, "ingestar", siempre_falla)

    d = correr(cliente, cab_admin, id_)
    assert d["estado"] == "error"
    assert d["pasos"][0]["intentos"] == 2
    assert "2 intentos" in d["mensaje"]


def test_sin_reintentos_se_intenta_una_sola_vez(cliente, cab_admin,
                                                conexion_archivos_etl,
                                                monkeypatch):
    """
    Cero por omision: reintentar sin que nadie lo pida esconde un origen que va
    mal, y la primera vez que algo falla hay que verlo.
    """
    from app.conectores import archivos

    id_ = crear_flujo(cliente, cab_admin, {
        "nombre": "sin_reintentos",
        "pasos": [{"tipo": "carga", "id": conexion_archivos_etl}]})["id"]

    intentos = {"n": 0}

    def siempre_falla(self, p, ruta_destino):
        intentos["n"] += 1
        raise RuntimeError("la sucursal no contesta")

    monkeypatch.setattr(archivos.ConectorArchivos, "ingestar", siempre_falla)

    d = correr(cliente, cab_admin, id_)
    assert intentos["n"] == 1
    assert d["estado"] == "error"
    assert "intentos" not in d["pasos"][0]


# --------------------------------------------------------------------------- #
# La carga suelta tambien va por la cola
# --------------------------------------------------------------------------- #

def test_cargar_un_dataset_contesta_enseguida(cliente, cab_admin,
                                              conexion_archivos_etl):
    r = cliente.post(f"/api/conexiones/datasets/{conexion_archivos_etl}/cargar",
                     headers=cab_admin)
    assert r.status_code == 202, r.text
    assert r.json()["trabajo_id"] > 0
    assert trabajos.esperar(60)


def test_el_mismo_dataset_dos_veces_se_rechaza(cliente, cab_admin,
                                               conexion_archivos_etl):
    # Dos cargas del mismo dataset a la vez escriben los mismos Parquet.
    from app.conectores import archivos

    original = archivos.ConectorArchivos.ingestar
    segunda = {}

    def espiado(self, p, ruta_destino):
        r = cliente.post(
            f"/api/conexiones/datasets/{conexion_archivos_etl}/cargar",
            headers=cab_admin)
        segunda["codigo"] = r.status_code
        return original(self, p, ruta_destino)

    import pytest as _pytest
    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(archivos.ConectorArchivos, "ingestar", espiado)
    try:
        cliente.post(f"/api/conexiones/datasets/{conexion_archivos_etl}/cargar",
                     headers=cab_admin)
        assert trabajos.esperar(60)
    finally:
        monkeypatch.undo()
    assert segunda.get("codigo") == 409


# --------------------------------------------------------------------------- #
# Detener lo que ya arranco
# --------------------------------------------------------------------------- #

def _registrar_corriendo(tipo: str, objeto_id: int, nombre: str,
                         estado: str = "corriendo"):
    """
    Mete un trabajo en el registro sin encolarlo, para poder mirarlo quieto.

    Encolar de verdad lo pone en manos del trabajador, que lo termina cuando le
    toca: comprobar su estado seria una carrera.
    """
    from datetime import datetime, timezone

    with trabajos._reg.candado:
        t = trabajos.Trabajo(
            id=trabajos._reg.siguiente_id, tipo=tipo, objeto_id=objeto_id,
            nombre=nombre, actor_id=None, actor_email="prueba@astrolabio",
            a_la_par=False, encolado_en=datetime.now(timezone.utc),
            estado=estado)
        trabajos._reg.siguiente_id += 1
        trabajos._reg.vivos[t.id] = t
    return t


def test_detener_un_flujo_que_corre_no_corta_el_paso_en_curso(
        cliente, cab_admin, monkeypatch):
    """
    La garantia que importa: se para ENTRE pasos, nunca a media tabla.

    Cortar la ingesta en curso seria peor que esperarla — el destino se borra
    ANTES de escribir, asi que una recarga completa cortada en el momento justo
    deja el dataset vacio. Aqui se comprueba que el paso que estaba corriendo
    llega a terminar, y que los que faltan quedan como cancelados.
    """
    from app import flujos, trabajos
    from app.cargas import Actor
    from app.db import CrearSesion
    from app.modelos_db import EstadoCarga, Flujo

    hechos: list[int] = []
    parar_en = 2

    def falso_paso(sesion, ds, actor, **kw):
        hechos.append(len(hechos) + 1)
        if len(hechos) == parar_en:
            # A mitad del segundo paso alguien pide parar. El paso TIENE que
            # terminar: devuelve su resultado como cualquier otro.
            for t in trabajos.estado()["corriendo"]:
                trabajos.cancelar(t["id"])
        return {"filas": 7, "modo": "completo", "ms": 1}

    monkeypatch.setattr(flujos, "ejecutar_carga", falso_paso)

    with CrearSesion() as s:
        f = Flujo(nombre="para_detener", pasos=[], al_fallar="detener")
        s.add(f)
        s.flush()
        # Cuatro pasos al mismo dataset: da igual cual, la carga esta simulada.
        ds_id = s.execute(
            sa_text("SELECT id FROM dataset LIMIT 1")).scalar()
        f.pasos = [{"tipo": "carga", "id": ds_id, "nombre": f"p{i}"}
                   for i in range(1, 5)]
        s.commit()
        flujo_id = f.id

    trabajos.encolar("flujo", flujo_id, "para_detener",
                     Actor(id=None, email="prueba@astrolabio"))
    assert trabajos.esperar(30)

    with CrearSesion() as s:
        ejec = s.get(Flujo, flujo_id).ejecuciones[0]
        pasos = ejec.detalle["pasos"]
        # El segundo termino: es el paso que corria cuando se pidio parar.
        assert [p["estado"] for p in pasos[:2]] == ["exito", "exito"]
        # Y del tercero en adelante, nadie los intento.
        assert all(p["estado"] == "cancelado" for p in pasos[2:])
        assert ejec.estado == EstadoCarga.cancelado
        assert "2 de 4" in ejec.mensaje

    # Lo que de verdad se protege: no se llamo al tercero.
    assert hechos == [1, 2]


def test_detener_es_cancelado_y_no_error(cliente, cab_admin):
    """
    Un flujo que alguien paro no salio mal.

    Si se guardara como `error`, la pantalla lo pintaria en rojo como una averia
    y —peor— saldria el aviso de fallo por correo. Un correo de alarma por algo
    que acaba de hacer quien opera es la forma de que esos correos se dejen de
    leer.
    """
    from app.modelos_db import EstadoCarga

    assert EstadoCarga.cancelado.value == "cancelado"
    assert EstadoCarga.cancelado != EstadoCarga.error


def test_no_se_puede_cortar_una_carga_suelta(cliente, cab_admin):
    """
    Una carga no tiene pasos donde pararse: o termina, o se corta a la mitad.
    Se dice, en vez de fingir que se hizo algo.
    """
    from app import trabajos

    # Se registra a mano, sin encolar: si se encola, el trabajador la levanta y
    # la termina antes de la comprobacion, y la prueba pasa o falla segun quien
    # llegue primero. Una prueba que a veces pasa es peor que una que falla.
    t = _registrar_corriendo("carga", 999999, "inventada")
    assert trabajos.cancelar(t.id) == "no_se_puede"

    r = cliente.delete(f"/api/flujos/cola/{t.id}", headers=cab_admin)
    assert r.status_code == 409
    assert "esperarla" in r.json()["detail"]

    # Limpieza: si se queda vivo, `esperar()` de otras pruebas no vuelve.
    trabajos._reg.vivos.pop(t.id, None)


def test_sacar_de_la_cola_sigue_diciendo_que_se_saco(cliente, cab_admin):
    from app import trabajos

    t = _registrar_corriendo("carga", 888888, "en_espera", estado="en_cola")
    assert trabajos.cancelar(t.id) == "sacado"
    assert trabajos.cancelar(t.id) is None      # ya no esta
