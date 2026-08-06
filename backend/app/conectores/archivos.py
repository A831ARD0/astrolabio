"""
Conector de archivos: CSV, Excel, Parquet.

Incluye un caso que aparece de verdad: archivos con extension .xls
que en realidad son HTML exportado (los de bonificaciones canceladas). Se
detectan por contenido, no por extension, porque la extension miente.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import duckdb

from app.conectores.base import (
    ColumnaOrigen, Conector, ErrorConector, PeticionIngesta, ResultadoIngesta,
    ResultadoPrueba, TablaOrigen, cita_origen, limpiar_destino,
)

EXTENSIONES = {".csv", ".tsv", ".txt", ".parquet", ".xlsx", ".xls"}


def detectar_formato(ruta: Path) -> str:
    """
    Formato real por contenido. Un .xls que empieza con '<' o con '<!DOCTYPE' es
    HTML disfrazado; leerlo como Excel falla con un error incomprensible.
    """
    suf = ruta.suffix.lower()
    if suf == ".parquet":
        return "parquet"
    if suf in (".csv", ".tsv", ".txt"):
        return "csv"

    with open(ruta, "rb") as f:
        cabeza = f.read(2048).lstrip()

    if cabeza[:2] == b"PK":                      # zip -> xlsx moderno
        return "xlsx"
    if cabeza[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":   # OLE2 -> xls real
        return "xls"
    if cabeza[:1] == b"<" or cabeza[:9].lower() == b"<!doctype":
        return "html"                            # .xls que es HTML
    return "xlsx"


class ConectorArchivos(Conector):
    """
    `config` espera {"ruta_base": "/ruta/a/carpeta"}. Todo acceso queda
    confinado a ese directorio: no se puede leer fuera de el.
    """

    tipo = "archivo"

    @property
    def base(self) -> Path:
        return Path(self.config["ruta_base"]).resolve()

    def _resolver(self, relativa: str) -> Path:
        """Impide escapar de ruta_base con '..' o rutas absolutas."""
        destino = (self.base / relativa).resolve()
        if not destino.is_relative_to(self.base):
            raise ErrorConector(
                f"La ruta '{relativa}' queda fuera del directorio permitido."
            )
        if not destino.exists():
            raise ErrorConector(f"No existe el archivo '{relativa}'")
        return destino

    # -- identidad ---------------------------------------------------------- #

    def probar(self) -> ResultadoPrueba:
        try:
            if not self.base.is_dir():
                return ResultadoPrueba(
                    ok=False, mensaje=f"'{self.base}' no es un directorio")
            n = sum(1 for a in self.base.rglob("*")
                    if a.is_file() and a.suffix.lower() in EXTENSIONES)
            return ResultadoPrueba(
                ok=True,
                mensaje="Directorio accesible — "
                        + (f"{n} archivo legible" if n == 1
                           else f"{n} archivos legibles"),
                detalle={"archivos": n})
        except Exception as e:
            return ResultadoPrueba(ok=False, mensaje=str(e))

    # -- introspeccion ------------------------------------------------------ #

    def listar_esquemas(self) -> list[str]:
        """Los subdirectorios hacen de esquema."""
        return sorted({
            str(a.parent.relative_to(self.base))
            for a in self.base.rglob("*")
            if a.is_file() and a.suffix.lower() in EXTENSIONES
        })

    def listar_tablas(self, esquema: str | None = None) -> list[TablaOrigen]:
        raiz = self.base if esquema in (None, ".") else self.base / esquema
        if not raiz.is_dir():
            raise ErrorConector(f"No existe el directorio '{esquema}'")
        salida = []
        for a in sorted(raiz.iterdir()):
            if a.is_file() and a.suffix.lower() in EXTENSIONES:
                salida.append(TablaOrigen(
                    esquema=esquema, nombre=a.name,
                    filas_estimadas=None,
                ))
        return salida

    def _relacion(self, con: duckdb.DuckDBPyConnection, ruta: Path):
        """Expone el archivo como la vista 'datos', segun su formato real."""
        fmt = detectar_formato(ruta)
        p = str(ruta).replace("'", "''")

        if fmt == "parquet":
            con.execute(f"CREATE OR REPLACE TEMP VIEW datos AS SELECT * FROM read_parquet('{p}')")
        elif fmt == "csv":
            con.execute(f"CREATE OR REPLACE TEMP VIEW datos AS "
                        f"SELECT * FROM read_csv_auto('{p}', sample_size=-1)")
        elif fmt in ("xlsx", "xls"):
            con.execute("INSTALL excel")
            con.execute("LOAD excel")
            con.execute(f"CREATE OR REPLACE TEMP VIEW datos AS "
                        f"SELECT * FROM read_xlsx('{p}', all_varchar=true)")
        elif fmt == "html":
            # DuckDB no lee HTML: pandas si, y esos archivos son chicos.
            import pandas as pd
            tablas = pd.read_html(ruta)
            if not tablas:
                raise ErrorConector(f"No se encontro ninguna tabla en '{ruta.name}'")
            df = max(tablas, key=len).astype(str)
            df.columns = [str(c) for c in df.columns]
            con.register("datos_html", df)
            con.execute("CREATE OR REPLACE TEMP VIEW datos AS SELECT * FROM datos_html")
        else:
            raise ErrorConector(f"Formato no soportado: {fmt}")
        return fmt

    def describir_tabla(self, tabla: str, esquema: str | None = None) -> TablaOrigen:
        rel = tabla if esquema in (None, ".") else f"{esquema}/{tabla}"
        ruta = self._resolver(rel)
        con = duckdb.connect()
        try:
            fmt = self._relacion(con, ruta)
            info = con.execute("SELECT name, type FROM pragma_table_info('datos')").fetchall()
            filas = con.execute("SELECT COUNT(*) FROM datos").fetchone()[0]
            return TablaOrigen(
                esquema=esquema, nombre=tabla, filas_estimadas=filas,
                columnas=[ColumnaOrigen(nombre=n, tipo_origen=f"{t} ({fmt})",
                                        nulable=True) for n, t in info],
            )
        finally:
            con.close()

    def muestra(self, tabla: str, esquema: str | None = None,
                limite: int = 50,
                columnas: list[str] | None = None) -> tuple[list[str], list[tuple]]:
        rel = tabla if esquema in (None, ".") else f"{esquema}/{tabla}"
        ruta = self._resolver(rel)
        cols = ", ".join(cita_origen(c) for c in columnas) if columnas else "*"
        con = duckdb.connect()
        try:
            self._relacion(con, ruta)
            cur = con.execute(f"SELECT {cols} FROM datos LIMIT {int(limite)}")
            return [d[0] for d in cur.description], cur.fetchall()
        finally:
            con.close()

    # -- ingesta ------------------------------------------------------------ #

    def ingestar(self, p: PeticionIngesta, ruta_destino: str) -> ResultadoIngesta:
        if p.rango_desde or p.rango_hasta:
            raise ErrorConector(
                "La recarga por rango no aplica a un archivo: se vuelve a leer "
                "completo. Usa la carga completa."
            )
        rel = p.tabla if p.esquema in (None, ".") else f"{p.esquema}/{p.tabla}"
        ruta = self._resolver(rel)
        destino = Path(ruta_destino)
        destino.mkdir(parents=True, exist_ok=True)
        if p.reemplazar_todo:
            # Sin esto, recargar el mismo archivo deja los Parquet anteriores y
            # el dataset acaba con las filas duplicadas.
            limpiar_destino(destino)

        con = duckdb.connect()
        t0 = time.perf_counter()
        try:
            self._relacion(con, ruta)
            cols = ", ".join(f'"{c}"' for c in p.columnas) if p.columnas else "*"
            sql = f"SELECT {cols} FROM datos"
            params: list = []
            if p.columna_incremental and p.desde:
                # Un archivo se suele reemplazar completo, pero cuando se le
                # declara una columna incremental hay que respetarla: la interfaz
                # promete "trae solo lo posterior", y traerlo todo callando la
                # diferencia es peor que no ofrecerlo.
                sql += f' WHERE "{p.columna_incremental}" > ?'
                params.append(p.desde)
            if p.limite:
                sql += f" LIMIT {int(p.limite)}"
            con.execute(f"CREATE OR REPLACE TEMP TABLE lote AS {sql}", params)
            filas = con.execute("SELECT COUNT(*) FROM lote").fetchone()[0]

            # Con precision de segundos, dos cargas seguidas escriben el mismo
            # nombre y la segunda pisa a la primera.
            marca = datetime.now().strftime("%Y%m%d%H%M%S%f")
            archivo = destino / f"{p.destino}_{marca}.parquet"
            con.execute(f"COPY lote TO '{archivo}' "
                        f"(FORMAT parquet, COMPRESSION zstd)")

            # Sin esta marca, un dataset de archivo con columna incremental nunca
            # llegaba a ser incremental: la siguiente carga no tenia desde donde
            # seguir y volvia a traer todo, sin decirlo.
            marca_max = None
            if p.columna_incremental:
                v = con.execute(
                    f'SELECT MAX("{p.columna_incremental}") FROM lote'
                ).fetchone()[0]
                marca_max = str(v) if v is not None else None

            return ResultadoIngesta(
                filas=filas, archivos=[archivo.name],
                bytes_escritos=archivo.stat().st_size,
                ms=round((time.perf_counter() - t0) * 1000, 1),
                marca_maxima=marca_max,
            )
        finally:
            con.close()
