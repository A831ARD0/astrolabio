"""
Transformaciones: los pasos visuales y su compilación a SQL.

El objetivo de esta capa es que el usuario no escriba código **y a la vez** que lo
que hace sea SQL legible y auditable. Cada paso se compila a un CTE con nombre, de
forma que el SQL resultante se lee como la lista de pasos:

    WITH p0_origen AS (...),
         p1_filtrar AS (SELECT * FROM p0_origen WHERE ...),
         p2_agrupar AS (SELECT ... FROM p1_filtrar GROUP BY ...)
    SELECT * FROM p2_agrupar

No es estética: cuando una cifra no cuadra, poder leer el SQL paso por paso —y
contar filas en cada uno— es la diferencia entre depurarlo en diez minutos y
adivinar.

Sobre las expresiones que escribe el usuario (una columna derivada, una condición):
son SQL de verdad, como en cualquier herramienta de BI. Se pasan por el analizador
de SQLGlot y se **rechaza** todo lo que no sea una expresión escalar: subconsultas,
DDL, DML, varias sentencias. Los valores de los filtros no se interpolan nunca: van
como parámetros.
"""

from __future__ import annotations

from typing import Any, Literal

import sqlglot
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlglot import exp

DIALECTO = "duckdb"

OPERADORES = {
    "=": "=", "!=": "<>", ">": ">", ">=": ">=", "<": "<", "<=": "<=",
    "contiene": "ILIKE", "empieza_con": "ILIKE", "termina_con": "ILIKE",
    "en": "IN", "no_en": "NOT IN", "es_nulo": "IS NULL", "no_es_nulo": "IS NOT NULL",
}
SIN_VALOR = {"es_nulo", "no_es_nulo"}
DE_LISTA = {"en", "no_en"}

AGREGADOS = {
    "suma": "SUM", "promedio": "AVG", "minimo": "MIN", "maximo": "MAX",
    "cuenta": "COUNT", "cuenta_distintos": "COUNT",
}

TIPOS_UNION = {
    "interna": "INNER JOIN",
    "izquierda": "LEFT JOIN",
    "derecha": "RIGHT JOIN",
    "completa": "FULL OUTER JOIN",
}


class ErrorTransformacion(Exception):
    """La transformación no se puede compilar. El mensaje es para el usuario."""


# --------------------------------------------------------------------------- #
# Validación de expresiones
# --------------------------------------------------------------------------- #

_PROHIBIDOS = (
    exp.Select, exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop,
    exp.Alter, exp.Command, exp.Subquery, exp.Union,
)


