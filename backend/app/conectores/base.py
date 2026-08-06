"""
Abstraccion de conectores.

Cada origen (MySQL, ODBC, archivos) implementa esta interfaz. El resto de
Astrolabio no sabe de que tipo de origen viene un dato: pide introspeccion o pide
ingesta, y el conector se encarga.

El objetivo de diseño es que agregar un origen nuevo sea escribir una clase, no
tocar la API ni la ingesta.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


class ErrorConector(Exception):
    """Fallo al conectar, introspeccionar o leer de un origen."""


# Identificadores validos. Todo nombre de tabla o columna que venga de fuera pasa
# por aqui antes de entrar en un SQL: no se pueden ligar como parametros, asi que
# se validan en vez de escaparse.
#
# Esto vale para los nombres que ponemos NOSOTROS —los del destino, que salen del
# catalogo de Astrolabio y siempre son limpios—. Para los del ORIGEN no vale: hay
# bases reales con tablas llamadas 'NF Header' o columnas con acentos, y rechazar
# el nombre significa no poder traer la tabla nunca. Esas van por `cita_origen`.
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,63}$")

# Lo unico que no se puede escapar dentro de un identificador entrecomillado.
# Un NUL corta la cadena en el driver y un salto de linea rompe el SQL.
_IMPOSIBLE = re.compile(r"[\x00-\x1f\x7f]")


def valida_ident(nombre: str) -> str:
    if not _IDENT.match(nombre):
        raise ErrorConector(f"Nombre de identificador no valido: {nombre!r}")
    return nombre


def cita_origen(nombre: str, cita: str = '"') -> str:
    """
    Entrecomilla un identificador que viene del ORIGEN, escapandolo en vez de
    rechazarlo.

    La regla del SQL entrecomillado es que la comilla se dobla dentro: un nombre
    con comilla no puede cerrar el identificador y colar SQL detras. Con eso, un
    espacio, un acento o un guion dejan de ser un problema y siguen sin serlo las
    inyecciones. El corchete de SQL Server abre y cierra distinto: ahi lo que se
    dobla es el que cierra.
    """
    if not nombre or _IMPOSIBLE.search(nombre):
        raise ErrorConector(f"Nombre de identificador no valido: {nombre!r}")
    if cita == "[":
        return "[" + nombre.replace("]", "]]") + "]"
    return cita + nombre.replace(cita, cita * 2) + cita


def comillas(nombre: str) -> str:
    """
    Comillas de DuckDB. Es el dialecto del DESTINO, no del origen: aunque los
    datos vengan de MySQL, el backtick es error de sintaxis aqui.
    """
    return f'"{valida_ident(nombre)}"'


# --------------------------------------------------------------------------- #
# Escritura en el destino
#
# Quien borra que es la parte delicada de la ingesta: un borrado de mas pierde
# historico y uno de menos duplica filas. Vive aqui, en un solo sitio, para que
# todos los conectores se comporten igual.
# --------------------------------------------------------------------------- #

def limpiar_destino(destino: Path) -> None:
    """Vacia el directorio del dataset. Solo para carga completa."""
    for hijo in destino.iterdir():
        shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()


def particiones_del_rango(desde: str, hasta: str) -> list[str]:
    """
    Meses que cubre un rango, como carpetas 'anio=2026/mes=3'.

    Se calcula del RANGO PEDIDO, no de los datos traidos: recargar marzo debe
    dejar marzo igual que el origen, incluso si en el origen ya no hay filas de
    marzo porque se borraron. Si se calculara de los datos, esas bajas nunca
    desaparecerian del Parquet.
    """
    try:
        d = date.fromisoformat(desde[:10])
        h = date.fromisoformat(hasta[:10])
    except ValueError as e:
        raise ErrorConector(
            f"Rango de recarga invalido ({desde!r} a {hasta!r}): "
            f"se esperan fechas AAAA-MM-DD"
        ) from e
    if h < d:
        raise ErrorConector(f"El rango termina antes de empezar: {desde} a {hasta}")

    salida, anio, mes = [], d.year, d.month
    while (anio, mes) <= (h.year, h.month):
        salida.append(f"anio={anio}/mes={mes}")
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    return salida


def borrar_particiones(destino: Path, particiones: list[str]) -> None:
    """
    Borra solo las particiones indicadas, como 'anio=2026/mes=7'.

    Confina el borrado dentro de `destino`: una particion viene de los datos, y
    un dato no debe poder senalar a un directorio de fuera.
    """
    for p in particiones:
        ruta = (destino / p).resolve()
        if not ruta.is_relative_to(destino.resolve()):
            raise ErrorConector(f"Particion fuera del destino: {p!r}")
        if ruta.is_dir():
            shutil.rmtree(ruta)


def marca_archivo() -> str:
    """
    Sufijo unico para el Parquet de un dataset sin particionar.

    Aqui habia `time.strftime("%Y%m%d%H%M%S%f")`, y estaba mal de dos maneras a
    la vez:

    1. **`%f` no existe en `time.strftime`** —es de `datetime`—. En Linux y macOS
       la biblioteca de C la deja pasar y el nombre acababa con una `f` literal;
       el CRT de Windows la valida y lanza `ValueError: Invalid format string`.
       Efecto: en Windows **ninguna carga podia terminar**, con un error que no
       menciona ni fechas ni nombres de archivo.

    2. Por eso mismo, la marca tenia resolucion de **un segundo**. Dos cargas del
       mismo dataset dentro del mismo segundo generaban el mismo nombre y la
       segunda pisaba a la primera, en silencio y en todas las plataformas.

    El uuid quita el segundo problema de raiz: no hay resolucion que apurar. La
    fecha delante se queda porque ordena los archivos por nombre, que es lo que
    uno quiere al mirar la carpeta.
    """
    return f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def escribir_lote(con, destino: Path, p: PeticionIngesta, t0: float,
                  tabla: str = "lote") -> ResultadoIngesta:
    """
    Escribe a Parquet una tabla temporal de DuckDB ya cargada, y devuelve el
    resultado. `con` es una conexion DuckDB donde existe `tabla`.

    Vive aqui porque es la parte que no puede divergir entre conectores: que se
    borra segun el modo, como se parte por anio/mes, y de donde sale la marca
    maxima de la siguiente carga incremental. Cada conector trae los datos como
    mejor pueda —MySQL con su extension nativa, ODBC fila por fila— pero todos
    escriben por aqui. Si cada uno tuviera su copia, un dia uno borraria de mas.
    """
    filas = con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]

    # Borrar ANTES de escribir, y solo lo que el modo permite. Esto va antes del
    # retorno por lote vacio a proposito: una recarga de marzo que no trae filas
    # significa que en el origen ya no hay marzo, y el Parquet debe reflejarlo.
    particiones: list[str] = []
    if p.rango_desde or p.rango_hasta:
        particiones = particiones_del_rango(p.rango_desde, p.rango_hasta)
        borrar_particiones(destino, particiones)
    elif p.reemplazar_todo:
        limpiar_destino(destino)

    if filas == 0:
        return ResultadoIngesta(
            filas=0, archivos=[], bytes_escritos=0,
            ms=round((time.perf_counter() - t0) * 1000, 1),
            particiones_escritas=particiones,
        )

    sin_fecha = 0
    if p.particionar_por:
        # TRY_CAST y no CAST a proposito: en muchos origenes las fechas suelen
        # venir como texto con cadenas vacias mezcladas. Un CAST duro tumba la
        # carga completa; TRY_CAST manda lo ilegible a su propia particion y
        # reporta cuantas filas fueron, en vez de fallar o de callarlo.
        col = cita_origen(p.particionar_por)
        sin_fecha = con.execute(
            f"SELECT COUNT(*) FROM {tabla} WHERE TRY_CAST({col} AS DATE) IS NULL"
        ).fetchone()[0]
        # FILENAME_PATTERN con uuid: en una carga incremental el lote nuevo cae
        # dentro de una particion que ya tiene archivos, y con el nombre por
        # defecto (data_0.parquet) se sobreescribiria lo anterior. Quien decide
        # que se borra es el modo, no el nombre del archivo.
        con.execute(f"""
            COPY (SELECT *,
                         YEAR(TRY_CAST({col} AS DATE))  AS anio,
                         MONTH(TRY_CAST({col} AS DATE)) AS mes
                  FROM {tabla})
            TO '{destino}' (FORMAT parquet, COMPRESSION zstd,
                            PARTITION_BY (anio, mes), OVERWRITE_OR_IGNORE,
                            FILENAME_PATTERN 'lote_{{uuid}}')
        """)
        if not particiones:
            particiones = [
                f"anio={a}/mes={m}" if a is not None else "anio=/mes="
                for a, m in con.execute(f"""
                    SELECT DISTINCT YEAR(TRY_CAST({col} AS DATE)),
                                    MONTH(TRY_CAST({col} AS DATE))
                    FROM {tabla} ORDER BY 1, 2
                """).fetchall()
            ]
    else:
        marca = marca_archivo()
        con.execute(
            f"COPY {tabla} TO '{destino / f'{p.destino}_{marca}.parquet'}' "
            f"(FORMAT parquet, COMPRESSION zstd)"
        )

    marca_max = None
    if p.columna_incremental:
        v = con.execute(
            f"SELECT MAX({cita_origen(p.columna_incremental)}) FROM {tabla}"
        ).fetchone()[0]
        marca_max = str(v) if v is not None else None

    archivos = [str(a.relative_to(destino)) for a in sorted(destino.rglob("*.parquet"))]
    bytes_tot = sum(a.stat().st_size for a in destino.rglob("*.parquet"))

    return ResultadoIngesta(
        filas=filas, archivos=archivos, bytes_escritos=bytes_tot,
        ms=round((time.perf_counter() - t0) * 1000, 1),
        marca_maxima=marca_max,
        filas_sin_particion=sin_fecha,
        particiones_escritas=particiones,
    )


@dataclass
class ColumnaOrigen:
    nombre: str
    tipo_origen: str
    nulable: bool
    es_clave: bool = False


@dataclass
class TablaOrigen:
    esquema: str | None
    nombre: str
    filas_estimadas: int | None = None
    es_vista: bool = False
    columnas: list[ColumnaOrigen] = field(default_factory=list)

    @property
    def nombre_completo(self) -> str:
        return f"{self.esquema}.{self.nombre}" if self.esquema else self.nombre


@dataclass
class ResultadoPrueba:
    ok: bool
    mensaje: str
    detalle: dict = field(default_factory=dict)


@dataclass
class PeticionIngesta:
    """
    Que traer y como.

    - `columna_incremental` + `desde`: trae solo lo nuevo. Imprescindible para
      tablas grandes y para las ~40 bases por sucursal.
    - `particionar_por`: columna de fecha con la que se parte el Parquet en
      carpetas anio=YYYY/mes=MM. Acelera cualquier consulta filtrada por fecha.

    Los tres modos de escritura son excluyentes y definen que se borra en el
    destino antes de escribir. Equivocarse aqui duplica o pierde filas, asi que
    el modo es explicito y no se deduce:

    - `reemplazar_todo=True`   -> el destino se vacia. Carga completa.
    - `rango_desde`/`rango_hasta` -> solo se borran las particiones que caen en
      el rango. Recarga de un mes sin tocar los otros diez años.
    - ninguno de los dos       -> se agregan archivos nuevos. Carga incremental.
    """
    esquema: str | None
    tabla: str
    destino: str                          # nombre logico del dataset
    columnas: list[str] | None = None     # None = todas
    columna_incremental: str | None = None
    desde: str | None = None
    particionar_por: str | None = None
    limite: int | None = None
    reemplazar_todo: bool = False
    rango_desde: str | None = None        # requiere particionar_por
    rango_hasta: str | None = None


@dataclass
class ResultadoIngesta:
    filas: int
    archivos: list[str]
    bytes_escritos: int
    ms: float
    marca_maxima: str | None = None       # para la siguiente carga incremental
    # Filas cuya columna de particion no se pudo interpretar como fecha. Se
    # reporta en vez de callarse: es la señal de una columna de texto sucia.
    filas_sin_particion: int = 0
    # Particiones reescritas, como ["anio=2026/mes=7"]. En una recarga parcial
    # es la prueba de que solo se toco lo que se pidio.
    particiones_escritas: list[str] = field(default_factory=list)


class Conector(ABC):
    """Un origen de datos. Las subclases no deben guardar estado mutable."""

    tipo: str = "abstracto"

    def __init__(self, config: dict):
        self.config = config

    # -- identidad ---------------------------------------------------------- #

    @abstractmethod
    def probar(self) -> ResultadoPrueba:
        """Verifica que se puede conectar. Nunca debe lanzar: devuelve el fallo."""

    def config_publica(self) -> dict:
        """
        Config sin secretos, apta para devolver por la API. Toda subclase debe
        asegurarse de que ningun secreto se cuele aqui.
        """
        secretos = {"password", "contrasena", "clave", "secret", "token", "pwd"}
        return {k: v for k, v in self.config.items() if k.lower() not in secretos}

    # -- introspeccion ------------------------------------------------------ #

    @abstractmethod
    def listar_esquemas(self) -> list[str]:
        ...

    @abstractmethod
    def listar_tablas(self, esquema: str | None = None) -> list[TablaOrigen]:
        """Sin columnas: es el listado rapido para poblar un arbol en la UI."""

    @abstractmethod
    def describir_tabla(self, tabla: str, esquema: str | None = None) -> TablaOrigen:
        """Con columnas y conteo real de filas."""

    @abstractmethod
    def muestra(self, tabla: str, esquema: str | None = None,
                limite: int = 50,
                columnas: list[str] | None = None) -> tuple[list[str], list[tuple]]:
        """
        Primeras filas, para la vista previa.

        `columnas` no es un filtro de presentacion: se le piden al origen esas y no
        las demas. La vista previa tiene que ser una muestra de lo que se va a
        traer, no de la tabla entera; si no, se elige la columna de particion
        mirando datos de columnas que se descartaron.
        """

    # -- ingesta ------------------------------------------------------------ #

    @abstractmethod
    def ingestar(self, peticion: PeticionIngesta, ruta_destino: str) -> ResultadoIngesta:
        """Copia del origen a Parquet en `ruta_destino`."""
