"""
Como viajan los valores entre los dos procesos.

El conector ODBC esta escrito alrededor de una idea: **los tipos los declara el
driver, no los adivina nadie**. Un puente que convierta todo a texto por el camino
tira justo eso a la basura, y la forma en que se nota es la peor posible — una
cifra de dinero que llega como cadena, o un DECIMAL(18,4) redondeado a float sin
que nadie se entere hasta que la suma no cuadra contra el sistema de origen.

Asi que aqui hay dos decisiones y las dos son a proposito:

1. **Los lotes viajan por columnas, no por filas.** Un valor que no es JSON nativo
   —Decimal, fecha, bytes— necesita decir de que tipo es. Etiquetando cada celda
   eso son 20,000 etiquetas por columna y por lote; etiquetando la columna entera,
   una. Ademas es la forma en la que Arrow los quiere despues.

2. **La etiqueta se decide mirando los valores, no lo que declara el driver.** Hay
   drivers que declaran una cosa y devuelven otra. Si en una columna aparecen
   tipos mezclados, la columna entera se manda como texto: perder el tipo de una
   columna rara es malo, pero convertir mal un numero es peor.

Los Decimal viajan como su texto, nunca como float: `float(Decimal("0.1"))` ya no
es 0.1, y ese es exactamente el error que este conector existe para no cometer.
"""

from __future__ import annotations

import base64
import datetime
import decimal
from typing import Any

#: Version del dialogo. El cliente la comprueba al abrir: un servidor viejo con un
#: cliente nuevo falla de formas raras y tarde, y aqui falla claro y al principio.
VERSION = 1


class Desconocido:
    """
    Marcador para un tipo que el driver declara y no sabemos traducir.

    Existe para no mentir diciendo `str`: el conector trata distinto una columna
    que el driver declara de texto de una que cayo a texto por no reconocerla —a
    la segunda le aplica `str()` sobre el valor— y esa diferencia se perderia si
    aqui se colara un `str` cualquiera.
    """


#: Tipos de Python que puede declarar un driver, y su nombre en el protocolo.
_TIPOS: list[tuple[str, type]] = [
    ("str", str),
    ("bool", bool),                 # antes que int: bool es subclase de int
    ("int", int),
    ("float", float),
    ("bytes", bytes),
    ("bytearray", bytearray),
    ("decimal", decimal.Decimal),
    ("datetime", datetime.datetime),  # antes que date, por lo mismo
    ("date", datetime.date),
    ("time", datetime.time),
]

_POR_NOMBRE: dict[str, type] = {n: t for n, t in _TIPOS}


def nombre_tipo(tipo: Any) -> str:
    for nombre, t in _TIPOS:
        if tipo is t:
            return nombre
    return "?"


def tipo_de(nombre: str) -> type:
    return _POR_NOMBRE.get(nombre, Desconocido)


# --------------------------------------------------------------------------- #
# Descripcion de columnas
# --------------------------------------------------------------------------- #

def codificar_descripcion(descripcion: Any) -> list[dict] | None:
    """`cursor.description` de pyodbc a algo que quepa en JSON."""
    if descripcion is None:
        return None
    return [
        {"nombre": d[0], "tipo": nombre_tipo(d[1]), "tamano": d[2],
         "bytes": d[3], "precision": d[4], "escala": d[5], "nulable": d[6]}
        for d in descripcion
    ]


def decodificar_descripcion(datos: list[dict] | None) -> list[tuple] | None:
    """De vuelta a la forma de 7 posiciones que espera el conector."""
    if datos is None:
        return None
    return [
        (d["nombre"], tipo_de(d["tipo"]), d["tamano"], d["bytes"],
         d["precision"], d["escala"], d["nulable"])
        for d in datos
    ]


# --------------------------------------------------------------------------- #
# Valores
# --------------------------------------------------------------------------- #

def _codigo_de(valor: Any) -> str:
    if valor is None:
        return "nulo"
    if isinstance(valor, bool):
        return "raw"
    if isinstance(valor, (int, float, str)):
        return "raw"
    if isinstance(valor, decimal.Decimal):
        return "dec"
    if isinstance(valor, datetime.datetime):
        return "dt"
    if isinstance(valor, datetime.date):
        return "date"
    if isinstance(valor, datetime.time):
        return "time"
    if isinstance(valor, (bytes, bytearray)):
        return "b64"
    return "txt"


_A_TEXTO = {
    "dec": str,
    "dt": lambda v: v.isoformat(),
    "date": lambda v: v.isoformat(),
    "time": lambda v: v.isoformat(),
    "b64": lambda v: base64.b64encode(bytes(v)).decode("ascii"),
    "txt": str,
}


def codificar_columna(valores: list) -> dict:
    """
    Una columna de un lote: su codigo y sus valores ya en JSON.

    Los NULL no votan por el codigo —una columna con un solo valor y mil nulos es
    del tipo de ese valor— y una columna entera de nulos se manda como esta.
    """
    codigo = "nulo"
    for v in valores:
        c = _codigo_de(v)
        if c == "nulo":
            continue
        if codigo == "nulo":
            codigo = c
        elif codigo != c:
            # Tipos mezclados en la misma columna. No se elige uno y se fuerza el
            # resto: se manda texto y que decida el conector, que es quien sabe
            # que tipo declaro el origen.
            codigo = "txt"
            break

    if codigo in ("nulo", "raw"):
        return {"cod": codigo, "v": list(valores)}
    a_texto = _A_TEXTO[codigo]
    return {"cod": codigo,
            "v": [None if v is None else a_texto(v) for v in valores]}


_DE_TEXTO = {
    "dec": decimal.Decimal,
    "dt": datetime.datetime.fromisoformat,
    "date": lambda s: datetime.date.fromisoformat(s),
    "time": datetime.time.fromisoformat,
    "b64": lambda s: base64.b64decode(s.encode("ascii")),
    "txt": lambda s: s,
}


def decodificar_columna(datos: dict) -> list:
    codigo = datos["cod"]
    valores = datos["v"]
    if codigo in ("nulo", "raw"):
        return list(valores)
    de_texto = _DE_TEXTO[codigo]
    return [None if v is None else de_texto(v) for v in valores]


def codificar_lote(filas: list) -> dict:
    """Un bloque de filas de pyodbc como columnas codificadas."""
    if not filas:
        return {"filas": 0, "columnas": []}
    columnas = list(zip(*(tuple(f) for f in filas)))
    return {"filas": len(filas),
            "columnas": [codificar_columna(list(c)) for c in columnas]}


def decodificar_lote(datos: dict) -> list[tuple]:
    """De vuelta a filas, que es lo que el conector espera de `fetchmany`."""
    if not datos.get("filas"):
        return []
    columnas = [decodificar_columna(c) for c in datos["columnas"]]
    return list(zip(*columnas))
