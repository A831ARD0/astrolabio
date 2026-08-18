"""
Genera la base analítica de demostración: un grupo automotriz ficticio con
varias marcas, 40 sucursales, 4 regiones y 10 años de historia.

Todo lo que hay aquí es inventado y determinista (semilla fija): mismos números
en todas las máquinas, que es lo que permite que las pruebas comparen contra
cifras exactas.

**La forma importa más que los datos.** Este generador incluye a propósito las
cinco trampas que rompen un motor de BI, para poder probar contra ellas en vez de
descubrirlas en producción con una cifra mal:

  1. FAN TRAP       `fact_presupuesto` vive a grano sucursal × mes; al unirla con
                    `fact_venta` (grano línea de factura) un SUM() se infla.
  2. RUTA AMBIGUA   hay dos caminos de `fact_venta` a `cat_marca`: por
                    `cat_sucursal` (la marca de la agencia) y por `dim_vehiculo`
                    (la marca del coche). Los dos son legítimos y dan resultados
                    distintos, así que el motor tiene que preguntar en vez de
                    elegir uno.
  3. TABLA HUÉRFANA `tbl_encuesta_clima` no tiene ninguna relación.
  4. SERIE COMPART. la misma serie fiscal existe en dos sucursales distintas, así
                    que contar por serie no equivale a contar por sucursal.
  5. CANCELACIONES  notas de crédito con montos y unidades en negativo, que al
                    sumar deben neutralizar la venta original.

Uso:

    python demo/generar_datos.py              # completo (~11.5M filas, ~120 MB)
    python demo/generar_datos.py --rapido     # 20 veces más chico, para CI
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np

SEMILLA = 20260803
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config import config                                       # noqa: E402

# La MISMA ruta que abre la API, no una fija. Cuando eran dos, el generador
# escribia en `datos/analitico.duckdb` mientras el servidor leia la que le dice
# ASTROLABIO_RUTA_DUCKDB, y en Docker —donde el compose la mueve a otro
# volumen— sembrar la demo dejaba las pantallas vacias sin un solo error.
DB = Path(config().ruta_duckdb)

# Marcas inventadas de un grupo automotriz que no existe.
MARCAS = [
    (1, "Aurex"), (2, "Belmar"), (9, "Corvo"), (12, "Dalia"), (14, "Ekos"),
    (54, "Faro"), (57, "Galia"), (58, "Hexa"), (60, "Iris"), (99, "Aurex-HP"),
]

# Regiones, no estados reales.
REGIONES = [(1, "Norte"), (2, "Centro"), (3, "Sur"), (4, "Occidente")]

# (id, nombre, marca_id, region_id, nombre_conexion)
#
# La región 3 tiene EXACTAMENTE una sucursal (la 29). No es casualidad: es lo que
# hace verificable la prueba de seguridad por fila — un lector de la región 3 debe
# ver esa y ninguna más, y con dos sucursales el error de "ve una de más" pasaría
# desapercibido.
SUCURSALES = [
    (1, "Aurex Valle Alto", 1, 1, "AUREX_VALLE"),
    (2, "Aurex Puerto Luna", 1, 1, "AUREX_PUERTO"),
    (3, "Aurex Monte Azul", 1, 2, "AUREX_MONTE"),
    (4, "Aurex Villa Cielo", 1, 2, "AUREX_VILLA"),
    (5, "Aurex Costa Verde", 1, 2, "AUREX_COSTA"),
    (6, "Aurex Bahía Norte", 1, 1, "AUREX_BAHIA"),
    (7, "Aurex Ciudad Lago", 1, 2, "AUREX_LAGO"),
    (8, "Aurex Alto Robles", 1, 1, "AUREX_ROBLES"),
    (9, "Aurex Peña Larga", 1, 1, "AUREX_PENA"),
    (10, "Aurex Cabo Sur", 1, 4, "AUREX_CABO"),
    (11, "Aurex-HP Valle Alto", 99, 1, "AHP_VALLE"),
    (12, "Aurex-HP Monte Azul", 99, 2, "AHP_MONTE"),
    (13, "Aurex-HP Villa Cielo", 99, 2, "AHP_VILLA"),
    (14, "Aurex-HP Cabo Sur", 99, 4, "AHP_CABO"),
    (15, "Belmar Valle Alto", 2, 1, "BELMAR_VALLE"),
    (16, "Belmar Monte Azul", 2, 2, "BELMAR_MONTE"),
    (17, "Galia Valle Alto", 57, 1, "GALIA_VALLE"),
    (18, "Galia Villa Cielo", 57, 2, "GALIA_VILLA"),
    (19, "Corvo Valle Alto", 9, 1, "CORVO_VALLE"),
    (20, "Dalia Valle Alto", 12, 1, "DALIA_VALLE"),
    (21, "Dalia Villa Cielo", 12, 2, "DALIA_VILLA"),
    (22, "Dalia Ciudad Lago", 12, 2, "DALIA_LAGO"),
    (23, "Dalia Bahía Norte", 12, 1, "DALIA_BAHIA"),
    (24, "Dalia Alto Robles", 12, 1, "DALIA_ROBLES"),
    (25, "Ekos Valle Alto", 14, 1, "EKOS_VALLE"),
    (26, "Ekos Alto Robles", 14, 1, "EKOS_ROBLES"),
    (27, "Ekos Bahía Norte", 14, 1, "EKOS_BAHIA"),
    (28, "Ekos Costa Verde", 14, 2, "EKOS_COSTA"),
    (29, "Ekos Río Blanco", 14, 3, "EKOS_RIO"),
    (30, "Faro Valle Alto", 54, 1, "FARO_VALLE"),
    (31, "Faro Monte Azul", 54, 2, "FARO_MONTE"),
    (32, "Faro Villa Cielo", 54, 2, "FARO_VILLA"),
    (33, "Faro Bahía Norte", 54, 1, "FARO_BAHIA"),
    (34, "Faro Alto Robles", 54, 1, "FARO_ROBLES"),
    (35, "Hexa Valle Alto", 58, 1, "HEXA_VALLE"),
    (36, "Hexa Villa Cielo", 58, 2, "HEXA_VILLA"),
    (37, "Hexa Prado Norte", 58, 2, "HEXA_PRADO"),
    (38, "Hexa Monte Azul", 58, 2, "HEXA_MONTE"),
    (39, "Iris Valle Alto", 60, 1, "IRIS_VALLE"),
    (40, "Belmar Peña Larga", 2, 1, "BELMAR_PENA"),
]

# TRAMPA 4: la serie 'BX1' aparece en la sucursal 15 y en la 32. Es un caso real
# en grupos con varias agencias: la serie fiscal la asigna el fabricante y dos
# agencias distintas pueden acabar con la misma.
SERIES = [
    (1, "AV1"), (2, "AP1"), (3, "AM1"), (4, "AC1"), (5, "AO1"), (6, "AB1"),
    (7, "AL1"), (8, "AR1"), (9, "AN1"), (10, "AS1"),
    (15, "BX1"), (32, "BX1"),
    (16, "BM1"), (17, "GV1"), (18, "GC1"), (19, "CV1"),
    (20, "DV1"), (21, "DC1"), (22, "DL1"), (23, "DB1"), (24, "DR1"),
    (25, "EV1"), (26, "ER1"), (27, "EB1"), (28, "EC1"), (29, "EO1"),
    (30, "FV1"), (31, "FM1"), (33, "FB1"), (34, "FR1"),
    (35, "HV1"), (36, "HC1"), (37, "HP1"), (38, "HM1"), (39, "IV1"), (40, "BP1"),
]

MODELOS = [
    ("Nara", 1), ("Solio", 1), ("Vento Sur", 1), ("Cruce", 1), ("Duna", 1),
    ("Lito", 2), ("Bisel", 2), ("Arena", 2),
    ("C3", 9), ("Q7", 9),
    ("Fresa", 12), ("Sendero", 12), ("Ribera", 12),
    ("E5", 14), ("HX", 14), ("ZR", 14),
    ("Faro 7", 54), ("Faro 8", 54),
    ("Forma", 57), ("Lito Sport", 57),
    ("Cobalto", 58), ("Azor", 58),
    ("Iris 5", 60), ("Iris 7", 60),
]


def generar(rapido: bool = False) -> Path:
    """Crea la base desde cero. Devuelve la ruta."""
    rng = np.random.default_rng(SEMILLA)
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))

    # En modo rapido las tablas de hechos se dividen: la FORMA se conserva —las
    # cinco trampas siguen ahi— y lo unico que baja es el volumen.
    div = 20 if rapido else 1

    print("Generando catalogos...")
    con.execute("CREATE TABLE cat_marca (marca_id INTEGER, marca_nombre VARCHAR)")
    con.executemany("INSERT INTO cat_marca VALUES (?, ?)", MARCAS)

    con.execute("CREATE TABLE cat_region (region_id INTEGER, region_nombre VARCHAR)")
    con.executemany("INSERT INTO cat_region VALUES (?, ?)", REGIONES)

    con.execute("""CREATE TABLE cat_sucursal (
        sucursal_id INTEGER, sucursal_nombre VARCHAR, marca_id INTEGER,
        region_id INTEGER, nombre_conexion VARCHAR)""")
    con.executemany("INSERT INTO cat_sucursal VALUES (?, ?, ?, ?, ?)", SUCURSALES)

    con.execute("CREATE TABLE cat_serie (sucursal_id INTEGER, serie VARCHAR)")
    con.executemany("INSERT INTO cat_serie VALUES (?, ?)", SERIES)

    print("Generando calendario...")
    con.execute("""
        CREATE TABLE dim_calendario AS
        SELECT
            CAST(d AS DATE)                              AS fecha,
            YEAR(d)                                      AS anio,
            MONTH(d)                                     AS mes,
            -- En español, y a mano: `MONTHNAME` devuelve el nombre en ingles
            -- —«July»— haga lo que haga la configuracion de la maquina, asi que
            -- traducirlo con una lista es lo unico que da el mismo resultado en
            -- todas. Ojo con el orden: se ordena por `mes`, no por el nombre, o el
            -- año empieza en abril.
            ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
             'agosto', 'septiembre', 'octubre', 'noviembre',
             'diciembre'][MONTH(d)]                      AS mes_nombre,
            QUARTER(d)                                   AS trimestre,
            YEAR(d) * 100 + MONTH(d)                     AS anio_mes,
            ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado',
             'domingo'][ISODOW(d)]                       AS dia_nombre,
            CASE WHEN DAYOFWEEK(d) = 0 THEN FALSE ELSE TRUE END AS es_habil
        FROM generate_series(DATE '2016-01-01', DATE '2026-07-31', INTERVAL 1 DAY) AS t(d)
    """)

    # dim_vehiculo tiene marca_id PROPIA: de ahi sale la trampa 2 (ruta ambigua).
    print("Generando dim_vehiculo...")
    n_veh = 4_000
    idx = rng.integers(0, len(MODELOS), n_veh)
    con.execute("""CREATE TABLE dim_vehiculo (
        vehiculo_id INTEGER, modelo VARCHAR, marca_id INTEGER,
        anio_modelo INTEGER, segmento VARCHAR)""")
    segmentos = np.array(["Subcompacto", "Compacto", "SUV", "Premium"])
    con.executemany(
        "INSERT INTO dim_vehiculo VALUES (?, ?, ?, ?, ?)",
        [(int(i + 1), MODELOS[idx[i]][0], int(MODELOS[idx[i]][1]),
          int(rng.integers(2016, 2027)), str(segmentos[rng.integers(0, 4)]))
         for i in range(n_veh)],
    )

    print("Generando dim_cliente...")
    n_cli = 120_000 // div
    con.execute("""CREATE TABLE dim_cliente AS
        SELECT i AS cliente_id,
               'Cliente ' || i AS cliente_nombre,
               CASE WHEN i % 7 = 0 THEN 'Flotilla' ELSE 'Particular' END AS segmento_cliente,
               1 + (i % 4) AS region_id
        FROM generate_series(1, ?) AS t(i)""", [n_cli])

    # ---------------- fact_venta ----------------
    # Grano: linea de factura. Incluye cancelaciones en negativo (TRAMPA 5).
    n_v = 500_000 // div
    print(f"Generando fact_venta ({n_v:,})...")
    serie_por_suc: dict[int, list[str]] = {}
    for s_id, s in SERIES:
        serie_por_suc.setdefault(s_id, []).append(s)
    # Las sucursales de hojalateria y pintura (Aurex-HP) no venden vehiculos
    # nuevos, asi que no tienen serie: solo facturan servicio.
    suc_con_venta = np.array(sorted(serie_por_suc.keys()))
    suc = suc_con_venta[rng.integers(0, len(suc_con_venta), n_v)]
    series_col = np.array([serie_por_suc[int(s)][0] for s in suc])

    dias = rng.integers(0, 3865, n_v)
    fechas = (np.datetime64("2016-01-01") + dias).astype("datetime64[us]")
    es_cancel = rng.random(n_v) < 0.06          # 6% son cancelaciones
    signo = np.where(es_cancel, -1.0, 1.0)

    base = rng.normal(420_000, 130_000, n_v).clip(120_000, 1_400_000).round(2)
    costo = (base * rng.uniform(0.78, 0.92, n_v)).round(2)
    impuesto = (base * 0.0165).round(2)
    bonus = np.where(rng.random(n_v) < 0.55,
                     rng.uniform(4_000, 32_000, n_v).round(2), 0.0)
    bonus_cancel = np.where(es_cancel & (rng.random(n_v) < 0.7),
                            rng.uniform(4_000, 32_000, n_v).round(2), 0.0)

    con.execute("""CREATE TABLE fact_venta (
        venta_id BIGINT, nr_nota INTEGER, serie VARCHAR, sucursal_id INTEGER,
        cliente_id INTEGER, vehiculo_id INTEGER, fecha_emision DATE,
        monto_base DOUBLE, monto_impuesto DOUBLE, monto_costo DOUBLE,
        monto_bonus DOUBLE, monto_bonus_cancel DOUBLE, unidades INTEGER,
        es_cancelacion BOOLEAN)""")
    con.register("tmp_v", {
        "venta_id": np.arange(1, n_v + 1, dtype=np.int64),
        "nr_nota": rng.integers(10_000, 99_999, n_v),
        "serie": series_col,
        "sucursal_id": suc,
        "cliente_id": rng.integers(1, n_cli + 1, n_v),
        "vehiculo_id": rng.integers(1, n_veh + 1, n_v),
        "fecha_emision": fechas,
        "monto_base": base * signo,
        "monto_impuesto": impuesto * signo,
        "monto_costo": costo * signo,
        "monto_bonus": bonus * signo,
        "monto_bonus_cancel": bonus_cancel,
        "unidades": signo.astype(np.int32),
        "es_cancelacion": es_cancel,
    })
    con.execute("INSERT INTO fact_venta SELECT * FROM tmp_v")
    con.unregister("tmp_v")

    # ---------------- fact_servicio ----------------
    n_s = 3_000_000 // div
    print(f"Generando fact_servicio ({n_s:,})...")
    dias_s = rng.integers(0, 3865, n_s)
    con.execute("""CREATE TABLE fact_servicio (
        servicio_id BIGINT, nr_os INTEGER, sucursal_id INTEGER,
        vehiculo_id INTEGER, cliente_id INTEGER, fecha_apertura DATE,
        monto_mano_obra DOUBLE, horas_facturadas DOUBLE, tipo_os VARCHAR)""")
    tipos = np.array(["Mantenimiento", "Garantia", "Hojalateria", "Diagnostico"])
    con.register("tmp_s", {
        "servicio_id": np.arange(1, n_s + 1, dtype=np.int64),
        "nr_os": rng.integers(1000, 999_999, n_s),
        "sucursal_id": rng.integers(1, 41, n_s),
        "vehiculo_id": rng.integers(1, n_veh + 1, n_s),
        "cliente_id": rng.integers(1, n_cli + 1, n_s),
        "fecha_apertura": (np.datetime64("2016-01-01") + dias_s).astype("datetime64[us]"),
        "monto_mano_obra": rng.normal(3_200, 1_500, n_s).clip(300, 40_000).round(2),
        "horas_facturadas": rng.uniform(0.5, 12, n_s).round(1),
        "tipo_os": tipos[rng.integers(0, 4, n_s)],
    })
    con.execute("INSERT INTO fact_servicio SELECT * FROM tmp_s")
    con.unregister("tmp_s")

    # ---------------- fact_refaccion ----------------
    n_r = 8_000_000 // div
    print(f"Generando fact_refaccion ({n_r:,})...")
    dias_r = rng.integers(0, 3865, n_r)
    con.execute("""CREATE TABLE fact_refaccion (
        refaccion_id BIGINT, sucursal_id INTEGER, fecha_venta DATE,
        linea_producto VARCHAR, monto_venta DOUBLE, monto_costo DOUBLE,
        piezas INTEGER)""")
    lineas = np.array(["Motor", "Frenos", "Suspension", "Electrico",
                       "Carroceria", "Lubricantes", "Accesorios", "Llantas"])
    mv = rng.normal(1_800, 900, n_r).clip(80, 30_000).round(2)
    con.register("tmp_r", {
        "refaccion_id": np.arange(1, n_r + 1, dtype=np.int64),
        "sucursal_id": rng.integers(1, 41, n_r),
        "fecha_venta": (np.datetime64("2016-01-01") + dias_r).astype("datetime64[us]"),
        "linea_producto": lineas[rng.integers(0, 8, n_r)],
        "monto_venta": mv,
        "monto_costo": (mv * rng.uniform(0.6, 0.85, n_r)).round(2),
        "piezas": rng.integers(1, 9, n_r),
    })
    con.execute("INSERT INTO fact_refaccion SELECT * FROM tmp_r")
    con.unregister("tmp_r")

    # ---------------- fact_presupuesto (TRAMPA 1: fan trap) ----------------
    # Grano: sucursal x anio_mes. Mucho mas grueso que fact_venta.
    print("Generando fact_presupuesto (grano sucursal x mes)...")
    con.execute("""
        CREATE TABLE fact_presupuesto AS
        SELECT
            ROW_NUMBER() OVER ()                       AS presupuesto_id,
            s.sucursal_id,
            c.anio_mes,
            CAST(30 + (s.sucursal_id % 7) * 8 AS INTEGER) AS objetivo_unidades,
            CAST((30 + (s.sucursal_id % 7) * 8) * 430000 AS DOUBLE) AS objetivo_monto
        FROM cat_sucursal s
        CROSS JOIN (SELECT DISTINCT anio_mes FROM dim_calendario) c
    """)

    # ---------------- TRAMPA 3: tabla huerfana ----------------
    print("Generando tbl_encuesta_clima (huerfana, sin relaciones)...")
    con.execute("""
        CREATE TABLE tbl_encuesta_clima AS
        SELECT i AS encuesta_id,
               'Sucursal texto libre ' || (1 + (i % 40)) AS sucursal_texto,
               ROUND(3 + random() * 2, 1) AS resultado,
               2024 + (i % 3) AS anio
        FROM generate_series(1, 5000) AS t(i)
    """)

    print("\n--- Resumen ---")
    for (t,) in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    ).fetchall():
        n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        print(f"  {t:24s} {n:>12,} filas")

    con.close()
    print(f"\nBase: {DB}  ({DB.stat().st_size / 1024 / 1024:,.1f} MB)")
    return DB


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rapido", action="store_true",
                   help="20 veces menos filas: para CI y para probar rapido")
    generar(rapido=p.parse_args().rapido)
