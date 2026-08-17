"""
El lenguaje de formulas de las metricas.

Dos mitades: que compile a SQL que DuckDB acepta y que DA el numero correcto —eso
se prueba ejecutandolo de verdad, no comparando cadenas— y que la revision
estatica señale los errores que se cometen, en el sitio donde estan.
"""

import duckdb
import pytest

from semantic.formula import (
    CATALOGO, Contexto, ContextoCompuesta, ErrorFormula, catalogo_para_pantalla,
    compilar, compilar_compuesta, revisar,
)

CAMPOS = {"importe", "costo", "unidades", "tipo", "fecha", "folio"}


@pytest.fixture
def ctx():
    return Contexto(
        campos=set(CAMPOS),
        metricas={"utilidad": "SUMA(importe) - SUMA(costo)",
                  "venta": "SUMA(importe)"},
    )


@pytest.fixture(scope="module")
def con():
    """
    Tres filas con numeros a mano, para poder afirmar el resultado exacto.

    Se ejecuta contra DuckDB de verdad y no contra un doble: la mitad del valor
    de este modulo es demostrar que el SQL que sale se puede correr, y un doble
    aceptaria feliz un `FILTER` mal escrito.
    """
    c = duckdb.connect()
    c.execute("""
        CREATE TABLE t AS SELECT * FROM (VALUES
            (100.0, 60.0, 2, 'Contado',  DATE '2026-01-15', 'A-1'),
            (200.0, 150.0, 3, 'Credito', DATE '2026-02-20', 'A-2'),
            (300.0, 240.0, 0, 'Contado', DATE '2026-03-10', 'B-3')
        ) AS v(importe, costo, unidades, tipo, fecha, folio)
    """)
    return c


def valor(con, ctx, formula):
    return con.execute(f"SELECT {compilar(formula, ctx)} FROM t").fetchone()[0]


# --------------------------------------------------------------------------- #
# Compatibilidad: lo que ya estaba guardado sigue funcionando
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("sql", [
    "sum(unidades)",
    "SUM(importe) - SUM(costo)",
    "count(*)",
    "sum(importe) / nullif(sum(unidades), 0)",
])
def test_el_sql_de_siempre_pasa_tal_cual(con, ctx, sql):
    """
    Las metricas guardadas son SQL pelado. El lenguaje se agrego ENCIMA, y esto
    es lo que lo demuestra: nada de lo que ya existia necesita tocarse.
    """
    assert con.execute(f"SELECT {compilar(sql, ctx)} FROM t").fetchone() is not None
    assert revisar(sql, ctx) == []


# --------------------------------------------------------------------------- #
# Funciones
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("formula,esperado", [
    ("SUMA(importe)", 600.0),
    ("PROMEDIO(unidades)", pytest.approx(5 / 3)),
    ("CONTAR()", 3),
    ("CONTAR(unidades)", 3),
    ("CONTARUNICOS(tipo)", 2),
    ("MINIMO(importe)", 100.0),
    ("MAXIMO(importe)", 300.0),
    ("MEDIANA(importe)", 200.0),
    ("DIVIDIR(SUMA(importe) - SUMA(costo), SUMA(importe))", pytest.approx(0.25)),
    ("SI(SUMA(unidades) > 0, 1, 0)", 1),
    ("SUMA(SI(tipo = 'Contado', importe, 0))", 400.0),
    ("ELEGIR(MAXIMO(tipo), 'Contado', 1, 'Credito', 2, 0)", 2),
    ("SUMA(SI(EN(tipo, 'Contado'), unidades, 0))", 2),
    ("CONTARSI(unidades > 0)", 2),
    ("SUMASI(importe, tipo = 'Contado')", 400.0),
    ("PROMEDIOSI(importe, tipo = 'Contado')", 200.0),
    ("CONTARUNICOSSI(tipo, importe > 150)", 2),
    ("SUMA(SI(CONTIENE(tipo, 'CONT'), 1, 0))", 2),
    ("SUMA(SI(EMPIEZACON(folio, 'a'), 1, 0))", 2),
    ("MAXIMO(ANIO(fecha))", 2026),
    ("MAXIMO(MES(fecha))", 3),
    ("MAXIMO(INICIOMES(fecha))", __import__("datetime").date(2026, 3, 1)),
    ("MAXIMO(SUMARMESES(fecha, -1))", __import__("datetime").datetime(2026, 2, 10)),
    ("MAXIMO(DIFDIAS(FECHA(2026, 1, 1), fecha))", 68),
    ("REDONDEAR(PROMEDIO(importe), 1)", 200.0),
    ("SIVACIO(SUMA(importe), 0)", 600.0),
    ("SIERROR(NUMERO(MAXIMO(folio)), -1)", -1.0),
])
def test_cada_funcion_da_el_numero_correcto(con, ctx, formula, esperado):
    assert valor(con, ctx, formula) == esperado


