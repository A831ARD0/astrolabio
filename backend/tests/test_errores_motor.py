"""
Los errores del motor, dichos en castellano.

La regla que se prueba: se explica, y **nunca se pierde el original**. Una
traduccion que se traga el mensaje del motor deja sin nada a quien tiene que
depurar el caso raro que la traduccion no previo.
"""

from app.errores_motor import en_castellano


def test_la_agregacion_anidada_se_explica():
    crudo = ("Binder Error: aggregate function calls cannot be nested\n"
             'LINE 5:     COALESCE((SUM((SUM("t0"."Utilidad")))) / NULLIF(\n'
             "                           ^")
    dicho = en_castellano(crudo)
    assert "agregacion dentro de otra" in dicho
    assert "ya agrega" in dicho


def test_el_detalle_del_motor_no_se_tira():
    dicho = en_castellano("Binder Error: aggregate function calls cannot be nested")
    assert "Binder Error" in dicho


def test_solo_la_primera_linea_del_detalle():
    """
    DuckDB adjunta el SQL con un cursor de flechas debajo. En una consulta con
    CTE eso es media pantalla de algo que quien lee no escribio.
    """
    dicho = en_castellano("Binder Error: aggregate function calls cannot be nested\n"
                          "LINE 5: " + "x" * 400 + "\n     ^")
    assert "LINE 5" not in dicho


def test_columna_inexistente_dice_cual():
    dicho = en_castellano('Binder Error: Referenced column "Id_Externo" not found')
    assert "'Id_Externo'" in dicho


def test_tabla_inexistente_apunta_a_la_carga():
    dicho = en_castellano("Catalog Error: Table with name fact_ventas does not exist")
    assert "'fact_ventas'" in dicho
    assert "cargado" in dicho


def test_lo_que_no_se_reconoce_se_devuelve_tal_cual():
    """Inventarse una explicacion que no corresponde es peor que no traducir."""
    crudo = "IO Error: algo rarisimo del disco"
    assert en_castellano(crudo) == crudo


def test_acepta_una_excepcion_y_no_solo_texto():
    assert "agregacion dentro de otra" in en_castellano(
        RuntimeError("Binder Error: aggregate function calls cannot be nested"))