def expresion_segura(texto: str, para: str) -> str:
    """
    Valida una expresión escalar escrita por el usuario y la devuelve normalizada.

    Se apoya en el árbol sintáctico y no en una lista de palabras prohibidas:
    buscar "DROP" en el texto se salta con comentarios, mayúsculas raras o un
    identificador entre comillas. El árbol no se deja engañar.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ErrorTransformacion(f"{para}: la expresión está vacía.")
    try:
        arboles = sqlglot.parse(texto, read=DIALECTO)
    except Exception as e:
        raise ErrorTransformacion(f"{para}: no se entiende la expresión — {e}") from e

    if len(arboles) != 1 or arboles[0] is None:
        raise ErrorTransformacion(
            f"{para}: se espera una sola expresión, no varias sentencias.")
    arbol = arboles[0]

    if isinstance(arbol, _PROHIBIDOS) or any(
        isinstance(n, _PROHIBIDOS) for n in arbol.walk()
    ):
        raise ErrorTransformacion(
            f"{para}: solo se admite una expresión de columna. Una subconsulta o "
            f"una sentencia completa no van aquí — para eso está el modo SQL.")
    return arbol.sql(dialect=DIALECTO)


def _ident(nombre: str) -> str:
    """Identificador citado. Los nombres de columna vienen del catálogo, no de aire."""
    if not nombre or '"' in nombre:
        raise ErrorTransformacion(f"Nombre de columna no válido: {nombre!r}")
    return '"' + nombre + '"'


# --------------------------------------------------------------------------- #
# Pasos
# --------------------------------------------------------------------------- #

class _Paso(BaseModel):
    model_config = ConfigDict(extra="allow")


class Condicion(_Paso):
    campo: str
    op: str
    valor: Any = None

    @field_validator("op")
    @classmethod
    def operador_conocido(cls, v: str) -> str:
        if v not in OPERADORES:
            raise ValueError(
                f"operador '{v}' desconocido; los válidos son: "
                f"{', '.join(sorted(OPERADORES))}")
        return v


class PasoFiltrar(_Paso):
    tipo: Literal["filtrar"] = "filtrar"
    condiciones: list[Condicion] = Field(min_length=1)
    modo: Literal["y", "o"] = "y"


class PasoColumnas(_Paso):
    """Elegir columnas. `mantener` manda si viene; si no, se quitan las de `quitar`."""
    tipo: Literal["columnas"] = "columnas"
    mantener: list[str] = []
    quitar: list[str] = []


class PasoRenombrar(_Paso):
    tipo: Literal["renombrar"] = "renombrar"
    cambios: dict[str, str] = Field(min_length=1)


class PasoDerivar(_Paso):
    tipo: Literal["derivar"] = "derivar"
    nombre: str
    expresion: str


class Agregado(_Paso):
    nombre: str
    funcion: str
    campo: str | None = None      # None solo para cuenta(*)

    @field_validator("funcion")
    @classmethod
    def funcion_conocida(cls, v: str) -> str:
        if v not in AGREGADOS:
            raise ValueError(
                f"función '{v}' desconocida; las válidas son: "
                f"{', '.join(sorted(AGREGADOS))}")
        return v


class PasoAgrupar(_Paso):
    tipo: Literal["agrupar"] = "agrupar"
    por: list[str] = []
    agregados: list[Agregado] = Field(min_length=1)


class PasoUnir(_Paso):
    """
    `traer` dice qué columnas se toman del lado derecho, y `renombres` cómo se
    llaman al llegar. Se piden explícitas en vez de traerlas todas con un prefijo
    automático porque dos columnas con el mismo nombre tras un join es de donde
    salen los "columna ambigua" a mitad de un tablero, y un prefijo automático
    ensucia todos los nombres para evitar un choque que casi nunca ocurre.

    Si `traer` viene vacío se traen todas menos las claves del join, que ya están
    del lado izquierdo.
    """
    tipo: Literal["unir"] = "unir"
    con: str                                  # nombre de otro origen
    como: Literal["interna", "izquierda", "derecha", "completa"] = "izquierda"
    en: list[tuple[str, str]] = Field(min_length=1)   # [(izquierda, derecha)]
    traer: list[str] = []
    renombres: dict[str, str] = {}


class PasoApilar(_Paso):
    """Union: pegar filas de otro origen con las mismas columnas."""
    tipo: Literal["apilar"] = "apilar"
    con: list[str] = Field(min_length=1)
    quitar_repetidas: bool = False


class PasoOrdenar(_Paso):
    tipo: Literal["ordenar"] = "ordenar"
    por: list[str] = Field(min_length=1)
    descendente: bool = False


class PasoLimitar(_Paso):
    tipo: Literal["limitar"] = "limitar"
    n: int = Field(ge=1, le=10_000_000)


class PasoDistintos(_Paso):
    tipo: Literal["distintos"] = "distintos"


Paso = (
    PasoFiltrar | PasoColumnas | PasoRenombrar | PasoDerivar | PasoAgrupar
    | PasoUnir | PasoApilar | PasoOrdenar | PasoLimitar | PasoDistintos
)


class Origen(_Paso):
    """
    De dónde sale una tabla de entrada.

      tabla                 una tabla o vista del motor analítico
      dataset               un dataset ingestado (Parquet particionado)
      tabla_en_conexiones   la MISMA tabla traída de todas las conexiones,
                            apilada; `referencia` es el nombre de la tabla en el
                            origen, no el de un dataset

    El tercero existe por las cuarenta sucursales: declarar cuarenta orígenes a
    mano —y acordarse de agregar el cuarenta y uno cuando abra una agencia
    nueva— es trabajo que la máquina hace sola. Cada parte llega con las
    etiquetas de su conexión, que es lo que después distingue de dónde vino cada
    fila.

    En los tres casos el motor ve un nombre; la diferencia la resuelve quien
    prepara la conexión, no el compilador.
    """
    nombre: str                     # alias dentro de la transformación
    tipo: Literal["tabla", "dataset", "tabla_en_conexiones"] = "tabla"
    referencia: str                 # nombre de la tabla o del dataset


class Transformacion(BaseModel):
    model_config = ConfigDict(extra="allow")

    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None
    # Sin minimo: en modo SQL una consulta puede no leer de ninguna tabla. El
    # caso real es generar un calendario —`FROM range(fecha, fecha, INTERVAL)`—,
    # que es una tabla que no existe en ningun origen porque se fabrica aqui.
    # Obligar a declarar un origen que no se usa era pedir un tramite.
    origenes: list[Origen] = []
    pasos: list[Paso] = []
    # Modo SQL: si viene, manda sobre los pasos. Existe porque mucha gente ya
    # tiene su consulta escrita y obligarla a rearmarla en una interfaz es
    # perder su trabajo.
    sql: str | None = None

    @model_validator(mode="after")
    def con_origenes_o_con_sql(self):
        if not self.origenes and not self.es_sql:
            raise ValueError(
                "una transformacion por pasos necesita al menos un origen")
        return self

    @field_validator("origenes")
    @classmethod
    def alias_unicos(cls, v: list[Origen]) -> list[Origen]:
        nombres = [o.nombre for o in v]
        repetidos = {n for n in nombres if nombres.count(n) > 1}
        if repetidos:
            raise ValueError(f"orígenes repetidos: {', '.join(sorted(repetidos))}")
        return v

    @property
    def es_sql(self) -> bool:
        return bool(self.sql and self.sql.strip())


# --------------------------------------------------------------------------- #
# Compilador
# --------------------------------------------------------------------------- #

class Compilada:
    def __init__(self, sql: str, parametros: list[Any], etapas: list[tuple[str, str]]):
        self.sql = sql
        self.parametros = parametros
        # [(nombre_cte, descripción)] en orden. Sirve para contar filas por paso.
        self.etapas = etapas


def compilar(t: Transformacion, resolver: dict[str, str]) -> Compilada:
    """
    Compila la transformación a un SELECT.

    `resolver` traduce el alias de cada origen a lo que se pone en el FROM (un
    nombre de tabla o un `read_parquet(...)`). El compilador no sabe de rutas de
    disco: eso es de la capa que ejecuta.
    """
    for o in t.origenes:
        if o.nombre not in resolver:
            raise ErrorTransformacion(
                f"El origen '{o.nombre}' no se pudo resolver a una tabla.")

    if t.es_sql:
        return _compilar_sql(t, resolver)

    partes: list[str] = []
    parametros: list[Any] = []
    etapas: list[tuple[str, str]] = []

    primero = t.origenes[0]
    actual = "p0_origen"
    partes.append(f"{actual} AS (SELECT * FROM {resolver[primero.nombre]})")
    etapas.append((actual, f"origen: {primero.referencia}"))

    for i, paso in enumerate(t.pasos, start=1):
        nombre = f"p{i}_{paso.tipo}"
        cuerpo, params, descripcion = _compilar_paso(paso, actual, resolver)
        partes.append(f"{nombre} AS ({cuerpo})")
        parametros.extend(params)
        etapas.append((nombre, descripcion))
        actual = nombre

    sql = "WITH " + ",\n     ".join(partes) + f"\nSELECT * FROM {actual}"
    return Compilada(sql, parametros, etapas)


def _compilar_sql(t: Transformacion, resolver: dict[str, str]) -> Compilada:
    """
    Modo SQL: la consulta del usuario tal cual, con los orígenes disponibles como
    CTEs con su alias. Así una consulta pegada puede referirse a `ventas` sin saber
    si detrás hay una tabla o un Parquet particionado.
    """
    texto = (t.sql or "").strip().rstrip(";")
    try:
        arboles = sqlglot.parse(texto, read=DIALECTO)
    except Exception as e:
        raise ErrorTransformacion(f"El SQL no se entiende: {e}") from e
    if len(arboles) != 1 or arboles[0] is None:
        raise ErrorTransformacion(
            "Se espera una sola consulta. Varias sentencias separadas por ';' no.")
    arbol = arboles[0]
    if not isinstance(arbol, (exp.Select, exp.Union, exp.Subquery, exp.With)):
        raise ErrorTransformacion(
            "Solo se admite una consulta de lectura (SELECT). Una transformación "
            "no ejecuta DDL ni DML: lo que produce se materializa aparte.")
    for prohibido in (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop,
                      exp.Alter, exp.Command):
        if list(arbol.find_all(prohibido)):
            raise ErrorTransformacion(
                f"El SQL contiene una sentencia que no se permite aquí "
                f"({prohibido.__name__.upper()}).")

    # Lo que la consulta nombra en sus FROM/JOIN tiene que estar entre los
    # origenes. Si no, DuckDB contesta «Catalog Error: Table with name X does not
    # exist! Did you mean "information_schema.constraint_column_usage"?», que
    # culpa a la tabla y no dice lo unico util: que falta agregarla como origen.
    alias = {o.nombre for o in t.origenes}
    propias = {c.alias_or_name for c in arbol.find_all(exp.CTE)}
    faltan = sorted(
        n.name for n in arbol.find_all(exp.Table)
        if n.name and n.name not in alias and n.name not in propias
    )
    if faltan:
        disponibles = ", ".join(sorted(alias)) or "ninguno"
        raise ErrorTransformacion(
            f"La consulta lee de {', '.join(repr(f) for f in faltan)}, que no está "
            f"entre los orígenes de esta transformación. Agrégalo desde «Orígenes "
            f"disponibles», a la izquierda, y volverá a funcionar. "
            f"Orígenes de esta transformación: {disponibles}.")

    cuerpo = arbol.sql(dialect=DIALECTO, pretty=True)
    # Sin origenes no hay CTE que anteponer, y un `WITH` vacio no es SQL. Pasa
    # cuando la consulta fabrica sus propias filas: un calendario sale de
    # `range(fecha, fecha, INTERVAL)` y no lee de ninguna tabla.
    if not t.origenes:
        return Compilada(cuerpo, [], [("sql", "consulta escrita a mano")])

    ctes = ",\n     ".join(
        f"{_ident(o.nombre)} AS (SELECT * FROM {resolver[o.nombre]})"
        for o in t.origenes
    )
    return Compilada(f"WITH {ctes}\n{cuerpo}", [],
                     [("sql", "consulta escrita a mano")])


def _compilar_paso(paso: Paso, entrada: str,
                   resolver: dict[str, str]) -> tuple[str, list[Any], str]:
    if isinstance(paso, PasoFiltrar):
        trozos, params = [], []
        for c in paso.condiciones:
            sql_op = OPERADORES[c.op]
            col = _ident(c.campo)
            if c.op in SIN_VALOR:
                trozos.append(f"{col} {sql_op}")
            elif c.op in DE_LISTA:
                valores = list(c.valor or [])
                if not valores:
                    raise ErrorTransformacion(
                        f"filtrar {c.campo}: la lista de valores está vacía.")
                trozos.append(f"{col} {sql_op} ({', '.join('?' for _ in valores)})")
                params.extend(valores)
            elif c.op in ("contiene", "empieza_con", "termina_con"):
                patron = {
                    "contiene": f"%{c.valor}%",
                    "empieza_con": f"{c.valor}%",
                    "termina_con": f"%{c.valor}",
                }[c.op]
                trozos.append(f"{col} {sql_op} ?")
                params.append(patron)
            else:
                trozos.append(f"{col} {sql_op} ?")
                params.append(c.valor)
        union = " AND " if paso.modo == "y" else " OR "
        donde = union.join(trozos)
        return (f"SELECT * FROM {entrada} WHERE {donde}", params,
                f"filtrar: {len(paso.condiciones)} condición(es)")

    if isinstance(paso, PasoColumnas):
        if paso.mantener:
            cols = ", ".join(_ident(c) for c in paso.mantener)
            return (f"SELECT {cols} FROM {entrada}", [],
                    f"columnas: quedan {len(paso.mantener)}")
        if paso.quitar:
            # EXCLUDE de DuckDB: quitar columnas sin tener que listar las demás,
            # que además cambiarían si la tabla de origen cambia.
            cols = ", ".join(_ident(c) for c in paso.quitar)
            return (f"SELECT * EXCLUDE ({cols}) FROM {entrada}", [],
                    f"columnas: se quitan {len(paso.quitar)}")
        raise ErrorTransformacion(
            "columnas: hay que decir cuáles se mantienen o cuáles se quitan.")

    if isinstance(paso, PasoRenombrar):
        renombres = ", ".join(
            f"{_ident(de)} AS {_ident(a)}" for de, a in paso.cambios.items())
        quitar = ", ".join(_ident(de) for de in paso.cambios)
        return (f"SELECT * EXCLUDE ({quitar}), {renombres} FROM {entrada}", [],
                f"renombrar: {len(paso.cambios)} columna(s)")

    if isinstance(paso, PasoDerivar):
        expresion = expresion_segura(paso.expresion, f"derivar '{paso.nombre}'")
        return (f"SELECT *, {expresion} AS {_ident(paso.nombre)} FROM {entrada}", [],
                f"derivar: {paso.nombre}")

    if isinstance(paso, PasoAgrupar):
        seleccion = [_ident(c) for c in paso.por]
        for a in paso.agregados:
            fn = AGREGADOS[a.funcion]
            if a.funcion == "cuenta" and not a.campo:
                seleccion.append(f"COUNT(*) AS {_ident(a.nombre)}")
            elif a.funcion == "cuenta_distintos":
                seleccion.append(
                    f"COUNT(DISTINCT {_ident(a.campo or '')}) AS {_ident(a.nombre)}")
            else:
                if not a.campo:
                    raise ErrorTransformacion(
                        f"agrupar: '{a.nombre}' ({a.funcion}) necesita una columna.")
                seleccion.append(f"{fn}({_ident(a.campo)}) AS {_ident(a.nombre)}")
        sql = f"SELECT {', '.join(seleccion)} FROM {entrada}"
        if paso.por:
            sql += f" GROUP BY {', '.join(_ident(c) for c in paso.por)}"
        return (sql, [],
                f"agrupar: por {len(paso.por)}, {len(paso.agregados)} agregado(s)")

    if isinstance(paso, PasoUnir):
        if paso.con not in resolver:
            raise ErrorTransformacion(
                f"unir: el origen '{paso.con}' no está entre los orígenes.")
        tipo = TIPOS_UNION[paso.como]
        condicion = " AND ".join(
            f"izq.{_ident(i)} = der.{_ident(d)}" for i, d in paso.en)

        if paso.traer:
            derecha = ", ".join(
                f"der.{_ident(c)} AS {_ident(paso.renombres.get(c, c))}"
                for c in paso.traer)
        else:
            # Las claves del join ya están del lado izquierdo: traerlas otra vez
            # duplicaría el nombre y DuckDB rechazaría la consulta.
            usadas = ", ".join(_ident(d) for _, d in paso.en)
            derecha = f"der.* EXCLUDE ({usadas})"

        return (
            f"SELECT izq.*, {derecha} FROM {entrada} AS izq "
            f"{tipo} {resolver[paso.con]} AS der ON {condicion}",
            [], f"unir con {paso.con} ({paso.como})")

    if isinstance(paso, PasoApilar):
        for nombre in paso.con:
            if nombre not in resolver:
                raise ErrorTransformacion(
                    f"apilar: el origen '{nombre}' no está entre los orígenes.")
        operador = "UNION" if paso.quitar_repetidas else "UNION ALL"
        # BY NAME: apilar por posición es la forma clásica de mezclar la columna
        # de importe con la de fecha cuando dos tablas no traen el mismo orden.
        piezas = [f"SELECT * FROM {entrada}"] + [
            f"SELECT * FROM {resolver[n]}" for n in paso.con]
        return (f" {operador} BY NAME ".join(piezas), [],
                f"apilar: {len(paso.con) + 1} orígenes")

    if isinstance(paso, PasoOrdenar):
        direccion = "DESC" if paso.descendente else "ASC"
        cols = ", ".join(f"{_ident(c)} {direccion}" for c in paso.por)
        return (f"SELECT * FROM {entrada} ORDER BY {cols}", [],
                f"ordenar por {', '.join(paso.por)}")

    if isinstance(paso, PasoLimitar):
        return (f"SELECT * FROM {entrada} LIMIT {int(paso.n)}", [],
                f"limitar a {paso.n}")

    if isinstance(paso, PasoDistintos):
        return (f"SELECT DISTINCT * FROM {entrada}", [], "quitar filas repetidas")

    raise ErrorTransformacion(f"Paso no soportado: {getattr(paso, 'tipo', '?')}")
