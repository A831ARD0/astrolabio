"""
Origenes ODBC que no tienen esquemas.

El Pervasive de TotalDealer es el caso: el DSN ya apunta a los datos, no hay
catalogo ni esquema que elegir, y `SQLTables` devuelve las tablas con esos dos
campos vacios. El explorador pedia las tablas sin esquema —porque no hay
ninguno que ofrecer— y el conector respondia «Hace falta indicar el esquema o
la base de datos», que para ese origen es pedir algo que no existe. La conexion
quedaba inservible.

Aqui no hace falta un driver de verdad: lo unico en juego es que el conector no
exija un esquema que el origen no tiene, y que al listar sin filtro se quite lo
que es del motor y no de nadie.
"""

from __future__ import annotations

from app.conectores.odbc import ConectorODBC


class _Fila:
    def __init__(self, cat, esq, nombre, tipo="TABLE"):
        self.table_cat = cat
        self.table_schem = esq
        self.table_name = nombre
        self.table_type = tipo


class _Cursor:
    def __init__(self, filas):
        self._filas = filas
        self.pedido = None

    def tables(self, **kw):
        self.pedido = kw
        return list(self._filas)


class _Conexion:
    def __init__(self, filas, motor=""):
        self.cursor_ = _Cursor(filas)
        self.motor = motor
        self.cerrada = False

    def cursor(self):
        return self.cursor_

    def getinfo(self, _cual):
        return self.motor

    def close(self):
        self.cerrada = True


def _conector(filas, motor="", **cfg):
    con = _Conexion(filas, motor)
    c = ConectorODBC({"perfil": "dsn", "dsn": "VW_MATRIZ", **cfg})
    c._abrir = lambda: con        # type: ignore[method-assign]
    return c, con


def test_lista_las_tablas_aunque_el_origen_no_tenga_esquema():
    c, con = _conector([_Fila(None, None, "CLIENTES"),
                        _Fila("", "", "VENTAS", "VIEW")])
    tablas = c.listar_tablas()
    assert [t.nombre for t in tablas] == ["CLIENTES", "VENTAS"]
    assert [t.esquema for t in tablas] == [None, None]
    assert tablas[1].es_vista is True
    # Sin destino no se filtra por catalogo ni por esquema: se piden todas.
    assert con.cursor_.pedido == {}
    assert con.cerrada


def test_cada_tabla_se_queda_con_el_esquema_que_declare_el_driver():
    c, _ = _conector([_Fila("ventas_2024", None, "PEDIDOS")])
    tablas = c.listar_tablas()
    assert tablas[0].esquema == "ventas_2024"


def test_al_listar_sin_filtro_se_quitan_los_catalogos_del_motor():
    c, _ = _conector([_Fila("mysql", None, "user"),
                      _Fila("information_schema", None, "TABLES"),
                      _Fila("bonn", None, "clientes")],
                     motor="MySQL")
    assert [t.nombre for t in c.listar_tablas()] == ["clientes"]


def test_con_base_indicada_se_sigue_filtrando_por_ella():
    c, con = _conector([_Fila("bonn", None, "clientes")],
                       motor="MySQL", database="bonn")
    tablas = c.listar_tablas()
    assert con.cursor_.pedido == {"catalog": "bonn"}
    assert tablas[0].esquema == "bonn"


def test_no_se_cuelan_las_tablas_de_sistema_del_driver():
    # Pervasive publica sus diccionarios como SYSTEM TABLE.
    c, _ = _conector([_Fila(None, None, "X$File", "SYSTEM TABLE"),
                      _Fila(None, None, "CLIENTES")])
    assert [t.nombre for t in c.listar_tablas()] == ["CLIENTES"]
