"""
Simulador de seguridad por fila: "que veria esta persona".

Por que hace falta y no es un lujo: las politicas NO aplican a un administrador.
Quien las escribe es exactamente quien no puede comprobarlas mirando sus propias
consultas. Sin un simulador, la unica forma de verificar una politica es pedirle a
alguien que entre y te cuente lo que ve — es decir, publicar primero y verificar
despues, que es al reves.

Dos reglas que dan forma a este modulo:

  1. Se simula por el MISMO camino que se ejecuta. La consulta simulada pasa por
     `ejecutar_consulta` con un contexto fabricado; no hay una version "de prueba"
     del compilador. Si la simulacion pasara por otro lado, comprobaria otra cosa.

  2. La comparacion es el producto. Un numero solo ("ve 58,544 filas") no dice
     nada; "ve 58,544 de 439,970" dice si la politica esta filtrando de verdad o
     si no esta haciendo nada.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analitico import conexion, ejecutar_consulta
from app.modelos_db import Rol, Usuario
from app.politicas import CapaPoliticas, ContextoUsuario, PoliticaInvalida
from semantic.engine import Consulta, Modelo, _calificar, _cita

# Tope de la muestra de valores visibles. Es una comprobacion, no un listado.
MUESTRA = 12


def contexto_de(usuario: Usuario) -> ContextoUsuario:
    return ContextoUsuario(
        usuario_id=usuario.id, email=usuario.email, rol=usuario.rol.value,
        atributos=usuario.dict_atributos,
    )


def contexto_ficticio(rol: str, atributos: dict[str, str]) -> ContextoUsuario:
    """
    Un usuario que no existe, para probar una politica antes de crear a nadie.

    Vale la pena: la secuencia natural es escribir la politica, comprobarla y
    despues dar de alta a la persona. Al reves obliga a crear cuentas para probar.
    """
    return ContextoUsuario(usuario_id=None, email=f"(ficticio: {rol})", rol=rol,
                           atributos=atributos)


@dataclass
class Comparacion:
    columnas: list[str]
    filas: list[dict]
    filas_admin: list[dict]
    ms: float


def _conteo(sql: str, parametros: list) -> int:
    return int(conexion().execute(sql, parametros).fetchone()[0])


def _campo_muestra(modelo: Modelo, entidad: str) -> str | None:
    """Un campo con el que la muestra se pueda leer: mejor un nombre que un id."""
    ent = modelo.entidades[entidad]
    texto = [c.nombre for c in ent.campos.values()
             if c.rol == "dimension" and c.tipo == "texto"]
    if texto:
        return texto[0]
    dims = [c.nombre for c in ent.campos.values() if c.rol == "dimension"]
    return dims[0] if dims else ent.clave_primaria


def _por_entidad(modelo: Modelo, aplicados: list) -> list[dict]:
    """
    Filas visibles vs totales en la tabla de cada politica.

    Se cuenta en la entidad de la politica y no al final de un join a proposito: es
    donde el predicado actua, y un conteo ahi no depende de por que camino se
    llegue. Lo que la persona ve en un tablero es la consecuencia de esto.
    """
    salida = []
    for p in aplicados:
        ent = modelo.entidades[p.entidad]
        tabla = _cita(ent.tabla)
        campos = set(ent.campos)
        donde = _calificar(p.sql, "t0", campos)

        total = _conteo(f"SELECT COUNT(*) FROM {tabla} AS t0", [])
        visibles = _conteo(
            f"SELECT COUNT(*) FROM {tabla} AS t0 WHERE {donde}", list(p.parametros))

        muestra: list = []
        campo = _campo_muestra(modelo, p.entidad)
        if campo:
            filas = conexion().execute(
                f"SELECT DISTINCT t0.{_cita(campo)} FROM {tabla} AS t0 "
                f"WHERE {donde} ORDER BY 1 LIMIT {MUESTRA + 1}",
                list(p.parametros)).fetchall()
            muestra = [f[0] for f in filas[:MUESTRA]]

        salida.append({
            "politica": p.politica,
            "entidad": p.entidad,
            "predicado": p.sql,
            "valores": list(p.parametros),
            "filas_totales": total,
            "filas_visibles": visibles,
            "campo_muestra": campo,
            "muestra": muestra,
            "hay_mas": campo is not None and len(muestra) == MUESTRA,
        })
    return salida


def simular(modelo: Modelo, ctx: ContextoUsuario,
            consulta: Consulta | None = None) -> dict:
    """
    Que veria `ctx`: politicas resueltas, filas visibles por entidad y, si se pide,
    una consulta ejecutada con y sin politicas para poder comparar.
    """
    capa = CapaPoliticas(modelo, modelo.politicas)
    expl = capa.explicar(ctx)

    salida: dict = {
        "rol": ctx.rol,
        "email": ctx.email,
        "atributos": ctx.atributos,
        "es_administrador": ctx.es_administrador,
        "aplicadas": [
            {"politica": p.politica, "entidad": p.entidad, "predicado": p.sql,
             "valores": list(p.parametros)}
            for p in expl.aplicados
        ],
        "omitidas": expl.omitidos,
        "error": expl.error,
        "entidades": [],
        "consulta": None,
    }

    if expl.error:
        # Falla cerrado: no se cuenta nada. Es la respuesta correcta y ademas es la
        # que esa persona recibiria de verdad al abrir un tablero.
        return salida

    salida["entidades"] = _por_entidad(modelo, expl.aplicados)

    if consulta is not None:
        # El mismo `ejecutar_consulta` de siempre. El contexto de administrador es
        # el "sin politicas" — no se salta la capa, la atraviesa sin predicados.
        admin = ContextoUsuario(usuario_id=None, email="(sin politicas)",
                                rol=Rol.administrador.value, atributos={})
        try:
            res = ejecutar_consulta(modelo, consulta, ctx)
        except PoliticaInvalida as e:
            salida["error"] = str(e)
            return salida
        sin = ejecutar_consulta(modelo, consulta, admin)
        salida["consulta"] = {
            "columnas": res.columnas,
            "filas": res.filas,
            "filas_sin_politicas": sin.filas,
            "cuenta": len(res.filas),
            "cuenta_sin_politicas": len(sin.filas),
            "ms": res.ms,
            "sql": res.sql,
        }
    return salida
