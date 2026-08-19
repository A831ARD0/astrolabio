"""
El informe que sale por correo solo.

Lo que se fija aqui no es que el correo salga —eso es smtplib— sino las decisiones que
se pueden desviar sin que nadie lo note:

  1. **El periodo se resuelve en cada envio.** Un informe mensual con los filtros
     escritos a mano manda el mismo mes para siempre: la cifra es correcta, el archivo
     se ve bien, y en octubre es de julio. Nadie lo nota hasta el trimestre siguiente.
  2. **El mes va en el asunto.** Un PDF que circula tiene que poder decir de que mes es
     sin que haya que abrirlo.
  3. **Se manda con la sesion de quien lo creo**, asi que las politicas de seguridad por
     fila del correo son las de esa persona y no las de nadie.
  4. **Lo que no se puede resolver se dice al guardar**, no el dia 2 a las siete.

El correo se intercepta: lo que importa es lo que lleva dentro.
"""

import itertools
from datetime import datetime

import pytest

from app import envios as motor
from app import informe_pdf
from app.modelos_db import EnvioInforme


_siguiente = itertools.count(1)


@pytest.fixture
def tablero(cliente, cab_admin, yaml_modelo):
    """
    Un modelo propio POR PRUEBA, no uno compartido.

    Una de estas pruebas le quita al modelo la marca de mes para comprobar que el envio
    no se deja guardar, y con un modelo compartido eso rompia a las siguientes: la base
    de metadatos vive toda la corrida, asi que el orden de ejecucion decidiria quien
    pasa.
    """
    m = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"envio_modelo_{next(_siguiente)}", "yaml": yaml_modelo})
    assert m.status_code == 201, m.text
    modelo_id = m.json()["id"]
    r = cliente.post("/api/dashboards", headers=cab_admin, json={
        "nombre": "Comercial", "modelo_id": modelo_id,
        "definicion": {"hojas": [{"id": "h1", "nombre": "1.- VENTAS",
                                  "lienzo": {"modo": "pantalla", "columnas": 12,
                                             "filas": 12}}],
                       "widgets": [],
                       "selecciones": {"cat_sucursal.sucursal_nombre": ["Ekos Río Blanco"]}},
    })
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def correo(monkeypatch):
    """Se queda con el mensaje en vez de mandarlo."""
    mandados = []
    monkeypatch.setattr(motor, "_correo",
                        lambda envio, asunto, texto, pdf, imagen, nombre:
                        mandados.append({"asunto": asunto, "texto": texto, "pdf": pdf,
                                         "imagen": imagen, "nombre": nombre,
                                         "a": envio.destinatarios}))
    return mandados


@pytest.fixture
def sin_navegador(monkeypatch):
    """El PDF no se genera de verdad: eso ya tiene sus pruebas."""
    monkeypatch.setattr(informe_pdf, "generar",
                        lambda *a, **k: b"\x89PNG" if k.get("imagen") else b"%PDF-1.4")


def crear(cliente, cab, tablero, **extra):
    cuerpo = {"destinatarios": "gerencia@ejemplo.com, direccion@ejemplo.com",
              "hoja": "1.- VENTAS", **extra}
    return cliente.post(f"/api/dashboards/{tablero['id']}/envios",
                        headers=cab, json=cuerpo)


# --------------------------------------------------------------------------- #
# El periodo
# --------------------------------------------------------------------------- #

def test_el_mes_anterior_se_calcula_y_no_se_guarda():
    """En enero manda diciembre del año pasado, que es donde falla lo escrito a mano."""
    assert motor.mes_anterior(datetime(2026, 9, 2)) == 202608
    assert motor.mes_anterior(datetime(2026, 1, 2)) == 202512
    assert motor.mes_anterior(datetime(2026, 3, 1)) == 202602


def test_el_periodo_se_lee_en_palabras():
    assert motor.como_se_lee(202608) == "agosto de 2026"
    assert motor.como_se_lee(202512) == "diciembre de 2025"


def test_el_filtro_del_mes_apunta_a_la_columna_marcada(cliente, cab_admin, tablero,
                                                       sesion_prueba=None):
    """
    El filtro sale de la columna que el modelo marca como mes, no de un nombre fijo:
    en un modelo se llama `anio_mes` y en otro `Periodo_YYYYMM`.
    """
    from app.db import CrearSesion
    r = crear(cliente, cab_admin, tablero, periodo="mes_anterior")
    assert r.status_code == 201, r.text
    with CrearSesion() as s:
        e = s.get(EnvioInforme, r.json()["id"])
        filtros, periodo = motor.filtros_del_periodo(s, e, datetime(2026, 9, 2))
    assert filtros == {"dim_calendario.anio_mes": [202608]}
    assert periodo == "agosto de 2026"


