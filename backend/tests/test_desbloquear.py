"""
Ver y quitar el bloqueo por intentos fallidos desde Gobierno.

Hasta ahora no se veia en ningun sitio —el contador vive en memoria del servicio,
no en la tabla de usuarios— y la unica salida era esperar quince minutos o
reiniciar, que suelta a TODAS las cuentas a la vez, tambien a la que alguien este
atacando de verdad. Restablecer la contraseña tampoco servia: la nueva no
funcionaba hasta pasado el bloqueo.

Se bloquea al editor y no al administrador, porque el administrador es quien tiene
que poder desbloquear.
"""

from __future__ import annotations

from tests.conftest import CONTRASENA

EDITOR = "editor@pruebas.example.com"


def _bloquear(cliente, email: str = EDITOR) -> None:
    for _ in range(8):
        cliente.post("/api/auth/token", data={"username": email, "password": "mala"})
    r = cliente.post("/api/auth/token", data={"username": email, "password": CONTRASENA})
    assert r.status_code == 429, "el montaje tiene que dejar la cuenta bloqueada"


def _usuario(cliente, cab, email: str = EDITOR) -> dict:
    return next(u for u in cliente.get("/api/auth/usuarios", headers=cab).json()
                if u["email"] == email)


def _entra(cliente, email: str, contrasena: str) -> int:
    return cliente.post("/api/auth/token",
                        data={"username": email, "password": contrasena}).status_code


def test_el_bloqueo_se_ve_en_la_lista(cliente, cab_admin):
    assert _usuario(cliente, cab_admin)["bloqueado_segundos"] == 0
    _bloquear(cliente)
    faltan = _usuario(cliente, cab_admin)["bloqueado_segundos"]
    assert 0 < faltan <= 15 * 60


def test_desbloquear_deja_entrar_al_momento(cliente, cab_admin):
    _bloquear(cliente)
    u = _usuario(cliente, cab_admin)

    r = cliente.post(f"/api/auth/usuarios/{u['id']}/desbloquear", headers=cab_admin)
    assert r.status_code == 200, r.text
    assert r.json()["bloqueado_segundos"] == 0

    assert _entra(cliente, EDITOR, CONTRASENA) == 200


def test_desbloquear_suelta_solo_a_esa_cuenta(cliente, cab_admin):
    """
    La razon de que exista en vez de reiniciar: reiniciar suelta a todas, tambien
    a la que alguien este atacando.
    """
    _bloquear(cliente)
    _bloquear(cliente, "norte@pruebas.example.com")

    u = _usuario(cliente, cab_admin)
    cliente.post(f"/api/auth/usuarios/{u['id']}/desbloquear", headers=cab_admin)

    assert _entra(cliente, EDITOR, CONTRASENA) == 200
    assert _entra(cliente, "norte@pruebas.example.com", CONTRASENA) == 429


def test_restablecer_la_contrasena_tambien_desbloquea(cliente, cab_admin):
    """
    Es lo que cualquiera espera: si alguien llama porque no puede entrar y se le da
    una contraseña nueva, esa contraseña tiene que servirle ya, no en quince
    minutos.
    """
    _bloquear(cliente)
    u = _usuario(cliente, cab_admin)

    nueva = "otra-contrasena-larga-99"
    r = cliente.post(f"/api/auth/usuarios/{u['id']}/contrasena", headers=cab_admin,
                     json={"nueva": nueva})
    assert r.status_code == 204, r.text

    assert _entra(cliente, EDITOR, nueva) == 200

    # Y se deja como estaba, que otras pruebas entran con la de siempre.
    cliente.post(f"/api/auth/usuarios/{u['id']}/contrasena", headers=cab_admin,
                 json={"nueva": CONTRASENA})


def test_desbloquear_queda_en_auditoria(cliente, cab_admin):
    """Desbloquear anula una defensa: tiene que saberse quien lo hizo."""
    _bloquear(cliente)
    u = _usuario(cliente, cab_admin)
    cliente.post(f"/api/auth/usuarios/{u['id']}/desbloquear", headers=cab_admin)

    from app.db import CrearSesion
    from app.modelos_db import Auditoria

    with CrearSesion() as s:
        fila = (s.query(Auditoria).filter(Auditoria.accion == "usuario_desbloqueado")
                .order_by(Auditoria.id.desc()).first())
        assert fila is not None
        assert fila.email_usuario == "admin@pruebas.example.com"
        assert fila.detalle["objetivo"] == EDITOR
        assert fila.detalle["segundos_que_faltaban"] > 0


def test_solo_un_administrador_puede_desbloquear(cliente, cab_admin, cab_lector):
    u = _usuario(cliente, cab_admin)
    r = cliente.post(f"/api/auth/usuarios/{u['id']}/desbloquear", headers=cab_lector)
    assert r.status_code == 403
