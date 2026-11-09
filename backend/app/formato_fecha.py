"""
Cómo guarda el origen la fecha de la columna de partición.

Muchos sistemas viejos no guardan las fechas como fechas: las guardan como texto
('20260715', '15/07/2026'), como número (20260715) o como días contados desde una
fecha (Excel, Clarion, Pervasive, Btrieve…). Para partir el Parquet por mes hay que
convertirlas, y para que una recarga por ventana sea rápida hay que filtrar **en el
origen**, escribiendo el rango como el origen lo entiende. Si no, se trae la tabla
entera y se recorta después: correcto, pero dos meses cuestan lo mismo que diez años.

Con una expresión libre de DuckDB lo primero se puede y lo segundo no, porque nadie
sabe cómo traducir esa expresión al SQL del origen. Por eso existe este campo: el
usuario dice **qué forma tiene** la fecha y de ahí salen las dos cosas.

Formas (se guardan como texto en `Dataset.formato_fecha`):

- ``texto:<formato>``: texto con un formato de strftime, p. ej. ``texto:%Y%m%d``,
  ``texto:%d/%m/%Y`` o ``texto:%Y-%m-%d %H:%M:%S``.
- ``numero:<formato>``: número cuyos dígitos siguen un formato, p. ej.
  ``numero:%Y%m%d`` (20260715) o ``numero:%Y%m`` (202607).
- ``dias:<AAAA-MM-DD>=<n>``: número de días; el valor ``n`` corresponde a esa
  fecha. ``dias:1899-12-30=0`` es el serial de Excel; ``dias:1970-01-01=719163``,
  el ordinal de Python/Pervasive; ``dias:1970-01-01=0``, días Unix.

El filtro en el origen solo es posible cuando comparar los valores del origen
equivale a comparar las fechas: texto o número en orden año-mes-día (``%Y%m%d``,
``%Y-%m-%d``…) y días. Con ``texto:%d/%m/%Y`` no lo es ('01/08' < '31/07'), así
que se trae la tabla y se recorta después, como antes: más lento, igual de correcto.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

#: Orden de significancia de las directivas que dejan comparar como texto/número.
_ORDEN = ["Y", "m", "d", "H", "M", "S"]
_DIRECTIVA = re.compile(r"%(.)")
_DIAS = re.compile(r"^(\d{4}-\d{2}-\d{2})=(-?\d{1,9})$")
_MIN, _MAX = date(1, 1, 1), date(9999, 12, 31)


class FormatoInvalido(ValueError):
    """El formato de fecha no se entiende."""


def catalogo() -> list[dict]:
    """Opciones para la pantalla, con ejemplos que el usuario reconoce."""
    return [
        {"clave": "texto", "etiqueta": "Texto con formato",
         "ejemplos": ["%Y%m%d", "%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"]},
        {"clave": "numero", "etiqueta": "Número con formato",
         "ejemplos": ["%Y%m%d", "%Y%m"]},
        {"clave": "dias", "etiqueta": "Días contados desde una fecha",
         "ejemplos": ["1899-12-30=0", "1970-01-01=719163", "1970-01-01=0"]},
    ]


def _partes(formato: str) -> tuple[str, str]:
    tipo, _, resto = (formato or "").partition(":")
    if tipo not in ("texto", "numero", "dias") or not resto:
        raise FormatoInvalido(
            f"Formato de fecha desconocido: '{formato}'. Usa 'texto:%Y%m%d', "
            f"'numero:%Y%m%d' o 'dias:1899-12-30=0'.")
    return tipo, resto


def validar(formato: str | None) -> str | None:
    """Devuelve el formato normalizado, None si viene vacío, o revienta."""
    if not formato or not formato.strip():
        return None
    formato = formato.strip()
    if len(formato) > 60:
        raise FormatoInvalido("El formato de fecha es demasiado largo (máximo 60).")
    tipo, resto = _partes(formato)
    if tipo == "dias":
        m = _DIAS.match(resto)
        if not m:
            raise FormatoInvalido(
                "Los días se escriben como 'AAAA-MM-DD=n': la fecha a la que "
                "corresponde el número n. Por ejemplo, 'dias:1899-12-30=0' (Excel).")
        try:
            date.fromisoformat(m.group(1))
        except ValueError:
            raise FormatoInvalido(f"'{m.group(1)}' no es una fecha válida.")
        return formato
    directivas = _DIRECTIVA.findall(resto)
    if not directivas:
        raise FormatoInvalido(
            "El formato no tiene ninguna directiva de fecha (%Y, %m, %d…).")
    if "Y" not in directivas and "y" not in directivas:
        raise FormatoInvalido("El formato necesita el año (%Y o %y).")
    if tipo == "numero" and _DIRECTIVA.sub("", resto):
        raise FormatoInvalido(
            "Un número solo lleva dígitos: el formato no puede tener separadores. "
            "Si el origen guarda '2026-07-15', es texto: usa 'texto:%Y-%m-%d'.")
    try:
        date(2026, 7, 15).strftime(resto)
    except ValueError as e:
        raise FormatoInvalido(f"Formato inválido: {e}")
    return formato


def _ref_dias(resto: str) -> tuple[date, int]:
    m = _DIAS.match(resto)
    return date.fromisoformat(m.group(1)), int(m.group(2))


def expresion(formato: str, columna_sql: str) -> str:
    """
    La expresión de DuckDB que convierte la columna (ya citada) en fecha.

    Siempre tolerante: un valor vacío o ilegible da NULL y la fila va a
    'sin_fecha', en vez de tumbar la carga entera.
    """
    tipo, resto = _partes(formato)
    if tipo == "texto":
        # trim: los CHAR de ancho fijo llegan con espacios a la derecha.
        return (f"try_strptime(trim(CAST({columna_sql} AS VARCHAR)), "
                f"'{_sql_texto(resto)}')")
    if tipo == "numero":
        return (f"try_strptime(CAST(TRY_CAST({columna_sql} AS BIGINT) AS VARCHAR), "
                f"'{_sql_texto(resto)}')")
    ref, n = _ref_dias(resto)
    lo = n - (ref - _MIN).days
    hi = n + (_MAX - ref).days
    valor = f"TRY_CAST({columna_sql} AS BIGINT)"
    return (f"CASE WHEN {valor} BETWEEN {lo} AND {hi} "
            f"THEN DATE '{ref.isoformat()}' + CAST({valor} - {n} AS INTEGER) END")


def _sql_texto(s: str) -> str:
    return s.replace("'", "''")


def _granularidad(directivas: list[str]) -> str | None:
    """
    La directiva más fina si el formato se puede comparar como texto o número,
    o None si no. Se puede cuando las directivas van de la más significativa a la
    menos, empezando por el año de cuatro cifras y sin saltarse ninguna:
    %Y, %Y%m, %Y%m%d, %Y-%m-%d %H:%M…
    """
    if not directivas or directivas != _ORDEN[:len(directivas)]:
        return None
    return directivas[-1]


def limites(formato: str | None, desde: str, hasta: str) -> tuple[str, str] | None:
    """
    El rango [desde, hasta] (inclusive, AAAA-MM-DD) como dos literales SQL del
    origen: ``columna >= a AND columna < b``. None si el formato no deja filtrar
    allá; entonces se trae todo y se recorta al escribir.

    Los límites pueden quedar más anchos que el rango (un formato solo de año trae
    el año entero): lo que sobra se recorta al escribir. Nunca más estrechos.
    """
    if not formato:
        return None
    tipo, resto = _partes(formato)
    d0 = date.fromisoformat(desde[:10])
    d1 = date.fromisoformat(hasta[:10]) + timedelta(days=1)
    if tipo == "dias":
        ref, n = _ref_dias(resto)
        return str(n + (d0 - ref).days), str(n + (d1 - ref).days)
    fino = _granularidad(_DIRECTIVA.findall(resto))
    if fino is None:
        return None
    if fino == "Y":
        a, b = date(d0.year, 1, 1), date(d1.year + (d1 != date(d1.year, 1, 1)), 1, 1)
    elif fino == "m":
        a = d0.replace(day=1)
        b = d1 if d1.day == 1 else (d1.replace(day=1) + timedelta(days=32)).replace(day=1)
    else:
        a, b = d0, d1
    la, lb = a.strftime(resto), b.strftime(resto)
    if tipo == "numero":
        return str(int(la)), str(int(lb))
    return f"'{_sql_texto(la)}'", f"'{_sql_texto(lb)}'"
