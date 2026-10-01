"""
Por qué falló un ingreso, en la auditoría.

La fila de un ingreso fallido salía en blanco, y es la que más se mira cuando
alguien dice "no puedo entrar". Ahora dice el motivo y cuántos intentos lleva.

A quien intenta entrar se le sigue diciendo lo mismo en los dos casos —no se
revela qué correos existen—; la auditoría la lee sólo un administrador.
"""

from __future__ import annotations

from app.db import CrearSesion
from app.modelos_db import Auditoria, Usuario
from tests.conftest import CONTRASENA

TECLEADA = "Mi-Contraseña-Casi-Buena-77"


def _ultimo(email: str) -> Auditoria:
    with CrearSesion() as s:
        return (s.query(Auditoria).filter(Auditoria.email_usuario == email)
                .order_by(Auditoria.id.desc()).first())


def test_contrasena_incorrecta(cliente):
    r = cliente.post("/api/auth/token",
                     data={"username": "editor@pruebas.example.com", "password": TECLEADA})
    assert r.status_code == 401
    f = _ultimo("editor@pruebas.example.com")
    assert f.accion == "ingreso_fallido"
    assert f.detalle["motivo"] == "contraseña incorrecta"
    assert f.detalle["intento"] == 1
    assert f.detalle["bloqueo_tras"] == 8


def test_correo_que_no_existe(cliente):
    """El caso de quien escribe su usuario sin el @dominio."""
    r = cliente.post("/api/auth/token",
                     data={"username": "editor", "password": CONTRASENA})
    assert r.status_code == 401
    f = _ultimo("editor")
    assert f.detalle["motivo"] == "no existe ninguna cuenta con ese correo"


def test_a_quien_entra_se_le_dice_lo_mismo_en_los_dos_casos(cliente):
    """El motivo es para el administrador; desde fuera no se distingue."""
    a = cliente.post("/api/auth/token",
                     data={"username": "editor@pruebas.example.com", "password": "x"})
    b = cliente.post("/api/auth/token",
                     data={"username": "nadie@pruebas.example.com", "password": "x"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_cuenta_los_intentos_seguidos(cliente):
    for _ in range(3):
        cliente.post("/api/auth/token",
                     data={"username": "editor@pruebas.example.com", "password": "x"})
    assert _ultimo("editor@pruebas.example.com").detalle["intento"] == 3


def test_la_contrasena_tecleada_no_se_guarda_nunca(cliente):
    cliente.post("/api/auth/token",
                 data={"username": "editor@pruebas.example.com", "password": TECLEADA})
    f = _ultimo("editor@pruebas.example.com")
    texto = str(f.detalle)
    assert TECLEADA not in texto
    assert "Casi-Buena" not in texto, "ni siquiera un trozo"


def test_una_cuenta_desactivada_deja_rastro(cliente):
    """Antes el intento de una cuenta desactivada no quedaba en ninguna parte."""
    with CrearSesion() as s:
        u = s.query(Usuario).filter(Usuario.email == "incompleto@pruebas.example.com").one()
        u.activo = False
        s.commit()
    try:
        r = cliente.post("/api/auth/token",
                         data={"username": "incompleto@pruebas.example.com",
                               "password": CONTRASENA})
        assert r.status_code == 403
        f = _ultimo("incompleto@pruebas.example.com")
        assert f.accion == "ingreso_fallido"
        assert f.detalle["motivo"] == "la cuenta está desactivada"
    finally:
        with CrearSesion() as s:
            u = s.query(Usuario).filter(
                Usuario.email == "incompleto@pruebas.example.com").one()
            u.activo = True
            s.commit()
