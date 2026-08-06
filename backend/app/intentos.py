"""
Freno a los intentos de ingreso.

Sin esto, probar contraseñas contra `/api/auth/token` solo cuesta tiempo de CPU
del atacante. Argon2 ya hace lento cada intento —esa es la mitad del trabajo—,
pero lento no es imposible: con un diccionario y toda la noche, una contraseña
mediocre cae. Después de unos cuantos fallos seguidos la cuenta deja de contestar
durante un rato, y el ataque pasa de horas a años.

Tres decisiones:

- **Se cuenta por correo, no por IP.** Una oficina entera sale por la misma IP, así
  que frenar por IP castiga a quien no hizo nada; y un atacante con IPs de sobra
  la esquiva. El objetivo es proteger *la cuenta*.

- **El contador se borra al entrar bien.** Si no, quien se equivoca tres veces al
  mes acabaría bloqueado sin haber sufrido ningún ataque.

- **Vive en memoria del proceso.** Es una decisión, no un descuido: con varios
  trabajadores cada uno lleva su cuenta y el límite efectivo se multiplica por el
  número de procesos. Para el tamaño al que apunta esto —un servidor, un proceso—
  alcanza, y guardarlo en la base metería una escritura en cada intento fallido,
  que es justo lo que un atacante quiere provocar. Si algún día hay varios
  trabajadores, esto se muda a Redis y el resto no cambia.
"""

from __future__ import annotations

import threading
import time

from app.config import config

#: correo -> (fallos seguidos, momento del ultimo fallo)
_fallos: dict[str, tuple[int, float]] = {}
_candado = threading.Lock()


def _ahora() -> float:
    return time.monotonic()


def bloqueado(email: str) -> int:
    """Segundos que faltan para poder volver a intentar. 0 = adelante."""
    c = config()
    if not c.intentos_maximos:
        return 0
    with _candado:
        cuenta, cuando = _fallos.get(email.lower(), (0, 0.0))
    if cuenta < c.intentos_maximos:
        return 0
    faltan = c.minutos_bloqueo * 60 - (_ahora() - cuando)
    return max(0, int(faltan))


def fallo(email: str) -> None:
    clave = email.lower()
    with _candado:
        cuenta, cuando = _fallos.get(clave, (0, 0.0))
        # Pasado el bloqueo se empieza de cero: si no, el primer error despues de
        # semanas heredaria la cuenta vieja y bloquearia a la primera.
        if cuenta and (_ahora() - cuando) > config().minutos_bloqueo * 60:
            cuenta = 0
        _fallos[clave] = (cuenta + 1, _ahora())


def exito(email: str) -> None:
    with _candado:
        _fallos.pop(email.lower(), None)


def limpiar() -> None:
    """Solo para las pruebas: deja el contador como recien arrancado."""
    with _candado:
        _fallos.clear()
