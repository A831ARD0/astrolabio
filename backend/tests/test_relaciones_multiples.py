"""
Varias relaciones entre las mismas dos tablas.

El caso que las obliga: un hecho con fecha de alta, fecha de cierre y fecha de
entrega toca el calendario tres veces. Las tres uniones son ciertas y las tres se
quieren dejar escritas en el modelo, pero **al agregar solo puede mandar una**. Si
mandaran dos, cada consulta que pase por ahi tendria dos caminos igual de validos
y el total dependeria de cual eligiera el compilador — que es exactamente la
clase de numero plausible y equivocado que este producto existe para no dar.
"""

import textwrap

import pytest

from semantic.definicion import desde_yaml
from semantic.engine import Modelo, RutaAmbigua


def _yaml(activa_segunda: bool) -> str:
    return textwrap.dedent(f"""
        modelo: fechas
        version: 1
        entidades:
          - nombre: fact_os
            tipo: hecho
            origen: {{tabla: fact_os}}
            campos:
              - {{nombre: os_id,          tipo: entero, rol: clave}}
              - {{nombre: fecha_apertura, tipo: fecha,  rol: clave_externa}}
              - {{nombre: fecha_cierre,   tipo: fecha,  rol: clave_externa}}
              - {{nombre: importe,        tipo: decimal, rol: medida_base}}
          - nombre: dim_calendario
            tipo: dimension
            origen: {{tabla: dim_calendario}}
            clave_primaria: fecha
            campos:
              - {{nombre: fecha, tipo: fecha,  rol: clave}}
              - {{nombre: anio,  tipo: entero, rol: dimension}}
        relaciones:
          - desde: [fact_os, fecha_apertura]
            hasta: [dim_calendario, fecha]
            cardinalidad: muchos_a_uno
          - desde: [fact_os, fecha_cierre]
            hasta: [dim_calendario, fecha]
            cardinalidad: muchos_a_uno
            activa: {str(activa_segunda).lower()}
        metricas:
          - nombre: importe_total
            etiqueta: Importe
            entidad: fact_os
            expresion: SUMA(importe)
    """).strip()


@pytest.fixture
def escribir(tmp_path):
    def _escribir(texto: str):
        ruta = tmp_path / "m.yaml"
        ruta.write_text(texto, encoding="utf-8")
        return ruta
    return _escribir


def test_la_segunda_relacion_inactiva_se_guarda_y_no_estorba(escribir):
    """Las dos quedan escritas; solo la activa es un camino."""
    d = desde_yaml(_yaml(activa_segunda=False))
    assert d.revisar_referencias() == []
    assert len(d.relaciones) == 2

    m = Modelo(escribir(_yaml(activa_segunda=False)))
    assert len(m.relaciones) == 2
    # Un solo camino: el de la relacion activa.
    assert m.ruta_unica("fact_os", "dim_calendario") == ["fact_os", "dim_calendario"]
    assert len(m.grafo["dim_calendario"]) == 1


def test_dos_activas_entre_las_mismas_tablas_no_se_guardan(escribir):
    """
    Se bloquea al guardar y no al consultar. Descubrirlo en un tablero seis meses
    despues es descubrirlo tarde, y para entonces la cifra ya se uso.
    """
    errores = desde_yaml(_yaml(activa_segunda=True)).revisar_referencias()
    assert len(errores) == 1
    assert "2 relaciones activas" in errores[0]
    assert "inactivas" in errores[0]


def test_dos_activas_hacen_ambigua_la_ruta(escribir):
    """La razon de la regla anterior, comprobada: sin ella, esto es lo que pasa."""
    m = Modelo(escribir(_yaml(activa_segunda=True)))
    with pytest.raises(RutaAmbigua):
        m.ruta_unica("fact_os", "dim_calendario")


def test_la_inactiva_sale_en_el_diagnostico(escribir):
    """
    Una linea punteada en el lienzo tiene que poder explicarse sin adivinar. No
    es un error: es informativo, y dice que por ahi no pasa ninguna consulta.
    """
    m = Modelo(escribir(_yaml(activa_segunda=False)))
    avisos = [p for p in m.diagnosticar() if p["tipo"] == "relacion_inactiva"]
    assert len(avisos) == 1
    assert avisos[0]["gravedad"] == "informativo"
    assert "fecha_cierre" in avisos[0]["mensaje"]


def test_sin_declarar_nada_la_relacion_es_activa(escribir):
    """
    Compatibilidad: los modelos que ya existen no traen `activa` y tienen que
    seguir funcionando exactamente igual.
    """
    m = Modelo(escribir(_yaml(activa_segunda=False)))
    assert m.relaciones[0].activa is True
    assert "activa" not in _yaml(activa_segunda=False).split("cardinalidad: muchos_a_uno")[1][:20]


# --------------------------------------------------------------------------- #
# Un calendario que no sale de ninguna tabla
# --------------------------------------------------------------------------- #

def test_una_transformacion_sql_puede_no_leer_ninguna_tabla():
    """
    El calendario es la dimension que casi nadie tiene en su base y todos
    necesitan. Se fabrica con `range(fecha, fecha, INTERVAL)`, que no lee de
    ningun origen: obligar a declarar uno que no se usa era un tramite, y un
    `WITH` vacio delante ni siquiera es SQL valido.
    """
    import duckdb

    from semantic.transformacion import Transformacion, compilar

    t = Transformacion(nombre="dim_calendario", origenes=[], sql="""
        SELECT d::DATE AS fecha,
               YEAR(d) AS anio,
               MONTH(d) AS mes,
               YEAR(d) * 100 + MONTH(d) AS anio_mes
        FROM range(DATE '2024-01-01', DATE '2025-01-01', INTERVAL 1 DAY) AS t(d)
    """)
    sql = compilar(t, {}).sql
    assert not sql.startswith("WITH")
    assert duckdb.connect().execute(f"SELECT count(*) FROM ({sql})").fetchone()[0] == 366


def test_por_pasos_sigue_exigiendo_un_origen():
    """Sin SQL y sin origen no hay nada que transformar: eso sigue siendo error."""
    from pydantic import ValidationError

    from semantic.transformacion import Transformacion

    with pytest.raises(ValidationError, match="al menos un origen"):
        Transformacion(nombre="vacia", origenes=[], pasos=[])
