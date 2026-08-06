"""
Nombres del origen que no elegimos nosotros.

El Pervasive de una agencia tiene tablas llamadas 'NF Header', 'Movim Caixa',
'NFE Out Itens'. La validacion de identificadores exigia letras, digitos y guion
bajo, asi que al elegir cualquiera de esas el explorador contestaba «Nombre de
identificador no valido» y no habia forma de traerla.

Un identificador entrecomillado admite lo que sea dentro; lo unico que hay que
cuidar es que la comilla se doble, porque si no el nombre puede cerrar el
identificador y colar SQL detras. Eso es lo que se prueba aqui: que los nombres
raros pasen y que los peligrosos sigan sin poder escaparse.
"""

from __future__ import annotations

import pytest

from app.conectores.base import ErrorConector, cita_origen, valida_ident


@pytest.mark.parametrize("nombre, esperado", [
    ("NF Header", '"NF Header"'),
    ("Movim Caixa", '"Movim Caixa"'),
    ("NFe_Details_compl", '"NFe_Details_compl"'),
    ("Año", '"Año"'),
    ("total-neto", '"total-neto"'),
    ("2024", '"2024"'),
])
def test_los_nombres_reales_de_un_origen_pasan(nombre, esperado):
    assert cita_origen(nombre) == esperado


def test_la_comilla_se_dobla_y_no_puede_cerrar_el_identificador():
    # Si la comilla no se doblara, esto seria: "x"; DROP TABLE t; --" y el
    # DROP quedaria fuera del identificador.
    assert cita_origen('x"; DROP TABLE t; --') == '"x""; DROP TABLE t; --"'


def test_cada_motor_dobla_la_suya():
    assert cita_origen("a`b", "`") == "`a``b`"
    # El corchete de SQL Server abre y cierra distinto: se dobla el que cierra.
    assert cita_origen("a]b", "[") == "[a]]b]"
    assert cita_origen("NF Header", "[") == "[NF Header]"


@pytest.mark.parametrize("nombre", ["", "a\nb", "a\x00b", "\t"])
def test_lo_que_no_se_puede_escapar_se_rechaza(nombre):
    # Un NUL corta la cadena dentro del driver y un salto de linea rompe el SQL:
    # ninguno de los dos sobrevive a las comillas.
    with pytest.raises(ErrorConector):
        cita_origen(nombre)


def test_los_nombres_del_destino_siguen_siendo_estrictos():
    # `valida_ident` es para lo que generamos nosotros -el nombre del dataset-,
    # y ahi si conviene la regla dura: son nombres que elegimos y que acaban en
    # rutas de disco y en el catalogo del motor.
    assert valida_ident("vw_matriz__ventas") == "vw_matriz__ventas"
    with pytest.raises(ErrorConector):
        valida_ident("NF Header")
