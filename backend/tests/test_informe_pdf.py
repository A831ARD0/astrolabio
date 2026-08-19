"""
El informe como archivo, hecho en el servidor.

Aqui no se levanta Chromium: lo que se fija es el CONTRATO alrededor del
renderizador, que es lo que se rompe sin que nadie lo note.

  - La URL que se abre lleva la hoja y el modo informe, y el token NO va en la URL:
    una URL con el token dentro acaba en el historial, en los registros del servidor
    web y en la barra de direcciones de quien reciba el enlace.
  - Si falta el navegador, la respuesta lo DICE y con la orden para instalarlo, en vez
    de un 500 que parece un fallo del programa.
  - Un lector no saca el informe de un tablero que no esta publicado: el archivo es
    otra forma de leer los datos, y las reglas son las mismas.

El camino completo —Chromium de verdad, la hoja medida y el PDF de una pagina— se
comprueba a mano contra la aplicacion corriendo, porque necesita el servidor de la
interfaz levantado y eso no cabe en la suite.
"""

import pytest

from app import informe_pdf


@pytest.fixture
def tablero(cliente, cab_admin, yaml_modelo):
    """Un tablero de una hoja, sin publicar. Basta: aqui nadie mira los datos."""
    m = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": "informe_modelo", "yaml": yaml_modelo})
    modelo_id = (m.json()["id"] if m.status_code == 201 else
                 next(x["id"] for x in cliente.get("/api/modelos",
                                                   headers=cab_admin).json()
                      if x["nombre"] == "informe_modelo"))
    r = cliente.post("/api/dashboards", headers=cab_admin, json={
        "nombre": "Informe de prueba", "modelo_id": modelo_id,
        "definicion": {"hojas": [{"id": "h1", "nombre": "Hoja 1",
                                  "lienzo": {"modo": "pantalla", "columnas": 12,
                                             "filas": 12}}],
                       "widgets": [], "selecciones": {}},
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_la_url_pide_el_informe_y_la_hoja():
    url = informe_pdf._url(7, "1.- VENTAS")
    assert "/tableros/7" in url
    assert "informe=una-hoja" in url
    assert "hoja=1.-%20VENTAS" in url or "hoja=1.-+VENTAS" in url


def test_el_token_no_viaja_en_la_url():
    """Va en `localStorage` con un script de inicio, no como parametro."""
    assert "token" not in informe_pdf._url(1, None)


def test_sin_hoja_no_se_inventa_ninguna():
    assert "hoja=" not in informe_pdf._url(1, None)


def test_si_falta_el_navegador_la_respuesta_lo_dice(cliente, cab_admin, tablero,
                                                   monkeypatch):
    def sin_navegador(*a, **k):
        raise informe_pdf.SinNavegador(
            "Chromium no esta instalado para Playwright. En el servidor: "
            "python -m playwright install chromium.")

    monkeypatch.setattr(informe_pdf, "generar", sin_navegador)
    r = cliente.get(f"/api/dashboards/{tablero['id']}/informe", headers=cab_admin)
    # 501 y no 500: no es un fallo del programa, es una pieza que no esta puesta.
    assert r.status_code == 501, r.text
    assert "playwright install chromium" in r.text


def test_si_la_hoja_no_se_puede_medir_se_explica(cliente, cab_admin, tablero,
                                                 monkeypatch):
    monkeypatch.setattr(informe_pdf, "generar", lambda *a, **k: (_ for _ in ()).throw(
        informe_pdf.InformeFallido("La hoja mide 27310 px de alto y el navegador...")))
    r = cliente.get(f"/api/dashboards/{tablero['id']}/informe", headers=cab_admin)
    assert r.status_code == 422, r.text
    assert "27310" in r.text


def test_el_informe_sale_con_su_nombre_y_su_tipo(cliente, cab_admin, tablero,
                                                 monkeypatch):
    monkeypatch.setattr(informe_pdf, "generar", lambda *a, **k: b"%PDF-1.4 falso")
    r = cliente.get(f"/api/dashboards/{tablero['id']}/informe?hoja=Hoja%201",
                    headers=cab_admin)
    assert r.status_code == 200, r.text
    assert r.content == b"%PDF-1.4 falso"
    assert r.headers["content-type"] == "application/pdf"
    # Saneado: una cabecera HTTP se codifica en latin-1 y un nombre de tablero con
    # guion largo la tumbaba con un 500 despues de haber generado el PDF entero.
    r.headers["content-disposition"].encode("latin-1")
    assert ".pdf" in r.headers["content-disposition"]


def test_en_png_cambia_el_tipo(cliente, cab_admin, tablero, monkeypatch):
    monkeypatch.setattr(informe_pdf, "generar", lambda *a, **k: b"\x89PNG falso")
    r = cliente.get(f"/api/dashboards/{tablero['id']}/informe?formato=png",
                    headers=cab_admin)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"


def test_un_lector_no_saca_el_informe_de_un_borrador(cliente, cab_lector, tablero,
                                                     monkeypatch):
    """El archivo es otra forma de leer los datos: las reglas son las mismas."""
    monkeypatch.setattr(informe_pdf, "generar", lambda *a, **k: b"%PDF")
    r = cliente.get(f"/api/dashboards/{tablero['id']}/informe", headers=cab_lector)
    assert r.status_code == 404, r.text


def test_el_informe_queda_en_auditoria(cliente, cab_admin, tablero, monkeypatch):
    monkeypatch.setattr(informe_pdf, "generar", lambda *a, **k: b"%PDF")
    cliente.get(f"/api/dashboards/{tablero['id']}/informe", headers=cab_admin)
    r = cliente.get("/api/gobierno/auditoria?accion=informe", headers=cab_admin)
    assert r.status_code == 200, r.text
    ev = r.json()["eventos"]
    assert ev and ev[0]["detalle"]["formato"] == "pdf"


def test_sin_direccion_publica_se_dice_cual_es_la_variable(cliente, cab_admin, tablero,
                                                           monkeypatch):
    """
    El fallo mas probable al montar esto en un servidor, y el que menos se parece a su
    causa: el renderizador abre la aplicacion como la abre una persona, y si nadie le
    dijo por donde, lo que sale es un error de red que no señala a ninguna variable.
    """
    monkeypatch.setattr(informe_pdf, "generar", lambda *a, **k: (_ for _ in ()).throw(
        informe_pdf.FaltaDireccion(
            "No hay nada escuchando en http://localhost:5173, que es lo que dice "
            "ASTROLABIO_URL_PUBLICA.")))
    r = cliente.get(f"/api/dashboards/{tablero['id']}/informe", headers=cab_admin)
    # 501, como la falta de Chromium: no es un fallo del programa, es una pieza sin
    # montar, y el mensaje dice cual.
    assert r.status_code == 501, r.text
    assert "ASTROLABIO_URL_PUBLICA" in r.text
