"""
Lo que el servidor escribe NO se sube al repositorio.

Existe por como se fue descubriendo: la instalacion del servidor es un clon de git, asi
que todo lo que la aplicacion y el instalador escriben ahi dentro aparece en «cambios
sin subir». Fue saliendo de a poco —600 archivos de Chromium un dia, los registros del
servicio al siguiente— y cada vez lo vio la persona que administra el servidor, no una
prueba.

La lista de abajo es **lo que el servidor escribe**, y esta prueba pregunta a git si los
ignora. Cuando el instalador aprenda a escribir en un sitio nuevo, hay que agregarlo
aqui; y si a alguien se le olvida, esto lo dice antes de que se vea en el servidor.

Lo peligroso de verdad no es el ruido: es `CLAVES-GENERADAS.txt`, que lleva la clave con
la que se firman los tokens y la que cifra las credenciales de las conexiones. Ese es el
que no puede subirse nunca, y por eso esta primero.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent

#: Lo que aparece en la instalacion del servidor al correr, con por que aparece.
ESCRIBE_EL_SERVIDOR = [
    ("CLAVES-GENERADAS.txt", "las claves que genera el instalador"),
    (".env", "configuracion local con secretos"),
    ("registros/Astrolabio-error.log", "registros del servicio, por NSSM"),
    ("registros/salida.log", "registros del servicio, por NSSM"),
    ("herramientas/nssm.exe", "NSSM, bajado por el instalador"),
    ("navegador/chromium-1200/chrome-win64/chrome.exe",
     "Chromium de una instalacion anterior a que se moviera a ProgramData"),
    ("backend/datos/astrolabio.db", "la base de metadatos"),
    ("backend/datos/analitico.duckdb", "el motor analitico"),
    ("frontend/dist/index.html", "la interfaz compilada"),
    ("backend/venv/pyvenv.cfg", "el entorno de Python"),
]


@pytest.mark.parametrize("ruta,porque", ESCRIBE_EL_SERVIDOR,
                         ids=[r for r, _ in ESCRIBE_EL_SERVIDOR])
def test_git_lo_ignora(ruta: str, porque: str):
    if not shutil.which("git") or not (RAIZ / ".git").exists():
        pytest.skip("sin repositorio git")
    r = subprocess.run(["git", "check-ignore", "-q", ruta],
                       cwd=RAIZ, capture_output=True, text=True, timeout=30)
    # 0 = lo ignora, 1 = no lo ignora, 128 = error de git.
    assert r.returncode == 0, (
        f"git NO ignora '{ruta}' ({porque}), asi que va a aparecer como cambio sin "
        f"subir en el servidor. Agregalo a .gitignore.")
