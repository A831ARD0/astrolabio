"""
Pruebas del motor semantico contra el entorno con los datos de demostracion.
Cada prueba ataca una de las trampas que se sembraron a proposito.
"""

import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import config  # noqa: E402
from semantic.engine import (  # noqa: E402
    Compilador, Consulta, Modelo, MotorAsociativo, RutaAmbigua, SinRuta,
)

AQUI = Path(__file__).parent
# La que dice ASTROLABIO_RUTA_DUCKDB. Antes buscaba `demo/analitico.duckdb`,
# que no es donde `generar_datos.py` escribe.
con = duckdb.connect(config().ruta_duckdb, read_only=True)
modelo = Modelo(AQUI / "modelo_demo.yaml")
comp = Compilador(modelo)

fallos = []


def titulo(n, t):
    print(f"\n{'=' * 74}\nPRUEBA {n} — {t}\n{'=' * 74}")


def verificar(ok, msg):
    print(f"  {'✓' if ok else '✗ FALLO:'} {msg}")
    if not ok:
        fallos.append(msg)


# --------------------------------------------------------------------------- #
titulo(1, "Diagnostico del modelo: ¿detecta los problemas sembrados?")

problemas = modelo.diagnosticar()
print(f"  {len(problemas)} problemas detectados:\n")
for p in problemas:
    print(f"  [{p['gravedad'].upper():11s}] {p['tipo']}: {p['entidad']}")
    print(f"                {p['mensaje']}")
    for r in p.get("rutas", []):
        print(f"                  · {r}")

tipos = {p["tipo"] for p in problemas}
verificar("tabla_huerfana" in tipos, "Detecta la tabla huerfana (tbl_encuesta_clima)")
verificar(
    any(p["tipo"] == "tabla_huerfana" and p["entidad"] == "tbl_encuesta_clima"
        for p in problemas),
    "La huerfana identificada es la correcta",
)
verificar("ruta_ambigua" in tipos, "Detecta rutas ambiguas")
verificar("muchos_a_muchos" in tipos, "Advierte de la relacion muchos-a-muchos")


# --------------------------------------------------------------------------- #
titulo(2, "Ambiguedad: dos caminos a cat_marca. ¿Se niega a adivinar?")

try:
    comp.compilar(Consulta(
        dimensiones=["cat_marca.marca_nombre"],
        metricas=["monto_venta"],
    ))
    verificar(False, "Deberia haber fallado por ambiguedad, pero compilo")
except RutaAmbigua as e:
    verificar(True, "Se niega a elegir camino en silencio")
    print(f"\n  Mensaje al usuario:\n    {str(e)}\n")
    verificar(len(e.rutas) == 2, f"Ofrece las 2 rutas reales ({len(e.rutas)})")

# Con la ruta elegida explicitamente, si compila y ejecuta.
print("  Ahora eligiendo 'marca de la agencia' (via cat_sucursal):")
q = Consulta(
    dimensiones=["cat_marca.marca_nombre"],
    metricas=["monto_venta", "unidades_vendidas"],
    rutas_elegidas={"fact_venta->cat_marca": "fact_venta → cat_sucursal → cat_marca"},
)
cq = comp.compilar(q); filas = con.execute(cq.sql, cq.parametros).fetchall()
verificar(len(filas) > 0, f"Ejecuta y devuelve {len(filas)} marcas")
for f in filas[:4]:
    print(f"    {f[0]:10s}  venta={f[1]:>18,.2f}  unidades={f[2]:>8,}")

print("\n  Y eligiendo 'marca del vehiculo' (via dim_vehiculo):")
q2 = Consulta(
    dimensiones=["cat_marca.marca_nombre"],
    metricas=["monto_venta"],
    rutas_elegidas={"fact_venta->cat_marca": "fact_venta → dim_vehiculo → cat_marca"},
)
cq2 = comp.compilar(q2); filas2 = con.execute(cq2.sql, cq2.parametros).fetchall()
d1 = {f[0]: f[1] for f in filas}
d2 = {f[0]: f[1] for f in filas2}
distintos = sum(1 for k in d1 if abs(d1.get(k, 0) - d2.get(k, 0)) > 1)
verificar(distintos > 0,
          f"Las dos rutas dan cifras distintas en {distintos} marcas — por eso "
          f"no se puede adivinar")


# --------------------------------------------------------------------------- #
titulo(3, "FAN TRAP: objetivo mensual junto a venta por factura")

