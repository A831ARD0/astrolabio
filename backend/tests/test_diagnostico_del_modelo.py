"""
Tres problemas que el diagnostico no veia, y que frenan un modelo de verdad.

Los tres salieron de revisar un modelo ya armado —catorce tablas, veintidos
relaciones— cuyo diagnostico salia **vacio** mientras nada de lo que se queria
medir funcionaba. Un diagnostico limpio sobre un modelo que no sirve es peor que
ninguno: dice que todo esta bien.

  1. **Una dimension con columnas de medida.** El editor de metricas solo ofrece
     hechos en «Calcula desde», asi que esas columnas no se pueden sumar. Y no se
     ve como un error: se ve como que la tabla «no sale en la lista».
  2. **Los dos lados de una union con tipos distintos.** Comparar texto con
     entero no siempre falla, y cuando no falla es peor — no casa ninguna fila y
     la cifra sale vacia.
  3. **Una fecha guardada como texto.** Ordena mal, no se une al calendario y
     ninguna comparacion de periodos funciona encima.
"""

import textwrap

import pytest


def yaml_con(entidades: str, relaciones: str = "") -> str:
    # Los elementos de la lista van a la misma sangria que su clave, que en YAML
    # es valido y evita tener que re-sangrar los bloques de arriba.
    return (f"modelo: diagnostico\nversion: 1\n"
            f"entidades:\n{textwrap.dedent(entidades).strip()}\n"
            f"relaciones:\n{textwrap.dedent(relaciones).strip() or '[]'}\n")


def problemas(cliente, cab, texto: str) -> list[dict]:
    r = cliente.post("/api/modelos", headers=cab,
                     json={"nombre": f"diag_{abs(hash(texto)) % 10**9}",
                           "yaml": texto})
    assert r.status_code == 201, r.text
    identificador = r.json()["id"]
    try:
        d = cliente.get(f"/api/modelos/{identificador}/diagnostico", headers=cab)
        assert d.status_code == 200, d.text
        return d.json()["problemas"]
    finally:
        cliente.delete(f"/api/modelos/{identificador}", headers=cab)


ENTIDADES = """
- nombre: FACT
  tipo: hecho
  origen: {tabla: fact_venta}
  campos:
  - {nombre: sucursal_id, tipo: entero, rol: clave_externa}
  - {nombre: unidades, tipo: entero, rol: medida_base}
- nombre: OBJETIVOS
  tipo: dimension
  origen: {tabla: fact_presupuesto}
  clave_primaria: presupuesto_id
  campos:
  - {nombre: presupuesto_id, tipo: entero, rol: clave}
  - {nombre: sucursal_id, tipo: entero, rol: clave_externa}
  - {nombre: objetivo_unidades, tipo: entero, rol: medida_base}
  - {nombre: objetivo_monto, tipo: decimal, rol: medida_base}
- nombre: SUC
  tipo: dimension
  origen: {tabla: cat_sucursal}
  clave_primaria: sucursal_id
  campos:
  - {nombre: sucursal_id, tipo: entero, rol: clave}
  - {nombre: sucursal_nombre, tipo: texto, rol: dimension}
"""

RELACIONES = """
- {desde: [FACT, sucursal_id], hasta: [SUC, sucursal_id], cardinalidad: muchos_a_uno}
- {desde: [OBJETIVOS, sucursal_id], hasta: [SUC, sucursal_id], cardinalidad: muchos_a_uno}
"""


def test_una_dimension_con_medidas_sale_como_critico(cliente, cab_admin):
    """
    Es el caso que motivo esto: la tabla de objetivos marcada como dimension.
    Ninguna metrica se puede calcular desde ella, y el diagnostico callaba.
    """
    ps = problemas(cliente, cab_admin, yaml_con(ENTIDADES, RELACIONES))
    suyos = [p for p in ps if p["tipo"] == "dimension_con_medidas"]
    assert len(suyos) == 1, ps
    assert suyos[0]["gravedad"] == "critico"
    assert suyos[0]["entidad"] == "OBJETIVOS"
    # Tiene que nombrar las columnas y decir que hacer.
    assert "objetivo_unidades" in suyos[0]["mensaje"]
    assert "hecho" in suyos[0]["mensaje"]


