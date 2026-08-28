"""
Lo que siembra la demostracion tiene que poder abrirse.

Nadie valida `demo/sembrar.py` al correrlo: mete diccionarios en la base tal cual.
Asi que una clave mal escrita se guarda sin protestar y el fallo aparece lejos —al
ABRIR la pantalla de Transformar, con un 422 y una lista de errores de Pydantic
sobre las nueve variantes de paso—.

Paso exactamente eso: el paso de unir se sembro con `parejas` y `trae`, y los
nombres son `en` y `traer`. La demostracion se levantaba entera, el tablero daba
sus cifras, y la unica pantalla rota era la del ETL. Es el peor sitio donde
tenerlo: la demostracion existe para que alguien mire, y lo que mire tiene que
funcionar.
"""

from semantic.transformacion import Transformacion, compilar


def test_la_transformacion_de_la_demo_es_valida():
    """Se valida contra el mismo modelo que usa la API al abrirla."""
    from demo.sembrar import TRANSFORMACION

    t = Transformacion.model_validate(TRANSFORMACION)
    assert [p.tipo for p in t.pasos] == [
        "unir", "filtrar", "derivar", "agrupar", "ordenar"]


def test_y_ademas_compila():
    """
    Validar no basta: un paso puede ser valido y nombrar una columna que no
    existe. Compilar es lo que comprueba que los pasos encajan entre si.
    """
    from demo.sembrar import TRANSFORMACION

    t = Transformacion.model_validate(TRANSFORMACION)
    c = compilar(t, {"ventas": '"fact_venta"', "sucursales": '"cat_sucursal"'})
    assert "p1_unir" in c.sql
    assert c.sql.rstrip().endswith("SELECT * FROM p5_ordenar")


def test_el_modelo_de_la_demo_es_valido():
    """Lo mismo para el YAML del modelo: si no carga, no hay tablero que ver."""
    from pathlib import Path

    from semantic.definicion import desde_yaml

    yaml = Path(__file__).resolve().parent.parent / "demo" / "modelo_demo.yaml"
    d = desde_yaml(yaml.read_text(encoding="utf-8"))
    assert d.revisar_referencias() == []
    assert len(d.entidades) > 0 and len(d.metricas) > 0
