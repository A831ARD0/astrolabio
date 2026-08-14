"""
Una columna puede no repetirse sin ser la clave primaria.

De donde sale: un catalogo de sucursales trae varios identificadores que no se
repiten —el propio, el del sistema del taller, el del CRM— y cada uno es por
donde se une un hecho distinto. Del lado «uno» de una relacion muchos-a-uno lo
que hace falta no es ser la clave primaria: es no repetirse.

Antes solo se miraba la clave primaria, y como una entidad tiene UNA, la unica
forma de callar el aviso en una relacion era cambiarla — con lo que el mismo
aviso se encendia en las otras ocho que unian contra la anterior. Marcar la
columna como unica no le quita el sitio a nadie.
"""

import textwrap

import pytest

from semantic.definicion import desde_yaml
from semantic.engine import Modelo


def _yaml(*, unico: bool) -> str:
    return textwrap.dedent(f"""
        modelo: sucursales
        version: 1
        entidades:
          - nombre: fact_hubspot
            tipo: hecho
            origen: {{tabla: fact_hubspot}}
            campos:
              - {{nombre: id_lead,    tipo: entero,  rol: clave}}
              - {{nombre: id_sucursal, tipo: entero, rol: clave_externa}}
              - {{nombre: importe,    tipo: decimal, rol: medida_base}}
          - nombre: cat_sucursal
            tipo: dimension
            origen: {{tabla: cat_sucursal}}
            clave_primaria: id_sucursal_quiter
            campos:
              - {{nombre: id_sucursal_quiter, tipo: entero, rol: clave}}
              - {{nombre: id_sucursal_hubspot, tipo: entero, rol: clave,
                  unico: {str(unico).lower()}}}
              - {{nombre: nombre, tipo: texto, rol: dimension}}
        relaciones:
          - desde: [fact_hubspot, id_sucursal]
            hasta: [cat_sucursal, id_sucursal_hubspot]
            cardinalidad: muchos_a_uno
        metricas:
          - nombre: importe_total
            etiqueta: Importe
            entidad: fact_hubspot
            expresion: SUMA(importe)
    """).strip()


@pytest.fixture
def escribir(tmp_path):
    def _escribir(texto: str):
        ruta = tmp_path / "m.yaml"
        ruta.write_text(texto, encoding="utf-8")
        return ruta
    return _escribir


def _avisos(m: Modelo) -> list[dict]:
    return [p for p in m.diagnosticar() if p["tipo"] == "uno_sin_garantia"]


def test_sin_declarar_nada_el_lado_uno_se_avisa(escribir):
    """
    El aviso mas util del modelo, y hasta ahora solo existia en la pantalla:
    quien mira el diagnostico —o abre el YAML— no se enteraba.
    """
    avisos = _avisos(Modelo(escribir(_yaml(unico=False))))
    assert len(avisos) == 1
    assert avisos[0]["gravedad"] == "advertencia"
    assert "id_sucursal_hubspot" in avisos[0]["mensaje"]


def test_marcarla_unica_calla_el_aviso_sin_tocar_la_clave(escribir):
    """Lo que se venia a resolver: sin sustituir la clave primaria de nadie."""
    texto = _yaml(unico=True)
    d = desde_yaml(texto)
    assert d.revisar_referencias() == []

    m = Modelo(escribir(texto))
    assert _avisos(m) == []
    # Y la clave primaria sigue siendo la de siempre.
    assert m.entidades["cat_sucursal"].clave_primaria == "id_sucursal_quiter"


def test_la_clave_primaria_ya_vale_por_si_sola(escribir):
    """No hace falta marcar `unico` en la clave: lo es por definicion."""
    texto = _yaml(unico=False).replace(
        "hasta: [cat_sucursal, id_sucursal_hubspot]",
        "hasta: [cat_sucursal, id_sucursal_quiter]")
    assert _avisos(Modelo(escribir(texto))) == []


def test_una_relacion_inactiva_no_avisa(escribir):
    """
    Por ahi no pasa ninguna consulta, asi que no puede inflar ningun total.
    Avisar igual seria ruido sobre algo que esta apagado a proposito.
    """
    texto = _yaml(unico=False).replace(
        "    cardinalidad: muchos_a_uno",
        "    cardinalidad: muchos_a_uno\n    activa: false")
    assert _avisos(Modelo(escribir(texto))) == []


def test_el_campo_conserva_la_marca_al_ir_y_volver():
    """`unico` sobrevive al viaje por la definicion: no se pierde al guardar."""
    d = desde_yaml(_yaml(unico=True))
    campo = next(c for e in d.entidades for c in e.campos
                 if c.nombre == "id_sucursal_hubspot")
    assert campo.unico is True
    assert d.model_dump()["entidades"][1]["campos"][1]["unico"] is True