def test_dividir_entre_cero_da_vacio_en_vez_de_reventar(con, ctx):
    """
    El motivo de que DIVIDIR exista. En SQL pelado esto tumba la consulta entera
    y se lleva por delante las otras cinco metricas del tablero.
    """
    assert valor(con, ctx, "DIVIDIR(SUMA(importe), SUMA(importe) - 600)") is None
    assert valor(con, ctx, "DIVIDIR(SUMA(importe), SUMA(importe) - 600, 0)") == 0


# --------------------------------------------------------------------------- #
# CALCULAR
# --------------------------------------------------------------------------- #

def test_calcular_filtra_cada_agregacion_de_dentro(con, ctx):
    """
    Lo que hace util a CALCULAR: el filtro se aplica a las DOS sumas, no a la
    resta por fuera. Con las tres filas, contado son 100+300 de importe y 60+240
    de costo: 400 - 300 = 100.
    """
    formula = "CALCULAR(SUMA(importe) - SUMA(costo), tipo = 'Contado')"
    assert valor(con, ctx, formula) == 100.0
    assert compilar(formula, ctx).count("FILTER") == 2


def test_calcular_acumula_las_condiciones(con, ctx):
    assert valor(con, ctx,
                 "CALCULAR(SUMA(importe), tipo = 'Contado', unidades > 0)") == 100.0


def test_calcular_sobre_una_metrica_ya_filtrada_acumula(con, ctx):
    """
    Acotar una metrica que a su vez acota otra: «lo de contado, y ademas con
    unidades». Las dos condiciones tienen que valer a la vez.

    Antes esto ni siquiera daba un numero equivocado: fallaba diciendo que
    CALCULAR no encontraba ninguna agregacion dentro — habiendola, solo que ya
    envuelta en su propio FILTER—. Es el patron de toda una familia de medidas
    que llegan de Power BI: un total con su regla, y luego los tramos de ese
    total.
    """
    ctx.metricas["contado"] = "CALCULAR(SUMA(importe), tipo = 'Contado')"
    # De contado hay dos filas: 100 con 2 unidades y 300 con 0.
    assert valor(con, ctx, "[contado]") == 400.0
    assert valor(con, ctx, "CALCULAR([contado], unidades > 0)") == 100.0
    # Y las condiciones se juntan con Y, no se pisan.
    sql = compilar("CALCULAR([contado], unidades > 0)", ctx)
    assert sql.count("FILTER") == 1 and " AND " in sql


def test_calcular_sin_agregacion_dentro_no_pasa(ctx):
    """
    Filtrar una expresion que no agrega no significa nada, y en DAX es el error
    tipico de quien viene de Excel. Se dice, y se dice que use SI.
    """
    with pytest.raises(ErrorFormula) as e:
        compilar("CALCULAR(importe, tipo = 'Contado')", ctx)
    assert "SI" in str(e.value)


# --------------------------------------------------------------------------- #
# VAR / RETURN
# --------------------------------------------------------------------------- #

def test_var_y_return(con, ctx):
    formula = """
        -- utilidad porcentual
        VAR venta = SUMA(importe)
        VAR costo = SUMA(costo)     /* el costo directo */
        RETURN DIVIDIR(venta - costo, venta)
    """
    assert valor(con, ctx, formula) == pytest.approx(0.25)


def test_una_variable_puede_usar_las_anteriores(con, ctx):
    assert valor(con, ctx, """
        VAR a = SUMA(importe)
        VAR b = a - SUMA(costo)
        RETURN DIVIDIR(b, a)
    """) == pytest.approx(0.25)


def test_un_comentario_no_esconde_un_return(con, ctx):
    """
    El `RETURN` de dentro del comentario no cuenta. Si contara, la formula se
    partiria por el sitio equivocado y el error saldria lejos de aqui.
    """
    assert valor(con, ctx, """
        VAR a = SUMA(importe)   -- aqui iria un RETURN de mentira
        RETURN a
    """) == 600.0


def test_una_comilla_no_esconde_un_parentesis(con, ctx):
    """
    El `(` de dentro del literal no cuenta al medir la profundidad. Si contara,
    la formula quedaria desbalanceada y ni siquiera compilaria. Ninguna fila
    casa con ese texto, asi que la suma sale vacia — que es lo correcto.
    """
    assert valor(con, ctx, "SUMASI(importe, tipo = 'Cont(ado')") is None


