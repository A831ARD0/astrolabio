"""
Copia una parte de la base de demostración a MySQL, para poder probar de verdad
el conector de MySQL y el de ODBC.

Sin esto, las pruebas que hablan con un origen se saltan solas y el conector queda
sin verificar contra un motor real. Un conector probado solo contra archivos no
está probado: los tipos, las fechas sucias y el comportamiento de `fetchmany` son
justo lo que cambia de un motor a otro.

    python demo/cargar_mysql.py                        # localhost, root sin clave
    python demo/cargar_mysql.py --host db --user u --password p

La base se llama `astrolabio_demo` y **se recrea entera** cada vez. No la apuntes a
una base con datos que te importen: el script empieza con DROP DATABASE.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pymysql

RAIZ = Path(__file__).resolve().parent.parent
DUCK = RAIZ / "datos" / "analitico.duckdb"

BASE = "astrolabio_demo"

#: (tabla destino, consulta sobre la base de demostracion, DDL de MySQL)
#:
#: `ventas` es la unica grande: 200,000 filas bastan para que una carga
#: particionada tarde lo suficiente como para que se note si algo va mal, y son
#: pocas para que preparar el entorno no sea una espera.
TABLAS = [
    (
        "cat_marca",
        "SELECT marca_id, marca_nombre FROM cat_marca",
        """CREATE TABLE cat_marca (
             marca_id INT PRIMARY KEY,
             marca_nombre VARCHAR(60) NOT NULL)""",
    ),
    (
        "cat_sucursal",
        """SELECT sucursal_id, sucursal_nombre, marca_id, region_id,
                  nombre_conexion
           FROM cat_sucursal""",
        """CREATE TABLE cat_sucursal (
             sucursal_id INT PRIMARY KEY,
             sucursal_nombre VARCHAR(120) NOT NULL,
             marca_id INT,
             region_id INT,
             nombre_conexion VARCHAR(60))""",
    ),
    (
        "ventas",
        """SELECT venta_id, sucursal_id, cliente_id, vehiculo_id,
                  fecha_emision, serie,
                  -- Fecha guardada como TEXTO y con huecos, que es como llega de
                  -- verdad desde muchos sistemas viejos. Una de cada cien va
                  -- vacia: sirve para comprobar que la carga las reporta aparte
                  -- en vez de tirarlas en silencio o reventar.
                  CASE WHEN venta_id % 100 = 0 THEN ''
                       ELSE strftime(fecha_emision, '%Y-%m-%d') END AS fecha_texto,
                  CAST(monto_base AS DECIMAL(14,2))  AS monto_base,
                  CAST(monto_costo AS DECIMAL(14,2)) AS monto_costo,
                  unidades, es_cancelacion
           FROM fact_venta ORDER BY venta_id LIMIT 200000""",
        # DECIMAL y no DOUBLE a proposito: es como viene el dinero en los
        # sistemas de verdad, y es el tipo con el que un conector se equivoca.
        """CREATE TABLE ventas (
             venta_id BIGINT PRIMARY KEY,
             sucursal_id INT,
             cliente_id INT,
             vehiculo_id INT,
             fecha_emision DATE,
             serie VARCHAR(10),
             fecha_texto VARCHAR(10),
             monto_base DECIMAL(14,2),
             monto_costo DECIMAL(14,2),
             unidades INT,
             es_cancelacion TINYINT(1))""",
    ),
    (
        "presupuesto",
        """SELECT presupuesto_id, sucursal_id, anio_mes, objetivo_unidades,
                  CAST(objetivo_monto AS DECIMAL(14,2)) AS objetivo_monto
           FROM fact_presupuesto""",
        """CREATE TABLE presupuesto (
             presupuesto_id INT PRIMARY KEY,
             sucursal_id INT,
             anio_mes INT,
             objetivo_unidades INT,
             objetivo_monto DECIMAL(14,2))""",
    ),
]

LOTE = 10_000


def cargar(host: str, puerto: int, usuario: str, contrasena: str) -> None:
    if not DUCK.exists():
        raise SystemExit(
            f"No existe {DUCK}. Genera primero la base de demostración:\n"
            f"    python demo/generar_datos.py")

    duck = duckdb.connect(str(DUCK), read_only=True)
    con = pymysql.connect(host=host, port=puerto, user=usuario,
                          password=contrasena, autocommit=True)
    cur = con.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {BASE}")
    cur.execute(f"CREATE DATABASE {BASE} CHARACTER SET utf8mb4")
    cur.execute(f"USE {BASE}")

    for tabla, consulta, ddl in TABLAS:
        cur.execute(ddl)
        filas = duck.execute(consulta).fetchall()
        if filas:
            marcas = ", ".join(["%s"] * len(filas[0]))
            for i in range(0, len(filas), LOTE):
                cur.executemany(
                    f"INSERT INTO {tabla} VALUES ({marcas})", filas[i:i + LOTE])
        print(f"  {tabla:16s} {len(filas):>9,} filas")

    con.close()
    duck.close()
    print(f"\nListo. Base '{BASE}' en {host}:{puerto}.")
    print("Para que las pruebas la usen:")
    print(f"    export ASTROLABIO_PRUEBA_BASE={BASE}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--puerto", type=int, default=3306)
    p.add_argument("--user", default="root")
    p.add_argument("--password", default="")
    a = p.parse_args()
    cargar(a.host, a.puerto, a.user, a.password)
