"""Autenticacion y roles."""

from tests.conftest import CONTRASENA


def test_salud_sin_token(cliente):
    r = cliente.get("/api/salud")
    assert r.status_code == 200
    assert r.json()["estado"] == "ok"


def test_login_correcto(cliente):
    r = cliente.post("/api/auth/token",
                     data={"username": "admin@pruebas.example.com",
                           "password": "prueba-larga-1234"})
    assert r.status_code == 200
    assert r.json()["rol"] == "administrador"


def test_login_contrasena_mala(cliente):
    r = cliente.post("/api/auth/token",
                     data={"username": "admin@pruebas.example.com", "password": "mala"})
    assert r.status_code == 401


def test_correo_inexistente_da_mismo_mensaje(cliente):
    """No se debe poder averiguar cuales correos existen."""
    a = cliente.post("/api/auth/token",
                     data={"username": "nadie@pruebas.example.com", "password": "x" * 12})
    b = cliente.post("/api/auth/token",
                     data={"username": "admin@pruebas.example.com", "password": "x" * 12})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_sin_token_no_se_pasa(cliente):
    assert cliente.get("/api/auth/yo").status_code == 401


def test_token_invalido(cliente):
    r = cliente.get("/api/auth/yo", headers={"Authorization": "Bearer basura"})
    assert r.status_code == 401


def test_yo(cliente, cab_lector):
    r = cliente.get("/api/auth/yo", headers=cab_lector)
    assert r.status_code == 200
    d = r.json()
    assert d["email"] == "norte@pruebas.example.com"
    assert d["rol"] == "lector"
    assert d["atributos"] == {"region_id": "3"}


def test_lector_no_puede_listar_usuarios(cliente, cab_lector):
    r = cliente.get("/api/auth/usuarios", headers=cab_lector)
    assert r.status_code == 403
    assert "lector" in r.json()["detail"]


def test_editor_no_puede_crear_usuarios(cliente, cab_editor):
    r = cliente.post("/api/auth/usuarios", headers=cab_editor, json={
        "email": "nuevo@pruebas.example.com", "nombre": "Nuevo",
        "contrasena": "contrasena-larga", "rol": "lector",
    })
    assert r.status_code == 403


def test_admin_crea_usuario_con_atributos(cliente, cab_admin):
    r = cliente.post("/api/auth/usuarios", headers=cab_admin, json={
        "email": "puebla@pruebas.example.com", "nombre": "Direccion Puebla",
        "contrasena": "contrasena-larga", "rol": "lector",
        "atributos": {"region_id": "2"},
    })
    assert r.status_code == 201, r.text
    assert r.json()["atributos"] == {"region_id": "2"}


def test_correo_duplicado(cliente, cab_admin):
    cuerpo = {"email": "dup@pruebas.example.com", "nombre": "Dup",
              "contrasena": "contrasena-larga", "rol": "lector"}
    assert cliente.post("/api/auth/usuarios", headers=cab_admin, json=cuerpo).status_code == 201
    assert cliente.post("/api/auth/usuarios", headers=cab_admin, json=cuerpo).status_code == 409


def test_contrasena_corta_se_rechaza(cliente, cab_admin):
    r = cliente.post("/api/auth/usuarios", headers=cab_admin, json={
        "email": "corta@pruebas.example.com", "nombre": "Corta",
        "contrasena": "123", "rol": "lector",
    })
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Freno a la fuerza bruta
# --------------------------------------------------------------------------- #

def test_despues_de_varios_fallos_la_cuenta_deja_de_contestar(cliente):
    """
    Argon2 hace lento cada intento, pero lento no es imposible. Tras unos cuantos
    fallos seguidos la cuenta se frena, y el ataque pasa de horas a años.
    """
    for _ in range(8):
        r = cliente.post("/api/auth/token",
                         data={"username": "admin@pruebas.example.com",
                               "password": "no-es-la-buena"})
        assert r.status_code == 401

    r = cliente.post("/api/auth/token",
                     data={"username": "admin@pruebas.example.com",
                           "password": "no-es-la-buena"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers

    # Y la contraseña BUENA tampoco pasa mientras dura el bloqueo: si pasara, el
    # atacante sabria que acerto.
    r = cliente.post("/api/auth/token",
                     data={"username": "admin@pruebas.example.com",
                           "password": CONTRASENA})
    assert r.status_code == 429


def test_el_bloqueo_es_por_cuenta_y_no_tumba_a_los_demas(cliente):
    for _ in range(9):
        cliente.post("/api/auth/token",
                     data={"username": "admin@pruebas.example.com", "password": "x"})
    r = cliente.post("/api/auth/token",
                     data={"username": "editor@pruebas.example.com",
                           "password": CONTRASENA})
    assert r.status_code == 200


def test_entrar_bien_borra_la_cuenta_de_fallos(cliente):
    """Quien se equivoca dos veces al mes no debe acabar bloqueado."""
    for _ in range(3):
        cliente.post("/api/auth/token",
                     data={"username": "editor@pruebas.example.com", "password": "x"})
    assert cliente.post("/api/auth/token",
                        data={"username": "editor@pruebas.example.com",
                              "password": CONTRASENA}).status_code == 200
    for _ in range(6):
        cliente.post("/api/auth/token",
                     data={"username": "editor@pruebas.example.com", "password": "x"})
    # 3 + 6 = 9 fallos en total, pero el exito de en medio reinicio la cuenta.
    assert cliente.post("/api/auth/token",
                        data={"username": "editor@pruebas.example.com",
                              "password": CONTRASENA}).status_code == 200