def test_var_sin_return_se_explica(ctx):
    with pytest.raises(ErrorFormula) as e:
        compilar("VAR a = SUMA(importe)", ctx)
    assert "RETURN" in str(e.value)


def test_var_sin_igual_se_explica(ctx):
    with pytest.raises(ErrorFormula) as e:
        compilar("VAR a SUMA(importe)\nRETURN a", ctx)
    assert "=" in str(e.value)


# --------------------------------------------------------------------------- #
# Referencias a otras metricas
# --------------------------------------------------------------------------- #

def test_una_metrica_puede_apoyarse_en_otra(con, ctx):
    assert valor(con, ctx, "DIVIDIR([utilidad], [venta])") == pytest.approx(0.25)


def test_metrica_inexistente_se_señala_con_su_posicion(ctx):
    fallos = revisar("DIVIDIR([utilidd], [venta])", ctx)
    assert len(fallos) == 1
    assert "utilidd" in fallos[0]["mensaje"]
    assert "utilidad" in fallos[0]["mensaje"]          # sugiere la parecida
    assert fallos[0]["columna"] == 9


def test_sumar_una_metrica_que_ya_suma_se_atrapa_antes_de_ejecutar(ctx):
    """
    El error real: DuckDB contesta «aggregate function calls cannot be nested»
    y enseña un SQL con alias `t0` que quien escribio la formula no ha visto.
    Aqui tiene que decirse en terminos de lo que hay en la pantalla.
    """
    fallos = revisar("DIVIDIR(SUMA([venta]), SUMA([utilidad]), 0)", ctx)
    assert len(fallos) == 2
    assert all(f["gravedad"] == "error" for f in fallos)
    assert "[venta] ya agrega" in fallos[0]["mensaje"]
    assert "SUMA" in fallos[0]["mensaje"]
    # Señala la referencia, no la formula entera.
    assert fallos[0]["columna"] == 14
    assert fallos[0]["largo"] == len("[venta]")


def test_acotar_una_metrica_que_ya_agrega_no_es_agregar_dos_veces(con, ctx):
    """
    `CALCULAR([venta], cond)` es correcto y salia marcado como error.

    No agrega dos veces: le mete la condicion al SUM que ya hacia `[venta]`, y el
    SQL que sale lo demuestra —un solo SUM con su FILTER—. En el catalogo CALCULAR
    figura como que agrega, porque su resultado ES una cifra agregada, y la
    revision lo trataba como un SUMA de fuera. Con esto ocho medidas de inventario
    de un modelo real salian en rojo y en el diagnostico como criticas, haciendo
    algo que el motor calcula bien.
    """
    assert revisar("CALCULAR([venta], importe > 1)", ctx) == []
    sql = compilar("CALCULAR([venta], importe > 1)", ctx)
    assert sql.upper().count("SUM(") == 1
    assert valor(con, ctx, "CALCULAR([venta], importe > 1)") is not None

    # Y envolverlo en algo que SI agrega sigue siendo un error, CALCULAR en medio
    # o no: el aviso tiene que sobrevivir al arreglo.
    for expresion in ("SUMA([venta])",
                      "SUMA(CALCULAR([venta], importe > 1))"):
        fallos = revisar(expresion, ctx)
        assert any("ya agrega" in f["mensaje"] for f in fallos), expresion


def test_la_misma_metrica_sin_envolver_esta_bien(con, ctx):
    """La correccion que sugiere el mensaje anterior tiene que funcionar."""
    assert revisar("DIVIDIR([utilidad], [venta], 0)", ctx) == []
    assert valor(con, ctx, "DIVIDIR([utilidad], [venta], 0)") == pytest.approx(0.25)


def test_una_metrica_que_no_agrega_si_se_puede_envolver():
    """No es el nombre lo que molesta, es agregar dos veces."""
    ctx = Contexto(campos={"importe"}, metricas={"neto": "importe * 1.16"})
    assert revisar("SUMA([neto])", ctx) == []


def test_agregacion_dentro_de_agregacion_sin_referencias(ctx):
    fallos = revisar("SUMA(PROMEDIO(importe))", ctx)
    assert len(fallos) == 1
    assert "agregacion dentro de otra" in fallos[0]["mensaje"]


