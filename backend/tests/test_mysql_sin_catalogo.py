"""
Una tabla que el catálogo de MySQL no describe, y que sí se puede leer.

Salió de un caso real: el selector listaba `FACTURAS_PR`, en un cliente SQL se
consultaba sin problema, y Astrolabio contestaba «La tabla 'ventas_origen.FACTURAS_PR'
no existe». Mandar a alguien a buscar un error de escritura que no existe cuesta más
que el fallo.

La causa es que `information_schema.columns` vacío **no significa que la tabla no
exista**: esa vista filtra por privilegios columna a columna, y además se queda vacía
para una vista que MySQL no puede expandir. En los dos casos la tabla está ahí y se
puede leer, así que se le pregunta al servidor por la vía que no miente: un `LIMIT 0`
y la descripción del cursor.

Se prueba con un cursor de mentira y no contra un MySQL de verdad a propósito:
reproducir el caso pediría crear un usuario con privilegios por columna en la máquina
de quien corra las pruebas. Lo que hay que fijar es la decisión —qué se concluye de
cada combinación de respuestas—, y eso es exactamente lo que se ve aquí.
"""

import pytest

from app.conectores.base import ErrorConector
from app.conectores.mysql import ConectorMySQL


class CursorFalso:
    """
    Contesta a las tres consultas de `describir_tabla` según lo que se le pida.

    `columnas` es lo que devuelve `information_schema.columns`; `en_tablas` si hay
    fila en `information_schema.tables`; `descripcion` lo que daría el cursor tras un
    `SELECT * ... LIMIT 0`, o None para que ese SELECT falle.
    """

    def __init__(self, columnas, en_tablas, descripcion, tipo="BASE TABLE"):
        self._columnas = columnas
        self._en_tablas = en_tablas
        self._descripcion = descripcion
        self._tipo = tipo
        self.description = None
        self._ultima = None
        self.ejecutadas: list[str] = []

    def execute(self, sql, params=None):
        self.ejecutadas.append(sql)
        plano = " ".join(sql.split()).lower()
        if "information_schema.columns" in plano:
            self._ultima = list(self._columnas)
        elif "information_schema.tables" in plano:
            self._ultima = [(self._tipo,)] if self._en_tablas else []
        elif "limit 0" in plano:
            if self._descripcion is None:
                raise RuntimeError("SELECT command denied to user")
            self.description = self._descripcion
            self._ultima = []
        elif "count(*)" in plano:
            self._ultima = [(7,)]
        else:
            self._ultima = []

    def fetchall(self):
        return self._ultima or []

    def fetchone(self):
        return (self._ultima or [None])[0]


class ConexionFalsa:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def conector(cursor) -> ConectorMySQL:
    c = ConectorMySQL({"host": "x", "user": "y", "database": "ventas_origen"})
    c._pymysql = lambda con_base=True: ConexionFalsa(cursor)   # type: ignore[method-assign]
    return c


# --------------------------------------------------------------------------- #

def test_el_catalogo_manda_cuando_contesta():
    """Con columnas en el catálogo no se toca el camino de emergencia."""
    cur = CursorFalso(
        columnas=[("IDV", "int(11)", "NO", "PRI"),
                  ("BASTIDOR", "varchar(20)", "YES", "")],
        en_tablas=True, descripcion=None)
    t = conector(cur).describir_tabla("FACTURAS_PR", "ventas_origen")

    assert [c.nombre for c in t.columnas] == ["IDV", "BASTIDOR"]
    assert t.columnas[0].es_clave, "se perdió la clave primaria del catálogo"
    assert not any("limit 0" in s.lower() for s in cur.ejecutadas)


def test_sin_columnas_pero_legible_se_lee_del_cursor():
    """
    El caso que fallaba. La tabla existe, el catálogo no da sus columnas, y leerla
    funciona: entonces se trae.
    """
    cur = CursorFalso(
        columnas=[], en_tablas=True,
        descripcion=[("IDV", 3, None, None, None, None, False),
                     ("BASTIDOR", 253, None, None, None, None, True)])
    t = conector(cur).describir_tabla("FACTURAS_PR", "ventas_origen")

    assert [c.nombre for c in t.columnas] == ["IDV", "BASTIDOR"]
    assert t.filas_estimadas == 7
    # Sin clave primaria: la carga será completa, que es lo correcto con una tabla
    # de la que no se puede saber más. Inventarse una clave sería peor.
    assert not any(c.es_clave for c in t.columnas)
    assert t.columnas[1].nulable is True


def test_lo_que_de_verdad_no_esta_lo_dice_sin_culpar_al_nombre():
    """
    Sin fila en `information_schema.tables` sí se puede afirmar que no está — y hay
    que nombrar la otra causa posible, que es la frecuente: sin permiso de lectura,
    para Astrolabio no existe.
    """
    cur = CursorFalso(columnas=[], en_tablas=False, descripcion=None)
    with pytest.raises(ErrorConector) as e:
        conector(cur).describir_tabla("NO_ESTA", "ventas_origen")

    assert "permiso" in str(e.value)
    assert "esquema" in str(e.value)


def test_una_vista_ilegible_explica_por_que():
    """
    Existe, es una vista, y no se puede leer. «No existe» sería falso; el mensaje
    tiene que decir qué pasó para que se pueda arreglar.
    """
    cur = CursorFalso(columnas=[], en_tablas=True, descripcion=None, tipo="VIEW")
    with pytest.raises(ErrorConector) as e:
        conector(cur).describir_tabla("VW_ROTA", "ventas_origen")

    mensaje = str(e.value)
    assert "no existe" not in mensaje
    assert "definidor" in mensaje or "cambió de nombre" in mensaje
    assert "SELECT command denied" in mensaje, "se perdió lo que dijo el servidor"
