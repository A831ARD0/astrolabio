"""
Motor del modelo semantico.

Resuelve las tres cosas dificiles de una capa semantica de BI:

  1. RESOLUCION DE RUTAS con deteccion de ambiguedad. Cuando hay mas de un
     camino entre dos entidades, el motor NO elige uno en silencio: falla y
     obliga a decidir. Es la regla que evita que Astrolabio entregue un numero
     plausible pero equivocado.

  2. AGREGACION A PRUEBA DE FAN TRAP. Cada metrica se agrega en su propio CTE,
     a su propio grano, y solo despues se unen por las llaves de dimension. Un
     objetivo mensual nunca se multiplica por el numero de facturas del mes.

  3. ESTADOS ASOCIATIVOS (seleccionado / posible / alternativo / excluido) al
     estilo Qlik, calculados sobre SQL.

Distincion de diseño importante: la ambiguedad de rutas es un ERROR cuando se
agrega (dos caminos dan dos numeros distintos y hay que saber cual se quiere),
pero es una UNION cuando se calculan estados asociativos (un valor es alcanzable
si lo es por cualquier camino).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

import sqlglot
import sqlglot.expressions as exp
import yaml

from semantic.formula import COL_ANIO, COL_PERIODO
from semantic.formula import Contexto, ContextoCompuesta, ErrorFormula
from semantic.formula import compilar as compilar_formula
from semantic.formula import Compuesta, MARCA_CAPA, compilar_compuesta
from semantic.formula import revisar as revisar_formula
from semantic.formula import revisar_compuesta


# --------------------------------------------------------------------------- #
# Excepciones de dominio: cada una representa una decision que el motor se
# niega a tomar por su cuenta.
# --------------------------------------------------------------------------- #

class ErrorModelo(Exception):
    """Base de los errores del modelo semantico."""


class RutaAmbigua(ErrorModelo):
    def __init__(self, desde: str, hasta: str, rutas: list[list[str]]):
        self.desde, self.hasta, self.rutas = desde, hasta, rutas
        opciones = "\n".join(
            f"    {i + 1}. " + " → ".join(r) for i, r in enumerate(rutas)
        )
        super().__init__(
            f"Hay {len(rutas)} caminos posibles de '{desde}' a '{hasta}' y dan "
            f"resultados distintos. Elige cual usar:\n{opciones}"
        )


class SinRuta(ErrorModelo):
    def __init__(self, desde: str, hasta: str):
        self.desde, self.hasta = desde, hasta
        super().__init__(
            f"'{desde}' no tiene ninguna relacion con '{hasta}', asi que esa "
            f"metrica no se puede desglosar por esa dimension."
        )


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #

@dataclass
class Campo:
    nombre: str
    tipo: str
    rol: str
    etiqueta: str | None = None
    visible: bool = True
    pii: bool = False
    #: No se repite, aunque no sea la clave primaria. Ver `CampoDef.unico`.
    unico: bool = False
    #: Que periodo identifica, si identifica alguno. Ver `CampoDef.grano_tiempo`.
    grano_tiempo: str | None = None


@dataclass
class Entidad:
    nombre: str
    tipo: str
    tabla: str
    campos: dict[str, Campo]
    clave_primaria: str | None = None
    grano: list[str] = dc_field(default_factory=list)


@dataclass
class Relacion:
    entidad_a: str
    campo_a: str
    entidad_b: str
    campo_b: str
    cardinalidad: str
    direccion_filtro: str
    #: Solo las activas se recorren al consultar. Ver `RelacionDef.activa`.
    activa: bool = True

    @property
    def clave(self) -> str:
        """Como se nombra esta relacion desde una metrica. Ver `Metrica.uniones`."""
        return (f"{self.entidad_a}.{self.campo_a} -> "
                f"{self.entidad_b}.{self.campo_b}")

    @property
    def par(self) -> tuple[str, str]:
        return tuple(sorted((self.entidad_a, self.entidad_b)))  # type: ignore[return-value]


@dataclass
class Metrica:
    nombre: str
    etiqueta: str
    #: El hecho del que se agrega, y por tanto el FROM de su CTE. `None` la marca
    #: como COMPUESTA: no lee ninguna tabla, solo combina otras metricas, y se
    #: calcula despues de unirlas. Ver `Compilador.compilar`.
    entidad: str | None
    expresion: str
    formato: str = "numero"
    #: Relaciones que ESTA metrica usa en vez de la activa. Ver `Modelo.grafo_con`.
    uniones: tuple[str, ...] = ()

    @property
    def compuesta(self) -> bool:
        return self.entidad is None


class Modelo:
    def __init__(self, ruta: str | Path):
        crudo = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
        self.nombre: str = crudo["modelo"]
        self.version: int = crudo["version"]

        self.entidades: dict[str, Entidad] = {}
        for e in crudo["entidades"]:
            campos = {
                c["nombre"]: Campo(
                    nombre=c["nombre"], tipo=c["tipo"], rol=c["rol"],
                    etiqueta=c.get("etiqueta"), visible=c.get("visible", True),
                    pii=c.get("pii", False), unico=c.get("unico", False),
                    grano_tiempo=c.get("grano_tiempo"),
                )
                for c in e["campos"]
            }
            self.entidades[e["nombre"]] = Entidad(
                nombre=e["nombre"], tipo=e["tipo"], tabla=e["origen"]["tabla"],
                campos=campos, clave_primaria=e.get("clave_primaria"),
                grano=e.get("grano", []),
            )

        # .get y no [...]: un modelo recien creado en la interfaz tiene entidades
        # y todavia ninguna relacion, y tiene que poder guardarse asi.
        self.relaciones: list[Relacion] = [
            Relacion(r["desde"][0], r["desde"][1], r["hasta"][0], r["hasta"][1],
                     r["cardinalidad"], r.get("direccion_filtro", "ambas"),
                     r.get("activa", True))
            for r in crudo.get("relaciones", [])
        ]

        self.metricas: dict[str, Metrica] = {
            m["nombre"]: Metrica(m["nombre"], m["etiqueta"], m.get("entidad"),
                                 m["expresion"], m.get("formato", "numero"),
                                 tuple(m.get("uniones", []) or ()))
            for m in crudo.get("metricas", [])
        }

        # Las politicas se guardan crudas: las interpreta la capa de politicas
        # (app/politicas.py), que es la unica que conoce al usuario.
        self.politicas: list[dict] = crudo.get("politicas", [])

        # Grafo no dirigido: entidad -> [(vecina, relacion)]
        # Solo las activas. Una inactiva esta escrita en el modelo —se ve en el
        # lienzo y se puede activar— pero no es un camino: si lo fuera, tener
        # tres fechas contra el calendario haria ambigua cualquier consulta que
        # pase por ahi, que es justo lo que `activa` viene a evitar.
        self.grafo: dict[str, list[tuple[str, Relacion]]] = {n: [] for n in self.entidades}
        for r in self.relaciones:
            if not r.activa:
                continue
            self.grafo[r.entidad_a].append((r.entidad_b, r))
            self.grafo[r.entidad_b].append((r.entidad_a, r))

        # Formulas ya traducidas a SQL, por texto de expresion. Una metrica que
        # referencia a otra recompila la referenciada cada vez, y una consulta
        # con seis metricas encima de la misma base lo haria seis veces.
        self._sql_formula: dict[str, str] = {}
        #: Lo mismo para las compuestas, por nombre: su SQL y de que dependen.
        self._sql_compuesta: dict[str, Compuesta] = {}
        #: Grafos alternos, por juego de uniones pedidas. Ver `grafo_con`.
        self._grafos: dict[tuple[str, ...], dict] = {}

    # ---------------- metricas ----------------

    def contexto(self, entidad: str) -> Contexto:
        """
        Contra que se resuelve una formula: los campos de su entidad y las demas
        metricas de ESA entidad.

        Solo las de la misma entidad a proposito. Pegar dentro de una metrica de
        ventas la expresion de una que vive en objetivos daria SQL que compila
        —son columnas con nombre distinto— sobre una tabla que no las tiene, y el
        error saldria como «columna inexistente» en vez de decir lo que pasa.
        """
        e = self.entidades[entidad]
        return Contexto(
            campos=set(e.campos),
            metricas={m.nombre: m.expresion for m in self.metricas.values()
                      if m.entidad == entidad},
        )

    def contexto_compuesta(self) -> ContextoCompuesta:
        """
        Contra que se resuelve una compuesta: TODAS las metricas del modelo,
        vengan del hecho que vengan. Ese es justamente su motivo de ser.

        Se incluye tambien la que se esta compilando. Quitarla parecia la forma
        barata de impedir que se llamara a si misma, y lo que hacia era romper la
        recursion: al resolver `ida`, `vuelta` ya no encontraba a `ida` y el error
        salia como «no hay ninguna metrica llamada ida» en vez de decir que se
        llaman en circulo. De cortar el ciclo se encarga `_en_curso`, que es lo
        unico que sabe por donde se ha pasado.
        """
        return ContextoCompuesta(
            metricas={m.nombre: (m.expresion if m.compuesta else None)
                      for m in self.metricas.values()},
        )

    def sql_compuesta(self, metrica: Metrica) -> Compuesta:
        """El SQL de una compuesta, de que depende, y que hay que calcular antes."""
        if metrica.nombre not in self._sql_compuesta:
            try:
                self._sql_compuesta[metrica.nombre] = compilar_compuesta(
                    metrica.expresion, self.contexto_compuesta(),
                    (metrica.nombre,))
            except ErrorFormula as e:
                raise ErrorModelo(
                    f"La formula de la metrica compuesta '{metrica.nombre}' no "
                    f"se puede compilar: {e}") from e
        return self._sql_compuesta[metrica.nombre]

    def dependencias_base(self, nombre: str) -> list[str]:
        """
        Las metricas NO compuestas de las que depende, ya aplanadas.

        Son las que hay que calcular de verdad: una compuesta no agrega nada, asi
        que pedirla es pedir estas.
        """
        metrica = self.metricas[nombre]
        if not metrica.compuesta:
            return [nombre]
        return self.sql_compuesta(metrica).dependencias

    def sql_de(self, metrica: Metrica) -> str:
        """La formula de la metrica, ya como SQL de DuckDB."""
        if metrica.expresion not in self._sql_formula:
            try:
                sql = compilar_formula(metrica.expresion,
                                       self.contexto(metrica.entidad))
            except ErrorFormula as e:
                # Se traduce a ErrorModelo para que salga por el mismo camino que
                # una ruta ambigua: es un error de quien definio el modelo, la
                # respuesta es 422 y el texto se le enseña tal cual.
                raise ErrorModelo(
                    f"La formula de la metrica '{metrica.nombre}' no se puede "
                    f"compilar: {e}") from e
            self._sql_formula[metrica.expresion] = sql
        return self._sql_formula[metrica.expresion]

    # ---------------- rutas ----------------

    def relaciones_nombrables(self, entidad: str) -> list[Relacion]:
        """
        Las relaciones INACTIVAS que tocan a esta entidad.

        Son las unicas que una metrica puede pedir: la activa ya se usa sin decir
        nada, y nombrarla no cambiaria nada.
        """
        return [r for r in self.relaciones
                if not r.activa and entidad in (r.entidad_a, r.entidad_b)]

    def grafo_con(self, uniones: tuple[str, ...]) -> dict[str, list[tuple[str, Relacion]]]:
        """
        El grafo como lo ve una metrica que pidio unirse por otras relaciones.

        Un hecho toca el calendario por mas de una fecha mas a menudo de lo que
        parece: el contacto tiene fecha de primera visita, de asignacion y de
        prueba de manejo, y cada indicador cuenta por la suya. Solo UNA puede
        estar activa —si mandaran dos, cada consulta tendria dos caminos igual de
        validos y el total dependeria de cual eligiera el compilador—, asi que las
        demas se dejan dibujadas e inactivas y la metrica dice cual es la suya.

        Activar la pedida no basta: hay que APAGAR la que estaba activa entre ese
        mismo par de entidades. Si no, quedan dos caminos a la vez y el modelo
        vuelve a ser ambiguo justo donde se queria precision.
        """
        if not uniones:
            return self.grafo
        if uniones not in self._grafos:
            pedidas = {r.clave: r for r in self.relaciones if r.clave in uniones}
            pares = {r.par for r in pedidas.values()}
            grafo: dict[str, list[tuple[str, Relacion]]] = {n: [] for n in self.entidades}
            for r in self.relaciones:
                activa = r.clave in pedidas or (r.activa and r.par not in pares)
                if not activa:
                    continue
                grafo[r.entidad_a].append((r.entidad_b, r))
                grafo[r.entidad_b].append((r.entidad_a, r))
            self._grafos[uniones] = grafo
        return self._grafos[uniones]

    def rutas_minimas(self, desde: str, hasta: str, tope: int = 6,
                      atravesar_hechos: bool = False,
                      grafo: dict | None = None) -> list[list[str]]:
        """
        Rutas de longitud minima entre dos entidades.

        `atravesar_hechos` marca la diferencia entre los dos usos del grafo:

          False (agregacion) — una tabla de hechos es un TERMINAL, no un puente.
            Que cat_sucursal y dim_calendario se toquen "a traves de" fact_venta
            no es una ruta: es la definicion de un esquema en estrella. Permitir
            esos saltos genera decenas de ambiguedades falsas.

          True (estados asociativos) — los hechos SI son el puente. Es
            precisamente como se propaga una seleccion de Modelo hasta Estado.
        """
        if desde == hasta:
            return [[desde]]
        g = self.grafo if grafo is None else grafo
        encontradas: list[list[str]] = []
        mejor = tope

        def dfs(actual: str, camino: list[str]):
            nonlocal mejor
            if len(camino) - 1 > mejor:
                return
            for vecina, rel in g[actual]:
                if vecina in camino:
                    continue
                # Para agregar, cada salto debe ir del lado "muchos" al lado
                # "uno". Ir de uno a muchos (p.ej. marca -> vehiculo) expande
                # filas en vez de agrupar: produce un numero sin significado.
                if not atravesar_hechos and rel.cardinalidad == "muchos_a_uno":
                    if not (rel.entidad_a == actual and rel.entidad_b == vecina):
                        continue
                nuevo = camino + [vecina]
                if vecina == hasta:
                    largo = len(nuevo) - 1
                    if largo < mejor:
                        mejor, encontradas[:] = largo, [nuevo]
                    elif largo == mejor:
                        encontradas.append(nuevo)
                elif len(nuevo) - 1 < mejor:
                    # Un hecho intermedio solo se atraviesa si se permite.
                    if not atravesar_hechos and self.entidades[vecina].tipo == "hecho":
                        continue
                    dfs(vecina, nuevo)

        dfs(desde, [desde])
        return encontradas

    def ruta_unica(self, desde: str, hasta: str,
                   grafo: dict | None = None) -> list[str]:
        """Ruta unica para agregar, o error. Nunca elige en silencio."""
        rutas = self.rutas_minimas(desde, hasta, grafo=grafo)
        if not rutas:
            raise SinRuta(desde, hasta)
        if len(rutas) > 1:
            raise RutaAmbigua(desde, hasta, rutas)
        return rutas[0]

    def relacion_entre(self, a: str, b: str,
                       grafo: dict | None = None) -> Relacion:
        for vecina, rel in (self.grafo if grafo is None else grafo)[a]:
            if vecina == b:
                return rel
        raise SinRuta(a, b)

    # ---------------- diagnostico del modelo ----------------

    def diagnosticar(self) -> list[dict[str, Any]]:
        """Problemas que deben verse ANTES de construir un dashboard."""
        problemas: list[dict[str, Any]] = []

        for nombre in self.entidades:
            if not self.grafo[nombre]:
                problemas.append({
                    "tipo": "tabla_huerfana",
                    "gravedad": "advertencia",
                    "entidad": nombre,
                    "mensaje": f"'{nombre}' no tiene ninguna relacion: queda "
                               f"aislada del resto del analisis.",
                })

        # Una dimension con columnas de medida es, casi siempre, un hecho mal
        # marcado. Importa porque el editor de metricas solo ofrece hechos en
        # «Calcula desde»: los objetivos estan ahi, con sus seis columnas de
        # medida, y no se puede escribir una sola metrica sobre ellos. Y no se ve
        # como un error, se ve como que la tabla «no aparece en la lista».
        for nombre, e in self.entidades.items():
            if e.tipo != "dimension":
                continue
            medidas = [c.nombre for c in e.campos.values()
                       if c.rol == "medida_base"]
            if medidas:
                problemas.append({
                    "tipo": "dimension_con_medidas",
                    "gravedad": "critico",
                    "entidad": nombre,
                    "mensaje": f"'{nombre}' esta marcada como dimension pero "
                               f"tiene {len(medidas)} columna(s) de medida "
                               f"({', '.join(sorted(medidas)[:4])}"
                               f"{'…' if len(medidas) > 4 else ''}). Una metrica "
                               f"solo se puede calcular desde un hecho, asi que "
                               f"esas columnas no se pueden sumar: cambiale el "
                               f"tipo a hecho.",
                })

        # Los dos lados de una union tienen que ser del mismo tipo. Comparar un
        # texto con un entero no falla siempre —el motor a veces convierte— y
        # cuando no falla es peor: no casa ninguna fila y la cifra sale vacia o a
        # cero, sin una sola señal de por que.
        for r in self.relaciones:
            a = self.entidades.get(r.entidad_a)
            b = self.entidades.get(r.entidad_b)
            if a is None or b is None:
                continue
            ca, cb = a.campos.get(r.campo_a), b.campos.get(r.campo_b)
            if ca is None or cb is None or ca.tipo == cb.tipo:
                continue
            problemas.append({
                "tipo": "tipos_que_no_casan",
                "gravedad": "critico",
                "entidad": f"{r.entidad_a} → {r.entidad_b}",
                "mensaje": f"La union {r.entidad_a}.{r.campo_a} ({ca.tipo}) con "
                           f"{r.entidad_b}.{r.campo_b} ({cb.tipo}) compara dos "
                           f"tipos distintos. Arreglalo en la transformacion: si "
                           f"no casa ninguna fila, la cifra sale vacia sin "
                           f"avisar.",
            })

        # Una fecha guardada como texto. Se ordena mal —'10/01' antes que
        # '9/12'—, no se puede unir contra un calendario de fechas de verdad, y
        # ninguna comparacion de periodos funciona encima.
        for nombre, e in self.entidades.items():
            for c in e.campos.values():
                if c.tipo == "texto" and "fecha" in c.nombre.lower():
                    problemas.append({
                        "tipo": "fecha_como_texto",
                        "gravedad": "advertencia",
                        "entidad": f"{nombre}.{c.nombre}",
                        "mensaje": f"'{nombre}.{c.nombre}' parece una fecha y "
                                   f"esta guardada como texto. Asi no se puede "
                                   f"unir al calendario ni comparar contra otro "
                                   f"mes, y ordena mal. Conviertela en la "
                                   f"transformacion.",
                    })

        # Solo importa la ambiguedad hecho → dimension: es la unica que puede
        # afectar a una consulta real, porque toda metrica nace en un hecho.
        hechos = [n for n, e in self.entidades.items() if e.tipo == "hecho"]
        dims = [n for n, e in self.entidades.items() if e.tipo == "dimension"]
        for h in hechos:
            for d in dims:
                rutas = self.rutas_minimas(h, d)
                if len(rutas) > 1:
                    problemas.append({
                        "tipo": "ruta_ambigua",
                        "gravedad": "critico",
                        "entidad": f"{h} → {d}",
                        "mensaje": f"Hay {len(rutas)} caminos de igual longitud "
                                   f"de '{h}' a '{d}'; pueden dar cifras "
                                   f"distintas.",
                        "rutas": [" → ".join(r) for r in rutas],
                    })

        # Las inactivas se listan a proposito. No son un error —se marcan para
        # que el modelo tenga un solo camino— pero quien mire el lienzo y vea una
        # linea punteada tiene que poder saber que existe, que esta apagada y que
        # ninguna consulta pasa por ahi.
        for r in self.relaciones:
            if not r.activa:
                problemas.append({
                    "tipo": "relacion_inactiva",
                    "gravedad": "informativo",
                    "entidad": f"{r.entidad_a} ↔ {r.entidad_b}",
                    "mensaje": f"'{r.entidad_a}.{r.campo_a}' → "
                               f"'{r.entidad_b}.{r.campo_b}' esta inactiva: "
                               f"queda escrita en el modelo, pero al agregar no "
                               f"se usa. Manda la relacion activa entre esas dos "
                               f"tablas.",
                })

        # El lado «uno» tiene que ser de verdad uno. Es el aviso mas util del
        # modelo y hasta ahora solo existia en la pantalla: quien abre el YAML a
        # mano, o mira el diagnostico, no se enteraba. No basta con ser la clave
        # primaria —una entidad tiene una sola y suele haber varios
        # identificadores que tampoco se repiten—, asi que vale cualquiera de las
        # dos declaraciones.
        for r in self.relaciones:
            if r.cardinalidad != "muchos_a_uno" or not r.activa:
                continue
            destino = self.entidades.get(r.entidad_b)
            if destino is None:
                continue
            campo = destino.campos.get(r.campo_b)
            if destino.clave_primaria == r.campo_b or (campo and campo.unico):
                continue
            problemas.append({
                "tipo": "uno_sin_garantia",
                "gravedad": "advertencia",
                "entidad": f"{r.entidad_a} → {r.entidad_b}",
                "mensaje": f"'{r.entidad_b}.{r.campo_b}' esta del lado 'uno' de "
                           f"una relacion muchos-a-uno, pero no consta que sea "
                           f"unica: no es la clave primaria de '{r.entidad_b}' "
                           f"ni esta marcada como unica. Si se repitiera, esta "
                           f"union multiplicaria filas y los totales saldrian "
                           f"inflados.",
            })

        for r in self.relaciones:
            if r.cardinalidad == "muchos_a_muchos":
                problemas.append({
                    "tipo": "muchos_a_muchos",
                    "gravedad": "advertencia",
                    "entidad": f"{r.entidad_a} ↔ {r.entidad_b}",
                    "mensaje": f"Relacion muchos-a-muchos entre "
                               f"'{r.entidad_a}.{r.campo_a}' y "
                               f"'{r.entidad_b}.{r.campo_b}': revisa que no "
                               f"duplique filas al agregar.",
                })

        # Las formulas. Una metrica mal escrita no rompe nada hasta que alguien
        # la pone en un tablero, y para entonces el error le sale como «no se
        # pudo consultar» a quien solo estaba mirando una cifra.
        #
        # Se revisa entera y no solo si compila: un campo que no existe o uno
        # suelto fuera de la agregacion SI compilan, y son los dos errores que de
        # verdad se cometen.
        for m in self.metricas.values():
            if m.compuesta:
                fallos = revisar_compuesta(m.expresion,
                                           self.contexto_compuesta(), m.nombre)
            elif m.entidad in self.entidades:
                fallos = revisar_formula(m.expresion, self.contexto(m.entidad))
            else:
                continue                       # ya lo dice revisar_referencias
            for fallo in fallos:
                problemas.append({
                    "tipo": "formula",
                    "gravedad": ("critico" if fallo["gravedad"] == "error"
                                 else "advertencia"),
                    "entidad": (m.nombre if m.compuesta
                                else f"{m.entidad}.{m.nombre}"),
                    "mensaje": f"Metrica '{m.nombre}', linea {fallo['linea']}: "
                               f"{fallo['mensaje']}",
                })

        # Lo que hay que arreglar primero, arriba. `.get` con un tope al final
        # para que una gravedad nueva se coloque sola en vez de reventar la
        # pantalla entera de diagnostico.
        orden = {"critico": 0, "advertencia": 1, "informativo": 2}
        return sorted(problemas, key=lambda p: orden.get(p["gravedad"], 9))


# --------------------------------------------------------------------------- #
# Compilador de consultas
# --------------------------------------------------------------------------- #

def _cita(x: str) -> str:
    return '"' + x.replace('"', '""') + '"'


def _calificar(expresion: str, alias: str, campos: set[str],
               dialecto: str = "duckdb") -> str:
    """
    Antepone el alias de tabla a cada columna de una expresion de metrica.

    Se hace sobre el arbol sintactico con SQLGlot, no con reemplazo de texto: un
    reemplazo ingenuo convierte 'monto_bonus_cancel' en 't."monto_bonus"_cancel'
    porque 'monto_bonus' es prefijo suyo. Trabajar sobre el AST tambien es lo que
    despues permite traducir la misma expresion a otro motor sin reescribirla.
    """
    arbol = sqlglot.parse_one(expresion, read=dialecto)
    for col in arbol.find_all(exp.Column):
        if col.name in campos:
            col.set("table", exp.to_identifier(alias, quoted=False))
    return arbol.sql(dialect=dialecto, identify=True)


def _calificar_metricas(expresion: str, donde: dict[str, str],
                        dialecto: str = "duckdb") -> str:
    """
    En la formula de una compuesta, antepone a cada metrica el CTE que la calculo.

    `DIVIDIR([a], [b])` llega aqui como `"a" / NULLIF("b", 0)`, con `a` y `b`
    puestas como columnas por `compilar_compuesta`. Cada una vive en el CTE de su
    propio hecho, asi que sale `m0."a" / NULLIF(m1."b", 0)` — y ahi esta todo el
    asunto: son dos tablas distintas, ya agregadas cada una a su grano, y por eso
    el cociente no multiplica una por las filas de la otra.
    """
    arbol = sqlglot.parse_one(expresion, read=dialecto)
    for col in arbol.find_all(exp.Column):
        if col.name in donde:
            col.set("table", exp.to_identifier(donde[col.name], quoted=False))
    return arbol.sql(dialect=dialecto, identify=True)


def _indice_de_mes(columna: str, tipo: str) -> tuple[str, str]:
    """
    `(indice de mes, año)` a partir de la columna de periodo del desglose.

    El indice es un numero que crece de uno en uno por mes y no se reinicia en
    enero —`2026*12 + 3`—, que es lo que hace que «tres meses atras» cruce el
    cambio de año sin un caso especial. Es tambien lo que permite usar `RANGE` en
    la ventana: como el marco compara VALORES, un mes que falta sale vacio en vez
    de correr la cuenta una posicion.

    Se aceptan las dos formas en que suele venir un mes: una fecha, y el entero
    `202601`, que es como lo trae casi cualquier calendario heredado.
    """
    if tipo == "fecha":
        return (f"(YEAR({columna}) * 12 + MONTH({columna}))", f"YEAR({columna})")
    # `202601` -> año 2026, mes 1. `//` y no `/`: en DuckDB la barra sencilla es
    # division REAL, asi que `201601 / 100` da 2016.01 y el indice sale con
    # decimales — entonces `RANGE 1 PRECEDING` no encuentra nunca el mes de antes
    # y cada mes queda ademas en su propio año. Sale todo vacio, sin error.
    return (f"((CAST({columna} AS BIGINT) // 100) * 12 + "
            f"(CAST({columna} AS BIGINT) % 100))",
            f"(CAST({columna} AS BIGINT) // 100)")


def _resolver_ventanas(expresion: str, periodo: str, anio: str,
                       otras_dims: list[str], dialecto: str = "duckdb") -> str:
    """
    Rellena las ventanas de tiempo: por que se ordenan y dentro de que grupo.

    La formula llega con `__periodo__` y `__anio__` de relleno porque quien la
    escribio no sabe —ni tiene por que— por que columna se va a desglosar la
    consulta. El `PARTITION BY` de las demas dimensiones es lo que hace que el
    mes anterior de una sucursal sea el mes anterior DE ESA SUCURSAL, y no la
    fila que le tocara al lado.
    """
    arbol = sqlglot.parse_one(expresion, read=dialecto)
    marcas = {COL_PERIODO: periodo, COL_ANIO: anio}

    for ventana in arbol.find_all(exp.Window):
        previas = list(ventana.args.get("partition_by") or [])
        ventana.set("partition_by",
                    [sqlglot.parse_one(d, read=dialecto) for d in otras_dims]
                    + previas)
    for col in arbol.find_all(exp.Column):
        if col.name in marcas and not col.table:
            col.replace(sqlglot.parse_one(marcas[col.name], read=dialecto))
    return arbol.sql(dialect=dialecto, identify=True)


def _abarca_varios_meses(sql: str, dialecto: str = "duckdb") -> bool:
    """
    Si alguna ventana suma mas de un mes.

    `MESANTERIOR` es `RANGE BETWEEN 1 PRECEDING AND 1 PRECEDING`: un mes suelto,
    y sumar un solo valor no cambia nada. El acumulado del año y el promedio de
    tres meses si suman varios, y ahi la cifra tiene que poder sumarse.
    """
    for ventana in sqlglot.parse_one(sql, read=dialecto).find_all(exp.Window):
        spec = ventana.args.get("spec")
        if spec is None:
            continue
        inicio, fin = spec.args.get("start"), spec.args.get("end")
        if str(inicio).upper() == "UNBOUNDED" or str(inicio) != str(fin):
            return True
    return False


def _es_aditiva(sql: str, dialecto: str = "duckdb") -> bool:
    """
    Si sumar los valores de varios meses da el valor del conjunto.

    Una suma si; un conteo de valores distintos no —el mismo cliente en enero y
    en febrero es UN cliente, no dos— y un promedio tampoco. Importa solo para
    las ventanas que abarcan mas de un mes: `MESANTERIOR` mira un mes suelto, y
    sumar un solo valor es ese valor.
    """
    arbol = sqlglot.parse_one(sql, read=dialecto)
    agregados = list(arbol.find_all(exp.AggFunc))
    if not agregados:
        return False
    for a in agregados:
        if isinstance(a, exp.Sum):
            continue
        if isinstance(a, exp.Count) and a.find(exp.Distinct) is None:
            continue
        return False
    return True


@dataclass
class Consulta:
    """Peticion en terminos del modelo, no en SQL."""
    dimensiones: list[str]                       # "entidad.campo"
    metricas: list[str]                          # nombres de metrica
    filtros: list[dict] = dc_field(default_factory=list)
    rutas_elegidas: dict[str, str] = dc_field(default_factory=dict)
    limite: int = 5000


@dataclass
class ConsultaCompilada:
    """
    SQL mas parametros ligados. Nunca se interpolan valores en el texto: ni los
    filtros del usuario ni los predicados de seguridad por fila.
    """
    sql: str
    parametros: list


class Compilador:
    def __init__(self, modelo: Modelo):
        self.m = modelo

    # -- joins ---------------------------------------------------------------

    def _sql_join(self, ruta: list[str], alias: dict[str, str],
                  grafo: dict | None = None) -> str:
        partes = []
        for i in range(len(ruta) - 1):
            a, b = ruta[i], ruta[i + 1]
            rel = self.m.relacion_entre(a, b, grafo)
            if rel.entidad_a == a:
                ca, cb = rel.campo_a, rel.campo_b
            else:
                ca, cb = rel.campo_b, rel.campo_a
            partes.append(
                f"JOIN {_cita(self.m.entidades[b].tabla)} AS {alias[b]} "
                f"ON {alias[a]}.{_cita(ca)} = {alias[b]}.{_cita(cb)}"
            )
        return "\n  ".join(partes)

    def _plan_alcance(self, ent_base: str, objetivos: list[str],
                      rutas_elegidas: dict[str, str],
                      grafo: dict | None = None,
                      ) -> tuple[dict[str, str], list[str]]:
        """
        Alias de tabla y JOINs para alcanzar `objetivos` partiendo de `ent_base`.

        Lo usan la agregacion y la muestra de filas. Comparten esto a proposito:
        las dos tienen que aplicar las mismas politicas de seguridad, y si cada
        una resolviera sus rutas por su cuenta acabarian uniendo por caminos
        distintos — es decir, lo que un usuario puede ver dependeria de por que
        pantalla lo pregunta.
        """
        necesarias = {ent_base}
        rutas: dict[str, list[str]] = {}
        for ent in objetivos:
            if ent == ent_base:
                rutas[ent] = [ent_base]
                continue
            clave = f"{ent_base}->{ent}"
            if clave in rutas_elegidas:
                ruta = rutas_elegidas[clave].split(" → ")
            else:
                ruta = self.m.ruta_unica(ent_base, ent, grafo)
            rutas[ent] = ruta
            necesarias.update(ruta)

        alias = {e: f"t{i}" for i, e in enumerate(sorted(necesarias))}
        vistos = {ent_base}
        joins: list[str] = []
        for ruta in rutas.values():
            tramo = [ruta[0]]
            for paso in ruta[1:]:
                tramo.append(paso)
                if paso in vistos:
                    continue
                joins.append(self._sql_join(tramo[-2:], alias, grafo))
                vistos.add(paso)
        return alias, joins

    def compilar_muestra(self, entidad: str, limite: int,
                         predicados: list | None = None) -> ConsultaCompilada:
        """
        Unas filas de una entidad, tal como estan en su tabla, sin agregar nada.

        Contesta «¿que hay aqui dentro?», que es la pregunta previa a escribir la
        primera metrica: sin ver una fila no se sabe si `Fecha_Factura` trae
        fechas o trae texto, ni si `Tipo_Venta` dice 'Contado' o 'CONTADO'.

        Pasa por la seguridad por fila igual que cualquier otra lectura. Una
        muestra sin filtrar seria la puerta trasera perfecta: justo las filas que
        las politicas tapan en el resto de la aplicacion, servidas en una tabla.
        """
        if entidad not in self.m.entidades:
            raise ErrorModelo(f"La entidad '{entidad}' no esta en el modelo.")
        ent = self.m.entidades[entidad]
        predicados = predicados or []

        alias, joins = self._plan_alcance(entidad, [p.entidad for p in predicados], {})
        base = alias[entidad]

        where: list[str] = []
        params: list = []
        for p in predicados:
            campos_prot = set(self.m.entidades[p.entidad].campos)
            where.append(_calificar(p.sql, alias[p.entidad], campos_prot))
            params.extend(p.parametros)

        columnas = [c.nombre for c in ent.campos.values() if c.visible]
        # DISTINCT solo si una politica obligo a unir otra tabla: ese JOIN puede
        # multiplicar filas, y una muestra con la misma fila repetida seis veces
        # por culpa de un permiso no se parece a los datos que describe.
        sel = ", ".join(f"{base}.{_cita(c)} AS {_cita(c)}" for c in columnas)
        sql = (f"SELECT {'DISTINCT ' if joins else ''}{sel}"
               f"\nFROM {_cita(ent.tabla)} AS {base}")
        if joins:
            sql += "\n  " + "\n  ".join(joins)
        if where:
            sql += "\nWHERE " + " AND ".join(where)
        sql += f"\nLIMIT {int(limite)}"
        return ConsultaCompilada(sql, params)

    def _cte_metrica(self, ent_metrica: str, metricas: list[Metrica],
                     dims: list[tuple[str, str]], filtros: list[dict],
                     rutas_elegidas: dict[str, str],
                     predicados: list | None = None) -> tuple[str, list]:
        """
        CTE que agrega las metricas de UNA entidad a su propio grano, ya
        desglosadas por las dimensiones pedidas. Aqui es donde se evita el fan
        trap: la agregacion ocurre antes de tocar cualquier otra tabla de hechos.

        `predicados` son las reglas de seguridad por fila ya resueltas para el
        usuario. Si una regla protege una entidad que esta consulta no habria
        unido, se une a la fuerza: la regla se aplica siempre, no solo cuando la
        dimension aparece en el desglose.

        Lo mismo con los filtros del usuario, y por una razon mas fuerte: un
        filtro que no se puede aplicar tiene que hacer FALLAR la consulta, no
        colarse ignorado. Un tablero que filtra por marca y devuelve el total sin
        filtrar es peor que uno que no filtra: nadie lo nota.
        """
        predicados = predicados or []

        # Entidades a alcanzar: las de las dimensiones pedidas, MAS las de los
        # filtros, MAS las protegidas por una politica que aplique a este usuario.
        objetivos = [e for e, _ in dims]
        for f in filtros:
            ent_filtro = str(f["campo"]).split(".")[0]
            if ent_filtro not in objetivos:
                objetivos.append(ent_filtro)
        for p in predicados:
            if p.entidad not in objetivos:
                objetivos.append(p.entidad)

        # Todas las metricas de este CTE comparten uniones: `compilar` las agrupa
        # por eso, precisamente para poder unir aqui de una sola forma.
        grafo = self.m.grafo_con(metricas[0].uniones)
        alias, joins = self._plan_alcance(ent_metrica, objetivos, rutas_elegidas,
                                          grafo)

        sel_dims = [
            f"{alias[e]}.{_cita(c)} AS {_cita(f'{e}.{c}')}" for e, c in dims
        ]
        campos_ent = set(self.m.entidades[ent_metrica].campos)
        sel_mets = [
            f"{_calificar(self.m.sql_de(met), alias[ent_metrica], campos_ent)} "
            f"AS {_cita(met.nombre)}"
            for met in metricas
        ]

        where: list[str] = []
        params: list = []

        # Filtros del usuario — siempre ligados como parametros.
        for f in filtros:
            ent, campo = f["campo"].split(".")
            if ent not in alias:
                # No deberia pasar: la entidad del filtro se agrego a los
                # objetivos del join. Si pasa, es que no habia ruta, y callarlo
                # devolveria una cifra sin filtrar con toda la pinta de estar
                # filtrada.
                raise SinRuta(ent_metrica, ent)
            op = str(f["op"]).upper()
            if op not in {"=", "!=", ">", ">=", "<", "<=", "LIKE", "ILIKE", "IN"}:
                raise ErrorModelo(f"Operador no soportado: {f['op']}")
            if op == "IN":
                valores = list(f["valor"])
                marcas = ", ".join("?" for _ in valores)
                where.append(f"{alias[ent]}.{_cita(campo)} IN ({marcas})")
                params.extend(valores)
            else:
                where.append(f"{alias[ent]}.{_cita(campo)} {op} ?")
                params.append(f["valor"])

        # Seguridad por fila. El predicado viene escrito en terminos de columnas
        # de la entidad protegida, asi que se califica con su alias.
        for p in predicados:
            campos_prot = set(self.m.entidades[p.entidad].campos)
            where.append(_calificar(p.sql, alias[p.entidad], campos_prot))
            params.extend(p.parametros)

        grupo = [f"{alias[e]}.{_cita(c)}" for e, c in dims]
        sql = (
            f"SELECT\n    " + ",\n    ".join(sel_dims + sel_mets) +
            f"\n  FROM {_cita(self.m.entidades[ent_metrica].tabla)} AS {alias[ent_metrica]}"
        )
        if joins:
            sql += "\n  " + "\n  ".join(joins)
        if where:
            sql += "\n  WHERE " + " AND ".join(where)
        if grupo:
            sql += "\n  GROUP BY " + ", ".join(grupo)
        return sql, params

    def _con_tiempo(self, nombre: str, sql: str, deps: list[str],
                    dims: list[tuple[str, str]], prefijo: str = "e.") -> str:
        """
        Resuelve las ventanas de tiempo de una compuesta contra ESTE desglose.

        Una metrica de tiempo no significa nada sin una columna de periodo en el
        desglose: «el mes anterior» de un total sin meses no existe. Se exige, y
        se dice cual falta — devolver el total repetido seria dar un numero que
        parece una comparacion.
        """
        periodos = [(e, col) for e, col in dims
                    if self.m.entidades[e].campos[col].grano_tiempo == "mes"]
        if len(periodos) != 1:
            candidatas = [f"{e.nombre}.{c.nombre}"
                          for e in self.m.entidades.values()
                          for c in e.campos.values()
                          if c.grano_tiempo == "mes"]
            if not periodos:
                raise ErrorModelo(
                    f"La metrica '{nombre}' compara contra otro mes, asi que el "
                    f"desglose tiene que llevar una columna de meses. "
                    + (f"Agrega {' o '.join(candidatas)}." if candidatas else
                       "Ninguna columna del modelo esta marcada como mes: "
                       "marca la del calendario con grano de tiempo «mes»."))
            raise ErrorModelo(
                f"La metrica '{nombre}' compara contra otro mes y el desglose "
                f"lleva {len(periodos)} columnas de meses "
                f"({', '.join(f'{e}.{col}' for e, col in periodos)}). "
                f"Deja una sola: con dos no se sabe cual manda.")

        ent, col = periodos[0]
        columna = f"{prefijo}{_cita(f'{ent}.{col}')}"
        periodo, anio = _indice_de_mes(
            columna, self.m.entidades[ent].campos[col].tipo)
        otras = [f"{prefijo}{_cita(f'{e2}.{c2}')}" for e2, c2 in dims
                 if (e2, c2) != (ent, col)]

        # Sumar varios meses solo vale si la cifra se puede sumar. El caso que
        # importa es un conteo de clientes distintos: el mismo cliente en enero y
        # en febrero es UNO, y el acumulado del año lo contaria dos veces.
        if _abarca_varios_meses(sql):
            for d in deps:
                met = self.m.metricas[d]
                if met.compuesta or _es_aditiva(self.m.sql_de(met)):
                    continue
                raise ErrorModelo(
                    f"'{nombre}' suma varios meses de '{d}', y '{d}' no se puede "
                    f"sumar asi: cuenta valores distintos o promedia, y el mismo "
                    f"valor en dos meses no son dos. Compara contra un solo mes "
                    f"(MESANTERIOR, MISMOMESANIOANTERIOR) o calcula el acumulado "
                    f"desde una metrica que sume.")

        return _resolver_ventanas(sql, periodo, anio, otras)

    def compilar(self, c: Consulta,
                 predicados: list | None = None) -> ConsultaCompilada:
        dims = [tuple(d.split(".")) for d in c.dimensiones]

        # Las compuestas no agregan nada: se calculan al final, sobre las cifras
        # que ya dejo cada hecho. Lo que hay que meter en los CTE son sus
        # dependencias, esten o no pedidas — quien pide «% Logro Unidades» no ha
        # pedido las unidades ni el objetivo, pero sin ellos no hay cociente.
        compuestas: list[Metrica] = []
        pedidas: list[str] = []
        for nombre in c.metricas:
            if nombre not in self.m.metricas:
                raise ErrorModelo(f"La metrica '{nombre}' no existe en el modelo.")
            met = self.m.metricas[nombre]
            if met.compuesta:
                compuestas.append(met)
                pedidas.extend(self.m.dependencias_base(nombre))
            else:
                pedidas.append(nombre)

        # Por entidad Y por uniones, no solo por entidad: dos metricas del mismo
        # hecho que se unen al calendario por fechas distintas —una por la primera
        # visita y otra por la asignacion— no pueden compartir CTE, porque el CTE
        # es justamente donde se decide por donde se une.
        por_grupo: dict[tuple[str, tuple[str, ...]], list[Metrica]] = {}
        vistas: set[str] = set()
        for nombre in pedidas:
            if nombre in vistas:
                continue
            vistas.add(nombre)
            met = self.m.metricas[nombre]
            por_grupo.setdefault((met.entidad, met.uniones), []).append(met)

        ctes: list[tuple[str, str, list[str]]] = []
        parametros: list = []
        cols_dim = [f"{e}.{cc}" for e, cc in dims]
        for i, ((ent, _u), mets) in enumerate(por_grupo.items()):
            cuerpo, params = self._cte_metrica(
                ent, mets, dims, c.filtros, c.rutas_elegidas, predicados
            )
            ctes.append((f"m{i}", cuerpo, [m.nombre for m in mets]))
            parametros.extend(params)          # el orden importa: CTE por CTE

        # Sin un solo CTE no hay ninguna tabla que leer, y el SQL saldria como
        # `WITH  SELECT … FROM`, que no es SQL. Pasa con una compuesta que no
        # depende de nada —`0.05`, un objetivo escrito a mano— pedida sola: es
        # una constante, y una constante no tiene filas propias. Acompañada de
        # cualquier otra metrica funciona sin mas, porque entonces si hay CTE.
        if not ctes:
            sueltas = ", ".join(c.metricas)
            raise ErrorModelo(
                f"Esta consulta no pide ninguna cifra que salga de una tabla"
                + (f": {sueltas} no depende de ninguna metrica de un hecho. "
                   f"Pidela junto a la cifra con la que se compara."
                   if c.metricas else ". Elige al menos una metrica."))

        # Donde quedo cada metrica base, para poder nombrarla desde fuera.
        donde = {m: n for n, _, ms in ctes for m in ms}

        # Lo que hay que calcular una capa antes: las ventanas de tiempo metidas
        # dentro de otras. Se juntan las de todas las metricas pedidas, porque la
        # capa es una sola para la consulta entera.
        # Se guarda tambien de que depende cada una: la capa de abajo tambien
        # suma meses, asi que le toca la misma revision —no se acumula un conteo
        # de valores distintos— y sin las dependencias esa revision no puede
        # correr.
        intermedias: dict[str, tuple[str, list[str], str]] = {}
        for nombre in c.metricas:
            met = self.m.metricas[nombre]
            if met.compuesta:
                comp = self.m.sql_compuesta(met)
                for marca, sql_i in comp.intermedias.items():
                    intermedias[marca] = (sql_i, comp.dependencias, nombre)

        def expresion(nombre: str, sitio: dict[str, str], prefijo: str) -> str:
            met = self.m.metricas[nombre]
            if not met.compuesta:
                return f"{sitio[nombre]}.{_cita(nombre)}"
            comp = self.m.sql_compuesta(met)
            sql_c = _calificar_metricas(comp.sql, sitio)
            if COL_PERIODO in sql_c:
                sql_c = self._con_tiempo(nombre, sql_c, comp.dependencias, dims,
                                         prefijo)
            return sql_c

        def columnas_pedidas(sitio: dict[str, str], prefijo: str) -> list[str]:
            """
            Solo lo que se pidio, en el orden en que se pidio.

            Las dependencias que se metieron para poder calcular una compuesta se
            quedan dentro: quien pide el porcentaje de logro pidio una columna, no
            tres.
            """
            return [f"{expresion(n, sitio, prefijo)} AS {_cita(n)}"
                    if self.m.metricas[n].compuesta
                    else expresion(n, sitio, prefijo)
                    for n in c.metricas]

        if not dims:
            # Sin desglose: los CTE tienen una sola fila cada uno. Una metrica con
            # capa intermedia no llega aqui: `_con_tiempo` ya exige una columna de
            # meses en el desglose, y sin desglose no hay ninguna.
            froms = ", ".join(n for n, _, _ in ctes)
            partes = ",\n".join(f"{n} AS (\n  {b}\n)" for n, b, _ in ctes)
            return ConsultaCompilada(
                f"WITH {partes}\nSELECT "
                + ", ".join(columnas_pedidas(donde, "e.")) +
                f"\nFROM {froms}", parametros
            )

        # Espina dorsal: todas las combinaciones de dimension que aparecen en
        # cualquiera de las metricas. Asi no se pierde un mes con objetivo pero
        # sin venta, ni al contrario.
        cols = ", ".join(_cita(cd) for cd in cols_dim)
        espina = "\n  UNION\n  ".join(f"SELECT {cols} FROM {n}" for n, _, _ in ctes)

        joins = []
        for n, _, _ms in ctes:
            cond = " AND ".join(
                f"e.{_cita(cd)} IS NOT DISTINCT FROM {n}.{_cita(cd)}" for cd in cols_dim
            )
            joins.append(f"LEFT JOIN {n} ON {cond}")

        partes = ",\n".join(f"{n} AS (\n  {b}\n)" for n, b, _ in ctes)

        if intermedias:
            # Dos capas. Abajo se calcula el acumulado de cada mes; arriba se
            # desplaza doce meses. En una sola no cabe: una ventana no puede ir
            # dentro de otra, y ensanchar el marco no vale porque el ancho
            # dependeria del mes de cada fila.
            sel_capa = (
                [f"e.{_cita(cd)} AS {_cita(cd)}" for cd in cols_dim]
                + [f"{n}.{_cita(m)} AS {_cita(m)}" for n, _, ms in ctes for m in ms]
                + [f"{self._con_tiempo(duena, _calificar_metricas(sql_i, donde), deps, dims)}"
                   f" AS {_cita(k)}"
                   for k, (sql_i, deps, duena) in intermedias.items()]
            )
            arriba = {**{m: "b" for _n, _b, ms in ctes for m in ms},
                      **{k: "b" for k in intermedias}}
            sel = ([f"b.{_cita(cd)}" for cd in cols_dim]
                   + columnas_pedidas(arriba, "b."))
            sql = (
                f"WITH {partes},\nespina AS (\n  {espina}\n),\n"
                f"capa1 AS (\n  SELECT\n    " + ",\n    ".join(sel_capa) +
                f"\n  FROM espina AS e\n  " + "\n  ".join(joins) + "\n)\n"
                f"SELECT\n  " + ",\n  ".join(sel) +
                f"\nFROM capa1 AS b"
                f"\nORDER BY " + ", ".join(f"b.{_cita(cd)}" for cd in cols_dim) +
                f"\nLIMIT {int(c.limite)}"
            )
            return ConsultaCompilada(sql, parametros)

        sel = [f"e.{_cita(cd)}" for cd in cols_dim] + columnas_pedidas(donde, "e.")
        sql = (
            f"WITH {partes},\nespina AS (\n  {espina}\n)\n"
            f"SELECT\n  " + ",\n  ".join(sel) +
            f"\nFROM espina AS e\n" + "\n".join(joins) +
            f"\nORDER BY " + ", ".join(f"e.{_cita(cd)}" for cd in cols_dim) +
            f"\nLIMIT {int(c.limite)}"
        )
        # La espina repite los CTE en su UNION, pero SQL los referencia por
        # nombre: los parametros se ligan una sola vez, en el orden de los CTE.
        return ConsultaCompilada(sql, parametros)


# --------------------------------------------------------------------------- #
# Estados asociativos
# --------------------------------------------------------------------------- #

class MotorAsociativo:
    """
    Calcula los estados verde / blanco / gris claro / gris de Qlik.

      seleccionado : el usuario lo eligio explicitamente
      posible      : sobrevive a las selecciones de OTROS campos
      alternativo  : seria posible, pero hay una seleccion en su propio campo
                     que no lo incluye
      excluido     : no sobrevive a las selecciones de otros campos
    """

    def __init__(self, modelo: Modelo, con):
        self.m = modelo
        self.con = con

    def _valores(self, entidad: str, campo: str) -> list[Any]:
        tabla = self.m.entidades[entidad].tabla
        filas = self.con.execute(
            f"SELECT DISTINCT {_cita(campo)} FROM {_cita(tabla)} "
            f"WHERE {_cita(campo)} IS NOT NULL ORDER BY 1"
        ).fetchall()
        return [f[0] for f in filas]

    def _alcanzables(self, entidad: str, campo: str,
                     selecciones: dict[str, list[Any]]) -> set[Any] | None:
        """
        Valores del campo alcanzables dadas las selecciones. Devuelve None si no
        hay ninguna seleccion relevante (todo es posible).

        A diferencia de la agregacion, aqui la ambiguedad de rutas se resuelve
        por UNION: un valor es alcanzable si lo es por cualquier camino.
        """
        relevantes = {k: v for k, v in selecciones.items()
                      if v and k != f"{entidad}.{campo}"}
        if not relevantes:
            return None

        alcanzables: set[Any] | None = None
        for sel_campo, valores in relevantes.items():
            ent_sel, campo_sel = sel_campo.split(".")
            # atravesar_hechos=True: aqui los hechos SI son el puente. Es como
            # una seleccion de Modelo alcanza a Estado pasando por fact_venta.
            rutas = self.m.rutas_minimas(entidad, ent_sel, atravesar_hechos=True)
            if not rutas:
                raise SinRuta(entidad, ent_sel)

            por_este_campo: set[Any] = set()
            for ruta in rutas:                       # union sobre rutas
                alias = {e: f"t{i}" for i, e in enumerate(ruta)}
                sql = (
                    f"SELECT DISTINCT {alias[entidad]}.{_cita(campo)}\n"
                    f"FROM {_cita(self.m.entidades[entidad].tabla)} AS {alias[entidad]}\n"
                )
                comp = Compilador(self.m)
                if len(ruta) > 1:
                    sql += "  " + comp._sql_join(ruta, alias) + "\n"
                marcas = ", ".join("?" for _ in valores)
                sql += f"WHERE {alias[ent_sel]}.{_cita(campo_sel)} IN ({marcas})"
                filas = self.con.execute(sql, valores).fetchall()
                por_este_campo.update(f[0] for f in filas)

            # Interseccion entre campos distintos: las selecciones se acumulan.
            alcanzables = por_este_campo if alcanzables is None else (alcanzables & por_este_campo)
        return alcanzables

    def estados(self, entidad: str, campo: str,
                selecciones: dict[str, list[Any]]) -> dict[str, list[Any]]:
        clave = f"{entidad}.{campo}"
        todos = self._valores(entidad, campo)
        propias = set(selecciones.get(clave) or [])
        alcanzables = self._alcanzables(entidad, campo, selecciones)
        universo = set(todos) if alcanzables is None else alcanzables

        res: dict[str, list[Any]] = {
            "seleccionado": [], "posible": [], "alternativo": [], "excluido": [],
        }
        for v in todos:
            if v in propias:
                res["seleccionado"].append(v)
            elif v not in universo:
                res["excluido"].append(v)
            elif propias:
                res["alternativo"].append(v)
            else:
                res["posible"].append(v)
        return res
