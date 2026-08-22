"""
«Mostrar tambien las filas que no tienen cifras».

Por omision las filas de una tabla salen de las CIFRAS: sin cifras no hay filas, y en
vez de una tabla vacia el widget explica por que —la tabla no esta cargada, la union no
casa, una politica tapa todo, los filtros no dejan nada—. Eso esta bien para explorar.

No esta bien para un informe de una sucursal fija: ahi la respuesta es «cero», y un
recuadro explicando que no hay datos es un hueco en la hoja que alguien firma.

Con la bandera, los valores del desglose salen de sus propias tablas y las cifras se
les pegan por la izquierda. Lo que NO puede cambiar es quien ve que: la lista de
valores pasa por los mismos filtros y las mismas politicas por fila que una metrica, o
un widget sin datos seria la forma mas facil de averiguar los nombres que alguien no
tiene permitido ver.
"""

import itertools
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
YAML_DEMO = (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")

_siguiente = itertools.count(1)

SUC = "cat_sucursal.sucursal_nombre"
REG = "cat_region.region_nombre"


@pytest.fixture
def modelo(cliente, cab_admin):
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": f"sincifras_{next(_siguiente)}", "yaml": YAML_DEMO})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def consultar(cliente, cab, mid, metricas, dimensiones, filtros=None, sin_cifras=None):
    cuerpo = {"dimensiones": dimensiones, "metricas": metricas,
              "filtros": filtros or []}
    if sin_cifras is not None:
        cuerpo["filas_sin_cifras"] = sin_cifras
    return cliente.post(f"/api/modelos/{mid}/consultar", headers=cab, json=cuerpo)


#: Un filtro que no deja ninguna venta pero si deja la sucursal en su catalogo. Es la
#: forma de reproducir «la sucursal existe y no tiene cifras» sin tocar los datos.
SOLO_UNA = [{"campo": SUC, "op": "=", "valor": "Aurex-HP Cabo Sur"}]


# --------------------------------------------------------------------------- #

def test_sin_la_bandera_no_hay_ni_una_fila(cliente, cab_editor, modelo):
    """El comportamiento de siempre: sin cifras, sin filas, y el motivo explicado."""
    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC], SOLO_UNA)
    assert r.status_code == 200, r.text
    assert r.json()["filas"] == []
    assert r.json().get("vacio_porque")


def test_con_la_bandera_sale_la_fila_vacia(cliente, cab_editor, modelo):
    """
    La sucursal existe en su catalogo, asi que sale — con la cifra en blanco, que es
    la verdad. Un cero se consigue marcando la metrica con «si no hay dato, cero».
    """
    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC],
                  SOLO_UNA, sin_cifras=True)
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert [f[SUC] for f in filas] == ["Aurex-HP Cabo Sur"], filas
    assert filas[0]["unidades_vendidas"] is None


def test_las_que_si_tienen_cifras_no_se_duplican(cliente, cab_editor, modelo):
    """
    La espina es un UNION, no un apilado: una sucursal que sale por las dos vias sale
    una vez. Sin esto, cada fila con datos se contaria dos veces.
    """
    sin = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC])
    con = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC],
                    sin_cifras=True)
    assert con.status_code == 200, con.text
    de_sin = {f[SUC]: f["unidades_vendidas"] for f in sin.json()["filas"]}
    de_con = {f[SUC]: f["unidades_vendidas"] for f in con.json()["filas"]}
    # Cada nombre una sola vez, y las cifras que ya salian no cambian.
    assert len(de_con) == len(con.json()["filas"])
    assert len(de_con) > len(de_sin), "aparecen las que no tenian cifras"
    for nombre, valor in de_sin.items():
        assert de_con[nombre] == valor, nombre


