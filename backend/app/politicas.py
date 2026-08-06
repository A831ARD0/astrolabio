"""
Capa de politicas — seguridad a nivel de fila.

Por que existe desde la Fase 0 aunque su interfaz llegue en la Fase 6: TODA
consulta analitica pasa por aqui. Si este gancho no estuviera puesto desde el
principio, agregar seguridad por fila despues significaria reescribir el
compilador y auditar cada camino de consulta para ver si alguno se la salta.

Regla de oro: `resolver()` es el UNICO camino para ejecutar una consulta
analitica. No hay una via alterna "sin politicas". Si el usuario es
administrador, se resuelve a lista vacia — pero pasa por aqui igual.

La forma de una politica y su validacion viven en `semantic/politica.py`; aqui
solo se resuelve para un usuario concreto. La marca `{{ usuario.x }}` se importa
de alli en vez de reescribirse: es la frontera contra inyeccion y tiene que tener
una sola definicion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from semantic.engine import Modelo
from semantic.politica import MARCA as _MARCA
from semantic.politica import PoliticaInvalida

__all__ = ["CapaPoliticas", "ContextoUsuario", "Explicacion", "PoliticaInvalida",
           "PredicadoAplicado"]


@dataclass
class ContextoUsuario:
    """Lo que la capa de politicas necesita saber del usuario."""
    usuario_id: int | None
    email: str
    rol: str
    atributos: dict[str, str] = field(default_factory=dict)

    @property
    def es_administrador(self) -> bool:
        return self.rol == "administrador"


@dataclass
class PredicadoAplicado:
    """Un filtro obligatorio que el compilador debe inyectar."""
    entidad: str
    sql: str
    parametros: list
    politica: str


@dataclass
class Explicacion:
    """
    Por que este usuario ve lo que ve.

    Solo describe: no devuelve ni una fila de datos. Existe para el simulador de la
    Fase 6, porque un administrador nunca puede comprobar una politica mirando sus
    propias consultas — a el no le aplican.
    """
    aplicados: list[PredicadoAplicado]
    omitidos: list[dict]              # [{"nombre", "motivo"}]
    error: str | None = None          # si falla cerrado, el motivo


class CapaPoliticas:
    def __init__(self, modelo: Modelo, politicas_crudas: list[dict] | None = None):
        self.modelo = modelo
        self.politicas = politicas_crudas or []

    # ----------------------------------------------------------------- #
    # Resolucion
    # ----------------------------------------------------------------- #

    def resolver(self, ctx: ContextoUsuario) -> list[PredicadoAplicado]:
        """
        Traduce las politicas del modelo a predicados concretos para este usuario.
        Devuelve lista vacia si no aplica ninguna (p. ej. administrador).
        """
        if ctx.es_administrador:
            return []

        aplicados: list[PredicadoAplicado] = []
        for pol in self.politicas:
            aplicado, _ = self._una(pol, ctx)
            if aplicado is not None:
                aplicados.append(aplicado)
        return aplicados

    def explicar(self, ctx: ContextoUsuario) -> Explicacion:
        """
        Lo mismo que `resolver()`, pero contando el resultado en vez de reventar.

        Usa las mismas funciones: si explicara por otro camino, explicaria otra
        cosa distinta de la que se aplica, que es exactamente el fallo que un
        simulador tiene que no tener.
        """
        if ctx.es_administrador:
            return Explicacion(
                aplicados=[],
                omitidos=[{"nombre": str(p.get("nombre", "?")),
                           "motivo": "es administrador: las politicas no le aplican"}
                          for p in self.politicas],
            )

        aplicados: list[PredicadoAplicado] = []
        omitidos: list[dict] = []
        for pol in self.politicas:
            try:
                aplicado, motivo = self._una(pol, ctx)
            except PoliticaInvalida as e:
                # Falla cerrado: se corta aqui igual que en una consulta real, para
                # que el simulador muestre el mismo 403 y no una version optimista.
                return Explicacion(aplicados=aplicados, omitidos=omitidos,
                                   error=str(e))
            if aplicado is not None:
                aplicados.append(aplicado)
            else:
                omitidos.append({"nombre": str(pol.get("nombre", "?")),
                                 "motivo": motivo or "no aplica"})
        return Explicacion(aplicados=aplicados, omitidos=omitidos)

    # ----------------------------------------------------------------- #

    def _una(self, pol: dict, ctx: ContextoUsuario
             ) -> tuple[PredicadoAplicado | None, str | None]:
        """Resuelve una politica. Devuelve (predicado, None) o (None, motivo)."""
        nombre = pol.get("nombre", "?")
        roles = pol.get("aplica_a_roles") or []
        if roles and ctx.rol not in roles:
            return None, f"aplica a {', '.join(roles)}, y el rol es {ctx.rol}"

        entidad = pol["entidad"]
        if entidad not in self.modelo.entidades:
            raise PoliticaInvalida(
                f"La politica '{nombre}' apunta a la entidad "
                f"'{entidad}', que no existe en el modelo."
            )

        plantilla: str = pol["predicado"]
        faltantes = [c for c in _MARCA.findall(plantilla) if c not in ctx.atributos]
        if faltantes:
            # Falla cerrado: si falta el atributo, NO se entrega el dato.
            raise PoliticaInvalida(
                f"La politica '{nombre}' necesita el atributo "
                f"{faltantes} del usuario '{ctx.email}', que no esta "
                f"definido. No se entregan datos sin la regla aplicada."
            )

        parametros: list = []

        def _a_parametro(m: re.Match) -> str:
            parametros.append(ctx.atributos[m.group(1)])
            return "?"

        sql = _MARCA.sub(_a_parametro, plantilla)
        if "{{" in sql or "}}" in sql:
            raise PoliticaInvalida(
                f"La politica '{nombre}' tiene una sustitucion no "
                f"soportada. Solo se admite {{{{ usuario.<clave> }}}}."
            )

        return PredicadoAplicado(
            entidad=entidad, sql=sql, parametros=parametros, politica=nombre,
        ), None