# Verdad de campo, calculada directo sobre la tabla de presupuesto.
verdad = con.execute("""
    SELECT s.sucursal_nombre, SUM(p.objetivo_unidades)
    FROM fact_presupuesto p JOIN cat_sucursal s USING (sucursal_id)
    GROUP BY 1 ORDER BY 1
""").fetchall()
verdad_d = {r[0]: r[1] for r in verdad}

# Lo que haria un motor ingenuo: unir los dos hechos y luego agregar.
ingenuo = con.execute("""
    SELECT s.sucursal_nombre, SUM(p.objetivo_unidades)
    FROM fact_venta v
    JOIN cat_sucursal s USING (sucursal_id)
    JOIN dim_calendario c ON v.fecha_emision = c.fecha
    JOIN fact_presupuesto p ON p.sucursal_id = v.sucursal_id
                           AND p.anio_mes = c.anio_mes
    GROUP BY 1 ORDER BY 1
""").fetchall()
ingenuo_d = {r[0]: r[1] for r in ingenuo}

# Lo que hace Astrolabio.
q = Consulta(
    dimensiones=["cat_sucursal.sucursal_nombre"],
    metricas=["unidades_vendidas", "objetivo_unidades"],
)
cq = comp.compilar(q)
sql = cq.sql
nuestro = con.execute(sql, cq.parametros).fetchall()
nuestro_d = {r[0]: r[2] for r in nuestro}

muestra = "Aurex Valle Alto"
print(f"  Objetivo de unidades de '{muestra}':")
print(f"    Verdad de campo          : {verdad_d[muestra]:>14,}")
print(f"    Motor ingenuo (join+SUM) : {ingenuo_d[muestra]:>14,}  "
      f"← inflado {ingenuo_d[muestra] / verdad_d[muestra]:,.0f}x")
print(f"    Astrolabio                 : {nuestro_d[muestra]:>14,}")

verificar(ingenuo_d[muestra] > verdad_d[muestra] * 10,
          "El enfoque ingenuo si infla la cifra (la trampa es real)")
verificar(all(abs(nuestro_d[k] - verdad_d[k]) < 0.01 for k in verdad_d),
          f"Astrolabio coincide con la verdad de campo en las {len(verdad_d)} sucursales")

print("\n  SQL generado:")
print("  " + "\n  ".join(sql.splitlines()))


# --------------------------------------------------------------------------- #
titulo(4, "Metrica no desglosable: ¿avisa en vez de inventar?")

try:
    comp.compilar(Consulta(
        dimensiones=["dim_vehiculo.modelo"],
        metricas=["objetivo_unidades"],   # presupuesto no conoce el vehiculo
    ))
    verificar(False, "Deberia haber avisado que no se puede desglosar")
except (SinRuta, RutaAmbigua) as e:
    verificar(True, "Avisa que la metrica no se puede desglosar por esa dimension")
    print(f"    → {type(e).__name__}: {str(e).splitlines()[0]}")


# --------------------------------------------------------------------------- #
titulo(5, "Cancelaciones: ¿se neutralizan al sumar?")

q = Consulta(dimensiones=[], metricas=["monto_venta", "unidades_vendidas"])
cq = comp.compilar(q); total_venta, total_uds = con.execute(cq.sql, cq.parametros).fetchone()
bruto = con.execute(
    "SELECT SUM(monto_base), SUM(unidades) FROM fact_venta WHERE NOT es_cancelacion"
).fetchone()
canc = con.execute(
    "SELECT SUM(monto_base), SUM(unidades) FROM fact_venta WHERE es_cancelacion"
).fetchone()

print(f"    Ventas          : {bruto[0]:>18,.2f}   {bruto[1]:>9,} unidades")
print(f"    Cancelaciones   : {canc[0]:>18,.2f}   {canc[1]:>9,} unidades")
print(f"    Neto (Astrolabio) : {total_venta:>18,.2f}   {total_uds:>9,} unidades")
verificar(abs(total_venta - (bruto[0] + canc[0])) < 0.01,
          "El neto es venta + cancelaciones (las notas de credito restan)")
verificar(canc[1] < 0, "Las cancelaciones traen unidades en negativo")


# --------------------------------------------------------------------------- #
titulo(6, "Estados asociativos al estilo Qlik")

asoc = MotorAsociativo(modelo, con)

