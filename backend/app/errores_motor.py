"""
Los errores de DuckDB, dichos en castellano.

Un mensaje como

    Binder Error: aggregate function calls cannot be nested
    LINE 5:     COALESCE((SUM((SUM("t0"."Utilidad")))) / NULLIF(...

es correcto y es inutil: habla de un SQL que quien escribio la formula no ha
visto nunca, en un idioma que no es el suyo, y señala una columna `t0` que es un
alias que inventamos nosotros. La persona que lo lee escribio
`DIVIDIR(SUMA([utilidad_total]), ...)` y necesita que le hablen de eso.

Esto no sustituye a la revision de `semantic.formula`, que atrapa el problema
ANTES de ejecutar y con la posicion exacta. Es la red de abajo: para lo que se
escapa, para el SQL escrito a mano y para los modelos que llegaron por YAML sin
pasar por la pantalla.

El detalle original nunca se tira: va detras, porque cuando la traduccion no
acierta es lo unico que permite averiguar que paso.
"""

from __future__ import annotations

import re

#: (patron, que decir). El orden importa: gana el primero que case.
_TRADUCCIONES: list[tuple[str, str]] = [
    (
        r"aggregate function calls cannot be nested",
        "Hay una agregacion dentro de otra. Suele pasar al meter dentro de "
        "SUMA una metrica que ya suma: si '[otra_metrica]' ya agrega, se usa "
        "tal cual, sin envolverla.",
    ),
    (
        r"Referenced column \"?([\w.]+)\"? not found",
        "La columna '{0}' no existe en las tablas de esta consulta. Revisa "
        "como esta escrita en el modelo y si la entidad donde vive esta "
        "relacionada con esta.",
    ),
    (
        r"Table with name ([\w.]+) does not exist",
        "La tabla '{0}' no existe en el motor. Todavia no se ha cargado, o el "
        "modelo la nombra distinto de como se llama el dataset.",
    ),
    (
        r"No function matches the given name and argument types '([^']+)'",
        "No hay ninguna funcion '{0}' con esos argumentos. Revisa el nombre y "
        "cuantos valores lleva.",
    ),
    (
        r"Could not convert string '([^']*)' to",
        "El valor '{0}' no es del tipo que la operacion esperaba. Suele ser una "
        "columna declarada como numero o fecha que en los datos trae texto.",
    ),
    (
        r"division by zero",
        "Hay una division entre cero. DIVIDIR(a, b, 0) devuelve el tercer "
        "argumento en vez de fallar.",
    ),
    (
        r"column \"?([\w.]+)\"? must appear in the GROUP BY",
        "'{0}' esta fuera de una agregacion y mezclada con otras que si "
        "agregan. Envuelvela en SUMA, PROMEDIO, MAXIMO… o quitala.",
    ),
    (
        r"Out of Memory Error",
        "Al motor se le acabo la memoria con esta consulta. Baja el limite de "
        "filas o desglosa por menos dimensiones a la vez.",
    ),
]


def en_castellano(error: Exception | str) -> str:
    """
    El error, explicado. Si no se reconoce, se devuelve tal cual: inventarse una
    explicacion que no corresponde es peor que enseñar el mensaje del motor.
    """
    crudo = str(error)
    for patron, plantilla in _TRADUCCIONES:
        m = re.search(patron, crudo, re.IGNORECASE)
        if m:
            texto = plantilla.format(*m.groups())
            return f"{texto} · Detalle del motor: {_recortar(crudo)}"
    return crudo


def _recortar(crudo: str, tope: int = 300) -> str:
    """
    Una linea y no diez. DuckDB adjunta el SQL con un cursor de flechas debajo,
    que en una consulta con CTE ocupa media pantalla y no aporta nada a quien no
    escribio ese SQL.
    """
    primera = crudo.strip().split("\n")[0].strip()
    return primera[:tope] + ("…" if len(primera) > tope else "")
