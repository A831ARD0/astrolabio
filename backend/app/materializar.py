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

Lo que produce se puede usar como si fuera una tabla: `analitico.registrar_vistas`
le pone una **vista temporal** encima en la conexión de consultas, y así el modelo
semántico lo alcanza por su nombre.
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
    Compilada, ErrorTransformacion, PasoRenombrar, Transformacion, compilar,
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

    Aquí también entran **las etiquetas de la conexión**: constantes como
    `id_sucursal = 3` que se agregan como columna al leer el dataset. Se agregan
    al LEER y no se escriben en el Parquet a propósito — cambiar el número de una
    sucursal no puede obligar a volver a extraer cuarenta tablas.
    """
    etiquetas, por_tabla = _catalogo_de_datasets()
    salida: dict[str, str] = {}
    con = _conexion_trabajo()
    try:
        for o in t.origenes:
            if o.tipo == "dataset":
                salida[o.nombre] = _lee_dataset(
                    con, o.referencia, etiquetas.get(o.referencia, {}))
            elif o.tipo == "tabla_en_conexiones":
                salida[o.nombre] = _lee_de_todas(
                    con, o.referencia, etiquetas, por_tabla)
            else:
                if not _nombre_simple(o.referencia):
                    raise ErrorTransformacion(
                        f"Nombre de tabla no válido: {o.referencia!r}")
                salida[o.nombre] = f'{_alias_motor()}."{o.referencia}"'
    finally:
        con.close()
    return salida


def _catalogo_de_datasets() -> tuple[dict[str, dict], dict[str, list[str]]]:
    """
    Lo que hace falta saber de los datasets para resolver un origen:

      - que etiquetas hereda cada uno de su conexion,
      - que datasets traen la misma tabla del origen, para poder apilarlos.

    La tabla se indexa en minusculas: dos sucursales del mismo sistema pueden
    tener la tabla escrita distinto y siguen siendo la misma tabla.
    """
    from sqlalchemy import select as _select

    from app.db import CrearSesion
    from app.modelos_db import Conexion, Dataset

    with CrearSesion() as sesion:
        filas = sesion.execute(
            _select(Dataset.nombre, Dataset.tabla_origen, Conexion.etiquetas)
            .join(Conexion, Dataset.conexion_id == Conexion.id)
        ).all()

    etiquetas = {nombre: (etq or {}) for nombre, _, etq in filas}
    por_tabla: dict[str, list[str]] = {}
    for nombre, tabla, _ in filas:
        por_tabla.setdefault((tabla or "").lower(), []).append(nombre)
    return etiquetas, por_tabla


def _literal(v) -> str:
    """Un valor de etiqueta como literal de SQL. Solo escalares."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _columnas_de_parquet(con, desde: str) -> set[str]:
    """Los nombres de columna que ya trae el archivo. Lee solo la cabecera."""
    return {d[0] for d in con.execute(f"SELECT * FROM {desde} LIMIT 0").description}


def _lee_dataset(con, nombre: str, etiquetas: dict) -> str:
    ruta = ruta_datos_dataset(nombre)
    if ruta is None:
        raise ErrorTransformacion(
            f"El dataset '{nombre}' no tiene datos cargados todavía. "
            f"Ejecuta su carga antes de usarlo en una transformación.")
    base = f"read_parquet('{ruta}', hive_partitioning=true)"
    if not etiquetas:
        return base

    # Una etiqueta que se llama igual que una columna del origen dejaria dos
    # columnas con el mismo nombre y cualquier referencia a ella seria ambigua.
    # Se para aqui, con el nombre de las dos, en vez de dar un error de SQL.
    choques = sorted(set(etiquetas) & _columnas_de_parquet(con, base))
    if choques:
        raise ErrorTransformacion(
            f"La etiqueta {', '.join(repr(c) for c in choques)} de la conexión de "
            f"'{nombre}' se llama igual que una columna de la tabla. Cámbiale el "
            f"nombre a la etiqueta.")

    extra = ", ".join(f"{_literal(v)} AS {_ident(k)}"
                      for k, v in sorted(etiquetas.items()))
    return f"(SELECT *, {extra} FROM {base})"


