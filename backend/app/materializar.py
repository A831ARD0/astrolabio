"""
Ejecución de transformaciones.

La decisión que ordena todo este archivo: **la base analítica nunca se abre para
escribir.** Se adjunta en modo solo-lectura y el resultado se escribe como Parquet
en el directorio de datasets. Tres consecuencias, y las tres se querían:

- El camino de consultas mantiene su garantía: nada de lo que pase por aquí puede
  modificar una tabla que un tablero está leyendo.
- El resultado es un archivo, así que se puede respaldar, copiar a otra máquina y
  leer con cualquier herramienta. No queda encerrado.
- Ejecutar una transformación mientras alguien consulta no bloquea la base.

Lo que produce se registra como una **vista temporal** en la conexión de consultas,
así que el modelo semántico puede apuntar a ella como si fuera una tabla.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from app.config import config
from semantic.transformacion import (
    Compilada, ErrorTransformacion, Transformacion, compilar,
)

# Filas que se traen en una vista previa. Suficiente para ver la forma del
# resultado y lo bastante poco para que responda mientras se edita.
FILAS_PREVIA = 200


def raiz_datasets() -> Path:
    return Path(config().ruta_duckdb).parent / "datasets"


def ruta_salida(nombre: str) -> Path:
    return raiz_datasets() / nombre


@dataclass
class ResultadoPrevia:
    columnas: list[str]
    filas: list[dict[str, Any]]
    sql: str
    ms: float
    # [(paso, filas)] — el conteo por etapa es lo que convierte "no cuadra" en
    # "se pierde en el paso 3".
    conteos: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class ResultadoEjecucion:
    filas: int
    archivos: int
    bytes_escritos: int
    ms: float
    columnas: list[str]
    sql: str


def _resolver(t: Transformacion) -> dict[str, str]:
    """
    Traduce cada alias de origen a lo que va en el FROM.

    Un dataset es un directorio de Parquet particionado; una tabla vive en la base
    adjunta. El compilador no sabe de rutas: se enteran aquí.
    """
    salida: dict[str, str] = {}
    for o in t.origenes:
        if o.tipo == "dataset":
            ruta = ruta_datos_dataset(o.referencia)
            if ruta is None:
                raise ErrorTransformacion(
                    f"El dataset '{o.referencia}' no tiene datos cargados todavía. "
                    f"Ejecuta su carga antes de usarlo en una transformación.")
            salida[o.nombre] = f"read_parquet('{ruta}', hive_partitioning=true)"
        else:
            if not _nombre_simple(o.referencia):
                raise ErrorTransformacion(
                    f"Nombre de tabla no válido: {o.referencia!r}")
            salida[o.nombre] = f'origen."{o.referencia}"'
    return salida


def _nombre_simple(nombre: str) -> bool:
    return bool(nombre) and all(c.isalnum() or c in "_$" for c in nombre)


def ruta_datos_dataset(nombre: str) -> str | None:
    """Glob de los Parquet de un dataset, o None si no hay ninguno."""
    if not _nombre_simple(nombre):
        raise ErrorTransformacion(f"Nombre de dataset no válido: {nombre!r}")
    carpeta = raiz_datasets() / nombre
    if not carpeta.is_dir() or not any(carpeta.rglob("*.parquet")):
        return None
    return f"{carpeta}/**/*.parquet"


def _conexion_trabajo() -> duckdb.DuckDBPyConnection:
    """
    Conexión de trabajo: en memoria, con la base analítica adjunta en
    **solo lectura**. Escribir solo se puede hacia archivos Parquet.
    """
    con = duckdb.connect()
    ruta = config().ruta_duckdb
    if Path(ruta).exists():
        con.execute(f"ATTACH '{ruta}' AS origen (READ_ONLY)")
    return con


def previsualizar(t: Transformacion, con_conteos: bool = True) -> ResultadoPrevia:
    """Ejecuta la transformación acotada, sin escribir nada."""
    compilada = compilar(t, _resolver(t))
    con = _conexion_trabajo()
    t0 = time.perf_counter()
    try:
        cur = con.execute(
            f"SELECT * FROM ({compilada.sql}) LIMIT {FILAS_PREVIA}",
            compilada.parametros,
        )
        columnas = [d[0] for d in cur.description]
        filas = [dict(zip(columnas, f)) for f in cur.fetchall()]

        conteos: list[tuple[str, int]] = []
        if con_conteos and not t.es_sql:
            # Un COUNT por etapa. Se hace con la misma consulta compilada: contar
            # por otro camino podría contar otra cosa.
            for cte, descripcion in compilada.etapas:
                n = con.execute(
                    f"{_hasta(compilada.sql, cte)} SELECT COUNT(*) FROM {cte}",
                    compilada.parametros,
                ).fetchone()
                conteos.append((descripcion, int(n[0]) if n else 0))

        return ResultadoPrevia(
            columnas=columnas, filas=filas, sql=compilada.sql,
            ms=round((time.perf_counter() - t0) * 1000, 1), conteos=conteos,
        )
    finally:
        con.close()


def _hasta(sql: str, cte: str) -> str:
    """
    El bloque WITH completo, para poder consultar un CTE intermedio.

    Se reutiliza el WITH entero en vez de recortarlo: DuckDB solo materializa los
    CTE que necesita, así que sobra con quedarse con el prefijo hasta el SELECT
    final.
    """
    corte = sql.rfind("\nSELECT * FROM ")
    return sql[:corte] if corte > 0 else sql


def ejecutar(t: Transformacion, comprimir: str = "zstd") -> ResultadoEjecucion:
    """
    Materializa el resultado a Parquet.

    Escribe en un directorio temporal y **luego** reemplaza el definitivo. Si el
    proceso muere a media escritura, lo que había sigue completo: media
    transformación es peor que ninguna, porque parece un resultado.
    """
    compilada = compilar(t, _resolver(t))
    destino = ruta_salida(t.nombre)
    temporal = destino.with_name(destino.name + ".nuevo")

    con = _conexion_trabajo()
    t0 = time.perf_counter()
    try:
        if temporal.exists():
            shutil.rmtree(temporal)
        temporal.mkdir(parents=True, exist_ok=True)

        archivo = temporal / f"{t.nombre}.parquet"
        con.execute(
            f"COPY ({compilada.sql}) TO '{archivo}' "
            f"(FORMAT parquet, COMPRESSION {_compresion(comprimir)})",
            compilada.parametros,
        )
        filas = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{archivo}')").fetchone()
        columnas = [
            d[0] for d in con.execute(
                f"SELECT * FROM read_parquet('{archivo}') LIMIT 0").description
        ]

        if destino.exists():
            shutil.rmtree(destino)
        temporal.rename(destino)

        archivos = list(destino.rglob("*.parquet"))
        return ResultadoEjecucion(
            filas=int(filas[0]) if filas else 0,
            archivos=len(archivos),
            bytes_escritos=sum(a.stat().st_size for a in archivos),
            ms=round((time.perf_counter() - t0) * 1000, 1),
            columnas=columnas,
            sql=compilada.sql,
        )
    finally:
        con.close()
        if temporal.exists():
            shutil.rmtree(temporal, ignore_errors=True)


def _compresion(valor: str) -> str:
    if valor not in ("zstd", "snappy", "gzip", "uncompressed"):
        raise ErrorTransformacion(f"Compresión no soportada: {valor}")
    return valor


def columnas_de(origen_tipo: str, referencia: str) -> list[dict[str, str]]:
    """
    Columnas y tipos de un origen, para que la interfaz ofrezca los nombres en vez
    de pedir que se teclen.
    """
    con = _conexion_trabajo()
    try:
        if origen_tipo == "dataset":
            ruta = ruta_datos_dataset(referencia)
            if ruta is None:
                return []
            desde = f"read_parquet('{ruta}', hive_partitioning=true)"
        else:
            if not _nombre_simple(referencia):
                raise ErrorTransformacion(f"Nombre no válido: {referencia!r}")
            desde = f'origen."{referencia}"'
        cur = con.execute(f"SELECT * FROM {desde} LIMIT 0")
        return [{"nombre": d[0], "tipo": str(d[1])} for d in cur.description]
    finally:
        con.close()
