"""
Politicas de seguridad por fila: su forma, y su validacion antes de guardarlas.

Por que vive aqui y no en `app/politicas.py`: esta capa define QUE es una politica
valida y se usa al guardar el modelo; la de `app/` la RESUELVE para un usuario
concreto en tiempo de consulta. La marca de sustitucion (`{{ usuario.x }}`) es la
frontera contra inyeccion, y esta escrita **una sola vez**, aqui: dos copias de una
frontera de seguridad se separan tarde o temprano, y la que se olvida es la que se
usa.

Validar el predicado con el arbol sintactico y no con una lista de palabras
prohibidas es la misma decision que en las transformaciones: buscar "SELECT" en el
texto se esquiva con comentarios o con comillas raras. El arbol no.
"""

from __future__ import annotations

import re

import sqlglot
from pydantic import BaseModel, ConfigDict, Field
from sqlglot import exp

DIALECTO = "duckdb"

# Solo se admiten sustituciones de la forma {{ usuario.<clave> }}. Cualquier otra
# cosa entre llaves se rechaza.
MARCA = re.compile(r"\{\{\s*usuario\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Lo que un predicado no puede ser. Una politica es una condicion, no una consulta:
# una subconsulta dentro de una politica se ejecuta con los permisos de la propia
# politica y puede leer cualquier tabla, asi que se prohibe.
_PROHIBIDOS = (
    exp.Select, exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop,
    exp.Alter, exp.Command, exp.Subquery, exp.Union,
)

# Valor con el que se sustituye la marca para poder analizar el predicado sin
# conocer al usuario. Es un literal de texto, asi que `x = {{ usuario.y }}` y
# `x IN ({{ usuario.y }})` se analizan igual de bien.
_TESTIGO = "'__atributo__'"


class PoliticaInvalida(Exception):
    """El mensaje es para quien escribe la politica, no para el log."""


class PoliticaDef(BaseModel):
    # extra="allow" por lo mismo que en el resto de la definicion: lo que una
    # version futura agregue no se borra al guardar desde la interfaz.
    model_config = ConfigDict(extra="allow")

    nombre: str = Field(min_length=1, max_length=120)
    entidad: str = Field(min_length=1, max_length=120)
    predicado: str = Field(min_length=1)
    # Vacio significa "todos los roles menos administrador". Es lo mas restrictivo
    # de los dos valores por defecto posibles, y por eso es el que se toma.
    aplica_a_roles: list[str] = []
    descripcion: str | None = None


def atributos_requeridos(predicado: str) -> list[str]:
    """Las claves del usuario que el predicado necesita, en orden de aparicion."""
    vistos: list[str] = []
    for clave in MARCA.findall(predicado or ""):
        if clave not in vistos:
            vistos.append(clave)
    return vistos


def _arbol(predicado: str) -> exp.Expression:
    texto = MARCA.sub(_TESTIGO, predicado or "")
    if "{{" in texto or "}}" in texto:
        raise PoliticaInvalida(
            "Hay una sustitucion que no se reconoce. Solo se admite "
            "{{ usuario.clave }}.")
    try:
        arboles = sqlglot.parse(texto, read=DIALECTO)
    except Exception as e:
        raise PoliticaInvalida(f"No se entiende la condicion — {e}") from e
    if len(arboles) != 1 or arboles[0] is None:
        raise PoliticaInvalida("Se espera una sola condicion, no varias sentencias.")
    arbol = arboles[0]
    if isinstance(arbol, _PROHIBIDOS) or any(
        isinstance(n, _PROHIBIDOS) for n in arbol.walk()
    ):
        raise PoliticaInvalida(
            "Una politica es una condicion, no una consulta: aqui no van "
            "subconsultas ni sentencias completas.")
    if isinstance(arbol, (exp.Column, exp.Literal, exp.Star)):
        raise PoliticaInvalida(
            f"'{predicado}' no es una condicion. Hace falta una comparacion, "
            f"por ejemplo: region_id = {{{{ usuario.region_id }}}}")
    return arbol


def columnas_usadas(predicado: str) -> list[str]:
    """Las columnas que menciona el predicado. Valida el predicado de paso."""
    arbol = _arbol(predicado)
    vistas: list[str] = []
    for col in arbol.find_all(exp.Column):
        if col.name not in vistas:
            vistas.append(col.name)
    return vistas


def revisar_politica(pol: PoliticaDef, entidades: dict[str, set[str]]
                     ) -> tuple[list[str], list[str]]:
    """
    Devuelve (errores, avisos) de una politica contra las entidades del modelo.

    `entidades` es {nombre_entidad: {columnas}}.

    Un error impide guardar. Un aviso no: hay politicas raras que son legitimas, y
    convertir toda rareza en error obliga a la gente a rodear la herramienta.
    """
    errores: list[str] = []
    avisos: list[str] = []
    quien = f"La politica '{pol.nombre}'"

    if pol.entidad not in entidades:
        errores.append(f"{quien} apunta a la entidad '{pol.entidad}', "
                       f"que no existe en el modelo.")

    try:
        usadas = columnas_usadas(pol.predicado)
    except PoliticaInvalida as e:
        errores.append(f"{quien}: {e}")
        return errores, avisos

    if pol.entidad in entidades:
        campos = entidades[pol.entidad]
        # Una columna inexistente dentro de una politica no rompe solo esa
        # politica: rompe TODA consulta de los usuarios a los que aplica.
        faltantes = [c for c in usadas if c not in campos]
        if faltantes:
            errores.append(
                f"{quien} usa {faltantes} de '{pol.entidad}', que no son campos "
                f"de esa entidad.")

    if not atributos_requeridos(pol.predicado):
        avisos.append(
            f"{quien} no usa ningun atributo del usuario, asi que filtra igual "
            f"para todos. Si eso es lo que quieres, esta bien; si esperabas que "
            f"cada quien viera lo suyo, falta un {{{{ usuario.clave }}}}.")

    if not pol.aplica_a_roles:
        avisos.append(
            f"{quien} no limita roles, asi que aplica a todos menos a "
            f"administrador.")

    return errores, avisos


def revisar_politicas(politicas: list[dict], entidades: dict[str, set[str]]
                      ) -> tuple[list[str], list[str]]:
    """Todas las politicas de un modelo, mas los nombres repetidos."""
    errores: list[str] = []
    avisos: list[str] = []

    nombres = [str(p.get("nombre", "")) for p in politicas]
    for n in sorted({n for n in nombres if n and nombres.count(n) > 1}):
        errores.append(f"Hay mas de una politica llamada '{n}'.")

    for crudo in politicas:
        try:
            pol = PoliticaDef.model_validate(crudo)
        except Exception as e:
            errores.append(
                f"La politica {crudo.get('nombre') or crudo} esta incompleta: {e}")
            continue
        e_pol, a_pol = revisar_politica(pol, entidades)
        errores.extend(e_pol)
        avisos.extend(a_pol)

    return errores, avisos
