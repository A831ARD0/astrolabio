"""
El puente ODBC de 32 bits.

La prueba que decide si esto sirve es `test_el_puente_trae_lo_mismo_que_directo`:
la misma tabla traida por ODBC directo y por el puente, comparada con EXCEPT en
los dos sentidos. Un puente puede parecer que funciona —conecta, lista tablas,
escribe el numero de filas correcto— y estar redondeando un DECIMAL al pasarlo
por JSON. Contar filas no lo detecta. Es la misma prueba que se le hizo al
conector ODBC contra el nativo, por el mismo motivo.

Aqui el servidor del puente corre en un hilo del **mismo** interprete, que es de
64 bits. Eso no le quita valor: lo que se prueba es el protocolo entero —sesiones,
cursores, catalogo, tipos, errores—, que es donde estan los fallos posibles. La
parte que no se puede probar en esta maquina es que en 32 bits vea el driver de
32, y eso no es codigo: es el sistema operativo haciendo lo que promete.
"""

from __future__ import annotations

import datetime
import decimal
import threading

import duckdb
import pytest

from app.conectores import ErrorConector, crear
from app.conectores.base import PeticionIngesta
from app.conectores.puente import ErrorPuente
from puente32 import protocolo
from tests.conftest import config_odbc, necesita_odbc

TOKEN = "token-de-pruebas-no-secreto"
TABLA = "ventas"
FECHA = "fecha_emision"
CLAVE = "venta_id"
FILAS = 2_000


