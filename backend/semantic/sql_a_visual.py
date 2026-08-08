"""
De SQL a pasos visuales.

Es el camino de vuelta del compilador: se lee una consulta escrita a mano y se
intenta reconstruir la lista de pasos, para poder seguir editándola en la interfaz.

**La regla que ordena este archivo: no adivinar.** Cuando algo de la consulta no se
puede representar como paso —una ventana, un HAVING, una subconsulta correlacionada—
se anota en `no_representable` y se marca `convertible=False`. Una conversión
aproximada es peor que ninguna: el usuario creería que ya está, seguiría editando
sobre unos pasos que dicen otra cosa, y la cifra cambiaría sin que nadie tocara
nada.

Lo que sí se reconoce cubre la forma de la gran mayoría de consultas de informes:

    SELECT ... FROM t [JOIN ...] [WHERE ...] [GROUP BY ...] [ORDER BY ...] [LIMIT n]
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from semantic.transformacion import (
    AGREGADOS, Agregado, Condicion, DIALECTO, ErrorTransformacion, Origen, Paso,
    PasoAgrupar, PasoColumnas, PasoDerivar, PasoDistintos, PasoFiltrar,
    PasoLimitar, PasoOrdenar, PasoRenombrar, PasoUnir,
)

# SQL -> nombre del operador visual. Solo los que el compilador sabe volver a
# generar: si no puede ir y volver, no se ofrece.
_OPERADORES = {
    exp.EQ: "=", exp.NEQ: "!=", exp.GT: ">", exp.GTE: ">=",
    exp.LT: "<", exp.LTE: "<=",
}
_AGREGADOS_SQL = {
    "SUM": "suma", "AVG": "promedio", "MIN": "minimo", "MAX": "maximo",
    "COUNT": "cuenta",
}
_TIPOS_JOIN = {
    "": "interna", "INNER": "interna", "LEFT": "izquierda",
    "RIGHT": "derecha", "FULL": "completa",
}


def _arg(nodo: exp.Expression, clave: str):
    """
    Lee una clave del AST tolerando el nombre que use la versión de SQLGlot.

    En SQLGlot 30 el FROM pasó de la clave 'from' a 'from_'. Fijar solo una hace
    que la conversión falle en silencio con un "la consulta no tiene FROM" sobre
    una consulta que sí lo tiene.
    """
    if clave in nodo.args:
        return nodo.args.get(clave)
    return nodo.args.get(clave + "_")


@dataclass
class Conversion:
    origenes: list[Origen] = field(default_factory=list)
    pasos: list[Paso] = field(default_factory=list)
    no_representable: list[str] = field(default_factory=list)

    @property
    def convertible(self) -> bool:
        return not self.no_representable and bool(self.origenes)


def desde_sql(sql: str, conocidos: dict[str, str] | None = None) -> Conversion:
    """
    `conocidos` mapea el nombre de cada origen que EXISTE a su tipo: `tabla` para
    las del motor analitico, `dataset` para lo traido a Parquet —y para el
    resultado de otra transformacion—, `tabla_en_conexiones` para una tabla que
    llegó de varias conexiones a la vez.

    Sin ese mapa no se puede saber de donde sacar `FROM cat_conexiones`, y lo que
    se hacia era suponer que toda tabla nombrada era del motor analitico. Cuando no
    lo era, la consulta fallaba con un «Catalog Error: Table with name ... does not
    exist» de DuckDB que culpaba a la tabla y no explicaba nada.

    Lo construye la capa que tiene acceso a la base; aqui no se sabe de discos.
    """
    texto = (sql or "").strip().rstrip(";")
    if not texto:
        raise ErrorTransformacion("No hay ninguna consulta que convertir.")
    try:
        arboles = sqlglot.parse(texto, read=DIALECTO)
    except Exception as e:
        raise ErrorTransformacion(f"El SQL no se entiende: {e}") from e
    if len(arboles) != 1 or arboles[0] is None:
        raise ErrorTransformacion("Se espera una sola consulta.")

    arbol = arboles[0]
    c = Conversion()

    if isinstance(arbol, exp.Union):
        c.no_representable.append(
            "La consulta combina varios SELECT con UNION. El paso 'apilar' hace eso, "
            "pero reconstruirlo desde el SQL requiere que las partes sean simples; "
            "revísalo a mano.")
        return c
    if not isinstance(arbol, exp.Select):
        raise ErrorTransformacion(
            "Solo se puede convertir una consulta SELECT.")
    if _arg(arbol, "with"):
        c.no_representable.append(
            "La consulta usa CTEs (WITH). Los pasos visuales son la forma visual de "
            "un WITH, así que convertirla sería rehacerla: mejor a mano.")
        return c

    # ---- FROM y JOINs -> orígenes -------------------------------------------
    desde = _arg(arbol, "from")
    if desde is None:
        raise ErrorTransformacion("La consulta no tiene FROM.")
    principal = _origen_de(desde.this, c, conocidos)
    if principal is None:
        return c
    c.origenes.append(principal)

    joins = _arg(arbol, "joins") or []
    pasos_join: list[Paso] = []
    for j in joins:
        origen = _origen_de(j.this, c, conocidos)
        if origen is None:
            return c
        c.origenes.append(origen)
        paso = _paso_join(j, principal.nombre, origen.nombre, c)
        if paso is None:
            return c
        pasos_join.append(paso)

    # ---- WHERE -> filtrar ----------------------------------------------------
    donde = _arg(arbol, "where")
    paso_filtrar = _paso_filtrar(donde.this, c) if donde else None

    if _arg(arbol, "having"):
        c.no_representable.append(
            "La consulta usa HAVING (filtrar después de agrupar). Todavía no hay un "
            "paso para eso; se puede lograr agrupando y filtrando después.")
    if _arg(arbol, "qualify") or list(arbol.find_all(exp.Window)):
        c.no_representable.append(
            "La consulta usa funciones de ventana (OVER). No hay paso visual "
            "equivalente; conviene dejarla en modo SQL.")
    if list(arbol.find_all(exp.Subquery)):
        c.no_representable.append(
            "La consulta tiene subconsultas. Se pueden expresar como varias "
            "transformaciones encadenadas, pero no como pasos de esta.")

    # ---- SELECT -> columnas / renombrar / derivar / agrupar ------------------
    grupo = _arg(arbol, "group")
    if grupo:
        paso_agrupar = _paso_agrupar(arbol, grupo, c)
        pasos_finales: list[Paso] = [paso_agrupar] if paso_agrupar else []
    else:
        pasos_finales = _pasos_seleccion(arbol, c)

    if _arg(arbol, "distinct"):
        pasos_finales.append(PasoDistintos())

    # ---- ORDER BY y LIMIT ----------------------------------------------------
    orden = _arg(arbol, "order")
    if orden:
        columnas, descendente, mezclado = [], False, False
        for i, o in enumerate(orden.expressions):
            if not isinstance(o.this, exp.Column):
                c.no_representable.append(
                    "El ORDER BY ordena por una expresión, no por una columna. El "
                    "paso 'ordenar' solo admite columnas.")
                return c
            columnas.append(o.this.name)
            desc = bool(_arg(o, "desc"))
            if i == 0:
                descendente = desc
            elif desc != descendente:
                mezclado = True
        if mezclado:
            c.no_representable.append(
                "El ORDER BY mezcla ascendente y descendente. El paso 'ordenar' usa "
                "una sola dirección para todas las columnas.")
            return c
        pasos_finales.append(PasoOrdenar(por=columnas, descendente=descendente))

    limite = _arg(arbol, "limit")
    if limite is not None:
        try:
            pasos_finales.append(PasoLimitar(n=int(limite.expression.name)))
        except Exception:
            c.no_representable.append("El LIMIT no es un número fijo.")
            return c

    # El orden importa y no es negociable: en SQL el WHERE se aplica DESPUÉS de
    # los joins. Poner el filtro antes cambia el resultado de un LEFT JOIN —las
    # filas sin pareja se comportan distinto— y además el filtro podría
    # referirse a una columna que en ese punto todavía no existe. Adelantar el
    # filtro es una optimización, y de eso ya se encarga el motor.
    orden_pasos: list[Paso] = []
    orden_pasos.extend(pasos_join)
    if paso_filtrar is not None:
        orden_pasos.append(paso_filtrar)
    orden_pasos.extend(pasos_finales)
    c.pasos = orden_pasos
    return c


# --------------------------------------------------------------------------- #
# Piezas
# --------------------------------------------------------------------------- #

def _parecidos(nombre: str, conocidos: dict[str, str]) -> list[str]:
    """Los nombres que se parecen, para poder sugerir en vez de solo negar."""
    from difflib import get_close_matches

    return get_close_matches(nombre, list(conocidos), n=3, cutoff=0.6)


def _origen_de(nodo: exp.Expression, c: Conversion,
               conocidos: dict[str, str] | None) -> Origen | None:
    if not isinstance(nodo, exp.Table):
        c.no_representable.append(
            "Uno de los orígenes no es una tabla simple (puede ser una subconsulta). "
            "Los pasos visuales parten siempre de tablas.")
        return None
    nombre = nodo.alias_or_name
    ref = nodo.name

    if conocidos is None:
        # Sin catalogo no hay nada que resolver; se supone lo de siempre.
        return Origen(nombre=nombre, tipo="tabla", referencia=ref)

    tipo = conocidos.get(ref)
    if tipo is None:
        sugerencias = _parecidos(ref, conocidos)
        pista = (f" ¿Quisiste decir {', '.join(sugerencias)}?" if sugerencias
                 else " Míralo en «Orígenes disponibles», a la izquierda.")
        c.no_representable.append(
            f"No hay ningún origen llamado '{ref}'. Puede ser una tabla del motor, "
            f"un dataset ya cargado o el resultado de otra transformación —pero "
            f"tiene que existir aquí, no en la base de la que salieron los datos."
            f"{pista}")
        return None
    return Origen(nombre=nombre, tipo=tipo, referencia=ref)


def _paso_join(j: exp.Join, izquierda: str, derecha: str,
               c: Conversion) -> Paso | None:
    lado = (j.side or "").upper()
    clase = (j.kind or "").upper()
    tipo = _TIPOS_JOIN.get(lado or clase)
    if tipo is None:
        c.no_representable.append(
            f"El tipo de JOIN '{lado or clase}' no tiene paso equivalente.")
        return None

    condicion = _arg(j, "on")
    if condicion is None:
        c.no_representable.append(
            "Hay un JOIN sin ON (producto cartesiano o USING). No hay paso para eso.")
        return None

    pares: list[tuple[str, str]] = []
    pendientes = [condicion]
    while pendientes:
        nodo = pendientes.pop()
        if isinstance(nodo, exp.And):
            pendientes.extend([nodo.this, nodo.expression])
            continue
        if not isinstance(nodo, exp.EQ):
            c.no_representable.append(
                "La condición del JOIN no es una igualdad entre columnas. El paso "
                "'unir' solo admite igualdades.")
            return None
        izq, der = nodo.this, nodo.expression
        if not (isinstance(izq, exp.Column) and isinstance(der, exp.Column)):
            c.no_representable.append(
                "La condición del JOIN compara algo que no son dos columnas.")
            return None
        # Ordenar los lados según a qué tabla pertenece cada columna.
        if der.table == derecha or izq.table == izquierda:
            pares.append((izq.name, der.name))
        else:
            pares.append((der.name, izq.name))

    return PasoUnir(con=derecha, como=tipo, en=pares)


def _paso_filtrar(nodo: exp.Expression, c: Conversion) -> Paso | None:
    """Aplana un AND (o un OR) de comparaciones simples."""
    condiciones: list[Condicion] = []
    modo = "y"

    def recorrer(n: exp.Expression) -> bool:
        nonlocal modo
        if isinstance(n, exp.And):
            return recorrer(n.this) and recorrer(n.expression)
        if isinstance(n, exp.Or):
            modo = "o"
            return recorrer(n.this) and recorrer(n.expression)
        if isinstance(n, exp.Paren):
            return recorrer(n.this)

        if isinstance(n, exp.Is) and isinstance(n.expression, exp.Null):
            if isinstance(n.this, exp.Column):
                condiciones.append(Condicion(campo=n.this.name, op="es_nulo"))
                return True
        if isinstance(n, exp.Not) and isinstance(n.this, exp.Is):
            interno = n.this
            if isinstance(interno.expression, exp.Null) and isinstance(
                    interno.this, exp.Column):
                condiciones.append(Condicion(campo=interno.this.name,
                                             op="no_es_nulo"))
                return True
        if isinstance(n, exp.In) and isinstance(n.this, exp.Column):
            valores = [_valor(v) for v in (_arg(n, "expressions") or [])]
            if all(v is not None for v in valores) and valores:
                condiciones.append(Condicion(campo=n.this.name, op="en",
                                             valor=valores))
                return True

        for clase, op in _OPERADORES.items():
            if isinstance(n, clase):
                if isinstance(n.this, exp.Column):
                    valor = _valor(n.expression)
                    if valor is not None:
                        condiciones.append(
                            Condicion(campo=n.this.name, op=op, valor=valor))
                        return True
                break

        c.no_representable.append(
            f"Una condición del WHERE no se puede representar como paso: "
            f"{n.sql(dialect=DIALECTO)}")
        return False

    if not recorrer(nodo):
        return None
    if modo == "o" and len(condiciones) < 2:
        modo = "y"
    return PasoFiltrar(condiciones=condiciones, modo=modo)   # type: ignore[arg-type]


def _valor(nodo: exp.Expression):
    """Literal de Python, o None si no es un literal."""
    if isinstance(nodo, exp.Literal):
        if nodo.is_string:
            return nodo.this
        texto = str(nodo.this)
        try:
            return int(texto) if "." not in texto else float(texto)
        except ValueError:
            return texto
    if isinstance(nodo, exp.Boolean):
        return bool(nodo.this)
    if isinstance(nodo, exp.Neg) and isinstance(nodo.this, exp.Literal):
        v = _valor(nodo.this)
        return -v if isinstance(v, (int, float)) else None
    return None


def _paso_agrupar(select: exp.Select, grupo: exp.Group,
                  c: Conversion) -> Paso | None:
    por: list[str] = []
    for g in grupo.expressions:
        if not isinstance(g, exp.Column):
            c.no_representable.append(
                "El GROUP BY agrupa por una expresión, no por una columna. Deriva "
                "primero una columna y agrupa por ella.")
            return None
        por.append(g.name)

    agregados: list[Agregado] = []
    for proyeccion in select.expressions:
        nombre = proyeccion.alias_or_name
        interno = proyeccion.unalias() if hasattr(proyeccion, "unalias") else proyeccion

        if isinstance(interno, exp.Column):
            if interno.name not in por:
                c.no_representable.append(
                    f"'{interno.name}' está en el SELECT pero no en el GROUP BY.")
                return None
            continue

        if isinstance(interno, exp.AggFunc):
            fn = interno.sql_name().upper()
            visual = _AGREGADOS_SQL.get(fn)
            if visual is None:
                c.no_representable.append(
                    f"La función de agregación {fn} no tiene paso equivalente.")
                return None
            argumento = interno.this
            if isinstance(argumento, exp.Star) or argumento is None:
                agregados.append(Agregado(nombre=nombre, funcion="cuenta"))
                continue
            if isinstance(argumento, exp.Distinct):
                columnas = argumento.expressions
                if fn == "COUNT" and len(columnas) == 1 and isinstance(
                        columnas[0], exp.Column):
                    agregados.append(Agregado(nombre=nombre,
                                              funcion="cuenta_distintos",
                                              campo=columnas[0].name))
                    continue
                c.no_representable.append(
                    f"{fn}(DISTINCT ...) solo se soporta para contar una columna.")
                return None
            if not isinstance(argumento, exp.Column):
                c.no_representable.append(
                    f"{fn} se aplica a una expresión, no a una columna. Deriva "
                    f"primero una columna y agrégala.")
                return None
            agregados.append(Agregado(nombre=nombre, funcion=visual,
                                      campo=argumento.name))
            continue

        c.no_representable.append(
            f"'{proyeccion.sql(dialect=DIALECTO)}' no es ni una columna del GROUP BY "
            f"ni una agregación.")
        return None

    if not agregados:
        c.no_representable.append(
            "Hay GROUP BY pero ninguna agregación; eso es un 'quitar repetidas'.")
        return None
    assert AGREGADOS      # las funciones válidas viven en el compilador
    return PasoAgrupar(por=por, agregados=agregados)


def _pasos_seleccion(select: exp.Select, c: Conversion) -> list[Paso]:
    """SELECT sin GROUP BY: columnas, renombres y columnas derivadas."""
    if len(select.expressions) == 1 and isinstance(select.expressions[0], exp.Star):
        return []

    mantener: list[str] = []
    renombres: dict[str, str] = {}
    derivadas: list[Paso] = []
    hay_estrella = False

    for proyeccion in select.expressions:
        if isinstance(proyeccion, exp.Star):
            hay_estrella = True
            continue
        alias = proyeccion.alias_or_name
        interno = proyeccion.unalias() if hasattr(proyeccion, "unalias") else proyeccion

        if isinstance(interno, exp.Column):
            mantener.append(interno.name)
            if alias and alias != interno.name:
                renombres[interno.name] = alias
            continue

        # Cualquier otra cosa con alias es una columna derivada.
        if not alias:
            c.no_representable.append(
                f"La expresión '{interno.sql(dialect=DIALECTO)}' no tiene alias; "
                f"una columna derivada necesita nombre.")
            continue
        derivadas.append(
            PasoDerivar(nombre=alias, expresion=interno.sql(dialect=DIALECTO)))

    pasos: list[Paso] = []
    pasos.extend(derivadas)
    if mantener and not hay_estrella:
        # Las derivadas se calculan antes, así que también se pueden mantener.
        pasos.append(PasoColumnas(
            mantener=mantener + [p.nombre for p in derivadas    # type: ignore[attr-defined]
                                 if isinstance(p, PasoDerivar)]))
    if renombres:
        pasos.append(PasoRenombrar(cambios=renombres))
    return pasos
