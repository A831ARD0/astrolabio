"""
La definicion del modelo como estructura, y su ida y vuelta a YAML.

Por que existe esta capa aparte del motor: el motor
(`semantic/engine.py`) lee del YAML **solo lo que necesita para compilar SQL** e
ignora el resto — jerarquias, perspectivas, descripciones, la disposicion del
lienzo. Si la interfaz guardara serializando los objetos del motor, cada vez que
alguien tocara una relacion se **perderia en silencio** todo lo que el motor no
mira.

Asi que el camino de guardado no pasa por los objetos del motor: se edita el
mapa crudo del YAML y el motor solo se usa para VALIDAR que lo editado compila.
Lo que el motor no entiende, sobrevive.

Limitacion consciente: los comentarios del YAML si se pierden al guardar desde la
interfaz (`safe_load` no los conserva). Quien quiera comentarios los pone editando
el texto, que la interfaz tambien permite.
"""

from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from semantic.formula import Contexto, ErrorFormula
from semantic.formula import compilar as compilar_formula
from semantic.politica import PoliticaDef, revisar_politicas

TIPOS_CAMPO = ("entero", "decimal", "texto", "fecha", "booleano")
ROLES_CAMPO = ("clave", "clave_externa", "dimension", "medida_base")
CARDINALIDADES = ("muchos_a_uno", "uno_a_uno", "muchos_a_muchos")
DIRECCIONES = ("ambas", "una")


class _Base(BaseModel):
    # extra="allow": todo lo que la interfaz no conozca (una clave nueva, algo
    # que agregue una version futura) se conserva tal cual en vez de borrarse.
    model_config = ConfigDict(extra="allow")


class CampoDef(_Base):
    nombre: str = Field(min_length=1, max_length=120)
    tipo: Literal[TIPOS_CAMPO]           # type: ignore[valid-type]
    rol: Literal[ROLES_CAMPO]            # type: ignore[valid-type]
    etiqueta: str | None = None
    visible: bool = True
    pii: bool = False
    #: La columna no se repite, aunque no sea la clave primaria.
    #:
    #: Una entidad tiene UNA clave primaria: es la que la identifica. Pero un
    #: catalogo de sucursales suele traer varios identificadores que tampoco se
    #: repiten —el propio, el del sistema de origen, el del CRM—, y cada uno es
    #: por donde se une un hecho distinto. Lo que una relacion muchos-a-uno
    #: necesita del lado «uno» no es ser la clave primaria: es no repetirse.
    #:
    #: Sin esto, la unica forma de quitar el aviso «no es clave primaria» era
    #: cambiar la clave primaria de la entidad —y entonces el aviso aparecia en
    #: las otras ocho relaciones que unian contra la anterior—.
    unico: bool = False


class OrigenDef(_Base):
    tabla: str = Field(min_length=1, max_length=160)


class EntidadDef(_Base):
    nombre: str = Field(min_length=1, max_length=120)
    tipo: Literal["dimension", "hecho"]
    origen: OrigenDef
    campos: list[CampoDef] = Field(min_length=1)
    clave_primaria: str | None = None
    grano: list[str] = []

    @field_validator("campos")
    @classmethod
    def sin_campos_repetidos(cls, v: list[CampoDef]) -> list[CampoDef]:
        nombres = [c.nombre for c in v]
        repetidos = {n for n in nombres if nombres.count(n) > 1}
        if repetidos:
            raise ValueError(f"campos repetidos: {', '.join(sorted(repetidos))}")
        return v


class RelacionDef(_Base):
    """
    Una union entre dos entidades.

    `activa` existe porque dos tablas se relacionan por mas de una columna mas a
    menudo de lo que parece: un hecho con fecha de alta, fecha de cierre y fecha
    de entrega toca el calendario tres veces. Las tres son ciertas y las tres se
    quieren dejar escritas, pero al agregar solo puede mandar UNA —si mandaran
    dos, cada consulta tendria dos caminos igual de validos hacia el calendario y
    el total dependeria de cual eligiera el compilador—. Asi que una activa y las
    demas apuntadas, que es tambien como lo resuelve Power BI.
    """

    desde: list[str] = Field(min_length=2, max_length=2)   # [entidad, campo]
    hasta: list[str] = Field(min_length=2, max_length=2)
    cardinalidad: Literal[CARDINALIDADES]                  # type: ignore[valid-type]
    direccion_filtro: Literal[DIRECCIONES] = "ambas"       # type: ignore[valid-type]
    activa: bool = True


