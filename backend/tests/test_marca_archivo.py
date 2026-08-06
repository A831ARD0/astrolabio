"""
El sufijo del Parquet de un dataset sin particionar.

Parece un detalle y tumbó la instalación entera de Windows: `escribir_lote` usaba
`time.strftime("%Y%m%d%H%M%S%f")`, y `%f` no es una directiva de `time.strftime`
—es de `datetime`—. Linux y macOS la dejan pasar; Windows lanza `ValueError:
Invalid format string`, y **ninguna carga podía terminar**.

Estas pruebas no necesitan MySQL, y esa es la mitad del punto. Las de ingesta sí
lo necesitan, así que en el CI de Windows se saltaban todas y este camino no lo
recorría nadie: el error apareció por primera vez en el servidor de producción.
Aquí se recorre en cualquier máquina, incluida la de Windows del CI.
"""

from __future__ import annotations

import re

from app.conectores.base import marca_archivo


def test_no_lanza_y_no_deja_directivas_sin_traducir():
    """
    En Windows esto lanzaba; en Unix devolvia una 'f' literal al final. Las dos
    cosas se ven en la misma comprobacion: el resultado tiene que ser fecha,
    guion bajo y hexadecimal, sin nada mas.
    """
    marca = marca_archivo()
    assert re.fullmatch(r"\d{14}_[0-9a-f]{8}", marca), marca


def test_dos_cargas_en_el_mismo_segundo_no_chocan():
    """
    La marca vieja tenia resolucion de un segundo. Dos cargas seguidas del mismo
    dataset producian el mismo nombre y la segunda pisaba a la primera, sin
    error y en todas las plataformas.
    """
    marcas = {marca_archivo() for _ in range(500)}
    assert len(marcas) == 500


def test_sirve_como_nombre_de_archivo():
    """Sin ':' ni nada que Windows rechace en una ruta."""
    prohibidos = set('<>:"/\\|?*')
    assert not (set(marca_archivo()) & prohibidos)
