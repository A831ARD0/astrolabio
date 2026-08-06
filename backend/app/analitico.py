"""
Acceso al motor analitico (DuckDB) y el UNICO camino para ejecutar consultas.

Todo lo que quiera leer datos pasa por `ejecutar_consulta`. No existe una via
alterna que se salte la capa de politicas: es lo que hace verificable que la
seguridad por fila se aplica siempre.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import duckdb

from app.config import config
from app.politicas import CapaPoliticas, ContextoUsuario
from semantic.engine import Compilador, Consulta, Modelo, MotorAsociativo

_local = threading.local()


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


@dataclass
class Resultado:
    columnas: list[str]
    filas: list[dict[str, Any]]
    sql: str
    ms: float
    politicas_aplicadas: list[str]


def ejecutar_consulta(modelo: Modelo, consulta: Consulta,
                      ctx: ContextoUsuario) -> Resultado:
    """Compila y ejecuta. Siempre pasa por la capa de politicas."""
    capa = CapaPoliticas(modelo, modelo.politicas)
    predicados = capa.resolver(ctx)               # <- el gancho, sin excepcion

    compilada = Compilador(modelo).compilar(consulta, predicados)

    t0 = time.perf_counter()
    cur = conexion().execute(compilada.sql, compilada.parametros)
    columnas = [d[0] for d in cur.description]
    filas = [dict(zip(columnas, f)) for f in cur.fetchall()]
    ms = (time.perf_counter() - t0) * 1000

    return Resultado(
        columnas=columnas, filas=filas, sql=compilada.sql, ms=round(ms, 1),
        politicas_aplicadas=[p.politica for p in predicados],
    )


def estados_asociativos(modelo: Modelo, entidad: str, campo: str,
                        selecciones: dict[str, list], ctx: ContextoUsuario
                        ) -> dict[str, list]:
    """
    Estados asociativos. Tambien pasa por la capa de politicas: si un usuario no
    puede ver una sucursal, esa sucursal no debe aparecer ni como 'excluida' en
    un panel de filtros — su existencia misma es informacion.
    """
    capa = CapaPoliticas(modelo, modelo.politicas)
    predicados = capa.resolver(ctx)

    motor = MotorAsociativo(modelo, conexion())
    estados = motor.estados(entidad, campo, selecciones)

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