def test_con_periodo_guardado_van_los_filtros_del_tablero(cliente, cab_admin, tablero):
    from app.db import CrearSesion
    r = crear(cliente, cab_admin, tablero, periodo="guardado")
    with CrearSesion() as s:
        e = s.get(EnvioInforme, r.json()["id"])
        filtros, periodo = motor.filtros_del_periodo(s, e)
    assert filtros == {"cat_sucursal.sucursal_nombre": ["Ekos Río Blanco"]}
    # Sin periodo que nombrar: no lo decide el envio.
    assert periodo == ""


def test_sin_columna_de_mes_no_se_deja_guardar(cliente, cab_admin, tablero,
                                               yaml_modelo):
    """
    Se dice al guardar, que es cuando hay alguien delante. Si se dejara pasar, esto
    falla el dia 2 a las siete y nadie se entera hasta que alguien pregunta por su
    informe.
    """
    d = cliente.get(f"/api/modelos/{tablero['modelo_id']}/definicion",
                    headers=cab_admin).json()["definicion"]
    for ent in d["entidades"]:
        for campo in ent.get("campos", []):
            campo.pop("grano_tiempo", None)
    assert cliente.put(f"/api/modelos/{tablero['modelo_id']}/definicion",
                       headers=cab_admin,
                       json={"definicion": d}).status_code == 201
    # El tablero sigue anclado a la version vieja —eso es a proposito— asi que se
    # mueve a la nueva, que es la que ya no marca ningun mes.
    vigente = next(x["version_actual"] for x in
                   cliente.get("/api/modelos", headers=cab_admin).json()
                   if x["id"] == tablero["modelo_id"])
    r = cliente.post(f"/api/dashboards/{tablero['id']}/mover-a-version"
                     f"?version={vigente}", headers=cab_admin)
    assert r.status_code == 200, r.text

    r = crear(cliente, cab_admin, tablero, periodo="mes_anterior")
    assert r.status_code == 422, r.text
    assert "marcada como mes" in r.text


# --------------------------------------------------------------------------- #
# El correo
# --------------------------------------------------------------------------- #

def test_el_asunto_lleva_el_mes(cliente, cab_admin, tablero, correo, sin_navegador):
    r = crear(cliente, cab_admin, tablero, periodo="mes_anterior")
    envio = r.json()["id"]
    assert cliente.post(
        f"/api/dashboards/{tablero['id']}/envios/{envio}/probar",
        headers=cab_admin).status_code == 200

    assert len(correo) == 1
    asunto = correo[0]["asunto"]
    assert "Comercial" in asunto and "1.- VENTAS" in asunto
    assert " de 20" in asunto, f"el asunto no dice de que mes es: {asunto}"


def test_un_asunto_propio_tambien_lleva_el_mes(cliente, cab_admin, tablero, correo,
                                               sin_navegador):
    r = crear(cliente, cab_admin, tablero, asunto="Plan de acción")
    cliente.post(f"/api/dashboards/{tablero['id']}/envios/{r.json()['id']}/probar",
                 headers=cab_admin)
    assert correo[0]["asunto"].startswith("Plan de acción — ")
    assert " de 20" in correo[0]["asunto"]


def test_pdf_adjunto_imagen_en_el_cuerpo_o_las_dos(cliente, cab_admin, tablero, correo,
                                                   sin_navegador):
    for cuerpo, con_pdf, con_imagen in [("pdf", True, False),
                                        ("imagen", False, True),
                                        ("ambos", True, True)]:
        correo.clear()
        r = crear(cliente, cab_admin, tablero, cuerpo=cuerpo)
        cliente.post(f"/api/dashboards/{tablero['id']}/envios/{r.json()['id']}/probar",
                     headers=cab_admin)
        assert (correo[0]["pdf"] is not None) is con_pdf, cuerpo
        assert (correo[0]["imagen"] is not None) is con_imagen, cuerpo