def test_un_hecho_con_medidas_no_se_reporta(cliente, cab_admin):
    """Lo normal: un hecho con columnas de medida no tiene nada de malo."""
    arreglado = ENTIDADES.replace(
        "- nombre: OBJETIVOS\n  tipo: dimension",
        "- nombre: OBJETIVOS\n  tipo: hecho")
    ps = problemas(cliente, cab_admin, yaml_con(arreglado, RELACIONES))
    assert [p for p in ps if p["tipo"] == "dimension_con_medidas"] == []


def test_una_union_con_tipos_distintos_sale_como_critico(cliente, cab_admin):
    roto = ENTIDADES.replace(
        "  - {nombre: sucursal_id, tipo: entero, rol: clave_externa}\n"
        "  - {nombre: unidades, tipo: entero, rol: medida_base}",
        "  - {nombre: sucursal_id, tipo: texto, rol: clave_externa}\n"
        "  - {nombre: unidades, tipo: entero, rol: medida_base}", 1)
    ps = problemas(cliente, cab_admin, yaml_con(roto, RELACIONES))
    suyos = [p for p in ps if p["tipo"] == "tipos_que_no_casan"]
    assert len(suyos) == 1, ps
    assert suyos[0]["gravedad"] == "critico"
    assert "texto" in suyos[0]["mensaje"] and "entero" in suyos[0]["mensaje"]


def test_una_union_con_tipos_iguales_no_se_reporta(cliente, cab_admin):
    ps = problemas(cliente, cab_admin, yaml_con(ENTIDADES, RELACIONES))
    assert [p for p in ps if p["tipo"] == "tipos_que_no_casan"] == []


@pytest.mark.parametrize("columna", [
    "fecha_qlik", "fecha_prueba_de_manejo", "Fecha_Factura", "FECHA",
])
def test_una_fecha_como_texto_se_avisa(cliente, cab_admin, columna):
    con_texto = ENTIDADES.replace(
        "  - {nombre: unidades, tipo: entero, rol: medida_base}",
        f"  - {{nombre: unidades, tipo: entero, rol: medida_base}}\n"
        f"  - {{nombre: {columna}, tipo: texto, rol: dimension}}", 1)
    ps = problemas(cliente, cab_admin, yaml_con(con_texto, RELACIONES))
    suyos = [p for p in ps if p["tipo"] == "fecha_como_texto"]
    assert len(suyos) == 1, ps
    assert suyos[0]["entidad"] == f"FACT.{columna}"
    assert suyos[0]["gravedad"] == "advertencia"


def test_una_fecha_de_verdad_no_se_avisa(cliente, cab_admin):
    """No se avisa por el nombre: se avisa por el nombre Y el tipo."""
    con_fecha = ENTIDADES.replace(
        "  - {nombre: unidades, tipo: entero, rol: medida_base}",
        "  - {nombre: unidades, tipo: entero, rol: medida_base}\n"
        "  - {nombre: fecha_emision, tipo: fecha, rol: dimension}", 1)
    ps = problemas(cliente, cab_admin, yaml_con(con_fecha, RELACIONES))
    assert [p for p in ps if p["tipo"] == "fecha_como_texto"] == []


def test_lo_critico_sale_antes_que_lo_demas(cliente, cab_admin):
    """
    El orden es la mitad del valor: con catorce tablas, un critico enterrado
    entre avisos no se lee.
    """
    roto = ENTIDADES.replace(
        "  - {nombre: unidades, tipo: entero, rol: medida_base}",
        "  - {nombre: unidades, tipo: entero, rol: medida_base}\n"
        "  - {nombre: fecha_algo, tipo: texto, rol: dimension}", 1)
    ps = problemas(cliente, cab_admin, yaml_con(roto, RELACIONES))
    gravedades = [p["gravedad"] for p in ps]
    assert "critico" in gravedades and "advertencia" in gravedades
    assert gravedades.index("critico") < gravedades.index("advertencia")