def _lee_de_todas(con, tabla: str, etiquetas: dict[str, dict],
                  por_tabla: dict[str, list[str]]) -> str:
    """
    La misma tabla traida de TODAS las conexiones, apilada.

    `UNION ALL BY NAME` y no `UNION ALL` a secas: una sucursal con una columna de
    mas —o de menos— no puede tumbar la union de las otras treinta y nueve. Lo
    que falte llega en nulo.

    Si alguna no tiene datos todavia **se detiene y las nombra**, en vez de
    apilar las que si y devolver un total al que le faltan sucursales sin que
    nadie lo note. Es la misma regla que en los flujos: un numero que parece
    fresco y no lo es hace mas dano que un fallo.
    """
    nombres = sorted(por_tabla.get((tabla or "").lower(), []))
    if not nombres:
        raise ErrorTransformacion(
            f"Ninguna conexión trae la tabla '{tabla}'. Créala como dataset en "
            f"las conexiones que la tengan.")

    sin_datos = [n for n in nombres if ruta_datos_dataset(n) is None]
    if sin_datos:
        raise ErrorTransformacion(
            f"{len(sin_datos)} de {len(nombres)} datasets de '{tabla}' no tienen "
            f"datos todavía: {', '.join(sin_datos[:6])}"
            f"{'…' if len(sin_datos) > 6 else ''}. Cárgalos antes, o el resultado "
            f"no tendría todas las sucursales.")

    partes = [f"SELECT * FROM {_lee_dataset(con, n, etiquetas.get(n, {}))}"
              for n in nombres]
    return "(" + " UNION ALL BY NAME ".join(partes) + ")"


def _ident(nombre: str) -> str:
    """
    Comillas para un nombre de etiqueta.

    Las claves se validan al guardarlas (letras, digitos y guion bajo), asi que
    esto es el segundo cinturon, no el primero.
    """
    return '"' + str(nombre).replace('"', '""') + '"'


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


def _alias_motor() -> str:
    """
    Con qué nombre se llama a la base analítica dentro de la conexión de trabajo.

    Depende de cómo se haya podido abrir (ver `_conexion_trabajo`), y se calcula
    solo con la configuración porque el SQL se compila sin una conexión a mano.
    """
    if config().duckdb_solo_lectura:
        return "origen"
    # Sin ATTACH no hay alias que elegir: es el nombre que DuckDB le da al archivo.
    return Path(config().ruta_duckdb).stem


def _conexion_trabajo() -> duckdb.DuckDBPyConnection:
    """
    Conexión de trabajo. Escribir solo se puede hacia archivos Parquet: de la base
    analítica aquí únicamente se lee.

    Dos caminos, y no por gusto. Lo normal es una conexión en memoria con el
    archivo adjunto en solo lectura. Pero DuckDB no admite dos manejadores del
    mismo archivo en un proceso si alguno es de escritura, y
    `ASTROLABIO_DUCKDB_SOLO_LECTURA=false` provoca justo eso: `analitico.conexion()`
    lo abre para escribir y el ATTACH de aquí revienta con

        Binder Error: Unique file handle conflict: Cannot attach "origen"

    Eso dejaba el ETL entero inservible —previsualizar, ejecutar, y hasta ofrecer
    los nombres de las columnas— sin ninguna pista de que la causa fuera una
    variable de entorno. Con esa bandera puesta se abre el archivo directamente,
    reaprovechando el manejador que el proceso ya tiene.
    """
    ruta = config().ruta_duckdb
    if not config().duckdb_solo_lectura:
        return duckdb.connect(ruta, read_only=False)

    con = duckdb.connect()
    if Path(ruta).exists():
        con.execute(f"ATTACH '{ruta}' AS origen (READ_ONLY)")
    return con


