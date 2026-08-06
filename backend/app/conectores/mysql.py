"""
Conector MySQL / MariaDB.

Dos bibliotecas a proposito, cada una en lo que es mejor:

  - pymysql   para introspeccion: information_schema con SQL conocido y confiable.
  - DuckDB    para mover datos: la extension mysql copia a ~360,000 filas/s,
              medido contra una tabla de 500,000 filas. Un cursor de Python fila por
              fila es dos ordenes de magnitud mas lento.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import duckdb
import pymysql

from app.conectores.base import (
    ColumnaOrigen, Conector, ErrorConector, PeticionIngesta, ResultadoIngesta,
    ResultadoPrueba, TablaOrigen, cita_origen, escribir_lote,
)
#: Comillas de DuckDB para nombres que vienen del ORIGEN: tabla y columnas de
#: MySQL leidas a traves del escaneador. Son nombres ajenos, se escapan.
from app.conectores.base import cita_origen as _ident_duck


def _ident(nombre: str) -> str:
    """
    Comillas de MySQL — para el SQL que ejecuta pymysql.

    El nombre del origen no lo elegimos nosotros: puede llevar espacios o
    acentos. Se escapa doblando el acento grave, no se rechaza.
    """
    return cita_origen(nombre, "`")


class ConectorMySQL(Conector):
    tipo = "mysql"

    # -- conexiones internas ------------------------------------------------ #

    def _pymysql(self, con_base: bool = True):
        try:
            return pymysql.connect(
                host=self.config["host"],
                port=int(self.config.get("port", 3306)),
                user=self.config["user"],
                password=self.config.get("password") or "",
                database=self.config.get("database") if con_base else None,
                connect_timeout=10,
                read_timeout=300,
                charset=self.config.get("charset", "utf8mb4"),
            )
        except Exception as e:
            raise ErrorConector(f"No se pudo conectar a MySQL: {e}") from e

    def _cadena_duckdb(self) -> str:
        """
        Cadena de ATTACH para DuckDB. Ojo: `password=` vacio no se admite, hay
        que omitir el parametro por completo.
        """
        partes = [
            f"host={self.config['host']}",
            f"port={int(self.config.get('port', 3306))}",
            f"user={self.config['user']}",
            f"db={self.config['database']}",
        ]
        clave = self.config.get("password")
        if clave:
            partes.insert(3, f"password={clave}")
        return " ".join(partes)

    def _duckdb(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.execute("INSTALL mysql")
        con.execute("LOAD mysql")
        # READ_ONLY: Astrolabio nunca escribe en un origen.
        con.execute(f"ATTACH '{self._cadena_duckdb()}' AS origen "
                    f"(TYPE mysql, READ_ONLY)")
        return con

    # -- identidad ---------------------------------------------------------- #

    def probar(self) -> ResultadoPrueba:
        try:
            con = self._pymysql(con_base=False)
            cur = con.cursor()
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            base = self.config.get("database")
            tablas = None
            if base:
                cur.execute("""SELECT COUNT(*) FROM information_schema.tables
                               WHERE table_schema=%s""", (base,))
                tablas = cur.fetchone()[0]
            con.close()
            return ResultadoPrueba(
                ok=True,
                mensaje=f"Conexion correcta a MySQL {version}"
                        + (f" — {tablas} tablas en '{base}'" if tablas is not None else ""),
                detalle={"version": version, "tablas": tablas},
            )
        except Exception as e:
            return ResultadoPrueba(ok=False, mensaje=str(e))

    # -- introspeccion ------------------------------------------------------ #

    def listar_esquemas(self) -> list[str]:
        con = self._pymysql(con_base=False)
        try:
            cur = con.cursor()
            cur.execute("""SELECT schema_name FROM information_schema.schemata
                           WHERE schema_name NOT IN
                             ('information_schema','performance_schema','mysql','sys')
                           ORDER BY schema_name""")
            return [f[0] for f in cur.fetchall()]
        finally:
            con.close()

    def listar_tablas(self, esquema: str | None = None) -> list[TablaOrigen]:
        esquema = esquema or self.config.get("database")
        if not esquema:
            raise ErrorConector("Hace falta indicar el esquema o la base de datos")
        con = self._pymysql(con_base=False)
        try:
            cur = con.cursor()
            cur.execute("""SELECT table_name, table_rows, table_type
                           FROM information_schema.tables
                           WHERE table_schema=%s ORDER BY table_name""", (esquema,))
            return [
                TablaOrigen(esquema=esquema, nombre=n,
                            filas_estimadas=int(f or 0),
                            es_vista=(t == "VIEW"))
                for n, f, t in cur.fetchall()
            ]
        finally:
            con.close()

    def describir_tabla(self, tabla: str, esquema: str | None = None) -> TablaOrigen:
        esquema = esquema or self.config.get("database")
        con = self._pymysql(con_base=False)
        try:
            cur = con.cursor()
            cur.execute("""SELECT column_name, column_type, is_nullable, column_key
                           FROM information_schema.columns
                           WHERE table_schema=%s AND table_name=%s
                           ORDER BY ordinal_position""", (esquema, tabla))
            columnas = [
                ColumnaOrigen(nombre=n, tipo_origen=t,
                              nulable=(nul == "YES"), es_clave=(k == "PRI"))
                for n, t, nul, k in cur.fetchall()
            ]
            if not columnas:
                raise ErrorConector(f"La tabla '{esquema}.{tabla}' no existe")

            cur.execute("""SELECT table_type FROM information_schema.tables
                           WHERE table_schema=%s AND table_name=%s""", (esquema, tabla))
            fila = cur.fetchone()
            es_vista = bool(fila and fila[0] == "VIEW")

            # Conteo real: el estimado de information_schema se desvia mucho en
            # InnoDB, y para decidir carga incremental hace falta el numero real.
            cur.execute(f"SELECT COUNT(*) FROM {_ident(esquema)}.{_ident(tabla)}")
            filas = cur.fetchone()[0]

            return TablaOrigen(esquema=esquema, nombre=tabla, filas_estimadas=filas,
                               es_vista=es_vista, columnas=columnas)
        finally:
            con.close()

    def muestra(self, tabla: str, esquema: str | None = None,
                limite: int = 50,
                columnas: list[str] | None = None) -> tuple[list[str], list[tuple]]:
        esquema = esquema or self.config.get("database")
        cols = ", ".join(_ident(c) for c in columnas) if columnas else "*"
        con = self._pymysql(con_base=False)
        try:
            cur = con.cursor()
            cur.execute(
                f"SELECT {cols} FROM {_ident(esquema)}.{_ident(tabla)} LIMIT %s",
                (int(limite),)
            )
            return [d[0] for d in cur.description], list(cur.fetchall())
        finally:
            con.close()

    # -- ingesta ------------------------------------------------------------ #

    def ingestar(self, p: PeticionIngesta, ruta_destino: str) -> ResultadoIngesta:
        esquema = p.esquema or self.config["database"]
        if esquema != self.config["database"]:
            raise ErrorConector(
                f"La conexion apunta a '{self.config['database']}' pero se pidio "
                f"ingestar de '{esquema}'. Crea una conexion para ese esquema."
            )

        # Validar las columnas ANTES de mover datos: un error de DuckDB a media
        # copia es incomprensible, y en la base real abundan los nombres que
        # parecen existir y no existen.
        disponibles = {c.nombre for c in self.describir_tabla(p.tabla, esquema).columnas}
        for etiqueta, col in (("particionar_por", p.particionar_por),
                              ("columna_incremental", p.columna_incremental)):
            if col and col not in disponibles:
                cercanas = sorted(c for c in disponibles if col.split("_")[0] in c)[:5]
                raise ErrorConector(
                    f"La columna '{col}' ({etiqueta}) no existe en "
                    f"'{esquema}.{p.tabla}'."
                    + (f" Columnas parecidas: {', '.join(cercanas)}" if cercanas else "")
                )
        if p.columnas:
            faltan = set(p.columnas) - disponibles
            if faltan:
                raise ErrorConector(
                    f"Columnas inexistentes en '{p.tabla}': {', '.join(sorted(faltan))}"
                )
        if p.rango_desde or p.rango_hasta:
            if not p.particionar_por:
                raise ErrorConector(
                    "Recargar un rango de fechas requiere que el dataset este "
                    "particionado: sin particiones no hay nada que reemplazar "
                    "sin reescribir todo."
                )
            if not (p.rango_desde and p.rango_hasta):
                raise ErrorConector(
                    "La recarga por rango necesita inicio y fin. Un rango "
                    "abierto no dice cuantas particiones hay que reemplazar."
                )

        destino = Path(ruta_destino)
        destino.mkdir(parents=True, exist_ok=True)

        # Todo este SQL lo ejecuta DuckDB, no MySQL: comillas de DuckDB.
        cols = "*"
        if p.columnas:
            cols = ", ".join(_ident_duck(c) for c in p.columnas)

        origen = f"origen.{_ident_duck(p.tabla)}"
        sql = f"SELECT {cols} FROM {origen}"
        params: list = []
        donde: list[str] = []

        if p.columna_incremental and p.desde:
            donde.append(f"{_ident_duck(p.columna_incremental)} > ?")
            params.append(p.desde)
        if p.rango_desde or p.rango_hasta:
            # TRY_CAST igual que al particionar: la columna suele ser texto.
            fecha = f"TRY_CAST({_ident_duck(p.particionar_por)} AS DATE)"
            if p.rango_desde:
                donde.append(f"{fecha} >= TRY_CAST(? AS DATE)")
                params.append(p.rango_desde)
            if p.rango_hasta:
                donde.append(f"{fecha} <= TRY_CAST(? AS DATE)")
                params.append(p.rango_hasta)
        if donde:
            sql += " WHERE " + " AND ".join(donde)
        if p.limite:
            sql += f" LIMIT {int(p.limite)}"

        con = self._duckdb()
        t0 = time.perf_counter()
        try:
            con.execute(f"CREATE OR REPLACE TEMP TABLE lote AS {sql}", params)
            # Lo que se borra, el particionado por anio/mes y la marca maxima son
            # los mismos para todos los conectores: viven en base.escribir_lote.
            return escribir_lote(con, destino, p, t0)
        finally:
            con.close()
