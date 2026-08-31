"""
Acceso al motor analitico (DuckDB) y el UNICO camino para ejecutar consultas.

Todo lo que quiera leer datos pasa por `ejecutar_consulta`. No existe una via
alterna que se salte la capa de politicas: es lo que hace verificable que la
seguridad por fila se aplica siempre.

Aqui viven tambien las **vistas de Parquet**: una carga o el resultado de una
transformacion es un directorio de archivos, no una tabla del motor, y el modelo
semantico solo sabe nombrar tablas. `registrar_vistas` cierra ese hueco creando
una vista temporal por nombre, en la conexion de consultas, apuntando al Parquet.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from pathlib import Path
from dataclasses import dataclass, replace
from typing import Any

import duckdb

from app.config import config
from app.politicas import CapaPoliticas, ContextoUsuario
from semantic.engine import (
    COL_MES_USADO, Compilador, Consulta, Modelo, MotorAsociativo,
)

_local = threading.local()


def asegurar_base() -> bool:
    """
    Crea el archivo del motor analitico si no existe. Devuelve si hizo falta.

    Hace falta porque `duckdb_solo_lectura` es True por omision —y debe serlo: la
    API no escribe en el motor, escribe Parquet—, y **en solo lectura DuckDB no
    crea el archivo que le falta**. En una instalacion nueva que nunca sembro los
    datos de demostracion, ese archivo no existe nunca, y entonces cualquier
    lectura falla con:

        IO Error: Cannot open database "...analitico.duckdb" in read-only mode:
        database does not exist

    Eso dejaba sin tablas del motor al ETL, a los tableros y al modelo, en una
    instalacion que por lo demas estaba bien. Una base vacia es un archivo de unos
    pocos kilobytes y `duckdb_tables()` sobre ella devuelve cero filas, que es la
    verdad: todavia no hay tablas.
    """
    ruta = Path(config().ruta_duckdb)
    if ruta.exists():
        return False
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Abrir para escribir y cerrar: con eso queda creada y vacia.
    duckdb.connect(str(ruta)).close()
    return True


def conexion() -> duckdb.DuckDBPyConnection:
    """
    Una conexion DuckDB por hilo. DuckDB no es seguro para compartir una misma
    conexion entre hilos, y FastAPI atiende en varios.
    """
    con = getattr(_local, "con", None)
    if con is None:
        con = duckdb.connect(config().ruta_duckdb,
                             read_only=config().duckdb_solo_lectura)
        _local.con = con
    return con


# Cuantas veces se han reescrito los datos de cada nombre. Es un contador global
# —compartido por todos los hilos— frente al recuerdo POR HILO de que ya se creo
# la vista. Sin el, cada hilo daba por buena para siempre la vista que creo la
# primera vez, y cuando una transformacion volvia a correr cambiando el tipo de
# una columna la vista seguia declarando el tipo viejo. DuckDB no lo deja pasar:
# «Contents of view were altered: types don't match! Expected [VARCHAR], but found
# [DATE]». Un `cast(... as date)` recien puesto tumbaba el catalogo con un 500
# hasta reiniciar el proceso, y hasta entonces el modelo seguia diciendo «texto».
_sellos: dict[str, int] = {}


def invalidar_vistas(*nombres: str) -> None:
    """
    Avisar de que un nombre tiene datos nuevos en disco.

    Lo llama quien escribe Parquet. No toca ninguna vista: solo sube el sello, y
    cada hilo vuelve a crear la suya la proxima vez que la use. Tocar las vistas
    de otro hilo desde aqui no se puede — cada conexion DuckDB es suya.
    """
    for n in nombres:
        _sellos[n] = _sellos.get(n, 0) + 1


def tablas_del_motor(con: duckdb.DuckDBPyConnection | None = None) -> set[str]:
    """Las tablas que existen de verdad dentro del archivo del motor."""
    con = con or conexion()
    return {n for (n,) in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE NOT internal").fetchall()}


def registrar_vistas(nombres: Iterable[str]) -> list[str]:
    """
    Deja utilizables como tabla los datasets y resultados que viven en Parquet.

    Sin esto, el modelo semantico solo alcanza lo que hay dentro de
    `analitico.duckdb` —los datos de demostracion— y todo lo que el usuario carga
    y transforma queda invisible para el: la transformacion corre, escribe su
    Parquet, y el lienzo del modelo no la encuentra.

    Tres decisiones:

    - **Vista temporal**, no una tabla dentro del motor. El motor se abre en solo
      lectura a proposito (ver `materializar`), y una vista temporal vive en el
      catalogo temporal de la conexion, asi que no lo contradice: el archivo no se
      toca. De paso, el glob se resuelve en cada consulta, asi que una carga nueva
      se ve sin volver a registrar nada.
    - **Una tabla real siempre gana** sobre un Parquet del mismo nombre. Es la
      unica regla que hace predecible una colision, y es la que menos sorprende:
      lo que ya consultaban los tableros sigue significando lo mismo.
    - **Solo se recuerda lo que se logro.** Un nombre sin datos todavia no se
      apunta como hecho, para que se reintente cuando su primera carga termine —
      la conexion vive lo que vive el hilo, y eso es mucho mas que una carga.

    Devuelve los nombres que quedaron registrados en esta llamada.
    """
    from app.materializar import ErrorTransformacion, ruta_datos_dataset

    con = conexion()
    # nombre -> sello con el que se creo la vista de ESTE hilo. Se rehace cuando
    # el sello global sube, que es como se entera de que los datos cambiaron.
    hechas: dict[str, int] = getattr(_local, "vistas", None)
    if hechas is None:
        hechas = _local.vistas = {}

    faltan = [n for n in dict.fromkeys(nombres)
              if hechas.get(n) != _sellos.get(n, 0)]
    if not faltan:
        return []

    reales = tablas_del_motor(con)
    nuevas = []
    for nombre in faltan:
        if nombre in reales:
            # No se le pone una vista encima: una tabla real siempre gana.
            hechas[nombre] = _sellos.get(nombre, 0)
            continue
        try:
            ruta = ruta_datos_dataset(nombre)
        except ErrorTransformacion:
            continue                    # no es un nombre de dataset; que falle al consultar
        if ruta is None:
            continue                    # todavia no tiene datos: se reintenta luego
        # La ruta no se puede pasar como parametro: una vista no admite parametros
        # ligados, se guarda su texto. El nombre ya viene validado por
        # `ruta_datos_dataset` y las comillas se escapan igual.
        con.execute(f'CREATE OR REPLACE TEMP VIEW {_cita_ident(nombre)} AS '
                    f"SELECT * FROM read_parquet('{ruta.replace(chr(39), chr(39) * 2)}', "
                    f'hive_partitioning=true)')
        hechas[nombre] = _sellos.get(nombre, 0)
        nuevas.append(nombre)
    return nuevas


def _cita_ident(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


def preparar(modelo: Modelo) -> None:
    """Registra las vistas que necesitan las entidades de este modelo."""
    registrar_vistas(e.tabla for e in modelo.entidades.values())


@dataclass
class Resultado:
    columnas: list[str]
    filas: list[dict[str, Any]]
    sql: str
    ms: float
    politicas_aplicadas: list[str]
    #: Si el limite dejo filas fuera. Una tabla recortada que no dice que lo esta
    #: es la peor clase de error: se lee como completa, se suma y se firma.
    truncado: bool = False
    #: Con que mes se calcularon las metricas de tiempo, cuando el mes no estaba en
    #: el desglose y lo puso el contexto. `None` si no habia ninguna metrica de
    #: tiempo, o si los meses venian en el propio desglose y cada fila es el suyo.
    mes_usado: Any = None
    #: Cuando no hubo ni una fila, por que. Vacio se ve igual venga de donde venga
    #: —tabla sin cargar, union que no casa, politica, filtros— y cada causa se
    #: arregla en otro sitio: sin decirlo, «Sin datos» manda a buscar a ciegas.
    vacio_porque: str | None = None


def ejecutar_consulta(modelo: Modelo, consulta: Consulta,
                      ctx: ContextoUsuario) -> Resultado:
    """
    Compila y ejecuta. Siempre pasa por la capa de politicas.

    Se pide **una fila mas** que el limite para poder responder si sobraba. Es la
    unica manera exacta de saberlo: contando las que vuelven no se distingue
    "justo caben mil" de "hay diez mil y se cortaron en mil", y esas dos cosas se
    parecen tanto en pantalla que sin distinguirlas nadie mira el numero dos
    veces. La fila de sobra se descarta; nunca sale de aqui.
    """
    preparar(modelo)
    capa = CapaPoliticas(modelo, modelo.politicas)
    predicados = capa.resolver(ctx)               # <- el gancho, sin excepcion

    tope = consulta.limite
    compilada = Compilador(modelo).compilar(
        replace(consulta, limite=tope + 1), predicados)

    t0 = time.perf_counter()
    cur = conexion().execute(compilada.sql, compilada.parametros)
    columnas = [d[0] for d in cur.description]
    filas = [dict(zip(columnas, f)) for f in cur.fetchall()]
    ms = (time.perf_counter() - t0) * 1000

    truncado = len(filas) > tope
    if truncado:
        del filas[tope:]

    # El mes con el que se resolvieron las ventanas de tiempo no es una columna que
    # nadie haya pedido: se saca de las filas y se cuenta aparte. Se queda dentro
    # seria una columna de mas en la tabla y en el Excel.
    mes_usado = None
    if COL_MES_USADO in columnas:
        columnas = [c for c in columnas if c != COL_MES_USADO]
        for f in filas:
            mes_usado = f.pop(COL_MES_USADO, None)

    return Resultado(
        columnas=columnas, filas=filas, sql=compilada.sql, ms=round(ms, 1),
        politicas_aplicadas=[p.politica for p in predicados],
        truncado=truncado, mes_usado=mes_usado,
        vacio_porque=(_por_que_vacio(modelo, consulta, predicados)
                      if not filas else None),
    )


def _por_que_vacio(modelo: Modelo, consulta: Consulta, predicados: list) -> str | None:
    """
    Por que la consulta no devolvio ni una fila.

    Vacio se ve igual venga de donde venga, y viene de sitios que se arreglan en
    sitios distintos: la tabla sin cargar, la union que no encuentra pareja, una
    politica que tapa todo, o los filtros. «Sin datos» a secas manda a buscar a
    ciegas por los cuatro.

    Cuesta tres conteos por hecho, y solo se paga cuando ya no hubo filas — que es
    justo cuando la consulta no costo nada.
    """
    try:
        sondas = Compilador(modelo).sondas_de_vacio(consulta, predicados)
    except Exception:                      # noqa: BLE001
        # Un diagnostico que falla no puede tapar el resultado: la consulta ya
        # salio bien y lo que se estaba armando era una explicacion de cortesia.
        return None

    con = conexion()

    def cuenta(par) -> int:
        sql, params = par
        return int(con.execute(sql, params).fetchone()[0])

    for s in sondas:
        try:
            if cuenta(s["sola"]) == 0:
                return (f"«{s['entidad']}» no tiene ni una fila: la tabla esta vacia. "
                        f"Falta cargarla.")
            if cuenta(s["unida"]) == 0:
                por = (" por " + ", ".join(s["uniones"])) if s["uniones"] else ""
                return (f"«{s['entidad']}» tiene filas, pero ninguna llega al "
                        f"desglose{por}: la union no encuentra pareja. Suele ser el "
                        f"tipo o el formato del codigo —texto con ceros delante "
                        f"contra un entero— y se ve mirando unas filas de cada "
                        f"tabla.")
            if cuenta(s["permitida"]) == 0:
                return (f"«{s['entidad']}» tiene filas y las uniones casan, pero las "
                        f"politicas de seguridad no te dejan ver ninguna.")
        except Exception:                  # noqa: BLE001
            return None

    return ("Los filtros puestos no dejan ninguna fila." if consulta.filtros
            else None)


def ejecutar_muestra(modelo: Modelo, entidad: str, limite: int,
                     ctx: ContextoUsuario, filtros: list[dict] | None = None,
                     orden: str | None = None,
                     descendente: bool = False) -> Resultado:
    """
    Unas filas de una entidad, sin agregar. Mismo camino que `ejecutar_consulta`:
    pasa por la capa de politicas antes de tocar el motor.

    `filtros` y `orden` los aplica el MOTOR, no la pantalla, porque el limite corta
    despues: sin ellos, «las ultimas facturas» de una tabla de cien mil filas no se
    puede pedir.
    """
    preparar(modelo)
    capa = CapaPoliticas(modelo, modelo.politicas)
    predicados = capa.resolver(ctx)

    # Una fila mas que el limite, igual que en `ejecutar_consulta` y por lo mismo:
    # contando las que vuelven no se distingue «justo caben cincuenta» de «hay
    # cinco mil y se cortaron en cincuenta». Se descarta al devolver.
    compilada = Compilador(modelo).compilar_muestra(
        entidad, limite + 1, predicados, filtros, orden, descendente)

    t0 = time.perf_counter()
    cur = conexion().execute(compilada.sql, compilada.parametros)
    columnas = [d[0] for d in cur.description]
    filas = [dict(zip(columnas, f)) for f in cur.fetchall()]
    ms = (time.perf_counter() - t0) * 1000

    truncado = len(filas) > limite
    if truncado:
        del filas[limite:]

    return Resultado(
        columnas=columnas, filas=filas, sql=compilada.sql, ms=round(ms, 1),
        politicas_aplicadas=[p.politica for p in predicados],
        truncado=truncado,
    )


def comprobar_grano(modelo: Modelo, entidad: str) -> dict:
    """
    Si el grano declarado de una entidad se cumple en los datos.

    Devuelve cuantas filas hay, cuantas combinaciones distintas del grano, y por
    tanto cuantas sobran. Que sobre una sola ya significa que cualquier metrica de
    esa tabla cuenta algo dos veces.
    """
    preparar(modelo)
    compilada = Compilador(modelo).compilar_grano(entidad)
    filas, combinaciones = conexion().execute(compilada.sql).fetchone()
    filas, combinaciones = int(filas or 0), int(combinaciones or 0)
    return {
        "entidad": entidad,
        "grano": list(modelo.entidades[entidad].grano),
        "filas": filas,
        "combinaciones": combinaciones,
        "repetidas": filas - combinaciones,
        "cumple": filas == combinaciones,
        "sql": compilada.sql,
    }


def estados_asociativos(modelo: Modelo, entidad: str, campo: str,
                        selecciones: dict[str, list], ctx: ContextoUsuario,
                        ordenar_por: str | None = None) -> dict[str, list]:
    """
    Estados asociativos. Tambien pasa por la capa de politicas: si un usuario no
    puede ver una sucursal, esa sucursal no debe aparecer ni como 'excluida' en
    un panel de filtros — su existencia misma es informacion.
    """
    preparar(modelo)
    capa = CapaPoliticas(modelo, modelo.politicas)
    predicados = capa.resolver(ctx)

    motor = MotorAsociativo(modelo, conexion())
    estados = motor.estados(entidad, campo, selecciones, ordenar_por)

    if predicados:
        visibles = _valores_visibles(modelo, entidad, campo, predicados)
        estados = {
            k: [v for v in vs if v in visibles] for k, vs in estados.items()
        }
    return estados


def _valores_visibles(modelo: Modelo, entidad: str, campo: str,
                      predicados: list) -> set:
    """Valores del campo que el usuario tiene permitido ver."""
    from semantic.engine import _calificar, _cita

    comp = Compilador(modelo)
    alias_base = "t0"
    sql = (f"SELECT DISTINCT {alias_base}.{_cita(campo)} "
           f"FROM {_cita(modelo.entidades[entidad].tabla)} AS {alias_base}")
    where, params = [], []

    for i, p in enumerate(predicados):
        if p.entidad == entidad:
            campos = set(modelo.entidades[entidad].campos)
            where.append(_calificar(p.sql, alias_base, campos))
            params.extend(p.parametros)
        else:
            rutas = modelo.rutas_minimas(entidad, p.entidad, atravesar_hechos=True)
            if not rutas:
                continue
            ruta = rutas[0]
            alias = {e: f"p{i}_{j}" for j, e in enumerate(ruta)}
            alias[entidad] = alias_base
            sql += "\n" + comp._sql_join(ruta, alias)
            campos = set(modelo.entidades[p.entidad].campos)
            where.append(_calificar(p.sql, alias[p.entidad], campos))
            params.extend(p.parametros)

    if where:
        sql += "\nWHERE " + " AND ".join(where)
    return {f[0] for f in conexion().execute(sql, params).fetchall()}