class TablaMedidasDef(_Base):
    """
    Una tabla que el usuario inventa para guardar metricas, sin datos propios.

    No es una entidad y no puede serlo: una entidad tiene tabla, columnas y
    relaciones, y sale en el diagnostico como huerfana si no se une a nada. Esto es
    solo un cajon con nombre — «KPIs de venta», «Indicadores de taller»— para que
    treinta metricas no sean una lista de treinta renglones donde no se encuentra
    ninguna.

    Es la «tabla de medidas» de Power BI, y como alli **solo organiza**: de donde
    salen las cifras lo sigue diciendo el hecho de cada metrica.
    """

    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None


class MetricaDef(_Base):
    nombre: str = Field(min_length=1, max_length=120)
    etiqueta: str
    #: El hecho del que se calcula: es lo que decide el FROM del SQL.
    entidad: str
    #: En que tabla de medidas se muestra. None = debajo de su propio hecho, que es
    #: como estaban todas antes de que esto existiera.
    tabla_medidas: str | None = None
    expresion: str = Field(min_length=1)
    formato: str = "numero"


class Definicion(_Base):
    """
    El modelo completo. `disposicion` guarda la posicion de cada nodo en el
    lienzo: va dentro del modelo a proposito, para que abrirlo en otra maquina se
    vea igual, y viaje con la version.
    """
    modelo: str = Field(min_length=1, max_length=120)
    version: int = 1
    entidades: list[EntidadDef] = Field(min_length=1)
    tablas_medidas: list[TablaMedidasDef] = []
    relaciones: list[RelacionDef] = []
    metricas: list[MetricaDef] = []
    politicas: list[PoliticaDef] = []
    disposicion: dict[str, dict[str, float]] = {}

    @field_validator("entidades")
    @classmethod
    def sin_entidades_repetidas(cls, v: list[EntidadDef]) -> list[EntidadDef]:
        nombres = [e.nombre for e in v]
        repetidos = {n for n in nombres if nombres.count(n) > 1}
        if repetidos:
            raise ValueError(f"entidades repetidas: {', '.join(sorted(repetidos))}")
        return v

    def revisar_referencias(self) -> list[str]:
        """
        Errores que Pydantic no puede ver porque cruzan objetos: una relacion que
        apunta a una entidad inexistente, una metrica sobre una entidad que no
        esta, una clave primaria que no es campo de su entidad.

        Se revisa aqui y no al compilar porque el mensaje tiene que decir QUE
        esta mal, no reventar con un KeyError a mitad de una consulta.
        """
        errores: list[str] = []
        entidades = {e.nombre: e for e in self.entidades}

        for e in self.entidades:
            campos = {c.nombre for c in e.campos}
            if e.clave_primaria and e.clave_primaria not in campos:
                errores.append(
                    f"La entidad '{e.nombre}' declara clave primaria "
                    f"'{e.clave_primaria}', que no esta entre sus campos.")
            for g in e.grano:
                if g not in campos:
                    errores.append(
                        f"El grano de '{e.nombre}' menciona '{g}', "
                        f"que no es uno de sus campos.")

        for i, r in enumerate(self.relaciones, 1):
            for extremo, (ent, campo) in (("desde", r.desde), ("hasta", r.hasta)):
                if ent not in entidades:
                    errores.append(
                        f"La relacion {i} ({extremo}) apunta a la entidad "
                        f"'{ent}', que no existe.")
                elif campo not in {c.nombre for c in entidades[ent].campos}:
                    errores.append(
                        f"La relacion {i} ({extremo}) usa el campo "
                        f"'{ent}.{campo}', que no existe.")
            if r.desde[0] == r.hasta[0]:
                errores.append(
                    f"La relacion {i} une '{r.desde[0]}' consigo misma.")

        # Dos activas entre el mismo par de tablas dejan dos caminos igual de
        # validos, y entonces el total depende de cual elija el compilador. Se
        # bloquea al guardar y no en la consulta: descubrirlo en un tablero seis
        # meses despues es descubrirlo tarde.
        activas: dict[tuple[str, str], list[int]] = {}
        for i, r in enumerate(self.relaciones, 1):
            if not r.activa:
                continue
            par = tuple(sorted((r.desde[0], r.hasta[0])))
            activas.setdefault(par, []).append(i)  # type: ignore[arg-type]
        for (a, b), cuales in activas.items():
            if len(cuales) > 1:
                errores.append(
                    f"Hay {len(cuales)} relaciones activas entre '{a}' y '{b}' "
                    f"(la {', la '.join(str(c) for c in cuales)}). Solo una "
                    f"puede estar activa: deja activa la que se usa al agregar y "
                    f"marca las demas como inactivas.")

        for m in self.metricas:
            if m.entidad not in entidades:
                errores.append(
                    f"La metrica '{m.nombre}' se calcula desde la entidad "
                    f"'{m.entidad}', que no existe.")

        # Las tablas de medidas: nombres unicos, y que no se llamen como una
        # entidad. Dos cosas distintas con el mismo nombre en el mismo panel no es
        # un detalle de presentacion — es no saber que se esta mirando.
        nombres_tm = [t.nombre for t in self.tablas_medidas]
        for repetido in sorted({n for n in nombres_tm if nombres_tm.count(n) > 1}):
            errores.append(f"Hay dos tablas de medidas llamadas '{repetido}'.")
        for choque in sorted(set(nombres_tm) & set(entidades)):
            errores.append(
                f"'{choque}' es a la vez una entidad y una tabla de medidas. "
                f"Cambiale el nombre a una de las dos.")

        for m in self.metricas:
            if m.tabla_medidas and m.tabla_medidas not in set(nombres_tm):
                errores.append(
                    f"La metrica '{m.nombre}' dice mostrarse en la tabla de "
                    f"medidas '{m.tabla_medidas}', que no existe.")

        # Que la formula al menos COMPILE. Lo que no compila no se guarda: una
        # metrica rota no falla al guardarla, falla en el primer tablero que la
        # use, y para entonces quien la escribio ya no esta mirando.
        #
        # Solo compilar, no la revision completa: «este campo no existe» y «este
        # campo esta fuera de la agregacion» salen en el diagnostico y en el
        # editor de la metrica, en rojo y con la linea señalada, pero no impiden
        # guardar. Hay modelos que apoyan una metrica en una columna de una tabla
        # unida, y romperles el guardado al actualizar seria cobrarles el cambio
        # a ellos.
        for m in self.metricas:
            if m.entidad not in entidades:
                continue
            ent = entidades[m.entidad]
            contexto = Contexto(
                campos={c.nombre for c in ent.campos},
                metricas={o.nombre: o.expresion for o in self.metricas
                          if o.entidad == m.entidad and o.nombre != m.nombre},
            )
            try:
                compilar_formula(m.expresion, contexto)
            except ErrorFormula as e:
                for f in e.fallos:
                    errores.append(
                        f"La formula de '{m.nombre}' (linea {f.con_posicion(m.expresion)['linea']}): "
                        f"{f.mensaje}")
            except Exception as e:                       # pragma: no cover
                errores.append(f"La formula de '{m.nombre}' no se pudo leer: {e}")

        nombres_metrica = [m.nombre for m in self.metricas]
        for n in {n for n in nombres_metrica if nombres_metrica.count(n) > 1}:
            errores.append(f"Hay mas de una metrica llamada '{n}'.")

        # Una metrica y una entidad con el mismo nombre hacen ambigua cualquier
        # referencia en la interfaz.
        for n in set(nombres_metrica) & set(entidades):
            errores.append(
                f"'{n}' es a la vez nombre de metrica y de entidad.")

        errores.extend(self._politicas()[0])
        return errores

    def revisar_politicas(self) -> tuple[list[str], list[str]]:
        """(errores, avisos) de las politicas. Los avisos no impiden guardar."""
        return self._politicas()

    def _politicas(self) -> tuple[list[str], list[str]]:
        campos_por_entidad = {
            e.nombre: {c.nombre for c in e.campos} for e in self.entidades
        }
        return revisar_politicas(
            [p.model_dump(exclude_none=True, mode="json") for p in self.politicas],
            campos_por_entidad,
        )

    def a_yaml(self) -> str:
        return volcar_yaml(self.model_dump(exclude_none=True, mode="json"))


def volcar_yaml(crudo: dict) -> str:
    """
    Vuelca el mapa a YAML en un orden estable.

    El orden importa: este archivo se versiona y se revisa en diff. Si las claves
    salieran en orden alfabetico o al azar, cada guardado produciria un diff
    ilegible y nadie revisaria nada.
    """
    orden = ["modelo", "version", "entidades", "tablas_medidas", "relaciones",
             "metricas", "politicas", "disposicion"]
    ordenado = {k: crudo[k] for k in orden if k in crudo and crudo[k] not in ([], {})}
    for k, v in crudo.items():                      # claves futuras al final
        if k not in ordenado and k not in orden:
            ordenado[k] = v
    return yaml.safe_dump(ordenado, allow_unicode=True, sort_keys=False,
                          default_flow_style=False, width=100)


def desde_yaml(texto: str) -> Definicion:
    crudo = yaml.safe_load(texto)
    if not isinstance(crudo, dict):
        raise ValueError("El YAML del modelo debe ser un mapa de claves.")
    return Definicion.model_validate(crudo)