def _renombres_que_no_se_hacen(t: Transformacion, compilada: Compilada, con) -> None:
    """
    Un renombre cuyo destino ya existe NO se hace, y nadie lo dice.

    `SELECT * EXCLUDE (Id_DB), Id_DB AS Id_Sucursal` sobre una tabla que ya traia
    `Id_Sucursal` no falla: DuckDB desambigua y la columna nueva acaba llamandose
    `Id_Sucursal_1`. El renombre no surtio efecto, la columna que el usuario cree haber
    creado apunta a otro dato, y todo sigue funcionando — hasta que un cambio ajeno
    quita la original, el renombre por fin se hace, y las cifras cambian de sitio sin
    que nada señale la causa.

    Paso de verdad: un catalogo de sucursales que sirvio un identificador durante meses
    y empezo a servir otro al cambiar el origen principal, dejando media docena de
    widgets en blanco.

    Se comprueba contra las columnas que le LLEGAN a ese paso —una consulta vacia por
    cada renombre, que no cuesta nada— y no contra el resultado final, porque un paso
    posterior puede quitar la columna legitimamente.
    """
    if t.es_sql:
        return
    for i, paso in enumerate(t.pasos, start=1):
        if not isinstance(paso, PasoRenombrar):
            continue
        antes = compilada.etapas[i - 1][0]
        llegan = [d[0] for d in con.execute(
            f"{_hasta(compilada.sql, antes)} SELECT * FROM {antes} LIMIT 0",
            compilada.parametros).description]
        # Las que se van con el EXCLUDE dejan su nombre libre: renombrar A→B y B→C a la
        # vez es legitimo, y el intercambio tambien.
        se_van = {c.lower() for c in paso.cambios}
        quedan = {c.lower() for c in llegan if c.lower() not in se_van}
        for de, a in paso.cambios.items():
            if a.lower() in quedan:
                raise ErrorTransformacion(
                    f"El renombre '{de}' → '{a}' no se puede hacer: en ese punto ya "
                    f"hay una columna llamada '{a}'. No fallaria —la nueva acabaria "
                    f"llamandose '{a}_1'— y entonces '{a}' seria la de antes y no la "
                    f"que acabas de renombrar. Elige otro nombre, o quita la que "
                    f"estorba con «Elegir columnas» antes de este paso.")


def previsualizar(t: Transformacion, con_conteos: bool = True) -> ResultadoPrevia:
    """Ejecuta la transformación acotada, sin escribir nada."""
    compilada = compilar(t, _resolver(t))
    con = _conexion_trabajo()
    t0 = time.perf_counter()
    try:
        # ANTES de la consulta de la previa, y no despues: en DuckDB una consulta nueva
        # sobre la misma conexion deja el cursor anterior sin resultado, asi que
        # comprobar en medio devolvia las columnas de la comprobacion.
        _renombres_que_no_se_hacen(t, compilada, con)
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
        # Antes de escribir: comprobarlo despues del COPY seria escribir un Parquet
        # entero para tirarlo.
        _renombres_que_no_se_hacen(t, compilada, con)
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

        # Los datos de este nombre son otros. Sin avisar, cada hilo que ya le
        # habia puesto una vista encima seguiria usando la vieja, y si esta
        # corrida cambio el tipo de una columna —un `cast(... as date)` recien
        # puesto— DuckDB rechaza la vista entera con «types don't match». La
        # importacion va aqui dentro para no cerrar el ciclo entre los dos
        # modulos: `analitico` ya lee de `materializar`.
        from app.analitico import invalidar_vistas
        invalidar_vistas(t.nombre)

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
        if origen_tipo in ("dataset", "tabla_en_conexiones"):
            etiquetas, por_tabla = _catalogo_de_datasets()
            try:
                desde = (_lee_dataset(con, referencia,
                                      etiquetas.get(referencia, {}))
                         if origen_tipo == "dataset"
                         else _lee_de_todas(con, referencia, etiquetas, por_tabla))
            except ErrorTransformacion:
                # Ofrecer los nombres de columna es una ayuda de la interfaz: si
                # todavia no hay datos no es un error, simplemente no hay nada
                # que ofrecer.
                return []
        else:
            if not _nombre_simple(referencia):
                raise ErrorTransformacion(f"Nombre no válido: {referencia!r}")
            desde = f'{_alias_motor()}."{referencia}"'
        cur = con.execute(f"SELECT * FROM {desde} LIMIT 0")
        return [{"nombre": d[0], "tipo": str(d[1])} for d in cur.description]
    finally:
        con.close()
