"""Hash de contraseñas, tokens JWT y cifrado de credenciales."""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from cryptography.fernet import Fernet
from passlib.context import CryptContext

from app.config import config

# argon2: el estandar actual recomendado para contraseñas.
_ctx = CryptContext(schemes=["argon2"], deprecated="auto")


def hashear(contrasena: str) -> str:
    return _ctx.hash(contrasena)


def verificar(contrasena: str, hash_guardado: str) -> bool:
    return _ctx.verify(contrasena, hash_guardado)


def crear_token(sujeto: str, rol: str, extra: dict | None = None) -> str:
    c = config()
    ahora = datetime.now(timezone.utc)
    carga: dict[str, Any] = {
        "sub": sujeto,
        "rol": rol,
        "iat": ahora,
        "exp": ahora + timedelta(minutes=c.minutos_expiracion_token),
    }
    if extra:
        carga.update(extra)
    return jwt.encode(carga, c.clave_secreta, algorithm=c.algoritmo_jwt)


def leer_token(token: str) -> dict:
    c = config()
    return jwt.decode(token, c.clave_secreta, algorithms=[c.algoritmo_jwt])


# --------------------------------------------------------------------------- #
# Cifrado de credenciales de conexiones
# --------------------------------------------------------------------------- #

def _fernet() -> Fernet:
    clave = config().clave_cifrado
    if not clave:
        if config().es_produccion:
            raise RuntimeError("ASTROLABIO_CLAVE_CIFRADO es obligatoria en produccion")
        # En desarrollo se deriva una clave estable de la clave secreta para no
        # obligar a configurar dos cosas antes de poder arrancar.
        import base64
        import hashlib
        semilla = hashlib.sha256(config().clave_secreta.encode()).digest()
        clave = base64.urlsafe_b64encode(semilla).decode()
    return Fernet(clave.encode() if isinstance(clave, str) else clave)


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode()


def descifrar(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