print("  Sin ninguna seleccion — Estado:")
e = asoc.estados("cat_region", "region_nombre", {})
print(f"    posible={e['posible']}")
verificar(len(e["posible"]) == 4 and not e["excluido"],
          "Sin seleccion, los 4 estados son posibles")

print("\n  Seleccionando Modelo = 'Cruce' (solo lo vende Aurex):")
sel = {"dim_vehiculo.modelo": ["Cruce"]}
e = asoc.estados("cat_marca", "marca_nombre", sel)
print(f"    seleccionado = {e['seleccionado']}")
print(f"    posible      = {e['posible']}")
print(f"    excluido     = {e['excluido']}")
verificar("Aurex" in e["posible"], "Aurex queda posible")
verificar(len(e["excluido"]) > 0, f"{len(e['excluido'])} marcas quedan excluidas")

print("\n  Seleccionando Estado = 'Veracruz' (solo Ekos Río Blanco):")
sel = {"cat_region.region_nombre": ["Sur"]}
e = asoc.estados("cat_sucursal", "sucursal_nombre", sel)
print(f"    posible  = {e['posible']}")
print(f"    excluido = {len(e['excluido'])} sucursales")
verificar(e["posible"] == ["Ekos Río Blanco"],
          "Solo Ekos Río Blanco es posible en la region Sur")

print("\n  Estado alternativo (seleccion en el propio campo):")
sel = {"cat_region.region_nombre": ["Norte"]}
e = asoc.estados("cat_region", "region_nombre", sel)
print(f"    seleccionado = {e['seleccionado']}")
print(f"    alternativo  = {e['alternativo']}")
verificar(e["seleccionado"] == ["Norte"], "Norte queda seleccionado")
verificar(sorted(e["alternativo"]) == ["Centro", "Occidente", "Sur"],
          "Las otras 3 regiones quedan 'alternativo', no 'excluido'")

print("\n  Union sobre rutas ambiguas — Marca desde Serie (llega por 2 caminos):")
sel = {"fact_venta.serie": ["HM1"]}       # serie de una agencia Hexa
e = asoc.estados("cat_marca", "marca_nombre", sel)
print(f"    posible = {e['posible']}")
verificar("Hexa" in e["posible"],
          "La union sobre rutas encuentra Hexa (por agencia y por vehiculo)")


# --------------------------------------------------------------------------- #
titulo(7, "Desempeño sobre 11.6M filas")

pruebas = [
    ("Venta por sucursal y año",
     Consulta(dimensiones=["cat_sucursal.sucursal_nombre", "dim_calendario.anio"],
              metricas=["monto_venta", "monto_utilidad", "unidades_vendidas"])),
    ("3 hechos distintos por estado (8.5M+3M+500k filas)",
     Consulta(dimensiones=["cat_region.region_nombre"],
              metricas=["monto_venta", "venta_mano_obra", "venta_refacciones"])),
    ("Venta vs objetivo por sucursal y mes",
     Consulta(dimensiones=["cat_sucursal.sucursal_nombre", "dim_calendario.anio_mes"],
              metricas=["unidades_vendidas", "objetivo_unidades"])),
    ("Refacciones por linea de producto y trimestre",
     Consulta(dimensiones=["fact_refaccion.linea_producto", "dim_calendario.trimestre"],
              metricas=["venta_refacciones"])),
]
for etiqueta, q in pruebas:
    cq = comp.compilar(q)
    t0 = time.perf_counter()
    filas = con.execute(cq.sql, cq.parametros).fetchall()
    ms = (time.perf_counter() - t0) * 1000
    print(f"    {etiqueta:52s} {ms:7.0f} ms  ({len(filas):,} filas)")
    verificar(ms < 5000, f"'{etiqueta}' responde en menos de 5 s")

t0 = time.perf_counter()
asoc.estados("cat_sucursal", "sucursal_nombre", {"dim_vehiculo.modelo": ["Lito"]})
ms = (time.perf_counter() - t0) * 1000
print(f"    {'Estados asociativos (sucursal | modelo=Lito)':52s} {ms:7.0f} ms")
verificar(ms < 3000, "Los estados asociativos responden en menos de 3 s")


# --------------------------------------------------------------------------- #
print(f"\n{'=' * 74}")
if fallos:
    print(f"RESULTADO: {len(fallos)} FALLOS")
    for f in fallos:
        print(f"  ✗ {f}")
    sys.exit(1)
print("RESULTADO: todas las pruebas pasaron")
print("=" * 74)