# --------------------------------------------------------------------------- #
# El servidor, en un hilo
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def puente_url():
    from puente32 import servidor

    servidor.Manejador.registro = servidor.Registro()
    servidor.Manejador.token = TOKEN
    # Puerto 0: lo elige el sistema. Fijar uno hace que las pruebas fallen en
    # cuanto algo mas lo tenga tomado.
    srv = servidor.Servidor(("127.0.0.1", 0), servidor.Manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def por_puente(puente_url, monkeypatch):
    """Un conector ODBC igual que el normal, pero pasando por el puente."""
    monkeypatch.setattr("app.conectores.odbc._ajustes_del_puente",
                        lambda: (puente_url, TOKEN))

    def crear_conector(**extra):
        return crear("odbc", {**config_odbc(), "puente": True, **extra})

    return crear_conector


def _pet(**kw) -> PeticionIngesta:
    return PeticionIngesta(esquema=None, tabla=TABLA, destino="gm",
                           particionar_por=FECHA, columna_incremental=CLAVE, **kw)


def _leer(ruta) -> str:
    return f"read_parquet('{ruta}/**/*.parquet', hive_partitioning=true)"


# --------------------------------------------------------------------------- #
# El protocolo, sin red de por medio
# --------------------------------------------------------------------------- #

def _ida_y_vuelta(valores: list) -> list:
    return protocolo.decodificar_columna(protocolo.codificar_columna(valores))


def test_un_decimal_no_pasa_por_float():
    """
    El fallo silencioso que este puente NO puede cometer.

    `float(Decimal("1189519.10"))` ya no es esa cifra, y una carga que redondea
    centavos no falla: cuadra mal contra el sistema de origen meses despues.
    """
    original = [decimal.Decimal("1189519.10"), decimal.Decimal("0.1"), None,
                decimal.Decimal("-0.000000000000000001")]
    vuelta = _ida_y_vuelta(original)
    assert vuelta == original
    assert all(v is None or isinstance(v, decimal.Decimal) for v in vuelta)


def test_fechas_horas_y_bytes_vuelven_como_eran():
    casos = [
        [datetime.date(2026, 8, 6), None],
        [datetime.datetime(2026, 8, 6, 23, 59, 58, 123456)],
        [datetime.time(7, 5, 3)],
        [b"\x00\xff binario", None],
        ["texto", "con acentos: ñ"],
        [1, 2, None, 3],
        [True, False],
        [1.5, None],
    ]
    for original in casos:
        assert _ida_y_vuelta(original) == original


def test_una_columna_de_puros_nulos_no_inventa_tipo():
    assert _ida_y_vuelta([None, None]) == [None, None]


def test_una_columna_con_tipos_mezclados_se_va_a_texto():
    """
    Hay drivers que declaran una cosa y devuelven otra. Elegir uno de los tipos y
    forzar el resto convertiria mal la mitad; el conector ya sabe tratar una
    columna que llega como texto.
    """
    codificada = protocolo.codificar_columna([1, "dos", decimal.Decimal("3")])
    assert codificada["cod"] == "txt"
    assert protocolo.decodificar_columna(codificada) == ["1", "dos", "3"]


def test_el_lote_vacio_no_revienta():
    assert protocolo.decodificar_lote(protocolo.codificar_lote([])) == []


def test_la_descripcion_conserva_el_tipo_declarado():
    original = [("importe", decimal.Decimal, None, None, 18, 4, True),
                ("nombre", str, None, None, 45, 0, False)]
    vuelta = protocolo.decodificar_descripcion(
        protocolo.codificar_descripcion(original))
    assert vuelta == original


def test_un_tipo_que_no_conocemos_no_se_hace_pasar_por_texto():
    """
    El conector trata distinto "el driver dice que es texto" de "no reconocemos
    lo que dice el driver": al segundo le aplica `str()` sobre el valor. Si aqui
    se colara un `str`, esa conversion dejaria de hacerse.
    """
    class Raro:
        pass

    vuelta = protocolo.decodificar_descripcion(
        protocolo.codificar_descripcion([("x", Raro, None, None, 0, 0, True)]))
    assert vuelta[0][1] is protocolo.Desconocido
    assert vuelta[0][1] is not str


# --------------------------------------------------------------------------- #
# Transporte y errores
# --------------------------------------------------------------------------- #

def test_salud_dice_los_bits_y_los_drivers(puente_url):
    from app.conectores import puente

    salud = puente.salud(puente_url, TOKEN)
    assert salud["version"] == protocolo.VERSION
    assert salud["bits"] in (32, 64)
    assert isinstance(salud["drivers"], list)


def test_un_token_que_no_es_no_entra(puente_url):
    from app.conectores import puente

    with pytest.raises(ErrorPuente) as e:
        puente.salud(puente_url, "otro-token")
    assert "token" in str(e.value).lower()


def test_si_el_puente_no_esta_se_dice_cual_es_el_servicio():
    from app.conectores import puente

    # Puerto cerrado: es lo que pasa cuando el servicio no arranco.
    with pytest.raises(ErrorPuente) as e:
        puente.salud("http://127.0.0.1:9", TOKEN)
    assert "AstrolabioPuente32" in str(e.value)


def test_una_sesion_que_ya_no_existe_lo_dice_claro(puente_url):
    """
    Es lo que ve una carga cuando el puente se reinicio a media faena. El mensaje
    tiene que apuntar al puente, no parecer un fallo del origen.
    """
    import httpx

    from app.conectores.puente import _pedir

    with httpx.Client(base_url=puente_url) as cliente:
        with pytest.raises(ErrorPuente) as e:
            _pedir(cliente, TOKEN, "cursor", sesion="inventada")
    assert "reinicio" in str(e.value)


def test_sin_token_configurado_se_dice_como_crearlo(monkeypatch, tmp_path):
    from app.conectores.odbc import _ajustes_del_puente

    class Falsa:
        puente_token = ""
        puente_token_archivo = str(tmp_path / "no-existe.token")
        puente_url = "http://127.0.0.1:8001"

    monkeypatch.setattr("app.config.config", lambda: Falsa())
    with pytest.raises(ErrorConector) as e:
        _ajustes_del_puente()
    assert "-Puente32" in str(e.value)


def test_el_token_sale_del_archivo(monkeypatch, tmp_path):
    from app.conectores.odbc import _ajustes_del_puente

    archivo = tmp_path / "puente.token"
    archivo.write_text("  secreto-con-espacios  \n", encoding="utf-8")

    class Falsa:
        puente_token = ""
        puente_token_archivo = str(archivo)
        puente_url = "http://127.0.0.1:7777"

    monkeypatch.setattr("app.config.config", lambda: Falsa())
    assert _ajustes_del_puente() == ("http://127.0.0.1:7777", "secreto-con-espacios")


# --------------------------------------------------------------------------- #
# El conector completo, a traves del puente
# --------------------------------------------------------------------------- #

@necesita_odbc
def test_probar_por_el_puente(por_puente):
    r = por_puente().probar()
    assert r.ok, r.mensaje
    # El dialecto se le pregunta al driver a traves del puente: si `getinfo` no
    # cruzara bien, esto diria "esquema" en vez de "catalogo" y las tablas se
    # buscarian donde no estan.
    assert r.detalle["usa"] == "catalogo"
    assert r.detalle["identificadores"] == "`…`"


@necesita_odbc
def test_listar_y_describir_por_el_puente(por_puente):
    c = por_puente()
    assert TABLA in [t.nombre for t in c.listar_tablas()]

    tabla = c.describir_tabla(TABLA)
    assert tabla.filas_estimadas > 0
    columnas = {col.nombre: col for col in tabla.columnas}
    assert FECHA in columnas
    # `primaryKeys` es una funcion de catalogo aparte, y es la que mas drivers
    # implementan a medias: se comprueba que el viaje la trajo.
    assert columnas[CLAVE].es_clave


@necesita_odbc
def test_muestra_por_el_puente(por_puente):
    columnas, filas = por_puente().muestra(TABLA, limite=7)
    assert len(filas) == 7
    assert FECHA in columnas


@necesita_odbc
def test_el_puente_trae_lo_mismo_que_directo(por_puente, tmp_path):
    """
    La prueba que decide. Misma tabla, dos caminos, comparada fila a fila.

    Si el puente perdiera precision en un decimal, cortara microsegundos de un
    datetime o cambiara la zona de una fecha, EXCEPT lo saca; contar filas no.
    """
    directo = crear("odbc", config_odbc())

    a = por_puente().ingestar(
        _pet(reemplazar_todo=True, limite=FILAS), str(tmp_path / "puente"))
    b = directo.ingestar(
        _pet(reemplazar_todo=True, limite=FILAS), str(tmp_path / "directo"))

    assert a.filas == b.filas == FILAS
    assert a.particiones_escritas == b.particiones_escritas

    con = duckdb.connect()
    x, y = _leer(tmp_path / "puente"), _leer(tmp_path / "directo")
    sobran = con.execute(
        f"SELECT COUNT(*) FROM ((SELECT * FROM {x}) EXCEPT (SELECT * FROM {y}))"
    ).fetchone()[0]
    faltan = con.execute(
        f"SELECT COUNT(*) FROM ((SELECT * FROM {y}) EXCEPT (SELECT * FROM {x}))"
    ).fetchone()[0]
    assert (sobran, faltan) == (0, 0)


@necesita_odbc
def test_los_tipos_sobreviven_al_viaje(por_puente, tmp_path):
    por_puente().ingestar(_pet(reemplazar_todo=True, limite=200),
                          str(tmp_path / "d"))
    con = duckdb.connect()
    tipos = dict(con.execute(
        f"DESCRIBE SELECT * FROM {_leer(tmp_path / 'd')}"
    ).df()[["column_name", "column_type"]].values)
    assert tipos[FECHA] == "DATE"
    assert tipos[CLAVE] == "BIGINT"
    assert any(t.startswith("DECIMAL") for t in tipos.values())


@necesita_odbc
def test_la_carga_incremental_funciona_igual(por_puente, tmp_path):
    """Los parametros ligados (`?`) tambien cruzan el puente."""
    c = por_puente()
    destino = str(tmp_path / "inc")
    c.ingestar(_pet(reemplazar_todo=True, limite=100), destino)
    segunda = c.ingestar(_pet(desde="99999999"), destino)
    assert segunda.filas == 0


@necesita_odbc
def test_un_error_del_driver_llega_como_error_del_driver(por_puente):
    """
    Un fallo del origen tiene que verse igual con puente que sin el. Si llegara
    como un error de transporte, el conector no lo trataria y la pantalla diria
    "fallo el puente" cuando lo que fallo es la consulta.
    """
    with pytest.raises(ErrorConector) as e:
        por_puente().describir_tabla("tabla_que_no_existe_ni_de_broma")
    assert "no existe" in str(e.value).lower()


@necesita_odbc
def test_el_puente_no_deja_sesiones_abiertas(por_puente, puente_url):
    """Cada `close()` del conector tiene que cerrar la conexion del otro lado."""
    from app.conectores import puente

    antes = puente.salud(puente_url, TOKEN)["sesiones"]
    por_puente().probar()
    por_puente().listar_tablas()
    assert puente.salud(puente_url, TOKEN)["sesiones"] == antes
