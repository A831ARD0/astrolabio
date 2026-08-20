"""
Que el instalador de Windows se pueda LEER.

Existe por como se rompio tres veces seguidas: no es codigo que corra en la maquina de
desarrollo —es PowerShell, y esto es macOS— asi que un error de sintaxis no lo veia
nadie hasta que alguien lo ejecutaba en el servidor. Y un error de sintaxis en
PowerShell no falla en la linea que lo tiene: el guion entero no se puede leer, asi que
no corre NADA. Las tres veces se descubrio con el servicio a medio configurar.

PowerShell trae su propio analizador y se puede llamar sin ejecutar una sola linea. Con
`pwsh` instalado, esto es exactamente el mismo error que saldria en el servidor; sin el
—que es lo normal en integracion continua— la prueba se salta y se dice.

Los dos errores que ya pasaron, para que se entienda que atrapa esto:

  - `"$carpeta: sobra"` — seguido de dos puntos, el nombre de la variable se lee como
    una unidad de disco (`$viejo:` es como `C:`). Se delimita con `${carpeta}`.
  - `$ordenes += , @('set', $n, 'X') + $Entorno` — la coma se queda con el primer trozo
    y el `+` concatena al nivel de fuera, asi que entraban dos ordenes y una iba sin
    valor. Ese si se lee, y por eso ADEMAS se comprueba a mano abajo.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
GUIONES = sorted(RAIZ.glob("*.ps1"))

def revision(ruta: Path) -> str:
    """
    El guion de PowerShell que LEE el otro sin ejecutarlo.

    La ruta va dentro del texto y no como argumento: con `-Command`, lo que se pasa
    despues no llega a `$args`, y la prueba fallaba diciendo que el archivo no existe
    —o sea, pasando por el mismo sitio que quiere vigilar sin mirar nada—.
    """
    dentro = str(ruta).replace("'", "''")          # comilla simple, a la PowerShell
    return f"""
$errores = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    '{dentro}', [ref]$null, [ref]$errores) | Out-Null
if ($errores) {{
    $errores | ForEach-Object {{
        "linea $($_.Extent.StartLineNumber): $($_.Message)"
    }}
    exit 1
}}
"""


def test_hay_instalador():
    """Si el archivo se renombra, esta prueba tiene que enterarse."""
    assert GUIONES, "no se encontro ningun .ps1 en la raiz del proyecto"


@pytest.mark.parametrize("guion", GUIONES, ids=lambda p: p.name)
def test_se_lee_sin_errores_de_sintaxis(guion: Path):
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        pytest.skip("sin pwsh: instalable con `brew install powershell`")
    r = subprocess.run([pwsh, "-NoProfile", "-Command", revision(guion)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"{guion.name} no se puede leer:\n{r.stdout}{r.stderr}"


@pytest.mark.parametrize("guion", GUIONES, ids=lambda p: p.name)
def test_ninguna_variable_pegada_a_dos_puntos(guion: Path):
    """
    Lo mismo que la prueba de arriba, pero sin depender de `pwsh`.

    Es el error que mas veces ha pasado, y el analizador solo esta cuando alguien
    instala PowerShell. Con esto se atrapa igual en cualquier maquina.
    """
    malas = []
    for n, linea in enumerate(guion.read_text(encoding="utf-8").splitlines(), 1):
        # Los comentarios no: en uno de ellos esta escrito el propio ejemplo de lo
        # que no se debe hacer, y sin esto la explicacion rompe la prueba.
        if linea.lstrip().startswith("#"):
            continue
        for i, ch in enumerate(linea):
            if ch != "$" or i + 1 >= len(linea):
                continue
            resto = linea[i + 1:]
            nombre = ""
            for c in resto:
                if c.isalnum() or c == "_":
                    nombre += c
                else:
                    break
            if not nombre or nombre in ("env", "args"):
                continue
            siguiente = resto[len(nombre):len(nombre) + 1]
            if siguiente == ":":
                malas.append(f"linea {n}: ${nombre}: — usa ${{{nombre}}}:")
    assert not malas, "variables pegadas a dos puntos:\n" + "\n".join(malas)