def test_los_filtros_siguen_valiendo(cliente, cab_editor, modelo):
    """
    Sacar las filas del catalogo no puede sacar las que el filtro descarta: entonces
    el filtro no filtraria, solo dejaria en blanco lo que no cumple.
    """
    filtro = [{"campo": REG, "op": "=", "valor": "Centro"}]
    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC],
                  filtro, sin_cifras=True)
    assert r.status_code == 200, r.text
    con_region = {f[SUC] for f in r.json()["filas"]}
    assert con_region, "la region Centro tiene sucursales"

    # Acota de verdad: no salen las de las demas regiones.
    todas = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC],
                      sin_cifras=True)
    assert con_region < {f[SUC] for f in todas.json()["filas"]}

    # Y dentro de la region si aparecen las que no tienen ventas, o esta prueba
    # pasaria igual sin la bandera y no diria nada.
    con_cifras = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC],
                           filtro)
    assert con_region > {f[SUC] for f in con_cifras.json()["filas"]}


def test_la_seguridad_por_fila_sigue_tapando(cliente, cab_lector, modelo,
                                             cab_admin):
    """
    Lo que mas importa de todo esto. El lector regional solo puede ver una sucursal; con
    la bandera puesta tiene que seguir viendo una, no las cuarenta. Un widget sin datos
    seria la forma mas facil de averiguar los nombres que alguien no puede ver.
    """
    # La politica ya viene en el modelo de demostracion (rls_por_region).
    r = consultar(cliente, cab_lector, modelo, ["unidades_vendidas"], [SUC],
                  sin_cifras=True)
    assert r.status_code == 200, r.text
    suyas = {f[SUC] for f in r.json()["filas"]}
    assert len(suyas) == 1, suyas

    del_admin = consultar(cliente, cab_admin, modelo, ["unidades_vendidas"], [SUC],
                          sin_cifras=True)
    assert len({f[SUC] for f in del_admin.json()["filas"]}) > 1
    assert suyas < {f[SUC] for f in del_admin.json()["filas"]}


def test_un_filtro_de_fecha_no_borra_valores_del_catalogo(cliente, cab_editor, modelo):
    """
    El caso que revienta si no se piensa: una hoja filtra por mes SIEMPRE.

    Una sucursal no deja de existir porque no facturara en un mes. Su tabla solo llega
    al calendario ATRAVESANDO las facturas, y ese camino significa «las que facturaron
    en ese mes» — lo contrario de lo que se pidio. Ese filtro no se aplica a la lista,
    y sin esta decision la consulta fallaba con «no hay relacion».
    """
    futuro = [{"campo": "dim_calendario.anio", "op": "=", "valor": 2099}]

    sin = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC], futuro)
    assert sin.status_code == 200, sin.text
    assert sin.json()["filas"] == []

    con = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC], futuro,
                    sin_cifras=True)
    assert con.status_code == 200, con.text
    filas = con.json()["filas"]
    assert len(filas) > 30, "salen todas las sucursales del catalogo"
    assert all(f["unidades_vendidas"] is None for f in filas), filas[:2]


def test_una_metrica_con_cero_conserva_su_nombre(cliente, cab_editor, modelo):
    """
    Una metrica de un hecho se llamaba sola: la columna del CTE ya trae su nombre.
    Envuelta en COALESCE deja de llamarse asi, y la columna salia como
    `COALESCE(m0."x", 0)` en la cabecera y en el Excel.
    """
    r = cliente.get(f"/api/modelos/{modelo}/definicion", headers=cab_editor)
    d = r.json()["definicion"]
    for m in d["metricas"]:
        if m["nombre"] == "unidades_vendidas":
            m["sin_dato_cero"] = True
    assert cliente.put(f"/api/modelos/{modelo}/definicion", headers=cab_editor,
                       json={"definicion": d}).status_code == 201

    r = consultar(cliente, cab_editor, modelo, ["unidades_vendidas"], [SUC])
    assert r.status_code == 200, r.text
    assert "unidades_vendidas" in r.json()["columnas"], r.json()["columnas"]
    assert all("COALESCE" not in c for c in r.json()["columnas"]), r.json()["columnas"]
