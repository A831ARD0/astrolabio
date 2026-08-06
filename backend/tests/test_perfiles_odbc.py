"""
Perfiles ODBC: la cadena armada por tipo de origen.

Lo que se prueba es lo que se rompe: que los segmentos vacios se caigan (un `UID=`
sin valor hace que algunos drivers contesten un error de autenticacion en vez de
usar el usuario del sistema), que cada motor use el nombre de parametro que de
verdad espera, y que falte lo obligatorio se diga con el nombre del campo de la
pantalla y no con el del driver.
"""

from __future__ import annotations

import pytest

from app.conectores import crear
from app.conectores.base import ErrorConector
from app.conectores.perfiles_odbc import (
    LIBRES, PERFILES, armar, catalogo, faltan,
)


def test_pervasive_usa_servername_y_serverdsn():
    """Pervasive no dice SERVER ni DATABASE: dice SERVERNAME y SERVERDSN."""
    cadena = armar("pervasive", {
        "driver": "Pervasive ODBC Client Interface", "host": "SRVPERVASIVE",
        "database": "VENTAS_SUCURSAL1", "user": "master", "password": "x"})
    assert cadena == ("DRIVER=Pervasive ODBC Client Interface;"
                      "SERVERNAME=SRVPERVASIVE;SERVERDSN=VENTAS_SUCURSAL1;"
                      "UID=master;PWD=x")


def test_los_segmentos_vacios_se_caen():
    cadena = armar("pervasive", {"driver": "D", "host": "H", "database": "B"})
    assert "UID" not in cadena and "PWD" not in cadena
    assert not cadena.endswith(";")


def test_informix_pide_maquina_y_nombre_de_instancia():
    """Confundir los dos es el motivo mas comun de 'no se pudo conectar'."""
    cadena = armar("informix", {
        "driver": "IBM INFORMIX ODBC DRIVER", "host": "10.0.0.9", "port": 9088,
        "servidor_informix": "informix_tcp", "database": "qtr", "user": "u",
        "password": "p"})
    assert "HOST=10.0.0.9" in cadena
    assert "SERVER=informix_tcp" in cadena
    assert "SERVICE=9088" in cadena
    assert "PROTOCOL=onsoctcp" in cadena


def test_sql_server_pone_el_puerto_pegado_al_servidor():
    cadena = armar("sqlserver", {"driver": "ODBC Driver 18 for SQL Server",
                                 "host": "sql01", "port": 1433, "database": "b",
                                 "user": "u", "password": "p",
                                 "extra": "TrustServerCertificate=yes"})
    assert "SERVER=sql01,1433" in cadena
    assert cadena.endswith("TrustServerCertificate=yes")


def test_lo_que_falta_se_dice_con_el_nombre_de_la_pantalla():
    assert faltan("pervasive", {"host": "H"}) == ["DSN del servidor"]
    assert faltan("informix", {}) == ["Servidor", "Puerto", "Servidor Informix",
                                      "Base de datos", "Usuario", "Contraseña"]


def test_el_conector_avisa_antes_de_intentar_conectarse():
    c = crear("odbc", {"perfil": "pervasive", "host": "SRV"})
    with pytest.raises(ErrorConector) as e:
        c._cadena()
    assert "DSN del servidor" in str(e.value)


def test_perfil_inventado():
    c = crear("odbc", {"perfil": "sybase_de_1997", "host": "x"})
    with pytest.raises(ErrorConector) as e:
        c._cadena()
    assert "Perfil ODBC desconocido" in str(e.value)


def test_el_perfil_dsn_arma_la_cadena_del_dsn():
    """
    'dsn' y 'manual' son perfiles sin plantilla: no arman nada, el DSN o la
    cadena ya traen todo dentro. Pedirles plantilla los hacia contestar "Perfil
    ODBC desconocido" para un perfil que si existe y sale en el desplegable.
    """
    c = crear("odbc", {"perfil": "dsn", "dsn": "VW_MATRIZ", "user": "admin"})
    cadena = c._cadena()
    assert "DSN=VW_MATRIZ" in cadena
    assert "UID=admin" in cadena
    assert "desconocido" not in cadena


def test_el_perfil_dsn_sigue_exigiendo_el_nombre():
    c = crear("odbc", {"perfil": "dsn", "user": "admin"})
    with pytest.raises(ErrorConector) as e:
        c._cadena()
    assert "Nombre del DSN" in str(e.value)


def test_el_perfil_manual_usa_la_cadena_tal_cual():
    c = crear("odbc", {"perfil": "manual", "cadena": "DRIVER={X};SERVER=y"})
    assert c._cadena() == "DRIVER={X};SERVER=y"


def test_todos_los_perfiles_libres_se_pueden_armar():
    """Ninguno de los libres debe acabar en 'Perfil ODBC desconocido'."""
    ejemplos = {"dsn": {"dsn": "D"}, "manual": {"cadena": "DRIVER={X}"}}
    for p in LIBRES:
        c = crear("odbc", {"perfil": p["clave"], **ejemplos[p["clave"]]})
        assert c._cadena()


def test_todos_los_perfiles_declaran_sus_campos():
    """Un campo de la plantilla que no este en `campos` no se puede llenar."""
    import re
    for p in PERFILES:
        declarados = {c["clave"] for c in p["campos"]} | {"driver"}
        usados = set(re.findall(r"\{(\w+)\}", p["plantilla"]))
        assert usados <= declarados, f"{p['clave']}: sobran {usados - declarados}"


def test_el_catalogo_cruza_los_drivers_instalados():
    c = {p["clave"]: p for p in catalogo(
        ["Pervasive ODBC Client Interface", "MySQL ODBC 5.3 Unicode Driver"])}
    assert c["pervasive"]["instalado"] is True
    assert c["pervasive"]["driver_detectado"] == "Pervasive ODBC Client Interface"
    assert c["mysql"]["instalado"] is True
    assert c["informix"]["instalado"] is False
    # Y los patrones no se pisan entre motores.
    assert c["sqlserver"]["instalado"] is False


def test_el_catalogo_no_filtra_patrones_ni_pierde_las_notas():
    """La pantalla lee de aqui; los patrones son detalle interno."""
    c = {p["clave"]: p for p in catalogo([])}
    assert "patrones" not in c["pervasive"]
    assert any("32 bits" in n for n in c["pervasive"]["notas"])
    assert c["pervasive"]["driver"]["quien"] == "sistemas"
    assert "dsn" in c and "manual" in c


def test_la_ruta_dice_que_hay_instalado(cliente, cab_editor):
    r = cliente.get("/api/conexiones/odbc/perfiles", headers=cab_editor)
    assert r.status_code == 200
    cuerpo = r.json()
    claves = [p["clave"] for p in cuerpo["perfiles"]]
    assert "pervasive" in claves and "manual" in claves
    for p in cuerpo["perfiles"]:
        assert "campos" in p
