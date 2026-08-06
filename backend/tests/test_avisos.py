"""
Avisos de fallo.

Lo que hay que demostrar aqui no es que se mande un correo —eso lo hace smtplib—
sino las cuatro cosas que pueden hacer que un sistema de avisos sea peor que no
tener ninguno:

1. Que un aviso que no sale **no** tumbe la carga.
2. Que una carga rota cada 15 minutos no mande 96 correos.
3. Que despues del silencio alguien se entere de que ya se arreglo.
4. Que quede constancia del intento, tambien cuando fallo.

El canal se sustituye por una funcion que anota lo que se le pidio mandar. Probar
contra un servidor SMTP de verdad probaria smtplib, que ya esta probado.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app import avisos
from app.cargas import Actor, ErrorCarga, ejecutar_carga
from app.db import CrearSesion
from app.modelos_db import (
    AvisoEnviado, CargaEjecucion, Conexion, Dataset, EstadoCarga, ReglaAviso,
)
from app.seguridad import cifrar

# --------------------------------------------------------------------------- #
# Ayudas
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def sin_reglas_viejas():
    """
    Cada prueba arranca sin reglas.

    Las reglas son globales por diseño —"avísame de todo lo que falle"— asi que una
    regla que sobreviva de la prueba anterior dispara en la siguiente y la hace
    fallar por un motivo que no tiene nada que ver. La base de metadatos de
    pruebas vive toda la sesion.
    """
    with CrearSesion() as s:
        s.execute(delete(AvisoEnviado))
        s.execute(delete(ReglaAviso))
        s.commit()
    yield


class Canal:
    """Sustituye a `avisos.entregar`. Anota, y falla si se le pide."""

    def __init__(self, revienta: str | None = None):
        self.enviados: list[tuple[str, str, str]] = []
        self.revienta = revienta

    def __call__(self, canal: str, destino: str, asunto: str, cuerpo: str) -> None:
        if self.revienta:
            raise RuntimeError(self.revienta)
        self.enviados.append((canal, destino, asunto))


@pytest.fixture
def canal(monkeypatch):
    c = Canal()
    monkeypatch.setattr(avisos, "entregar", c)
    return c


def _regla(cliente, cab, **cambios) -> dict:
    cuerpo = {"nombre": f"regla_{datetime.now(timezone.utc).timestamp()}",
              "canal": "webhook", "destino": "https://ejemplo.invalido/aviso",
              "eventos": ["carga_fallida"], "silencio_minutos": 0}
    cuerpo.update(cambios)
    r = cliente.post("/api/avisos", headers=cab, json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Validacion
# --------------------------------------------------------------------------- #

def test_canal_desconocido_y_sin_eventos():
    errores = avisos.revisar("paloma", "x", [], 60)
    assert any("Canal desconocido" in e for e in errores)
    assert any("al menos un evento" in e for e in errores)


def test_recuperacion_sin_su_fallo_no_se_deja_guardar():
    """Una regla que solo pide 'recuperada' no dispararia nunca."""
    errores = avisos.revisar("webhook", "https://x.invalido",
                             ["carga_recuperada"], 60)
    assert any("no llega nunca" in e for e in errores)
    assert avisos.revisar("webhook", "https://x.invalido",
                          ["carga_fallida", "carga_recuperada"], 60) == []


def test_correo_mal_escrito_y_webhook_sin_esquema():
    assert any("no parece un correo" in e
               for e in avisos.revisar("correo", "sin-arroba.example.com",
                                       ["carga_fallida"], 60))
    assert any("http://" in e
               for e in avisos.revisar("webhook", "ejemplo.com/hook",
                                       ["carga_fallida"], 60))


def test_un_webhook_a_los_metadatos_de_la_nube_nunca_se_permite(monkeypatch):
    """
    169.254.169.254 entrega las credenciales de la maquina a quien las pida. Un
    webhook es una URL que escribe el usuario y visita el SERVIDOR, asi que sin
    esta guarda cualquier editor podria apuntar ahi.
    """
    motivo = avisos.destino_permitido("http://169.254.169.254/latest/meta-data/")
    assert motivo and "credenciales" in motivo
    # Ni siquiera encendiendo los webhooks a la red interna.
    monkeypatch.setattr(avisos.config(), "webhooks_a_red_interna", True)
    assert avisos.destino_permitido("http://169.254.169.254/x")


def test_la_red_interna_se_puede_encender_a_proposito(monkeypatch):
    assert avisos.destino_permitido("http://127.0.0.1:8899/hook")
    monkeypatch.setattr(avisos.config(), "webhooks_a_red_interna", True)
    assert avisos.destino_permitido("http://127.0.0.1:8899/hook") is None


def test_un_nombre_que_apunta_a_localhost_tampoco_pasa():
    """Mirar el texto de la URL no basta: hay que resolver el nombre."""
    assert avisos.destino_permitido("http://localhost/hook")


def test_varios_destinatarios_separados_como_sea():
    assert avisos.destinatarios("a@b.com, c@d.com; e@f.com") == \
        ["a@b.com", "c@d.com", "e@f.com"]


def test_correo_sin_configurar_lo_dice_y_el_webhook_no_lo_necesita():
    """En pruebas no hay SMTP; la regla se puede guardar pero no es cobertura."""
    listo, detalle = avisos.canal_listo("correo")
    assert listo is False and "ASTROLABIO_SMTP_HOST" in detalle
    assert avisos.canal_listo("webhook")[0] is True


def test_regla_de_dataset_con_evento_de_flujo_no_se_guarda(cliente, cab_editor):
    r = cliente.post("/api/avisos", headers=cab_editor, json={
        "nombre": "mezclada", "canal": "webhook", "destino": "https://x.invalido",
        "eventos": ["flujo_fallido"], "objeto_tipo": "dataset"})
    assert r.status_code == 422
    assert "eventos de flujo" in str(r.json()["detail"]["errores"])


def test_alcance_a_un_dataset_que_no_existe(cliente, cab_editor):
    r = cliente.post("/api/avisos", headers=cab_editor, json={
        "nombre": "fantasma", "canal": "webhook", "destino": "https://x.invalido",
        "eventos": ["carga_fallida"], "objeto_tipo": "dataset",
        "objeto_id": 999_999})
    assert r.status_code == 422


def test_nombre_repetido(cliente, cab_editor):
    uno = _regla(cliente, cab_editor)
    r = cliente.post("/api/avisos", headers=cab_editor, json={
        "nombre": uno["nombre"], "canal": "webhook",
        "destino": "https://x.invalido", "eventos": ["carga_fallida"]})
    assert r.status_code == 409


def test_lector_no_ve_los_avisos(cliente, cab_lector):
    assert cliente.get("/api/avisos", headers=cab_lector).status_code == 403


# --------------------------------------------------------------------------- #
# Probar la regla
# --------------------------------------------------------------------------- #

def test_probar_manda_ahora_sin_importar_eventos_ni_silencio(
        cliente, cab_editor, canal):
    regla = _regla(cliente, cab_editor, silencio_minutos=600)
    for _ in range(2):
        r = cliente.post(f"/api/avisos/{regla['id']}/probar", headers=cab_editor)
        assert r.status_code == 200 and r.json()["ok"] is True
    assert len(canal.enviados) == 2, "el silencio no debe aplicar a la prueba"
    assert "prueba" in canal.enviados[0][2].lower()


def test_probar_que_falla_contesta_200_con_el_error(cliente, cab_editor,
                                                    monkeypatch):
    """
    El fallo es el resultado util de esta ruta: dice que corregir. Devolver 400
    lo convertiria en un error de la peticion y el frontend lo pintaria como tal.
    """
    monkeypatch.setattr(avisos, "entregar", Canal(revienta="Name or service not known"))
    regla = _regla(cliente, cab_editor)
    r = cliente.post(f"/api/avisos/{regla['id']}/probar", headers=cab_editor)
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "Name or service not known" in r.json()["detalle"]

    envios = cliente.get("/api/avisos/historial", headers=cab_editor).json()["envios"]
    assert envios[0]["estado"] == "error", "el intento fallido tambien se guarda"


# --------------------------------------------------------------------------- #
# Disparo
# --------------------------------------------------------------------------- #

def _notificar(evento="carga_fallida", objeto_tipo="dataset", objeto_id=1):
    with CrearSesion() as s:
        salida = avisos.notificar(s, evento, objeto_tipo=objeto_tipo,
                                  objeto_id=objeto_id, asunto="asunto",
                                  cuerpo="cuerpo")
        s.commit()
    return salida


def test_solo_disparan_las_reglas_que_aplican(cliente, cab_editor, canal):
    _regla(cliente, cab_editor, nombre="todo", eventos=["carga_fallida"])
    _regla(cliente, cab_editor, nombre="solo_flujos", eventos=["flujo_fallido"],
           objeto_tipo="flujo")
    _regla(cliente, cab_editor, nombre="apagada", eventos=["carga_fallida"],
           activa=False)

    nombres = {x["regla"] for x in _notificar()}
    assert nombres == {"todo"}


def test_alcance_a_un_dataset_concreto(cliente, cab_editor, canal, conexion_archivo):
    ds_a, ds_b = conexion_archivo["dataset_ok"], conexion_archivo["dataset_roto"]
    _regla(cliente, cab_editor, nombre=f"solo_{ds_a}", eventos=["carga_fallida"],
           objeto_tipo="dataset", objeto_id=ds_a)

    assert [x["regla"] for x in _notificar(objeto_id=ds_a)] == [f"solo_{ds_a}"]
    assert _notificar(objeto_id=ds_b) == []


def test_el_silencio_manda_uno_y_calla_los_siguientes(cliente, cab_editor, canal):
    _regla(cliente, cab_editor, nombre="con_silencio", silencio_minutos=60)

    primero = _notificar()
    segundo = _notificar()
    assert primero[0]["estado"] == "enviado"
    assert segundo[0]["estado"] == "silenciado"
    assert len(canal.enviados) == 1
    # El silenciado se guarda: es la prueba de que hubo mas fallos que correos.
    assert "silencio" in segundo[0]["mensaje"]


def test_pasado_el_silencio_se_vuelve_a_avisar(cliente, cab_editor, canal):
    regla = _regla(cliente, cab_editor, nombre="silencio_corto",
                   silencio_minutos=30)
    _notificar()
    assert len(canal.enviados) == 1

    # Se envejece el envio en vez de esperar media hora.
    with CrearSesion() as s:
        e = s.scalars(
            select(AvisoEnviado).where(AvisoEnviado.regla_id == regla["id"])
            .order_by(AvisoEnviado.id.desc())).first()
        e.creado_en = datetime.now(timezone.utc).replace(tzinfo=None) - \
            timedelta(minutes=31)
        s.commit()

    assert _notificar()[0]["estado"] == "enviado"
    assert len(canal.enviados) == 2


def test_un_canal_caido_no_impide_registrar_el_intento(cliente, cab_editor,
                                                       monkeypatch):
    monkeypatch.setattr(avisos, "entregar", Canal(revienta="conexion rechazada"))
    _regla(cliente, cab_editor, nombre="canal_caido")
    salida = _notificar()
    assert salida[0]["estado"] == "error"
    assert "conexion rechazada" in salida[0]["mensaje"]


# --------------------------------------------------------------------------- #
# El camino completo: una carga que falla, y la misma que se recupera
# --------------------------------------------------------------------------- #

@pytest.fixture
def conexion_archivo(tmp_path_factory, cliente, cab_admin):
    """
    Una conexion de archivos con un CSV real y dos datasets: uno que apunta al
    CSV y otro a un archivo que no existe.

    Sirve para probar el camino completo sin depender de MySQL: el dataset roto
    falla de verdad dentro del conector, no en un mock.
    """
    carpeta = tmp_path_factory.mktemp("avisos_origen")
    with open(carpeta / "ventas.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "importe"])
        w.writerow([1, "100.50"])
        w.writerow([2, "200.25"])

    with CrearSesion() as s:
        # json.dumps, no una f-string: en Windows la ruta lleva '\' y pegarla a
        # mano produce JSON invalido ("C:\Users" tiene un \U que no es escape).
        # En Linux colaba, y esa clase de fallo solo aparece en el servidor.
        con = Conexion(nombre=f"archivos_avisos_{carpeta.name}", tipo="archivo",
                       config_cifrada=cifrar(json.dumps({"ruta_base": str(carpeta)})))
        s.add(con)
        s.flush()
        ok = Dataset(nombre=f"ventas_ok_{carpeta.name}", conexion_id=con.id,
                     tabla_origen="ventas.csv")
        roto = Dataset(nombre=f"ventas_roto_{carpeta.name}", conexion_id=con.id,
                       tabla_origen="no_existe.csv")
        s.add_all([ok, roto])
        s.commit()
        return {"conexion": con.id, "dataset_ok": ok.id, "dataset_roto": roto.id,
                "carpeta": carpeta}


def _cargar(dataset_id: int) -> str:
    with CrearSesion() as s:
        ds = s.get(Dataset, dataset_id)
        try:
            ejecutar_carga(s, ds, Actor.programador())
            s.commit()
            return "exito"
        except ErrorCarga:
            return "error"


def test_una_carga_que_falla_avisa_y_dice_de_cuando_son_los_datos(
        cliente, cab_editor, canal, conexion_archivo):
    _regla(cliente, cab_editor, nombre="avisa_cargas",
           eventos=["carga_fallida", "carga_recuperada"])

    assert _cargar(conexion_archivo["dataset_roto"]) == "error"

    assert len(canal.enviados) == 1
    _, _, asunto = canal.enviados[0]
    assert "Falló la carga" in asunto


def test_un_canal_caido_no_tumba_la_carga(monkeypatch, cliente, cab_editor,
                                          conexion_archivo):
    """
    Lo mas importante del modulo: si el aviso reventara hacia arriba, una carga
    buena fallaria por culpa del servidor de correo.
    """
    monkeypatch.setattr(avisos, "entregar", Canal(revienta="SMTP caido"))
    _regla(cliente, cab_editor, nombre="rompe_al_avisar",
           eventos=["carga_fallida", "carga_recuperada"])

    # La que falla sigue fallando por SU motivo, no por el aviso.
    with CrearSesion() as s:
        ds = s.get(Dataset, conexion_archivo["dataset_roto"])
        with pytest.raises(ErrorCarga) as e:
            ejecutar_carga(s, ds, Actor.programador())
    assert "no_existe.csv" in str(e.value)

    # Y la buena sale bien.
    assert _cargar(conexion_archivo["dataset_ok"]) == "exito"


def test_avisa_cuando_se_recupera(cliente, cab_editor, canal, conexion_archivo):
    _regla(cliente, cab_editor, nombre="avisa_recuperacion",
           eventos=["carga_fallida", "carga_recuperada"])
    ds_id = conexion_archivo["dataset_ok"]

    # Se fuerza una corrida fallida previa del MISMO dataset.
    with CrearSesion() as s:
        s.add(CargaEjecucion(dataset_id=ds_id, estado=EstadoCarga.error,
                             modo="completo", origen="programado",
                             mensaje="fallo anterior"))
        s.commit()

    assert _cargar(ds_id) == "exito"

    asuntos = [a for _, _, a in canal.enviados]
    assert any("Ya cargó bien" in a for a in asuntos), asuntos


def test_dos_exitos_seguidos_no_avisan(cliente, cab_editor, canal,
                                       conexion_archivo):
    """El aviso de recuperacion es solo despues de un fallo."""
    _regla(cliente, cab_editor, nombre="sin_ruido",
           eventos=["carga_fallida", "carga_recuperada"])
    _cargar(conexion_archivo["dataset_ok"])
    canal.enviados.clear()
    assert _cargar(conexion_archivo["dataset_ok"]) == "exito"
    assert canal.enviados == []


# --------------------------------------------------------------------------- #
# Flujos
# --------------------------------------------------------------------------- #

def test_un_flujo_detenido_avisa_y_dice_que_no_corrio(cliente, cab_editor, canal,
                                                      conexion_archivo):
    from app.flujos import ErrorFlujo
    from app.flujos import ejecutar as ejecutar_flujo
    from app.modelos_db import Flujo

    _regla(cliente, cab_editor, nombre="avisa_flujos",
           eventos=["flujo_fallido"], objeto_tipo="flujo")

    with CrearSesion() as s:
        f = Flujo(nombre=f"flujo_avisos_{conexion_archivo['dataset_roto']}",
                  pasos=[{"tipo": "carga", "id": conexion_archivo["dataset_roto"],
                          "nombre": "roto"},
                         {"tipo": "carga", "id": conexion_archivo["dataset_ok"],
                          "nombre": "el_bueno"}],
                  al_fallar="detener")
        s.add(f)
        s.commit()
        with pytest.raises(ErrorFlujo):
            ejecutar_flujo(s, f, Actor.programador())

    asuntos = [a for _, _, a in canal.enviados]
    assert any("Se detuvo el flujo" in a for a in asuntos), asuntos


def test_el_historial_muestra_enviados_y_silenciados(cliente, cab_editor, canal):
    _regla(cliente, cab_editor, nombre="para_historial", silencio_minutos=60)
    _notificar()
    _notificar()
    envios = cliente.get("/api/avisos/historial", headers=cab_editor).json()["envios"]
    estados = [e["estado"] for e in envios if e["regla"] == "para_historial"]
    assert estados[:2] == ["silenciado", "enviado"]
