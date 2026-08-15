"""
El lenguaje de formulas de las metricas.

Una metrica se escribia como SQL pelado: `sum(Unidades)`. Funciona, y se queda
corto en cuanto la formula deja de caber en un renglon. Lo que falta no es SQL
—DuckDB ya lo tiene todo— sino lo que hace legible una formula larga: poder
nombrar los pasos intermedios, poder comentarlos, y poder reutilizar una metrica
dentro de otra sin copiar y pegar su expresion.

Asi que este modulo agrega una capa fina ENCIMA de SQL, no un lenguaje aparte:

    -- Utilidad porcentual, con su piso de seguridad
    VAR venta  = SUMA(Importe_Venta)
    VAR costo  = SUMA(Costo_Venta)
    RETURN DIVIDIR(venta - costo, venta)

Cuatro cosas y ninguna mas:

  1. `VAR nombre = expresion` … `RETURN expresion`. Las variables se sustituyen
     en el sitio; no hay ejecucion por pasos ni nada que optimizar. Una variable
     solo ve a las declaradas ANTES que ella, que es lo que impide una definicion
     circular sin necesidad de detectarla.

  2. `[otra_metrica]` — pega la expresion de otra metrica de la misma entidad.
     Con deteccion de ciclos, porque aqui si se pueden hacer.

  3. Un catalogo de funciones en español (`CATALOGO`) que se traducen a SQL de
     DuckDB. No son un motor nuevo: `SUMA` es `SUM`, y `SI` es un `CASE WHEN`.
     Existen para que la pantalla pueda ofrecer una lista con firma, resumen y
     ejemplo, y para que `DIVIDIR` haga lo correcto —dividir entre cero da vacio,
     no revienta— sin que haya que acordarse de escribir el `NULLIF` cada vez.

  4. Revision estatica con posicion: campo que no existe, funcion mal escrita,
     numero de argumentos, y —la que de verdad importa— campo suelto fuera de una
     agregacion. Esa ultima es la que evita el error clasico: `Importe / Unidades`
     se ve bien, compila, y devuelve el cociente de UNA fila cualquiera del grupo.

Todo eso vale para una metrica que se agrega desde UN hecho. Aparte estan las
**metricas compuestas** (`compilar_compuesta`), que no leen ninguna tabla y solo
combinan otras metricas: son las que permiten dividir lo vendido entre lo
presupuestado cuando cada cifra vive en un hecho distinto. Se calculan despues de
agrupar y por eso no pueden nombrar columnas ni volver a agregar.

Lo que este lenguaje NO tiene, dicho aqui para que no haya que descubrirlo
probando: **inteligencia de tiempo al estilo DAX**. No hay `DATESINPERIOD` ni
`SAMEPERIODLASTYEAR`. Esas funciones de Power BI reescriben el contexto de filtro
de la consulta que las llama, y aqui una metrica es una expresion de agregacion
dentro de un GROUP BY: no tiene contexto que reescribir. La comparacion contra
otro periodo se arma en el tablero —o en una transformacion que deje la columna
del periodo anterior al lado— y esa es una diferencia de arquitectura, no una
funcion que falte por escribir.

Todo lo de aqui es compatible hacia atras: una expresion sin `VAR`, sin `RETURN`
y sin funciones del catalogo es SQL, se parsea como SQL y sale igual que entro.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp

DIALECTO = "duckdb"


# --------------------------------------------------------------------------- #
# Errores
# --------------------------------------------------------------------------- #

@dataclass
class Fallo:
    """Un problema con su sitio exacto, para poder subrayarlo en el editor."""

    mensaje: str
    #: Desplazamiento en caracteres dentro de la formula ORIGINAL.
    inicio: int = 0
    largo: int = 0
    gravedad: str = "error"

    def con_posicion(self, texto: str) -> dict:
        linea, columna = linea_columna(texto, self.inicio)
        return {"mensaje": self.mensaje, "linea": linea, "columna": columna,
                "largo": self.largo, "gravedad": self.gravedad}


class ErrorFormula(Exception):
    def __init__(self, fallos: list[Fallo]):
        self.fallos = fallos
        super().__init__("; ".join(f.mensaje for f in fallos))


def linea_columna(texto: str, desplazamiento: int) -> tuple[int, int]:
    """Linea y columna 1-based, que es como las cuenta cualquier editor."""
    trozo = texto[: max(0, desplazamiento)]
    linea = trozo.count("\n") + 1
    columna = len(trozo) - (trozo.rfind("\n") + 1) + 1
    return linea, columna


# --------------------------------------------------------------------------- #
# Catalogo de funciones
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Funcion:
    nombre: str
    firma: str
    categoria: str
    resumen: str
    ejemplo: str
    minimo: int
    #: None = sin tope (funciones variadicas como CONCATENAR).
    maximo: int | None
    agrega: bool = False


def _f(nombre, firma, categoria, resumen, ejemplo, minimo, maximo, agrega=False):
    return Funcion(nombre, firma, categoria, resumen, ejemplo, minimo, maximo,
                   agrega)


CATALOGO: dict[str, Funcion] = {
    f.nombre: f for f in [
        # ---- agregacion -----------------------------------------------------
        _f("SUMA", "SUMA(numero)", "agregacion",
           "Suma todos los valores del grupo.",
           "SUMA(Importe_Venta)", 1, 1, True),
        _f("PROMEDIO", "PROMEDIO(numero)", "agregacion",
           "Media aritmetica del grupo. Ignora los vacios.",
           "PROMEDIO(Utilidad)", 1, 1, True),
        _f("CONTAR", "CONTAR([campo])", "agregacion",
           "Cuenta filas. Sin argumento cuenta todas; con uno, solo las que no "
           "estan vacias.",
           "CONTAR()", 0, 1, True),
        _f("CONTARUNICOS", "CONTARUNICOS(campo)", "agregacion",
           "Cuenta cuantos valores DISTINTOS hay.",
           "CONTARUNICOS(Numero_Factura)", 1, 1, True),
        _f("MINIMO", "MINIMO(campo)", "agregacion",
           "El valor mas chico del grupo.", "MINIMO(Fecha_Factura)", 1, 1, True),
        _f("MAXIMO", "MAXIMO(campo)", "agregacion",
           "El valor mas grande del grupo.", "MAXIMO(Fecha_Factura)", 1, 1, True),
        _f("MEDIANA", "MEDIANA(numero)", "agregacion",
           "El valor de en medio. A diferencia del promedio, no se la lleva un "
           "solo dato enorme.",
           "MEDIANA(Importe_Venta)", 1, 1, True),
        _f("DESVEST", "DESVEST(numero)", "agregacion",
           "Desviacion estandar muestral.", "DESVEST(Utilidad)", 1, 1, True),
        _f("VARIANZA", "VARIANZA(numero)", "agregacion",
           "Varianza muestral.", "VARIANZA(Utilidad)", 1, 1, True),
        _f("PERCENTIL", "PERCENTIL(numero, fraccion)", "agregacion",
           "El percentil pedido, con la fraccion entre 0 y 1.",
           "PERCENTIL(Importe_Venta, 0.9)", 2, 2, True),
        _f("PRIMERO", "PRIMERO(campo)", "agregacion",
           "El primer valor del grupo. Util cuando el grupo tiene un valor "
           "constante y solo hace falta sacarlo.",
           "PRIMERO(Tipo_Venta)", 1, 1, True),
        _f("ULTIMO", "ULTIMO(campo)", "agregacion",
           "El ultimo valor del grupo.", "ULTIMO(Tipo_Venta)", 1, 1, True),
        _f("LISTA", "LISTA(texto, separador)", "agregacion",
           "Pega en un solo texto todos los valores del grupo.",
           "LISTA(Tipo_Venta, ', ')", 1, 2, True),

        # ---- agregacion con condicion --------------------------------------
        _f("CALCULAR", "CALCULAR(expresion, condicion, ...)", "condicion",
           "Calcula la expresion contando solo las filas que cumplen las "
           "condiciones. Es el equivalente honesto de CALCULATE: se le aplica a "
           "CADA agregacion que haya dentro.",
           "CALCULAR(SUMA(Importe_Venta), Tipo_Venta = 'Contado')", 2, None, True),
        _f("SUMASI", "SUMASI(numero, condicion)", "condicion",
           "Suma solo las filas que cumplen la condicion.",
           "SUMASI(Importe_Venta, Unidades > 0)", 2, 2, True),
        _f("CONTARSI", "CONTARSI(condicion)", "condicion",
           "Cuenta las filas que cumplen la condicion.",
           "CONTARSI(Utilidad < 0)", 1, 1, True),
        _f("PROMEDIOSI", "PROMEDIOSI(numero, condicion)", "condicion",
           "Promedia solo las filas que cumplen la condicion.",
           "PROMEDIOSI(Utilidad, Tipo_Venta = 'Contado')", 2, 2, True),
        _f("CONTARUNICOSSI", "CONTARUNICOSSI(campo, condicion)", "condicion",
           "Cuenta valores distintos entre las filas que cumplen la condicion.",
           "CONTARUNICOSSI(ID_Vehiculo, Unidades > 0)", 2, 2, True),

        # ---- logica ---------------------------------------------------------
        _f("SI", "SI(condicion, entonces, [si_no])", "condicion",
           "Devuelve un valor u otro segun la condicion.",
           "SI(Unidades > 0, Importe_Venta, 0)", 2, 3),
        _f("ELEGIR", "ELEGIR(expresion, valor1, resultado1, ..., [por_omision])",
           "condicion",
           "Compara la expresion contra cada valor y devuelve el resultado que "
           "case. El ultimo argumento suelto es el caso por omision.",
           "ELEGIR(Tipo_Venta, 'Contado', 1, 'Credito', 2, 0)", 3, None),
        _f("Y", "Y(condicion, condicion, ...)", "condicion",
           "Verdadero si todas se cumplen.",
           "Y(Unidades > 0, Utilidad > 0)", 2, None),
        _f("O", "O(condicion, condicion, ...)", "condicion",
           "Verdadero si al menos una se cumple.",
           "O(Tipo_Venta = 'Contado', Tipo_Venta = 'Credito')", 2, None),
        _f("NO", "NO(condicion)", "condicion",
           "Invierte la condicion.", "NO(Unidades > 0)", 1, 1),
        _f("EN", "EN(campo, valor, valor, ...)", "condicion",
           "Verdadero si el campo es alguno de los valores.",
           "EN(Tipo_Venta, 'Contado', 'Credito')", 2, None),
        _f("ENTRE", "ENTRE(campo, desde, hasta)", "condicion",
           "Verdadero si el valor cae en el rango, extremos incluidos.",
           "ENTRE(Unidades, 1, 10)", 3, 3),
        _f("ESVACIO", "ESVACIO(campo)", "condicion",
           "Verdadero si el valor esta vacio (NULL).",
           "ESVACIO(Fecha_Factura)", 1, 1),
        _f("SIVACIO", "SIVACIO(campo, alterno)", "condicion",
           "El valor, o el alterno si esta vacio.",
           "SIVACIO(Utilidad, 0)", 2, 2),
        _f("SIERROR", "SIERROR(expresion, alterno)", "condicion",
           "El valor, o el alterno si el calculo falla (una conversion "
           "imposible, por ejemplo).",
           "SIERROR(TEXTO_A_NUMERO(Folio), 0)", 2, 2),

        # ---- matematicas ----------------------------------------------------
        _f("DIVIDIR", "DIVIDIR(numerador, denominador, [si_cero])", "matematica",
           "Division segura: dividir entre cero da vacio en vez de reventar la "
           "consulta entera.",
           "DIVIDIR(SUMA(Utilidad), SUMA(Importe_Venta))", 2, 3),
        _f("ABSOLUTO", "ABSOLUTO(numero)", "matematica",
           "Valor absoluto.", "ABSOLUTO(Utilidad)", 1, 1),
        _f("REDONDEAR", "REDONDEAR(numero, [decimales])", "matematica",
           "Redondea a los decimales pedidos.",
           "REDONDEAR(PROMEDIO(Utilidad), 2)", 1, 2),
        _f("TECHO", "TECHO(numero)", "matematica",
           "Redondea hacia arriba.", "TECHO(Unidades / 4)", 1, 1),
        _f("PISO", "PISO(numero)", "matematica",
           "Redondea hacia abajo.", "PISO(Unidades / 4)", 1, 1),
        _f("TRUNCAR", "TRUNCAR(numero)", "matematica",
           "Quita los decimales sin redondear.", "TRUNCAR(Importe_Venta)", 1, 1),
        _f("POTENCIA", "POTENCIA(base, exponente)", "matematica",
           "Eleva a una potencia.", "POTENCIA(Unidades, 2)", 2, 2),
        _f("RAIZ", "RAIZ(numero)", "matematica",
           "Raiz cuadrada.", "RAIZ(VARIANZA(Utilidad))", 1, 1),
        _f("LN", "LN(numero)", "matematica",
           "Logaritmo natural.", "LN(Importe_Venta)", 1, 1),
        _f("LOG10", "LOG10(numero)", "matematica",
           "Logaritmo base 10.", "LOG10(Importe_Venta)", 1, 1),
        _f("EXP", "EXP(numero)", "matematica",
           "e elevado al numero.", "EXP(1)", 1, 1),
        _f("SIGNO", "SIGNO(numero)", "matematica",
           "-1, 0 o 1 segun el signo.", "SIGNO(Utilidad)", 1, 1),
        _f("RESIDUO", "RESIDUO(numero, divisor)", "matematica",
           "Resto de la division entera.", "RESIDUO(Unidades, 2)", 2, 2),

        # ---- texto ----------------------------------------------------------
        _f("CONCATENAR", "CONCATENAR(texto, texto, ...)", "texto",
           "Pega textos.", "CONCATENAR(Tipo_Venta, ' - ', Numero_Factura)", 2, None),
        _f("IZQUIERDA", "IZQUIERDA(texto, n)", "texto",
           "Los primeros n caracteres.", "IZQUIERDA(Numero_Factura, 3)", 2, 2),
        _f("DERECHA", "DERECHA(texto, n)", "texto",
           "Los ultimos n caracteres.", "DERECHA(Numero_Factura, 4)", 2, 2),
        _f("EXTRAE", "EXTRAE(texto, desde, largo)", "texto",
           "Un trozo del texto. `desde` empieza en 1.",
           "EXTRAE(Numero_Factura, 2, 5)", 3, 3),
        _f("LARGO", "LARGO(texto)", "texto",
           "Cuantos caracteres tiene.", "LARGO(Numero_Factura)", 1, 1),
        _f("MAYUSCULAS", "MAYUSCULAS(texto)", "texto",
           "Todo en mayusculas.", "MAYUSCULAS(Tipo_Venta)", 1, 1),
        _f("MINUSCULAS", "MINUSCULAS(texto)", "texto",
           "Todo en minusculas.", "MINUSCULAS(Tipo_Venta)", 1, 1),
        _f("RECORTAR", "RECORTAR(texto)", "texto",
           "Quita los espacios de los extremos.", "RECORTAR(Tipo_Venta)", 1, 1),
        _f("SUSTITUIR", "SUSTITUIR(texto, buscar, poner)", "texto",
           "Reemplaza todas las apariciones.",
           "SUSTITUIR(Numero_Factura, '-', '')", 3, 3),
        _f("CONTIENE", "CONTIENE(texto, buscado)", "texto",
           "Verdadero si el texto contiene al otro. No distingue mayusculas.",
           "CONTIENE(Tipo_Venta, 'credito')", 2, 2),
        _f("EMPIEZACON", "EMPIEZACON(texto, prefijo)", "texto",
           "Verdadero si empieza con ese prefijo.",
           "EMPIEZACON(Numero_Factura, 'A')", 2, 2),
        _f("TERMINACON", "TERMINACON(texto, sufijo)", "texto",
           "Verdadero si termina con ese sufijo.",
           "TERMINACON(Numero_Factura, '9')", 2, 2),
        _f("TEXTO", "TEXTO(valor)", "texto",
           "Convierte cualquier valor a texto.", "TEXTO(ID_Sucursal)", 1, 1),
        _f("NUMERO", "NUMERO(valor)", "texto",
           "Convierte a numero. Falla si no se puede; envuelvelo en SIERROR.",
           "NUMERO(Numero_Factura)", 1, 1),

        # ---- fechas ---------------------------------------------------------
        _f("ANIO", "ANIO(fecha)", "fecha",
           "El año como numero.", "ANIO(Fecha_Factura)", 1, 1),
        _f("MES", "MES(fecha)", "fecha",
           "El mes, 1 a 12.", "MES(Fecha_Factura)", 1, 1),
        _f("DIA", "DIA(fecha)", "fecha",
           "El dia del mes.", "DIA(Fecha_Factura)", 1, 1),
        _f("TRIMESTRE", "TRIMESTRE(fecha)", "fecha",
           "El trimestre, 1 a 4.", "TRIMESTRE(Fecha_Factura)", 1, 1),
        _f("SEMANA", "SEMANA(fecha)", "fecha",
           "La semana del año.", "SEMANA(Fecha_Factura)", 1, 1),
        _f("HOY", "HOY()", "fecha",
           "La fecha de hoy.", "HOY()", 0, 0),
        _f("FECHA", "FECHA(anio, mes, dia)", "fecha",
           "Arma una fecha.", "FECHA(2026, 1, 1)", 3, 3),
        _f("INICIOMES", "INICIOMES(fecha)", "fecha",
           "El dia 1 de ese mes.", "INICIOMES(Fecha_Factura)", 1, 1),
        _f("FINMES", "FINMES(fecha)", "fecha",
           "El ultimo dia de ese mes.", "FINMES(Fecha_Factura)", 1, 1),
        _f("INICIOANIO", "INICIOANIO(fecha)", "fecha",
           "El 1 de enero de ese año.", "INICIOANIO(Fecha_Factura)", 1, 1),
        _f("INICIOTRIMESTRE", "INICIOTRIMESTRE(fecha)", "fecha",
           "El primer dia de ese trimestre.",
           "INICIOTRIMESTRE(Fecha_Factura)", 1, 1),
        _f("INICIOSEMANA", "INICIOSEMANA(fecha)", "fecha",
           "El lunes de esa semana.", "INICIOSEMANA(Fecha_Factura)", 1, 1),
        _f("SUMARDIAS", "SUMARDIAS(fecha, n)", "fecha",
           "Corre la fecha n dias. Con n negativo va hacia atras.",
           "SUMARDIAS(Fecha_Factura, -30)", 2, 2),
        _f("SUMARMESES", "SUMARMESES(fecha, n)", "fecha",
           "Corre la fecha n meses.", "SUMARMESES(Fecha_Factura, -1)", 2, 2),
        _f("SUMARANIOS", "SUMARANIOS(fecha, n)", "fecha",
           "Corre la fecha n años.", "SUMARANIOS(Fecha_Factura, -1)", 2, 2),
        _f("DIFDIAS", "DIFDIAS(desde, hasta)", "fecha",
           "Cuantos dias hay entre las dos fechas.",
           "DIFDIAS(Fecha_Factura, HOY())", 2, 2),
        _f("DIFMESES", "DIFMESES(desde, hasta)", "fecha",
           "Cuantos meses hay entre las dos fechas.",
           "DIFMESES(Fecha_Factura, HOY())", 2, 2),
        _f("DIFANIOS", "DIFANIOS(desde, hasta)", "fecha",
           "Cuantos años hay entre las dos fechas.",
           "DIFANIOS(Fecha_Factura, HOY())", 2, 2),
        _f("NOMBREMES", "NOMBREMES(fecha)", "fecha",
           "El nombre del mes.", "NOMBREMES(Fecha_Factura)", 1, 1),
        _f("NOMBREDIA", "NOMBREDIA(fecha)", "fecha",
           "El nombre del dia de la semana.", "NOMBREDIA(Fecha_Factura)", 1, 1),
        _f("FORMATOFECHA", "FORMATOFECHA(fecha, patron)", "fecha",
           "La fecha como texto con el patron dado.",
           "FORMATOFECHA(Fecha_Factura, '%Y-%m')", 2, 2),

        # ---- tiempo ---------------------------------------------------------
        # Solo valen en una metrica COMPUESTA, y solo si el desglose lleva una
        # columna de periodo. Las dos cosas se comprueban al compilar la consulta.
        _f("MESANTERIOR", "MESANTERIOR([metrica])", "tiempo",
           "La misma cifra, del mes anterior. Si ese mes no tiene datos sale "
           "vacio, no el del mes de antes.",
           "MESANTERIOR([Unidades Vendidas])", 1, 1),
        _f("MISMOMESANIOANTERIOR", "MISMOMESANIOANTERIOR([metrica])", "tiempo",
           "La misma cifra, del mismo mes del año pasado.",
           "MISMOMESANIOANTERIOR([Unidades Vendidas])", 1, 1),
        _f("ACUMANIO", "ACUMANIO([metrica])", "tiempo",
           "Lo que va del año: suma desde enero hasta el mes de la fila.",
           "ACUMANIO([Unidades Vendidas])", 1, 1),
        _f("PROMEDIOMESES", "PROMEDIOMESES([metrica], meses)", "tiempo",
           "Promedio de los meses ANTERIORES, sin contar el de la fila. Divide "
           "entre los meses pedidos, asi que un mes sin datos cuenta como cero.",
           "PROMEDIOMESES([Unidades Vendidas], 3)", 2, 2),
    ]
}

#: Traduccion directa a una funcion de DuckDB con los mismos argumentos.
RENOMBRES: dict[str, str] = {
    "SUMA": "SUM", "PROMEDIO": "AVG", "MINIMO": "MIN", "MAXIMO": "MAX",
    "MEDIANA": "MEDIAN", "DESVEST": "STDDEV_SAMP", "VARIANZA": "VAR_SAMP",
    "PERCENTIL": "QUANTILE_CONT", "PRIMERO": "FIRST", "ULTIMO": "LAST",
    "LISTA": "STRING_AGG",
    "ABSOLUTO": "ABS", "REDONDEAR": "ROUND", "TECHO": "CEIL", "PISO": "FLOOR",
    "TRUNCAR": "TRUNC", "POTENCIA": "POW", "RAIZ": "SQRT", "SIGNO": "SIGN",
    "RESIDUO": "MOD", "LN": "LN", "LOG10": "LOG10", "EXP": "EXP",
    "CONCATENAR": "CONCAT", "IZQUIERDA": "LEFT", "DERECHA": "RIGHT",
    "EXTRAE": "SUBSTRING", "LARGO": "LENGTH", "MAYUSCULAS": "UPPER",
    "MINUSCULAS": "LOWER", "RECORTAR": "TRIM", "SUSTITUIR": "REPLACE",
    "ANIO": "YEAR", "MES": "MONTH", "DIA": "DAY", "TRIMESTRE": "QUARTER",
    "SEMANA": "WEEK", "FECHA": "MAKE_DATE",
    "FINMES": "LAST_DAY", "NOMBREMES": "MONTHNAME", "NOMBREDIA": "DAYNAME",
    "FORMATOFECHA": "STRFTIME",
}

#: Nombres de agregacion de DuckDB. Hacen falta como texto —y no solo como
#: clases de sqlglot— porque durante la reescritura los nodos todavia son
#: `Anonymous`: `SUMA(x)` ya se llama SUM pero aun no es un `exp.Sum`.
AGREGADOS_SQL = {
    "SUM", "AVG", "COUNT", "MIN", "MAX", "MEDIAN", "STDDEV_SAMP", "STDDEV_POP",
    "STDDEV", "VAR_SAMP", "VAR_POP", "VARIANCE", "QUANTILE_CONT",
    "QUANTILE_DISC", "FIRST", "LAST", "STRING_AGG", "ARRAY_AGG", "LIST",
    "BOOL_AND", "BOOL_OR", "BIT_AND", "BIT_OR", "PRODUCT", "MODE",
    "APPROX_COUNT_DISTINCT", "ENTROPY", "KURTOSIS", "SKEWNESS", "CORR",
    "COVAR_POP", "COVAR_SAMP", "REGR_SLOPE", "REGR_INTERCEPT", "REGR_R2",
    "ARG_MIN", "ARG_MAX", "SUM_NO_OVERFLOW", "FSUM", "HISTOGRAM", "ANY_VALUE",
}

#: SQL nativo que se deja pasar aunque no este en el catalogo. El catalogo es
#: para lo que la pantalla OFRECE; esto es lo que ademas se ACEPTA, porque quien
#: sabe SQL no tiene por que traducir su expresion a español para que le pase.
NATIVAS = AGREGADOS_SQL | {
    "ABS", "ROUND", "CEIL", "CEILING", "FLOOR", "TRUNC", "POW", "POWER", "SQRT",
    "CBRT", "SIGN", "MOD", "LOG", "LOG2", "GREATEST", "LEAST", "RANDOM",
    "COALESCE", "NULLIF", "IFNULL", "NVL", "CAST", "TRY_CAST", "TRY",
    "CONCAT", "CONCAT_WS", "LEFT", "RIGHT", "SUBSTRING", "SUBSTR", "LENGTH",
    "UPPER", "LOWER", "TRIM", "LTRIM", "RTRIM", "REPLACE", "REVERSE", "LPAD",
    "RPAD", "SPLIT_PART", "STRPOS", "POSITION", "CONTAINS", "STARTS_WITH",
    "ENDS_WITH", "REGEXP_MATCHES", "REGEXP_REPLACE", "REGEXP_EXTRACT",
    "FORMAT", "PRINTF", "MD5", "HASH", "REPEAT",
    "YEAR", "MONTH", "DAY", "QUARTER", "WEEK", "DAYOFWEEK", "DAYOFYEAR", "HOUR",
    "MINUTE", "SECOND", "EPOCH", "DATE_TRUNC", "DATE_DIFF", "DATE_PART",
    "DATE_ADD", "DATE_SUB", "MAKE_DATE", "MAKE_TIMESTAMP", "LAST_DAY",
    "MONTHNAME", "DAYNAME", "STRFTIME", "STRPTIME", "CURRENT_DATE", "NOW",
    "CURRENT_TIMESTAMP", "AGE", "DATEDIFF", "DATEPART", "DATETRUNC", "TODAY",
}


def catalogo_para_pantalla() -> list[dict]:
    """El catalogo tal como lo consume el editor: ordenado y ya serializado."""
    return [
        {"nombre": f.nombre, "firma": f.firma, "categoria": f.categoria,
         "resumen": f.resumen, "ejemplo": f.ejemplo, "agrega": f.agrega,
         "minimo": f.minimo, "maximo": f.maximo}
        for f in sorted(CATALOGO.values(),
                        key=lambda x: (x.categoria, x.nombre))
    ]


# --------------------------------------------------------------------------- #
# Contexto
# --------------------------------------------------------------------------- #

@dataclass
class Contexto:
    """
    Contra que se valida una formula: las columnas de la entidad donde vive la
    metrica y las demas metricas de esa misma entidad, que son las unicas que se
    pueden referenciar con `[nombre]`.
    """

    campos: set[str] = field(default_factory=set)
    metricas: dict[str, str] = field(default_factory=dict)

    def campo(self, nombre: str) -> bool:
        n = nombre.lower()
        return any(c.lower() == n for c in self.campos)

    def metrica(self, nombre: str) -> str | None:
        n = nombre.lower()
        for k, v in self.metricas.items():
            if k.lower() == n:
                return v
        return None


# --------------------------------------------------------------------------- #
# Lexico: enmascarar lo que no es codigo
# --------------------------------------------------------------------------- #

def enmascarar(texto: str) -> str:
    """
    El mismo texto, con los comentarios y los literales vueltos espacios.

    Sirve para buscar palabras clave y parentesis sin que un `-- RETURN algo` o
    un `'no es (un parentesis'` desordenen la cuenta. Se conserva el LARGO exacto
    —y los saltos de linea— para que cualquier posicion encontrada aqui valga
    tal cual sobre el texto original.
    """
    salida = list(texto)
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if c == "-" and texto.startswith("--", i):
            j = texto.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                salida[k] = " "
            i = j
        elif c == "/" and texto.startswith("/*", i):
            j = texto.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if salida[k] != "\n":
                    salida[k] = " "
            i = j
        elif c in "'\"":
            j = i + 1
            while j < n:
                if texto[j] == c:
                    if j + 1 < n and texto[j + 1] == c:   # '' escapado
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            for k in range(i, min(j, n)):
                if salida[k] != "\n":
                    salida[k] = " "
            i = j
        else:
            i += 1
    return "".join(salida)


def _profundidades(mascara: str) -> list[int]:
    """Profundidad de parentesis en cada posicion. -1 marca desbalance."""
    salida, d = [], 0
    for c in mascara:
        if c == "(":
            salida.append(d)
            d += 1
        elif c == ")":
            d -= 1
            salida.append(d)
        else:
            salida.append(d)
    return salida


# --------------------------------------------------------------------------- #
# VAR / RETURN
# --------------------------------------------------------------------------- #

_CLAVE = re.compile(r"\b(VAR|RETURN)\b", re.IGNORECASE)
_NOMBRE_VAR = re.compile(r"[A-Za-z_ÁÉÍÓÚÜÑáéíóúüñ][\w ÁÉÍÓÚÜÑáéíóúüñ]*$")


@dataclass
class Tramo:
    """Un trozo de la formula con su desplazamiento en el texto original."""

    texto: str
    base: int


def partir(texto: str) -> tuple[list[tuple[str, Tramo, int]], Tramo]:
    """
    Separa `VAR nombre = ...` de `RETURN ...`.

    Devuelve `([(nombre, tramo, pos_del_nombre)], tramo_del_return)`. Sin
    `RETURN` de primer nivel, la formula entera ES el return — que es lo que
    hace que una expresion de SQL de toda la vida siga funcionando sin tocarla.
    """
    mascara = enmascarar(texto)
    prof = _profundidades(mascara)
    marcas = [(m.start(), m.end(), m.group(1).upper())
              for m in _CLAVE.finditer(mascara) if prof[m.start()] == 0]

    if not marcas:
        return [], Tramo(texto, 0)

    returns = [m for m in marcas if m[2] == "RETURN"]
    if not returns:
        raise ErrorFormula([Fallo(
            "La formula declara variables con VAR pero no dice que devolver. "
            "Agrega una linea `RETURN ...` al final.",
            marcas[0][0], 3)])
    if len(returns) > 1:
        ini = returns[1][0]
        raise ErrorFormula([Fallo(
            "Solo puede haber un RETURN, y tiene que ser el ultimo.",
            ini, 6)])
    if marcas[-1][2] != "RETURN":
        ini = marcas[-1][0]
        raise ErrorFormula([Fallo(
            "Despues del RETURN ya no se pueden declarar variables: muevelas "
            "arriba.", ini, 3)])

    variables: list[tuple[str, Tramo, int]] = []
    for indice, (ini, fin, clave) in enumerate(marcas):
        # Hasta donde llega este tramo: hasta la siguiente palabra clave.
        hasta = marcas[indice + 1][0] if indice + 1 < len(marcas) else len(texto)
        if clave == "RETURN":
            return variables, Tramo(texto[fin:hasta], fin)

        igual = _igual_de_primer_nivel(mascara, fin, hasta, prof)
        if igual < 0:
            raise ErrorFormula([Fallo(
                "A esta variable le falta el `=`. Se escribe "
                "`VAR nombre = expresion`.", ini, 3)])
        crudo = texto[fin:igual]
        nombre = crudo.strip()
        if not _NOMBRE_VAR.match(nombre):
            raise ErrorFormula([Fallo(
                f"'{nombre}' no sirve como nombre de variable: empieza con "
                f"letra o guion bajo y sigue con letras, numeros o guiones "
                f"bajos.", fin + (len(crudo) - len(crudo.lstrip())),
                max(len(nombre), 1))])
        variables.append(
            (nombre, Tramo(texto[igual + 1:hasta], igual + 1),
             fin + (len(crudo) - len(crudo.lstrip()))))

    raise AssertionError("hay un RETURN, asi que no se llega aqui")


def _igual_de_primer_nivel(mascara: str, desde: int, hasta: int,
                           prof: list[int]) -> int:
    for i in range(desde, hasta):
        if mascara[i] == "=" and prof[i] == 0:
            # `>=`, `<=`, `!=` y `==` no son la asignacion.
            if i > desde and mascara[i - 1] in "><!=":
                continue
            if i + 1 < hasta and mascara[i + 1] == "=":
                continue
            return i
    return -1


# --------------------------------------------------------------------------- #
# Referencias a otras metricas: [nombre]
# --------------------------------------------------------------------------- #

_REFERENCIA = re.compile(r"\[([^\[\]]*)\]")
_MARCA = "__ref_{}__"


def _extraer_referencias(tramo: Tramo, ctx: Contexto,
                         fallos: list[Fallo]) -> tuple[str, dict[str, str]]:
    """
    Cambia cada `[metrica]` por una marca y devuelve a que apunta cada marca.

    La marca es un identificador normal, asi que el texto resultante sigue
    siendo SQL parseable. Las posiciones se desplazan, y por eso todo lo que se
    revisa con posicion exacta —incluida la existencia de la metrica— se revisa
    AQUI, sobre el texto original.
    """
    mascara = enmascarar(tramo.texto)
    apunta: dict[str, str] = {}
    piezas: list[str] = []
    ultimo = 0
    for i, m in enumerate(_REFERENCIA.finditer(mascara)):
        nombre = tramo.texto[m.start(1):m.end(1)].strip()
        expresion = ctx.metrica(nombre)
        if expresion is None:
            conocidas = list(ctx.metricas)
            parecida = difflib.get_close_matches(nombre, conocidas, 1, 0.6)
            pista = f" ¿Querias decir [{parecida[0]}]?" if parecida else (
                " Esta entidad todavia no tiene otras metricas."
                if not conocidas else
                f" Las de esta entidad son: {', '.join(sorted(conocidas))}.")
            fallos.append(Fallo(
                f"No hay ninguna metrica llamada '{nombre}'.{pista}",
                tramo.base + m.start(), m.end() - m.start()))
            marca = "NULL"
        else:
            marca = _MARCA.format(i)
            apunta[marca.lower()] = expresion
        piezas.append(tramo.texto[ultimo:m.start()])
        piezas.append(marca)
        ultimo = m.end()
    piezas.append(tramo.texto[ultimo:])
    return "".join(piezas), apunta


# --------------------------------------------------------------------------- #
# Reescritura de las funciones del catalogo a SQL
# --------------------------------------------------------------------------- #

def _es_agregado(nodo: exp.Expression) -> bool:
    if isinstance(nodo, exp.AggFunc):
        return True
    return isinstance(nodo, exp.Anonymous) and str(nodo.name).upper() in AGREGADOS_SQL


def _mapear(nodo: exp.Expression, fn) -> exp.Expression:
    """
    Recorre el arbol de ABAJO hacia arriba aplicando `fn` a cada nodo.

    No se usa `Expression.transform` de sqlglot, y no es por gusto: ese recorre
    de arriba hacia abajo y no vuelve a entrar en los nodos que la funcion
    construye. Como aqui casi toda reescritura FABRICA un nodo nuevo a partir de
    sus argumentos, con `transform` lo de dentro se quedaba sin traducir:
    `SI(SUMA(x) > 0, …)` salia con un `SUMA(` literal que DuckDB no conoce.
    """
    for clave, valor in list(nodo.args.items()):
        if isinstance(valor, list):
            nodo.set(clave, [_mapear(v, fn) if isinstance(v, exp.Expression) else v
                             for v in valor])
        elif isinstance(valor, exp.Expression):
            nodo.set(clave, _mapear(valor, fn))
    return fn(nodo)


def _filtrar(nodo: exp.Expression, condicion: exp.Expression) -> exp.Expression:
    """
    Le pone `FILTER (WHERE condicion)` a cada agregacion que haya dentro.

    Esto es lo que hace de CALCULAR algo util y no un adorno: filtrar la
    expresion entera por fuera cambiaria tambien las demas metricas de la
    consulta, mientras que FILTER acota exactamente esta agregacion y ninguna
    otra. Es tambien el limite honesto frente a CALCULATE de DAX, que ademas
    puede quitar filtros que puso otro — eso requiere un contexto de filtro que
    aqui no existe.
    """
    encontrado = [False]

    def envolver(n: exp.Expression) -> exp.Expression:
        if not _es_agregado(n) or isinstance(n.parent, exp.Filter):
            return n
        encontrado[0] = True
        return exp.Filter(this=n, expression=exp.Where(this=condicion.copy()))

    salida = _mapear(nodo.copy(), envolver)
    if not encontrado[0]:
        raise ErrorFormula([Fallo(
            "CALCULAR necesita una agregacion dentro (SUMA, CONTAR, PROMEDIO…). "
            "Sin ella no hay nada que filtrar: para una condicion sobre la fila "
            "usa SI.")])
    return salida


def _y(condiciones: list[exp.Expression]) -> exp.Expression:
    salida = condiciones[0].copy()
    for c in condiciones[1:]:
        salida = exp.And(this=salida, expression=c.copy())
    return salida


def _texto_plano(nodo: exp.Expression) -> exp.Expression:
    return exp.func("LOWER", exp.cast(nodo.copy(), "VARCHAR"))


def _envolver(nombre: str, *args: exp.Expression) -> exp.Expression:
    return exp.func(nombre, *[a.copy() for a in args], dialect=DIALECTO)


def _fecha_mas(fecha: exp.Expression, n: exp.Expression,
               unidad: str) -> exp.Expression:
    # `n` puede ser cualquier expresion y no solo un literal, asi que el
    # intervalo se construye multiplicando —`fecha + (n * INTERVAL '1' MES)`— en
    # vez de interpolar el numero dentro del texto del intervalo.
    paso = exp.Mul(this=exp.Paren(this=n.copy()),
                   expression=exp.Interval(this=exp.Literal.number(1),
                                           unit=exp.Var(this=unidad)))
    return exp.Paren(this=exp.Add(this=fecha.copy(),
                                  expression=exp.Paren(this=paso)))


def _reescribir(nodo: exp.Expression) -> exp.Expression:
    if not isinstance(nodo, exp.Anonymous):
        return nodo
    nombre = str(nodo.name).upper()
    args = list(nodo.expressions)

    if nombre == "CONTAR":
        return exp.Count(this=args[0].copy() if args else exp.Star())
    if nombre == "CONTARUNICOS":
        return exp.Count(this=exp.Distinct(expressions=[args[0].copy()]))
    if nombre == "CALCULAR":
        return _filtrar(args[0], _y(args[1:]))
    if nombre == "SUMASI":
        return _filtrar(exp.func("SUM", args[0].copy()), args[1])
    if nombre == "PROMEDIOSI":
        return _filtrar(exp.func("AVG", args[0].copy()), args[1])
    if nombre == "CONTARSI":
        return _filtrar(exp.Count(this=exp.Star()), args[0])
    if nombre == "CONTARUNICOSSI":
        return _filtrar(
            exp.Count(this=exp.Distinct(expressions=[args[0].copy()])), args[1])

    if nombre == "SI":
        return exp.Case(
            ifs=[exp.If(this=args[0].copy(), true=args[1].copy())],
            default=args[2].copy() if len(args) > 2 else None)
    if nombre == "ELEGIR":
        pares = args[1:]
        por_omision = None
        if len(pares) % 2:
            por_omision = pares[-1].copy()
            pares = pares[:-1]
        return exp.Case(
            this=args[0].copy(),
            ifs=[exp.If(this=pares[i].copy(), true=pares[i + 1].copy())
                 for i in range(0, len(pares), 2)],
            default=por_omision)
    if nombre == "Y":
        return exp.Paren(this=_y(args))
    if nombre == "O":
        salida = args[0].copy()
        for a in args[1:]:
            salida = exp.Or(this=salida, expression=a.copy())
        return exp.Paren(this=salida)
    if nombre == "NO":
        return exp.Not(this=exp.Paren(this=args[0].copy()))
    if nombre == "EN":
        return exp.In(this=args[0].copy(),
                      expressions=[a.copy() for a in args[1:]])
    if nombre == "ENTRE":
        return exp.Between(this=args[0].copy(), low=args[1].copy(),
                           high=args[2].copy())
    if nombre == "ESVACIO":
        return exp.Is(this=args[0].copy(), expression=exp.Null())
    if nombre == "SIVACIO":
        return _envolver("COALESCE", *args)
    if nombre == "SIERROR":
        return _envolver("COALESCE", exp.func("TRY", args[0].copy()), args[1])

    if nombre == "DIVIDIR":
        division = exp.Div(
            this=exp.Paren(this=args[0].copy()),
            expression=exp.func("NULLIF", exp.Paren(this=args[1].copy()),
                                exp.Literal.number(0)))
        if len(args) > 2:
            return _envolver("COALESCE", division, args[2])
        return division

    if nombre == "CONTIENE":
        return exp.GT(this=exp.func("STRPOS", _texto_plano(args[0]),
                                    _texto_plano(args[1])),
                      expression=exp.Literal.number(0))
    if nombre == "EMPIEZACON":
        return exp.func("STARTS_WITH", _texto_plano(args[0]),
                        _texto_plano(args[1]))
    if nombre == "TERMINACON":
        return exp.func("ENDS_WITH", _texto_plano(args[0]),
                        _texto_plano(args[1]))
    if nombre == "HOY":
        # Nodo propio y no un renombre: `CURRENT_DATE()` con parentesis no es
        # valido en DuckDB, y un renombre siempre los deja puestos.
        return exp.CurrentDate()
    if nombre == "TEXTO":
        return exp.cast(args[0].copy(), "VARCHAR")
    if nombre == "NUMERO":
        return exp.cast(args[0].copy(), "DOUBLE")

    if nombre == "INICIOMES":
        return _envolver("DATE_TRUNC", exp.Literal.string("month"), args[0])
    if nombre == "INICIOANIO":
        return _envolver("DATE_TRUNC", exp.Literal.string("year"), args[0])
    if nombre == "INICIOTRIMESTRE":
        return _envolver("DATE_TRUNC", exp.Literal.string("quarter"), args[0])
    if nombre == "INICIOSEMANA":
        return _envolver("DATE_TRUNC", exp.Literal.string("week"), args[0])
    if nombre == "SUMARDIAS":
        return _fecha_mas(args[0], args[1], "DAY")
    if nombre == "SUMARMESES":
        return _fecha_mas(args[0], args[1], "MONTH")
    if nombre == "SUMARANIOS":
        return _fecha_mas(args[0], args[1], "YEAR")
    if nombre in ("DIFDIAS", "DIFMESES", "DIFANIOS"):
        unidad = {"DIFDIAS": "day", "DIFMESES": "month",
                  "DIFANIOS": "year"}[nombre]
        return _envolver("DATE_DIFF", exp.Literal.string(unidad), *args)

    if nombre in RENOMBRES:
        nodo.set("this", RENOMBRES[nombre])
        return nodo
    return nodo


# --------------------------------------------------------------------------- #
# Compilar
# --------------------------------------------------------------------------- #

_ERROR_SQLGLOT = re.compile(r"Line (\d+), Col (\d+)")


def _parsear(texto: str, tramo: Tramo) -> exp.Expression:
    if not texto.strip():
        raise ErrorFormula([Fallo("Falta la expresion.", tramo.base, 1)])
    try:
        arbol = sqlglot.parse_one(texto, read=DIALECTO)
    except Exception as e:
        # sqlglot informa linea y columna dentro del trozo que se le dio; se
        # traducen a un desplazamiento dentro de la formula entera.
        m = _ERROR_SQLGLOT.search(str(e))
        desplazamiento = tramo.base
        if m:
            linea, columna = int(m.group(1)), int(m.group(2))
            renglones = texto.split("\n")[: linea - 1]
            desplazamiento += sum(len(r) + 1 for r in renglones) + columna - 1
        raise ErrorFormula([Fallo(
            "No se entiende la expresion. Revisa los parentesis, las comas y "
            "las comillas.", min(desplazamiento, tramo.base + len(texto)), 1)])
    if arbol is None:
        raise ErrorFormula([Fallo("Falta la expresion.", tramo.base, 1)])
    return arbol


def _sustituir_nombres(arbol: exp.Expression,
                       tabla: dict[str, exp.Expression]) -> exp.Expression:
    """Cambia cada columna suelta cuyo nombre este en `tabla` por su arbol."""
    if not tabla:
        return arbol

    def tr(n: exp.Expression) -> exp.Expression:
        if not isinstance(n, exp.Column) or n.table:
            return n
        reemplazo = tabla.get(n.name.lower())
        if reemplazo is None:
            return n
        return exp.Paren(this=reemplazo.copy())

    return arbol.transform(tr, copy=True)


def compilar(expresion: str, ctx: Contexto | None = None,
             _en_curso: tuple[str, ...] = ()) -> str:
    """
    Compila la formula a SQL de DuckDB. Levanta `ErrorFormula` con posiciones.

    Una expresion que ya era SQL sale igual que entro (normalizada por sqlglot):
    ese es el contrato con todo lo que ya estaba guardado.
    """
    ctx = ctx or Contexto()
    fallos: list[Fallo] = []
    variables, tramo_return = partir(expresion)

    definidas: dict[str, exp.Expression] = {}
    for nombre, tramo, _pos in variables:
        arbol = _preparar(tramo, ctx, definidas, fallos, _en_curso)
        definidas[nombre.lower()] = arbol

    arbol = _preparar(tramo_return, ctx, definidas, fallos, _en_curso)
    if fallos:
        raise ErrorFormula(fallos)
    return arbol.sql(dialect=DIALECTO)


def _preparar(tramo: Tramo, ctx: Contexto,
              definidas: dict[str, exp.Expression], fallos: list[Fallo],
              en_curso: tuple[str, ...]) -> exp.Expression:
    """Un tramo: referencias, parseo, variables y reescritura de funciones."""
    texto, referencias = _extraer_referencias(tramo, ctx, fallos)
    arbol = _parsear(texto, tramo)

    # Las metricas referenciadas se compilan recursivamente, con la cadena de
    # llamadas a cuestas para poder cortar un ciclo antes de que se coma la pila.
    sustituciones = dict(definidas)
    for marca, expresion_metrica in referencias.items():
        nombre = _nombre_de_marca(marca, ctx, expresion_metrica)
        if nombre and nombre.lower() in {e.lower() for e in en_curso}:
            cadena = " → ".join([*en_curso, nombre])
            raise ErrorFormula([Fallo(
                f"Estas metricas se llaman entre si sin final: {cadena}.",
                tramo.base, len(tramo.texto))])
        sql_metrica = compilar(expresion_metrica, ctx,
                               (*en_curso, nombre or "?"))
        sustituciones[marca] = sqlglot.parse_one(sql_metrica, read=DIALECTO)

    arbol = _sustituir_nombres(arbol, sustituciones)
    arbol = _mapear(arbol.copy(), _reescribir)
    # Se vuelve a parsear a proposito: la reescritura deja nodos `Anonymous`
    # llamados SUM, y solo tras releerlos son `exp.Sum` de verdad. De eso depende
    # que la revision de agregaciones vea lo que hay y no lo que parecia haber.
    return sqlglot.parse_one(arbol.sql(dialect=DIALECTO), read=DIALECTO)


def _nombre_de_marca(marca: str, ctx: Contexto, expresion: str) -> str | None:
    for k, v in ctx.metricas.items():
        if v == expresion:
            return k
    return None


# --------------------------------------------------------------------------- #
# Metricas compuestas
# --------------------------------------------------------------------------- #

@dataclass
class ContextoCompuesta:
    """
    Las metricas que una compuesta puede nombrar, y de que tipo es cada una.

    `None` marca una metrica normal —la que se agrega desde un hecho— y una
    cadena marca otra compuesta, con su expresion, que hay que meter dentro.
    """

    metricas: dict[str, str | None] = field(default_factory=dict)

    def buscar(self, nombre: str) -> tuple[str, str | None] | None:
        """(nombre real, expresion si es compuesta). None si no existe."""
        n = nombre.lower()
        for k, v in self.metricas.items():
            if k.lower() == n:
                return k, v
        return None


_MARCA_METRICA = "__met_{}__"


@dataclass(frozen=True)
class Ventana:
    """
    Una funcion de tiempo, ya resuelta a un marco de ventana en meses.

    `desde`/`hasta` son cuantos meses hacia atras abarca, contando el mes de la
    propia fila como 0. `MESANTERIOR` es (1, 1) —solo el mes de antes—, el
    promedio de tres meses es (3, 1), y el acumulado del año es (None, 0), donde
    `None` significa «desde el principio».

    `reinicia_anio` marca el acumulado del año, que es el unico que ademas
    particiona por año para volver a empezar cada enero.

    `divisor` sale de DAX: el promedio de tres meses de Power BI divide entre 3
    fijo, aunque falte alguno. Se respeta eso y no un AVG, porque cambiar el
    denominador cambiaria la cifra que ya estan mirando.
    """

    nombre: str
    desde: int | None
    hasta: int
    reinicia_anio: bool = False
    divisor: int | None = None


#: Las funciones de tiempo. No se traducen a SQL aqui: lo que las convierte en
#: una ventana es el compilador de consultas, que es el unico que sabe por que
#: columna se esta desglosando y cual de ellas es el periodo.
VENTANAS: dict[str, Ventana] = {
    "MESANTERIOR": Ventana("MESANTERIOR", 1, 1),
    "MISMOMESANIOANTERIOR": Ventana("MISMOMESANIOANTERIOR", 12, 12),
    "ACUMANIO": Ventana("ACUMANIO", None, 0, reinicia_anio=True),
    "PROMEDIOMESES": Ventana("PROMEDIOMESES", 0, 1),   # el 0 lo pone el argumento
}


def _referencias_compuesta(
    tramo: Tramo, ctx: ContextoCompuesta, fallos: list[Fallo],
    en_curso: tuple[str, ...],
) -> tuple[str, dict[str, exp.Expression], set[str]]:
    """
    Cambia cada `[metrica]` por una marca, y dice a que arbol apunta cada una.

    La diferencia con `_extraer_referencias` es toda la idea de una compuesta: una
    metrica normal PEGA la expresion de la que referencia, porque las dos se
    agregan sobre la misma tabla. Aqui no se puede — las dos vienen de hechos
    distintos— asi que una metrica base se deja como una COLUMNA con su nombre,
    que el compilador de consultas resolvera contra la columna ya agregada.
    """
    mascara = enmascarar(tramo.texto)
    apunta: dict[str, exp.Expression] = {}
    dependencias: set[str] = set()
    piezas: list[str] = []
    ultimo = 0
    for i, m in enumerate(_REFERENCIA.finditer(mascara)):
        nombre = tramo.texto[m.start(1):m.end(1)].strip()
        hallada = ctx.buscar(nombre)
        marca = _MARCA_METRICA.format(i)
        if hallada is None:
            conocidas = list(ctx.metricas)
            parecida = difflib.get_close_matches(nombre, conocidas, 1, 0.6)
            pista = (f" ¿Querias decir [{parecida[0]}]?" if parecida else
                     " El modelo todavia no tiene otras metricas."
                     if not conocidas else
                     f" Las del modelo son: {', '.join(sorted(conocidas))}.")
            fallos.append(Fallo(
                f"No hay ninguna metrica llamada '{nombre}'.{pista}",
                tramo.base + m.start(), m.end() - m.start()))
            arbol: exp.Expression = exp.Null()
        else:
            real, expresion = hallada
            if real.lower() in {e.lower() for e in en_curso}:
                raise ErrorFormula([Fallo(
                    "Estas metricas compuestas se llaman entre si sin final: "
                    + " → ".join([*en_curso, real]) + ".",
                    tramo.base + m.start(), m.end() - m.start())])
            if expresion is None:
                dependencias.add(real)
                arbol = exp.column(real, quoted=True)
            else:
                sql, deps = compilar_compuesta(expresion, ctx, (*en_curso, real))
                dependencias.update(deps)
                arbol = sqlglot.parse_one(sql, read=DIALECTO)
        apunta[marca.lower()] = arbol
        piezas.append(tramo.texto[ultimo:m.start()])
        piezas.append(marca)
        ultimo = m.end()
    piezas.append(tramo.texto[ultimo:])
    return "".join(piezas), apunta, dependencias


#: La columna por la que se ordena una ventana de tiempo, y la que reinicia el
#: acumulado del año. Las pone `compilar_compuesta` y las resuelve el compilador
#: de consultas, que es el unico que sabe por que columna se esta desglosando.
COL_PERIODO = "__periodo__"
COL_ANIO = "__anio__"


def _marco(v: Ventana, desde: int | None) -> exp.WindowSpec:
    """
    El marco en MESES, no en filas.

    `RANGE` y no `ROWS` es toda la diferencia: `ROWS 1 PRECEDING` significa «la
    fila anterior del resultado», asi que si un mes se queda sin ventas te da el
    de dos meses atras sin avisar. `RANGE` compara el VALOR del periodo, asi que
    un mes que falta deja el marco vacio y sale en blanco — que es la verdad.
    """
    return exp.WindowSpec(
        kind="RANGE",
        start="UNBOUNDED" if desde is None else str(desde),
        start_side="PRECEDING",
        end="CURRENT ROW" if v.hasta == 0 else str(v.hasta),
        end_side=None if v.hasta == 0 else "PRECEDING",
    )


def _en_ventana(arbol: exp.Expression, v: Ventana,
                desde: int | None) -> exp.Expression:
    """
    Mete cada metrica del arbol en la ventana, en vez de meter el arbol entero.

    Es la diferencia entre el promedio de tres cocientes y el cociente de tres
    meses, y no son el mismo numero. `ACUMANIO(DIVIDIR([Utilidad], [Unidades]))`
    tiene que ser `DIVIDIR(acumulado de Utilidad, acumulado de Unidades)`, que es
    lo que significa en DAX: el filtro de periodo se aplica al calculo entero, o
    sea a cada cifra que lo compone.
    """
    def envolver(n: exp.Expression) -> exp.Expression:
        if not isinstance(n, exp.Column) or n.table:
            return n
        # Las marcas de una ventana de mas adentro no son metricas: envolverlas
        # daba `PARTITION BY SUM("__anio__") OVER (…)`, que no significa nada.
        if n.name in (COL_PERIODO, COL_ANIO):
            return n
        return exp.Window(
            this=exp.func("SUM", n.copy()),
            partition_by=([exp.column(COL_ANIO, quoted=True)]
                          if v.reinicia_anio else []),
            order=exp.Order(expressions=[
                exp.Ordered(this=exp.column(COL_PERIODO, quoted=True))]),
            spec=_marco(v, desde),
        )

    return arbol.transform(envolver, copy=True)


def _reescribir_ventanas(nodo: exp.Expression) -> exp.Expression:
    if not isinstance(nodo, exp.Anonymous):
        return nodo
    v = VENTANAS.get(str(nodo.name).upper())
    if v is None:
        return nodo
    args = list(nodo.expressions)

    # Una funcion de tiempo dentro de otra —«el acumulado del año pasado»— no es
    # una ventana con otro marco: el marco tendria que ser mas ancho cuanto mas
    # avanzado el mes, y eso ya no es un marco fijo. Se dice, en vez de generar
    # SQL que compila y devuelve cualquier cosa.
    if args and args[0].find(exp.Window) is not None:
        raise ErrorFormula([Fallo(
            f"{v.nombre} no puede llevar otra funcion de tiempo dentro. Cada una "
            f"mira una ventana de meses, y una dentro de otra no define ninguna "
            f"ventana concreta. Calcula la de dentro en su propia metrica y "
            f"nombrala aqui.")])

    desde = v.desde
    divisor = v.divisor
    if v.nombre == "PROMEDIOMESES":
        cuantos = args[1] if len(args) > 1 else None
        if not (isinstance(cuantos, exp.Literal) and cuantos.is_int
                and int(cuantos.name) > 0):
            raise ErrorFormula([Fallo(
                "PROMEDIOMESES necesita saber cuantos meses, y tiene que ser un "
                "numero escrito ahi mismo: PROMEDIOMESES([Unidades], 3).")])
        desde = int(cuantos.name)
        divisor = desde

    salida = _en_ventana(args[0], v, desde)
    if divisor:
        # Se divide entre los meses PEDIDOS y no entre los que trajeron datos,
        # que es lo que hace DAX. Un mes sin ventas cuenta como cero, no se
        # descuenta del denominador: si no, un mes malo subiria el promedio.
        salida = exp.Div(this=exp.Paren(this=salida),
                         expression=exp.Literal.number(divisor))
    return exp.Paren(this=salida)


def compilar_compuesta(
    expresion: str, ctx: ContextoCompuesta,
    _en_curso: tuple[str, ...] = (),
) -> tuple[str, list[str]]:
    """
    Compila una metrica compuesta a SQL. Devuelve `(sql, metricas de las que
    depende)`, donde cada dependencia aparece en el SQL como una columna con su
    nombre.

    Una compuesta no lee ninguna tabla: se calcula DESPUES de agrupar, sobre las
    cifras que ya dejo cada hecho en su propio grano. Eso es lo que permite
    escribir `DIVIDIR([Unidades Vendidas], [Objetivo de Ventas])` cuando una vive
    en las facturas y la otra en los objetivos — dos tablas que no se pueden
    juntar antes de agregar sin multiplicar una por las filas de la otra.

    Y es tambien de donde salen sus dos limites, que son consecuencia y no
    capricho: no puede nombrar columnas —no hay ninguna tabla de la cual sacarlas—
    ni volver a agregar, porque lo que recibe ya viene agregado.
    """
    fallos: list[Fallo] = []
    variables, tramo_return = partir(expresion)
    definidas: dict[str, exp.Expression] = {}
    dependencias: set[str] = set()

    def preparar(tramo: Tramo) -> exp.Expression:
        texto, referencias, deps = _referencias_compuesta(
            tramo, ctx, fallos, _en_curso)
        dependencias.update(deps)
        arbol = _parsear(texto, tramo)
        arbol = _sustituir_nombres(arbol, {**definidas, **referencias})
        arbol = _mapear(arbol.copy(), _reescribir)
        # Las ventanas van DESPUES: envuelven columnas, y hasta aqui las
        # referencias a metricas no se habian vuelto columnas todavia.
        arbol = _mapear(arbol, _reescribir_ventanas)
        return sqlglot.parse_one(arbol.sql(dialect=DIALECTO), read=DIALECTO)

    for nombre, tramo, _pos in variables:
        definidas[nombre.lower()] = preparar(tramo)
    arbol = preparar(tramo_return)

    # Lo que quede como columna y no sea una de las metricas nombradas es un
    # campo suelto, y aqui no hay tabla de donde sacarlo. Se para al compilar y no
    # como aviso: no es una formula discutible, es uno que no se puede ejecutar.
    esperadas = {d.lower() for d in dependencias} | {COL_PERIODO, COL_ANIO}
    sueltas = sorted({c.name for c in arbol.find_all(exp.Column)
                      if c.name.lower() not in esperadas})
    if sueltas:
        fallos.append(Fallo(
            f"{'La columna' if len(sueltas) == 1 else 'Las columnas'} "
            f"{', '.join(sueltas)} no se {'puede' if len(sueltas) == 1 else 'pueden'} "
            f"usar aqui: una metrica compuesta no lee ninguna tabla, solo combina "
            f"otras metricas. Escribe [{sueltas[0]}] si es una metrica, o mueve el "
            f"calculo a una metrica del hecho donde vive esa columna.",
            0, len(expresion.split("\n")[0])))

    # El SUMA que lleva dentro una ventana de tiempo no cuenta: no vuelve a
    # agrupar, suma los meses que el marco abarca.
    if any(a.find_ancestor(exp.Window) is None
           for a in arbol.find_all(exp.AggFunc)):
        fallos.append(Fallo(
            "Una metrica compuesta no puede agregar: lo que recibe ya viene "
            "sumado por cada hecho. Quita el SUMA / PROMEDIO / CONTAR de fuera y "
            "combina las metricas directamente.",
            0, len(expresion.split("\n")[0])))

    if fallos:
        raise ErrorFormula(fallos)
    return arbol.sql(dialect=DIALECTO), sorted(dependencias)


def revisar_compuesta(expresion: str, ctx: ContextoCompuesta,
                      nombre: str | None = None) -> list[dict]:
    """
    Todo lo que esta mal en una formula compuesta, con linea y columna.

    `nombre` es el de la metrica que se esta revisando, y sirve para una sola
    cosa: que nombrarse a si misma salga como un circulo y no como una metrica
    que existe.
    """
    if not expresion.strip():
        return [Fallo("La metrica necesita una expresion.").con_posicion(expresion)]

    fallos = _revisar_nombres_de_funcion(expresion)
    if fallos:
        return [f.con_posicion(expresion) for f in fallos]

    try:
        compilar_compuesta(expresion, ctx, (nombre,) if nombre else ())
    except ErrorFormula as e:
        return [f.con_posicion(expresion) for f in e.fallos]
    except Exception as e:                               # pragma: no cover
        return [Fallo(f"La formula no se pudo compilar: {e}").con_posicion(expresion)]
    return []


# --------------------------------------------------------------------------- #
# Revision
# --------------------------------------------------------------------------- #

def _buscar(mascara: str, palabra: str, desde: int = 0) -> int:
    m = re.search(rf"\b{re.escape(palabra)}\b", mascara[desde:], re.IGNORECASE)
    return desde + m.start() if m else 0


_LLAMADA = re.compile(r"\b([A-Za-z_ÁÉÍÓÚÜÑáéíóúüñ][\w]*)\s*\(")


def _revisar_nombres_de_funcion(expresion: str) -> list[Fallo]:
    """
    Funciones que no existen y funciones con el numero de argumentos cambiado.

    Va aparte —y antes de compilar— porque se revisa sobre el texto TAL COMO SE
    ESCRIBIO: despues de la reescritura `SUMA` ya se llama SUM, y el mensaje
    hablaria de una funcion que no aparece en la pantalla. Lo usan por igual las
    metricas normales y las compuestas: equivocarse escribiendo `DIVIDR` es lo
    mismo en las dos.
    """
    mascara = enmascarar(expresion)
    fallos: list[Fallo] = []
    conocidos = {*CATALOGO, *NATIVAS}
    try:
        variables, _ = partir(expresion)
        nombres_var = {n.lower() for n, _, _ in variables}
    except ErrorFormula as e:
        return e.fallos

    for m in _LLAMADA.finditer(mascara):
        nombre = expresion[m.start(1):m.end(1)]
        if nombre.upper() in conocidos or nombre.lower() in nombres_var:
            continue
        parecida = difflib.get_close_matches(nombre.upper(), sorted(CATALOGO),
                                             1, 0.7)
        pista = f" ¿Querias decir {parecida[0]}?" if parecida else ""
        fallos.append(Fallo(
            f"No existe ninguna funcion '{nombre}'.{pista}",
            m.start(1), len(nombre)))

    for m in _LLAMADA.finditer(mascara):
        funcion = CATALOGO.get(expresion[m.start(1):m.end(1)].upper())
        if funcion is None:
            continue
        cuantos = _contar_argumentos(mascara, m.end() - 1)
        if cuantos is None:
            continue
        if cuantos < funcion.minimo or (funcion.maximo is not None
                                        and cuantos > funcion.maximo):
            pide = (str(funcion.minimo) if funcion.maximo == funcion.minimo
                    else f"entre {funcion.minimo} y {funcion.maximo}"
                    if funcion.maximo is not None else f"{funcion.minimo} o mas")
            fallos.append(Fallo(
                f"{funcion.nombre} lleva {pide} argumento(s) y le diste "
                f"{cuantos}. Se escribe {funcion.firma}.",
                m.start(1), len(funcion.nombre)))

    fallos.sort(key=lambda f: f.inicio)
    return fallos


def _columnas_desnudas(arbol: exp.Expression) -> list[str]:
    """
    Columnas que quedan FUERA de toda agregacion.

    Es la revision que mas errores atrapa. `SUMA(Importe) / Unidades` compila sin
    protestar y devuelve la suma del grupo dividida entre las unidades de una
    fila al azar de ese grupo. El numero sale, parece razonable, y esta mal.
    """
    sueltas: list[str] = []

    def caminar(n: exp.Expression) -> None:
        # `Filter` es el `FILTER (WHERE …)` de una agregacion: lo de dentro —la
        # condicion incluida— se evalua fila por fila DENTRO del grupo, asi que
        # ahi un campo suelto es lo correcto y no un error.
        if isinstance(n, (exp.AggFunc, exp.Filter)):
            return
        if isinstance(n, exp.Column):
            sueltas.append(n.name)
            return
        for hijo in n.args.values():
            for x in (hijo if isinstance(hijo, list) else [hijo]):
                if isinstance(x, exp.Expression):
                    caminar(x)

    caminar(arbol)
    return sueltas


def revisar(expresion: str, ctx: Contexto | None = None) -> list[dict]:
    """
    Todo lo que esta mal en la formula, con linea y columna. Lista vacia = bien.

    Devuelve TODOS los problemas que puede encontrar y no solo el primero: quien
    escribe una formula larga prefiere ver los cuatro campos mal escritos de una
    vez a descubrirlos de uno en uno.
    """
    ctx = ctx or Contexto()
    if not expresion.strip():
        return [Fallo("La metrica necesita una expresion.").con_posicion(expresion)]

    mascara = enmascarar(expresion)

    fallos = _revisar_nombres_de_funcion(expresion)
    if fallos:
        return [f.con_posicion(expresion) for f in fallos]

    try:
        sql = compilar(expresion, ctx)
    except ErrorFormula as e:
        return [f.con_posicion(expresion) for f in (fallos + e.fallos)]
    except Exception as e:                          # pragma: no cover
        return [*(f.con_posicion(expresion) for f in fallos),
                Fallo(f"La formula no se pudo compilar: {e}").con_posicion(expresion)]

    arbol = sqlglot.parse_one(sql, read=DIALECTO)

    # Campos inexistentes. Se comparan contra los de la entidad; las variables ya
    # se sustituyeron, asi que lo que quede como columna tiene que ser un campo.
    if ctx.campos:
        vistos: set[str] = set()
        for col in arbol.find_all(exp.Column):
            nombre = col.name
            if ctx.campo(nombre) or nombre.lower() in vistos:
                continue
            vistos.add(nombre.lower())
            parecido = difflib.get_close_matches(nombre, sorted(ctx.campos), 1, 0.6)
            pista = (f" ¿Querias decir {parecido[0]}?" if parecido else
                     f" Los campos de la entidad son: "
                     f"{', '.join(sorted(ctx.campos))}.")
            fallos.append(Fallo(
                f"'{nombre}' no es un campo de esta entidad.{pista}",
                _buscar(mascara, nombre), len(nombre)))

    # Agregar lo que ya viene agregado. El caso corriente es referenciar otra
    # metrica dentro de SUMA: `SUMA([utilidad_total])`, donde la referenciada ya
    # es un SUM. El motor lo rechaza con un «aggregate function calls cannot be
    # nested» que habla de un SQL que quien escribio la formula no ha visto.
    anidadas = _agregaciones_anidadas(expresion, mascara, ctx)
    if anidadas:
        fallos.extend(anidadas)
    elif _hay_agregado_dentro_de_agregado(arbol):
        fallos.append(Fallo(
            "Hay una agregacion dentro de otra, y eso no se puede calcular: el "
            "motor tendria que agrupar dos veces sobre el mismo grupo. Deja una "
            "sola.", 0, len(expresion.split("\n")[0])))

    hay_agregacion = arbol.find(exp.AggFunc) is not None
    sueltas = _columnas_desnudas(arbol)
    if sueltas and hay_agregacion:
        nombres = sorted(set(sueltas))
        fallos.append(Fallo(
            f"{'El campo' if len(nombres) == 1 else 'Los campos'} "
            f"{', '.join(nombres)} {'esta' if len(nombres) == 1 else 'estan'} "
            f"fuera de una agregacion, mezclado con otras que si agregan. El "
            f"resultado seria el de una fila cualquiera del grupo. Envuelvelo "
            f"en SUMA, PROMEDIO, MAXIMO… o usa PRIMERO si de verdad es "
            f"constante dentro del grupo.",
            _buscar(mascara, nombres[0]), len(nombres[0])))
    elif not hay_agregacion:
        fallos.append(Fallo(
            "Esta formula no agrega nada: devolveria un valor por fila y una "
            "metrica tiene que devolver uno por grupo. Envuelvela en SUMA, "
            "CONTAR, PROMEDIO…", 0, len(expresion.split("\n")[0]),
            gravedad="advertencia"))

    fallos.sort(key=lambda f: f.inicio)
    return [f.con_posicion(expresion) for f in fallos]


def _hay_agregado_dentro_de_agregado(arbol: exp.Expression) -> bool:
    """Un SUM dentro de otro SUM, en el SQL ya compilado."""
    for nodo in arbol.find_all(exp.AggFunc):
        for dentro in nodo.find_all(exp.AggFunc):
            if dentro is not nodo:
                return True
    return False


def _envolturas(mascara: str, posicion: int) -> list[tuple[str, int]]:
    """
    Las funciones que envuelven a `posicion`, de la mas cercana a la mas lejana.

    Se lee hacia atras contando parentesis sobre el texto ENMASCARADO, asi que un
    parentesis dentro de un comentario o de un literal no cuenta. Devuelve el
    nombre y donde empieza, para poder señalarlo.
    """
    fuera: list[tuple[str, int]] = []
    profundidad = 0
    i = posicion - 1
    while i >= 0:
        c = mascara[i]
        if c == ")":
            profundidad += 1
        elif c == "(":
            if profundidad > 0:
                profundidad -= 1
            else:
                # Parentesis sin cerrar antes de la posicion: lo que haya
                # pegado a su izquierda es la funcion que nos envuelve.
                j = i - 1
                while j >= 0 and mascara[j].isspace():
                    j -= 1
                fin = j + 1
                while j >= 0 and (mascara[j].isalnum() or mascara[j] == "_"):
                    j -= 1
                if fin > j + 1:
                    fuera.append((mascara[j + 1:fin], j + 1))
        i -= 1
    return fuera


def _agrega(nombre: str) -> bool:
    funcion = CATALOGO.get(nombre.upper())
    if funcion is not None:
        return funcion.agrega
    return nombre.upper() in AGREGADOS_SQL


def _agregaciones_anidadas(expresion: str, mascara: str,
                           ctx: Contexto) -> list[Fallo]:
    """
    Referencias a metricas que ya agregan, metidas dentro de una agregacion.

    Se revisa sobre el texto que se escribio y no sobre el SQL porque el mensaje
    tiene que hablar de `[utilidad_total]` y de `SUMA`, que es lo que hay en la
    pantalla. El SQL compilado dice `SUM(SUM(...))`, que no aparece en ningun
    sitio donde quien escribe pueda mirarlo.
    """
    fallos: list[Fallo] = []
    for m in re.finditer(r"\[([^\]]+)\]", mascara):
        nombre = expresion[m.start(1):m.end(1)].strip()
        referida = ctx.metrica(nombre)
        if referida is None:
            continue
        try:
            if sqlglot.parse_one(compilar(referida, ctx),
                                 read=DIALECTO).find(exp.AggFunc) is None:
                continue                      # no agrega: envolverla esta bien
        except (ErrorFormula, Exception):     # pragma: no cover
            continue                          # su propio error ya se dira aparte
        envoltura = next((f for f in _envolturas(mascara, m.start())
                          if _agrega(f[0])), None)
        if envoltura is None:
            continue
        funcion = envoltura[0].upper()
        fallos.append(Fallo(
            f"[{nombre}] ya agrega por si sola, asi que {funcion}([{nombre}]) "
            f"seria agregar dos veces y eso no se puede calcular. Quitale el "
            f"{funcion} de fuera y usa [{nombre}] directamente.",
            m.start(), m.end() - m.start()))
    return fallos


def _contar_argumentos(mascara: str, abre: int) -> int | None:
    """Cuantos argumentos hay entre el parentesis en `abre` y el que lo cierra."""
    profundidad, comas, i = 0, 0, abre
    vacio = True
    while i < len(mascara):
        c = mascara[i]
        if c == "(":
            profundidad += 1
        elif c == ")":
            profundidad -= 1
            if profundidad == 0:
                return 0 if vacio and comas == 0 else comas + 1
        elif c == "," and profundidad == 1:
            comas += 1
        elif not c.isspace() and profundidad == 1:
            vacio = False
        i += 1
    return None