def test_la_prueba_va_a_los_mismos_destinatarios(cliente, cab_admin, tablero, correo,
                                                 sin_navegador):
    """Un envio de prueba que solo se manda a uno no prueba la lista."""
    r = crear(cliente, cab_admin, tablero)
    cliente.post(f"/api/dashboards/{tablero['id']}/envios/{r.json()['id']}/probar",
                 headers=cab_admin)
    assert correo[0]["a"] == "gerencia@ejemplo.com, direccion@ejemplo.com"


def test_el_informe_se_genera_con_la_sesion_de_quien_lo_creo(cliente, cab_admin,
                                                             tablero, correo,
                                                             monkeypatch):
    """
    Y no con la de quien pulsa la prueba, ni con una de administrador puesta a mano: las
    politicas de seguridad por fila del correo son las de una persona concreta, y eso
    hay que saberlo al elegir destinatarios.
    """
    visto = {}
    monkeypatch.setattr(informe_pdf, "generar",
                        lambda *a, **k: (visto.update(k), b"%PDF")[1])
    r = crear(cliente, cab_admin, tablero)
    cliente.post(f"/api/dashboards/{tablero['id']}/envios/{r.json()['id']}/probar",
                 headers=cab_admin)
    assert visto["correo"] == "admin@pruebas.example.com"


def test_lo_que_falla_queda_escrito_en_el_envio(cliente, cab_admin, tablero,
                                                monkeypatch):
    """
    Un envio que lleva tres meses fallando y no lo dice en ningun sitio es un informe
    que nadie recibe y todos creen que llega.
    """
    monkeypatch.setattr(informe_pdf, "generar", lambda *a, **k: (_ for _ in ()).throw(
        informe_pdf.SinNavegador("Chromium no esta donde este proceso lo busca.")))
    r = crear(cliente, cab_admin, tablero)
    envio = r.json()["id"]
    p = cliente.post(f"/api/dashboards/{tablero['id']}/envios/{envio}/probar",
                     headers=cab_admin)
    assert p.status_code == 422, p.text

    lista = cliente.get(f"/api/dashboards/{tablero['id']}/envios",
                        headers=cab_admin).json()
    mio = next(x for x in lista if x["id"] == envio)
    assert "Chromium" in mio["ultimo_error"]
    assert mio["ultimo_envio"] is None


# --------------------------------------------------------------------------- #
# La lista y los permisos
# --------------------------------------------------------------------------- #

def test_el_envio_dice_si_el_correo_del_servidor_esta_configurado(cliente, cab_admin,
                                                                 tablero):
    """
    Uno guardado sobre un servidor de correo sin configurar se ve igual que uno que
    funciona, y esa confusion es la que hace que nadie reciba nada.
    """
    r = crear(cliente, cab_admin, tablero)
    assert r.status_code == 201, r.text
    assert r.json()["correo_listo"] is False
    assert "ASTROLABIO_SMTP_HOST" in r.json()["correo_dice"]


def test_por_omision_el_dia_2_a_las_siete_y_apagado(cliente, cab_admin, tablero):
    """
    El dia 2 y no el 1: el mes cerrado con un dia de margen para que la carga haya
    corrido. Y apagado, porque encenderlo es decidir que empieza a salir.
    """
    r = crear(cliente, cab_admin, tablero)
    assert r.json()["cron"] == "0 7 2 * *"
    assert r.json()["activa"] is False


def test_un_correo_mal_escrito_no_se_guarda(cliente, cab_admin, tablero):
    r = crear(cliente, cab_admin, tablero, destinatarios="gerencia, direccion@x.com")
    assert r.status_code == 422, r.text
    assert "gerencia" in r.text


def test_un_lector_no_puede_crear_envios(cliente, cab_lector, tablero):
    r = crear(cliente, cab_lector, tablero)
    assert r.status_code == 403


def test_se_puede_apagar_y_borrar(cliente, cab_admin, tablero):
    r = crear(cliente, cab_admin, tablero, activa=True)
    envio = r.json()["id"]
    r = cliente.put(f"/api/dashboards/{tablero['id']}/envios/{envio}",
                    headers=cab_admin,
                    json={"destinatarios": "solo@ejemplo.com", "activa": False})
    assert r.status_code == 200, r.text
    assert r.json()["activa"] is False and r.json()["destinatarios"] == "solo@ejemplo.com"

    assert cliente.delete(f"/api/dashboards/{tablero['id']}/envios/{envio}",
                          headers=cab_admin).status_code == 204
    assert cliente.get(f"/api/dashboards/{tablero['id']}/envios",
                       headers=cab_admin).json() == []
