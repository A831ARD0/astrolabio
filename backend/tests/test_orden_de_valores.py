"""
El orden en que se leen los valores de un campo en un filtro.

«Enero, febrero, marzo» no es el orden alfabetico. Un filtro de meses ordenado por
su propio valor empieza en abril y termina en septiembre, y en esa lista nadie
encuentra nada: es el mismo problema que resuelve el «ordenar por columna» de Power
BI, y se resuelve igual — diciendo por que OTRA columna se ordena.

Lo que se fija aqui es que el orden salga de esa otra columna y que el modelo no
acepte apuntar a una columna que no existe: un `ordenar_por` roto seria un ORDER BY
roto en cada consulta del filtro, y el aviso saldria al usarlo y no al guardarlo.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)

#: La columna existe en la tabla de demostracion pero el modelo no la declara: se
#: agrega aqui, que es justo el caso —una columna de texto con el nombre del mes—.
MES_NOMBRE = {"nombre": "mes_nombre", "tipo": "texto", "rol": "dimension",
              "etiqueta": "Nombre del mes"}


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"orden_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def con_nombre_del_mes(cliente, cab, modelo_id: int, ordenar_por: str | None):
    r = cliente.get(f"/api/modelos/{modelo_id}/definicion", headers=cab)
    d = r.json()["definicion"]
    cal = next(e for e in d["entidades"] if e["nombre"] == "dim_calendario")
    cal["campos"].append({**MES_NOMBRE, "ordenar_por": ordenar_por})
    return cliente.put(f"/api/modelos/{modelo_id}/definicion", headers=cab,
                       json={"definicion": d})


def valores(cliente, cab, modelo_id: int, campo: str) -> list:
    r = cliente.post(f"/api/modelos/{modelo_id}/asociativo", headers=cab,
                     json={"entidad": "dim_calendario", "campo": campo,
                           "selecciones": {}})
    assert r.status_code == 200, r.text
    e = r.json()
    return e["seleccionado"] + e["posible"] + e["alternativo"] + e["excluido"]


def test_los_meses_salen_como_va_el_anio_y_no_en_alfabetico(
        cliente, cab_editor, modelo):
    assert con_nombre_del_mes(cliente, cab_editor, modelo, "mes").status_code == 201

    orden = valores(cliente, cab_editor, modelo, "mes_nombre")
    assert len(orden) == 12

    # La verdad: el nombre de cada mes por su numero, sacado del propio calendario.
    # Lleva una metrica porque una consulta sin ninguna cifra no se acepta.
    r = cliente.post(f"/api/modelos/{modelo}/consultar", headers=cab_editor,
                     json={"dimensiones": ["dim_calendario.mes",
                                           "dim_calendario.mes_nombre"],
                           "metricas": ["unidades_vendidas"], "filtros": []})
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert len(filas) == 12, "los doce meses tienen ventas en la demostracion"
    esperado = [f["dim_calendario.mes_nombre"] for f in
                sorted(filas, key=lambda f: f["dim_calendario.mes"])]

    assert orden == esperado
    # Y que esto no pase por casualidad: el alfabetico es OTRO orden.
    assert orden != sorted(orden), "el alfabetico y el del año coinciden: no prueba nada"


def test_sin_ordenar_por_sigue_saliendo_por_su_valor(cliente, cab_editor, modelo):
    assert con_nombre_del_mes(cliente, cab_editor, modelo, None).status_code == 201
    orden = valores(cliente, cab_editor, modelo, "mes_nombre")
    assert orden == sorted(orden)


def test_ordenar_por_una_columna_que_no_existe_no_se_guarda(cliente, cab_editor,
                                                            modelo):
    r = con_nombre_del_mes(cliente, cab_editor, modelo, "numero_del_mes")
    assert r.status_code == 422, r.text
    assert "numero_del_mes" in r.text and "dim_calendario" in r.text


def test_ordenar_por_si_mismo_no_se_guarda(cliente, cab_editor, modelo):
    """No es un error de escritura inocente: quien lo escribe cree haber arreglado
    el orden, y el orden sigue siendo el mismo que le molestaba."""
    r = con_nombre_del_mes(cliente, cab_editor, modelo, "mes_nombre")
    assert r.status_code == 422, r.text
    assert "por si mismo" in r.text


def test_el_catalogo_dice_por_que_columna_se_ordena(cliente, cab_editor, modelo):
    """
    La interfaz tiene que poder ordenar igual que el modelo.

    Las columnas de una tabla dinamica las ordena el navegador —el cruce se hace
    ahi—, asi que sin este dato «Enero» sale despues de «Abril» aunque el modelo
    diga por donde va. Se manda ya calificado, `entidad.campo`, porque es como la
    interfaz nombra una columna en todos los demas sitios.
    """
    assert con_nombre_del_mes(cliente, cab_editor, modelo, "mes").status_code == 201

    r = cliente.get(f"/api/modelos/{modelo}/campos", headers=cab_editor)
    assert r.status_code == 200, r.text
    por_clave = {d["clave"]: d for d in r.json()["dimensiones"]}
    assert por_clave["dim_calendario.mes_nombre"]["ordenar_por"] == "dim_calendario.mes"
    # Y la que no se ordena por ninguna lo dice con un nulo, no omitiendo la clave:
    # la interfaz distingue «por su propio valor» de «no me lo dijeron».
    assert por_clave["dim_calendario.mes"]["ordenar_por"] is None