def test_las_metricas_circulares_se_cortan():
    ctx = Contexto(campos={"importe"},
                   metricas={"a": "[b] + 1", "b": "[a] + 1"})
    with pytest.raises(ErrorFormula) as e:
        compilar("[a]", ctx)
    assert "sin final" in str(e.value)


# --------------------------------------------------------------------------- #
# Revision estatica
# --------------------------------------------------------------------------- #

def test_campo_inexistente_con_sugerencia_y_posicion(ctx):
    fallos = revisar("SUMA(imprte)", ctx)
    assert len(fallos) == 1
    assert "importe" in fallos[0]["mensaje"]
    assert (fallos[0]["linea"], fallos[0]["columna"]) == (1, 6)


def test_funcion_mal_escrita_con_sugerencia(ctx):
    fallos = revisar("SUMAR(importe)", ctx)
    assert "SUMA" in fallos[0]["mensaje"]
    assert fallos[0]["columna"] == 1


def test_numero_de_argumentos(ctx):
    fallos = revisar("DIVIDIR(SUMA(importe))", ctx)
    assert "DIVIDIR" in fallos[0]["mensaje"]
    assert "2" in fallos[0]["mensaje"]


def test_campo_suelto_fuera_de_la_agregacion(ctx):
    """
    El error que de verdad importa: compila, corre y da un numero equivocado.
    `SUMA(importe) / unidades` divide la suma del grupo entre las unidades de una
    fila cualquiera de ese grupo.
    """
    fallos = revisar("SUMA(importe) / unidades", ctx)
    assert len(fallos) == 1
    assert fallos[0]["gravedad"] == "error"
    assert "unidades" in fallos[0]["mensaje"]
    assert fallos[0]["columna"] == 17


def test_dentro_de_un_filter_un_campo_suelto_es_correcto(ctx):
    """La condicion de SUMASI se evalua fila por fila: ahi no hay nada que avisar."""
    assert revisar("SUMASI(importe, unidades > 0)", ctx) == []
    assert revisar("CALCULAR(SUMA(importe), tipo = 'Contado')", ctx) == []


def test_una_formula_que_no_agrega_avisa_pero_no_es_error(ctx):
    fallos = revisar("importe - costo", ctx)
    assert [f["gravedad"] for f in fallos] == ["advertencia"]


def test_la_linea_del_error_es_la_del_error(ctx):
    fallos = revisar("VAR a = SUMA(importe)\nVAR b = SUMA(cotso)\nRETURN a - b", ctx)
    assert len(fallos) == 1
    assert fallos[0]["linea"] == 2


def test_una_formula_correcta_no_reporta_nada(ctx):
    assert revisar("""
        VAR venta = SUMA(importe)
        VAR costo = SUMA(costo)
        RETURN DIVIDIR(venta - costo, venta)
    """, ctx) == []


def test_expresion_vacia(ctx):
    assert revisar("   ", ctx)[0]["gravedad"] == "error"


def test_parentesis_sin_cerrar(ctx):
    fallos = revisar("SUMA(importe", ctx)
    assert fallos and fallos[0]["gravedad"] == "error"


# --------------------------------------------------------------------------- #
# Catalogo
# --------------------------------------------------------------------------- #

def test_todas_las_funciones_del_catalogo_tienen_un_ejemplo_que_compila():
    """
    El ejemplo sale en la pantalla y en el autocompletado. Uno que no compilara
    seria peor que ninguno: se copia y no funciona.

    Las de la categoria `tiempo` se compilan con el compilador de compuestas
    porque es el unico donde valen: no leen columnas, envuelven metricas.
    """
    ctx = Contexto(campos={
        "Importe_Venta", "Costo_Venta", "Unidades", "Tipo_Venta", "Fecha_Factura",
        "Numero_Factura", "ID_Vehiculo", "ID_Sucursal", "Utilidad", "Folio",
    })
    ctx_tiempo = ContextoCompuesta(metricas={"Unidades Vendidas": None})
    for f in CATALOGO.values():
        try:
            if f.categoria == "tiempo":
                compilar_compuesta(f.ejemplo, ctx_tiempo)
            else:
                compilar(f.ejemplo, ctx)
        except ErrorFormula as e:                        # pragma: no cover
            pytest.fail(f"El ejemplo de {f.nombre} no compila: {e}")


def test_el_catalogo_sale_ordenado_y_completo():
    filas = catalogo_para_pantalla()
    assert len(filas) == len(CATALOGO)
    assert filas == sorted(filas, key=lambda x: (x["categoria"], x["nombre"]))
    assert all(x["firma"] and x["resumen"] and x["ejemplo"] for x in filas)
