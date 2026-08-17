"""
Modelo semantico y ejecucion de consultas.

Las versiones del modelo son inmutables: guardar crea una version nueva. Editar
el modelo nunca reescribe lo que un dashboard publicado esta usando.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Literal

import yaml

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.analitico import ejecutar_consulta, ejecutar_muestra, estados_asociativos
from app.auditoria import registrar
from app.errores_motor import en_castellano
from app.exportar import (
    Procedencia, TOPE_FILAS, a_csv, a_excel, nombre_archivo,
)
from app.dependencias import ContextoDep, SesionDep, UsuarioDep, exigir_rol
from app.modelos_db import BorradorModelo, Dashboard
from app.modelos_db import Modelo as ModeloDB
from app.modelos_db import Rol, Usuario, VersionModelo, iso
from app.politicas import PoliticaInvalida
from semantic.definicion import Definicion, desde_yaml, volcar_yaml
from semantic.formula import (
    Contexto, ContextoCompuesta, ErrorFormula, catalogo_para_pantalla,
    compilar as compilar_formula, compilar_compuesta,
    revisar as revisar_formula, revisar_compuesta,
)
from semantic.politica import PoliticaDef, atributos_requeridos
from semantic.engine import Consulta, ErrorModelo
from semantic.engine import Metrica as MetricaSemantica
from semantic.engine import Modelo as ModeloSemantico

router = APIRouter(prefix="/api/modelos", tags=["modelos"])


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class CrearModelo(BaseModel):
    """
    Un modelo nuevo, de dos maneras.

    `yaml` es el camino de quien ya tiene el texto —una migracion, un respaldo, un
    modelo escrito a mano—. `definicion` es el de la interfaz, que no deberia tener
    que saber serializar YAML para crear algo. Uno de los dos, no los dos: si
    llegaran ambos habria que decidir cual manda, y esa decision no la puede tomar
    el servidor sin adivinar.
    """

    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None
    yaml: str | None = None
    definicion: Definicion | None = None

    @model_validator(mode="after")
    def uno_de_los_dos(self):
        if (self.yaml is None) == (self.definicion is None):
            raise ValueError("manda 'yaml' o 'definicion', exactamente uno")
        return self

    def texto(self) -> str:
        if self.definicion is not None:
            return self.definicion.a_yaml()
        assert self.yaml is not None
        return self.yaml


class NuevaVersion(BaseModel):
    yaml: str
    notas: str | None = None


class ModeloSalida(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    version_actual: int


class PeticionConsulta(BaseModel):
    dimensiones: list[str] = []
    metricas: list[str]
    filtros: list[dict] = []
    rutas_elegidas: dict[str, str] = {}
    limite: int = Field(default=5000, le=100_000)


class GuardarDefinicion(BaseModel):
    definicion: Definicion
    notas: str | None = None


class GuardarBorrador(BaseModel):
    definicion: Definicion


class Publicar(BaseModel):
    notas: str | None = None


class ProbarMetrica(BaseModel):
    #: `None` = compuesta: se calcula sobre las metricas ya guardadas.
    entidad: str | None = None
    expresion: str
    formato: str = "numero"
    dimensiones: list[str] = []
    limite: int = Field(default=20, le=500)


class RevisarFormula(BaseModel):
    """
    Lo que hace falta para revisar una formula sin haberla guardado.

    `campos` y `metricas` llegan del navegador y NO se leen del modelo guardado a
    proposito: se esta escribiendo sobre un borrador que puede tener una entidad
    o una metrica que el servidor todavia no ha visto, y revisar contra lo
    guardado subrayaria en rojo un campo que existe en la pantalla de quien
    escribe. Si no vienen, se cae al modelo guardado, que es lo correcto para
    quien llame a esta ruta desde fuera.
    """

    #: `None` = es una metrica compuesta y se revisa contra `metricas_del_modelo`.
    entidad: str | None = None
    expresion: str
    campos: list[str] | None = None
    metricas: dict[str, str] | None = None
    #: Solo para una compuesta: TODAS las metricas del modelo, con su expresion
    #: si tambien son compuestas y `None` si se agregan desde un hecho. Una
    #: compuesta puede nombrar cualquiera, que es su motivo de ser.
    metricas_del_modelo: dict[str, str | None] | None = None


class VistaPrevia(BaseModel):
    """
    Una consulta contra el modelo que se tiene EN PANTALLA.

    `definicion` llega del navegador por la misma razon que en `RevisarFormula`:
    quien esta editando quiere ver el resultado de las metricas que acaba de
    escribir, y esas todavia no estan publicadas —puede que ni guardadas—. Sin
    esto habria que publicar para poder mirar el numero, que es exactamente al
    reves de como se trabaja: primero se mira, y si cuadra se publica.

    Si no viene, se cae al borrador guardado, y si tampoco hay, a la version
    vigente.
    """

    definicion: Definicion | None = None
    dimensiones: list[str] = []
    metricas: list[str] = []
    filtros: list[dict] = []
    rutas_elegidas: dict[str, str] = {}
    limite: int = Field(default=200, le=5000)


class MuestraEntidad(BaseModel):
    """Filas crudas de una entidad, para ver que hay dentro de la tabla."""

    definicion: Definicion | None = None
    entidad: str
    limite: int = Field(default=50, le=500)


class PeticionExportar(PeticionConsulta):
    formato: Literal["xlsx", "csv"] = "xlsx"
    titulo: str = "Astrolabio"
    # El tope real lo revisa la ruta con TOPE_FILAS; aqui solo se acota lo absurdo.
    limite: int = Field(default=50_000, le=TOPE_FILAS)


class PeticionAsociativa(BaseModel):
    entidad: str
    campo: str
    selecciones: dict[str, list] = {}


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _cargar_semantico(yaml_texto: str) -> ModeloSemantico:
    """
    El motor semantico lee de archivo. Se escribe a un temporal en vez de
    cambiar su firma, para que el mismo motor sirva igual desde la API y desde
    los scripts de prueba.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                     encoding="utf-8") as f:
        f.write(yaml_texto)
        ruta = f.name
    try:
        return ModeloSemantico(ruta)
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"El YAML del modelo no es valido: {e}")
    finally:
        Path(ruta).unlink(missing_ok=True)


def _version_vigente(sesion: SesionDep, modelo_id: int) -> VersionModelo:
    v = sesion.scalar(
        select(VersionModelo)
        .where(VersionModelo.modelo_id == modelo_id)
        .order_by(VersionModelo.version.desc())
        .limit(1)
    )
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "El modelo no tiene ninguna version guardada")
    return v


def _version_exacta(sesion: SesionDep, modelo_id: int,
                    version: int) -> VersionModelo:
    """Una version concreta. Sirve para ver el modelo como estaba, sin restaurar."""
    v = sesion.scalar(
        select(VersionModelo)
        .where(VersionModelo.modelo_id == modelo_id,
               VersionModelo.version == version)
    )
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"El modelo no tiene la version {version}")
    return v


def _existe(sesion: SesionDep, modelo_id: int) -> ModeloDB:
    m = sesion.get(ModeloDB, modelo_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado")
    return m


def _modelo_en_curso(sesion: SesionDep, modelo_id: int,
                     definicion: Definicion | None) -> ModeloSemantico:
    """
    El modelo tal como lo esta viendo quien edita, y no el que ven los tableros.

    Por orden: lo que manda el navegador, el borrador guardado, la version
    vigente. Es la escalera de «lo mas fresco que haya», y existe para que mirar
    un resultado nunca obligue a publicar antes.
    """
    _existe(sesion, modelo_id)
    if definicion is not None:
        return _cargar_semantico(definicion.a_yaml())
    borrador = sesion.get(BorradorModelo, modelo_id)
    if borrador is not None:
        return _cargar_semantico(borrador.yaml)
    return _cargar_semantico(_version_vigente(sesion, modelo_id).yaml)


def _resumen_borrador(sesion: SesionDep, b: BorradorModelo) -> dict:
    """Quien lo tiene a medias y desde cuando. Sale junto con la definicion."""
    autor = sesion.get(Usuario, b.actualizado_por) if b.actualizado_por else None
    return {
        "desde_version": b.desde_version,
        "actualizado_en": iso(b.actualizado_en),
        "actualizado_por": autor.email if autor else None,
    }


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[ModeloSalida])
def listar(sesion: SesionDep, _: UsuarioDep):
    salida = []
    for m in sesion.scalars(select(ModeloDB).order_by(ModeloDB.id)):
        ultima = max((v.version for v in m.versiones), default=0)
        salida.append(ModeloSalida(id=m.id, nombre=m.nombre,
                                   descripcion=m.descripcion,
                                   version_actual=ultima))
    return salida


@router.get("/funciones")
def funciones(_: UsuarioDep):
    """
    El catalogo de funciones de formula: firma, resumen y ejemplo de cada una.

    Va antes que `/{modelo_id}/…` porque no depende de ningun modelo — el
    lenguaje es el mismo para todos— y asi el editor lo pide una sola vez y lo
    guarda en cache para el autocompletado.
    """
    return {"funciones": catalogo_para_pantalla()}


@router.post("", response_model=ModeloSalida, status_code=201)
def crear(cuerpo: CrearModelo, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    if cuerpo.definicion is not None:
        errores = cuerpo.definicion.revisar_referencias()
        if errores:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                {"errores": errores})
    texto = cuerpo.texto()
    _cargar_semantico(texto)            # valida antes de guardar

    if sesion.scalar(select(func.count()).select_from(ModeloDB)
                     .where(ModeloDB.nombre == cuerpo.nombre)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un modelo con ese nombre")

    modelo = ModeloDB(nombre=cuerpo.nombre, descripcion=cuerpo.descripcion)
    sesion.add(modelo)
    sesion.flush()
    sesion.add(VersionModelo(modelo_id=modelo.id, version=1, yaml=texto,
                             notas="Version inicial", creado_por=actor.id))
    registrar(sesion, accion="modelo_creado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="modelo", objeto_id=modelo.id,
              detalle={"nombre": modelo.nombre})
    return ModeloSalida(id=modelo.id, nombre=modelo.nombre,
                        descripcion=modelo.descripcion, version_actual=1)


@router.post("/{modelo_id}/versiones", status_code=201)
def nueva_version(modelo_id: int, cuerpo: NuevaVersion, sesion: SesionDep,
                  actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """Nunca sobreescribe: crea una version nueva e inmutable."""
    semantico = _cargar_semantico(cuerpo.yaml)
    if sesion.get(ModeloDB, modelo_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado")

    ultima = sesion.scalar(
        select(func.coalesce(func.max(VersionModelo.version), 0))
        .where(VersionModelo.modelo_id == modelo_id)
    )
    v = VersionModelo(modelo_id=modelo_id, version=ultima + 1, yaml=cuerpo.yaml,
                      notas=cuerpo.notas, creado_por=actor.id)
    sesion.add(v)
    sesion.flush()

    problemas = semantico.diagnosticar()
    registrar(sesion, accion="modelo_version_creada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"version": v.version, "notas": cuerpo.notas,
                       "problemas_criticos": sum(
                           1 for p in problemas if p["gravedad"] == "critico")})
    return {"version": v.version, "problemas": problemas}


@router.get("/{modelo_id}/versiones")
def versiones(modelo_id: int, sesion: SesionDep, _: UsuarioDep):
    """
    Historial. Las versiones son inmutables: esta lista es el registro de como
    fue cambiando el modelo, y cada dashboard esta anclado a una de ellas.
    """
    if sesion.get(ModeloDB, modelo_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado")
    filas = sesion.scalars(
        select(VersionModelo).where(VersionModelo.modelo_id == modelo_id)
        .order_by(VersionModelo.version.desc())
    )
    salida = []
    for v in filas:
        # Se parsea en vez de contar lineas: las metricas y las politicas tambien
        # empiezan por "- nombre:", asi que contar daba 18 donde habia 11.
        try:
            crudo = yaml.safe_load(v.yaml) or {}
            conteo = {
                "entidades": len(crudo.get("entidades") or []),
                "relaciones": len(crudo.get("relaciones") or []),
                "metricas": len(crudo.get("metricas") or []),
            }
        except Exception:
            conteo = {"entidades": 0, "relaciones": 0, "metricas": 0}
        salida.append({"version": v.version, "notas": v.notas,
                       "creado_en": iso(v.creado_en), **conteo})
    return {"versiones": salida}


@router.get("/{modelo_id}/definicion")
def leer_definicion(modelo_id: int, sesion: SesionDep, _: UsuarioDep,
                    version: int | None = None):
    """
    Lo que hay que abrir en el lienzo, mas su diagnostico.

    Si hay un borrador sin publicar, **es lo que se devuelve**: es el trabajo en
    curso, y abrir el editor en la version publicada haria que los cambios
    guardados pero no publicados parecieran perdidos. Pedir una `version`
    concreta salta el borrador — es la via para mirar el historial.

    Devuelve el YAML crudo tal cual, sin pasar por los objetos del motor: el
    motor ignora jerarquias, perspectivas y la disposicion del lienzo, y
    serializar desde el las borraria en silencio.
    """
    vigente = _version_vigente(sesion, modelo_id)
    borrador = None if version else sesion.get(BorradorModelo, modelo_id)
    if borrador is not None:
        texto, num = borrador.yaml, borrador.desde_version
    else:
        v = _version_exacta(sesion, modelo_id, version) if version else vigente
        texto, num = v.yaml, v.version

    try:
        definicion = desde_yaml(texto)
    except Exception as e:
        que = "El borrador" if borrador is not None else f"La version {num}"
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"{que} no se puede leer: {e}")
    return {
        "version": num,
        "es_vigente": num == vigente.version,
        "definicion": definicion.model_dump(exclude_none=True, mode="json"),
        "problemas": _cargar_semantico(texto).diagnosticar(),
        "borrador": _resumen_borrador(sesion, borrador) if borrador else None,
        "version_vigente": vigente.version,
    }


@router.put("/{modelo_id}/definicion", status_code=201)
def guardar_definicion(modelo_id: int, cuerpo: GuardarDefinicion,
                       sesion: SesionDep,
                       actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Publica la definicion como una version nueva.

    Dos validaciones distintas, y las dos hacen falta:
      1. referencias cruzadas — dicen QUE esta mal y donde.
      2. el motor — dice si el modelo compila de verdad.

    Publicar cierra el borrador: lo que se acaba de publicar ES el borrador, y
    dejarlo ahi haria que el editor siguiera abriendo trabajo «sin publicar»
    identico a la version vigente, con el aviso puesto y nada que hacerle.
    """
    _existe(sesion, modelo_id)

    errores = cuerpo.definicion.revisar_referencias()
    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": errores})

    texto = cuerpo.definicion.a_yaml()
    semantico = _cargar_semantico(texto)

    ultima = sesion.scalar(
        select(func.coalesce(func.max(VersionModelo.version), 0))
        .where(VersionModelo.modelo_id == modelo_id))
    v = VersionModelo(modelo_id=modelo_id, version=ultima + 1, yaml=texto,
                      notas=cuerpo.notas, creado_por=actor.id)
    sesion.add(v)
    sesion.flush()

    borrador = sesion.get(BorradorModelo, modelo_id)
    if borrador is not None:
        sesion.delete(borrador)

    problemas = semantico.diagnosticar()
    registrar(sesion, accion="modelo_version_creada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"version": v.version, "notas": cuerpo.notas,
                       "entidades": len(cuerpo.definicion.entidades),
                       "problemas_criticos": sum(
                           1 for p in problemas if p["gravedad"] == "critico")})
    return {"version": v.version, "problemas": problemas, "yaml": texto}


# --------------------------------------------------------------------------- #
# Borrador: guardar sin publicar
#
# La regla del modelo semantico es que una version es inmutable, y esa regla no
# se toca. Lo que faltaba era el escalon de antes: un sitio donde probar sin
# comprometer a nadie. Un borrador se guarda, se descarta entero y se publica; lo
# que ven los tableros no cambia hasta ese ultimo paso.
# --------------------------------------------------------------------------- #

@router.put("/{modelo_id}/borrador")
def guardar_borrador(modelo_id: int, cuerpo: GuardarBorrador, sesion: SesionDep,
                     actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Guarda el trabajo en curso. NO crea version y NO cambia lo que ven los
    tableros.

    Se valida igual de fuerte que al publicar, a proposito. Un borrador que no
    compila se guardaria sin protestar y el error saldria dias despues, al
    publicar, cuando ya nadie recuerda que se estaba haciendo. Guardar seguido es
    justo el momento en que un error sale barato.
    """
    _existe(sesion, modelo_id)

    errores = cuerpo.definicion.revisar_referencias()
    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": errores})

    texto = cuerpo.definicion.a_yaml()
    semantico = _cargar_semantico(texto)
    vigente = _version_vigente(sesion, modelo_id)

    b = sesion.get(BorradorModelo, modelo_id)
    if b is None:
        b = BorradorModelo(modelo_id=modelo_id, yaml=texto,
                           desde_version=vigente.version,
                           actualizado_por=actor.id)
        sesion.add(b)
    else:
        b.yaml = texto
        b.actualizado_por = actor.id
    sesion.flush()

    # Sin auditar. Un borrador se guarda decenas de veces en una tarde y el
    # registro dejaria de servir para lo que sirve: saber que cambio de verdad.
    # Lo que se audita es publicar y descartar, que son los actos con efecto.
    return {"problemas": semantico.diagnosticar(),
            "borrador": _resumen_borrador(sesion, b), "yaml": texto}


@router.delete("/{modelo_id}/borrador")
def descartar_borrador(modelo_id: int, sesion: SesionDep,
                       actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Tira el borrador entero y deja el modelo como la version vigente.

    Devuelve la version a la que se vuelve en vez de 204: quien descarta necesita
    ver de inmediato sobre que quedo parado, y el editor tiene que recargar algo.
    """
    _existe(sesion, modelo_id)
    b = sesion.get(BorradorModelo, modelo_id)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Este modelo no tiene ningun borrador que descartar")
    sesion.delete(b)
    vigente = _version_vigente(sesion, modelo_id)
    registrar(sesion, accion="modelo_borrador_descartado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"vuelve_a_version": vigente.version,
                       "era_de": b.actualizado_por})
    return {"version": vigente.version}


@router.post("/{modelo_id}/publicar", status_code=201)
def publicar(modelo_id: int, cuerpo: Publicar, sesion: SesionDep,
             actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Convierte el borrador en una version inmutable y lo cierra.

    Publica lo que hay GUARDADO en el borrador, no lo que el navegador tenga en
    pantalla: si fuera lo segundo, dos pestañas abiertas publicarian cosas
    distintas segun cual apretara el boton.
    """
    _existe(sesion, modelo_id)
    b = sesion.get(BorradorModelo, modelo_id)
    if b is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No hay nada que publicar: el modelo no tiene cambios sin publicar.")

    semantico = _cargar_semantico(b.yaml)
    definicion = desde_yaml(b.yaml)
    errores = definicion.revisar_referencias()
    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": errores})

    ultima = sesion.scalar(
        select(func.coalesce(func.max(VersionModelo.version), 0))
        .where(VersionModelo.modelo_id == modelo_id))
    v = VersionModelo(modelo_id=modelo_id, version=ultima + 1, yaml=b.yaml,
                      notas=cuerpo.notas, creado_por=actor.id)
    sesion.add(v)
    # `desde_version` puede haber quedado atras si alguien publico mientras
    # tanto. Se anota en la auditoria en vez de rechazar: el borrador es uno solo
    # y compartido, asi que lo que se publica ya incluye el trabajo de los dos.
    partio_de = b.desde_version
    sesion.delete(b)
    sesion.flush()

    problemas = semantico.diagnosticar()
    registrar(sesion, accion="modelo_version_creada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"version": v.version, "notas": cuerpo.notas,
                       "desde_borrador": True, "partio_de": partio_de,
                       "entidades": len(definicion.entidades),
                       "problemas_criticos": sum(
                           1 for p in problemas if p["gravedad"] == "critico")})
    return {"version": v.version, "problemas": problemas}


# --------------------------------------------------------------------------- #
# Borrar el modelo
# --------------------------------------------------------------------------- #

@router.delete("/{modelo_id}", status_code=204)
def borrar(modelo_id: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Borra el modelo entero: sus versiones, su borrador y su historial.

    Se niega si algun tablero esta anclado a una de sus versiones, y dice CUALES.
    Podria borrarlos en cascada, y seria peor: quien borra un modelo de prueba no
    espera perder ademas un tablero que alguien mas publico sobre el. Que la
    pantalla ensene la lista y que la decida una persona.

    Solo administrador. Un editor puede crear y publicar versiones —todo eso deja
    rastro y se puede volver atras— pero esto no se deshace.
    """
    m = _existe(sesion, modelo_id)

    anclados = list(sesion.scalars(
        select(Dashboard)
        .join(VersionModelo, VersionModelo.id == Dashboard.version_modelo_id)
        .where(VersionModelo.modelo_id == modelo_id)
        .order_by(Dashboard.nombre)
    ))
    if anclados:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "mensaje": f"No se puede borrar '{m.nombre}': "
                       f"{len(anclados)} tablero(s) lo estan usando.",
            "tableros": [{"id": d.id, "nombre": d.nombre,
                          "publicado": d.publicado} for d in anclados],
        })

    versiones = len(m.versiones)
    registrar(sesion, accion="modelo_borrado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"nombre": m.nombre, "versiones": versiones})
    sesion.delete(m)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Politicas (seguridad por fila)
# --------------------------------------------------------------------------- #

def _cobertura(sesion: SesionDep, politicas: list[dict]) -> list[dict]:
    """
    Para cada politica, quien se quedaria sin ver nada.

    Una politica que necesita `region_id` y un usuario de ese rol que no lo tiene
    no producen un dato de mas: producen un 403 y a nadie se le avisa hasta que la
    persona llama. Este cruce es el que lo dice antes.
    """
    usuarios = list(sesion.scalars(select(Usuario).where(Usuario.activo.is_(True))))
    salida = []
    for pol in politicas:
        necesita = atributos_requeridos(str(pol.get("predicado", "")))
        roles = pol.get("aplica_a_roles") or []
        alcanzados, sin_atributo = [], []
        for u in usuarios:
            if u.rol == Rol.administrador:
                continue                       # a un administrador no le aplica
            if roles and u.rol.value not in roles:
                continue
            alcanzados.append(u.email)
            faltan = [c for c in necesita if c not in u.dict_atributos]
            if faltan:
                sin_atributo.append({"email": u.email, "faltan": faltan})
        salida.append({
            "politica": pol.get("nombre"),
            "atributos": necesita,
            "usuarios_alcanzados": alcanzados,
            "sin_atributo": sin_atributo,
        })
    return salida


@router.get("/{modelo_id}/politicas")
def leer_politicas(modelo_id: int, sesion: SesionDep,
                   _: Usuario = Depends(exigir_rol(Rol.administrador)),
                   version: int | None = None):
    """
    Las politicas de la version, con todo lo que hace falta para editarlas: las
    entidades y sus campos, los roles, y quien se queda fuera por falta de
    atributo.
    """
    v = (_version_exacta(sesion, modelo_id, version) if version
         else _version_vigente(sesion, modelo_id))
    try:
        definicion = desde_yaml(v.yaml)
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"La version {v.version} no se puede leer: {e}")

    errores, avisos = definicion.revisar_politicas()
    politicas = [p.model_dump(exclude_none=True, mode="json")
                 for p in definicion.politicas]
    return {
        "version": v.version,
        "politicas": politicas,
        "errores": errores,
        "avisos": avisos,
        "cobertura": _cobertura(sesion, politicas),
        "entidades": [
            {"nombre": e.nombre, "tipo": e.tipo,
             "campos": [c.nombre for c in e.campos]}
            for e in definicion.entidades
        ],
        "roles": [r.value for r in Rol if r != Rol.administrador],
    }


class GuardarPoliticas(BaseModel):
    politicas: list[PoliticaDef]
    notas: str | None = None


@router.put("/{modelo_id}/politicas", status_code=201)
def guardar_politicas(modelo_id: int, cuerpo: GuardarPoliticas, sesion: SesionDep,
                      actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Guarda las politicas como una version nueva del modelo.

    Se edita el mapa crudo del YAML y no los objetos del motor, por lo mismo que el
    resto de la definicion: lo que el motor ignora tiene que sobrevivir al guardado.

    Cambiar una politica es una version nueva y no una edicion en sitio a proposito:
    "quien podia ver que, y desde cuando" es justo la pregunta que se hace despues
    de un incidente, y solo se puede contestar si cada cambio dejo su version.
    """
    if sesion.get(ModeloDB, modelo_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado")

    v = _version_vigente(sesion, modelo_id)
    crudo = yaml.safe_load(v.yaml) or {}
    nuevas = [p.model_dump(exclude_none=True, mode="json")
              for p in cuerpo.politicas]
    if nuevas:
        crudo["politicas"] = nuevas
    else:
        crudo.pop("politicas", None)

    definicion = Definicion.model_validate(crudo)
    errores, avisos = definicion.revisar_politicas()
    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": errores})

    texto = volcar_yaml(crudo)
    _cargar_semantico(texto)            # que el modelo siga compilando

    ultima = sesion.scalar(
        select(func.coalesce(func.max(VersionModelo.version), 0))
        .where(VersionModelo.modelo_id == modelo_id))
    nueva = VersionModelo(
        modelo_id=modelo_id, version=ultima + 1, yaml=texto,
        notas=cuerpo.notas or "Cambio de politicas de seguridad por fila",
        creado_por=actor.id)
    sesion.add(nueva)
    sesion.flush()

    registrar(sesion, accion="politicas_guardadas", usuario_id=actor.id,
              email=actor.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"version": nueva.version,
                       "politicas": [p["nombre"] for p in nuevas],
                       "antes": [p.nombre for p in desde_yaml(v.yaml).politicas]})
    return {"version": nueva.version, "politicas": nuevas, "avisos": avisos,
            "cobertura": _cobertura(sesion, nuevas)}


@router.get("/{modelo_id}/yaml")
def leer_yaml(modelo_id: int, sesion: SesionDep, version: int | None = None,
              _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    El texto tal cual. Existe para poder revisarlo, versionarlo y exportarlo.

    Si hay un borrador sin publicar, **es lo que se devuelve**, igual que en
    `/definicion`. Antes no: el lienzo enseñaba el borrador y esta ruta la version
    publicada, sin decirlo. Quien tenia trece tablas en el lienzo y una publicada
    veia UNA en el YAML y concluia, con razon, que el YAML estaba roto — cuando lo
    que pasaba es que estaba mirando otra cosa. Pedir una `version` concreta salta
    el borrador, que es la via para mirar el historial.
    """
    vigente = _version_vigente(sesion, modelo_id)
    borrador = None if version else sesion.get(BorradorModelo, modelo_id)
    if borrador is not None:
        return {"version": borrador.desde_version, "yaml": borrador.yaml,
                "es_borrador": True, "version_vigente": vigente.version}
    v = _version_exacta(sesion, modelo_id, version) if version else vigente
    return {"version": v.version, "yaml": v.yaml, "es_borrador": False,
            "version_vigente": vigente.version}


@router.get("/{modelo_id}/rutas")
def rutas(modelo_id: int, desde: str, hasta: str, sesion: SesionDep,
          _: UsuarioDep):
    """
    Los caminos entre dos entidades, para poder explicar una ambiguedad en el
    lienzo en vez de solo avisar de ella.
    """
    v = _version_vigente(sesion, modelo_id)
    m = _cargar_semantico(v.yaml)
    for nombre in (desde, hasta):
        if nombre not in m.entidades:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"La entidad '{nombre}' no esta en el modelo")
    agregacion = m.rutas_minimas(desde, hasta)
    return {
        "desde": desde, "hasta": hasta,
        # Para agregar: los hechos son terminales y cada salto va muchos -> uno.
        "agregacion": agregacion,
        "ambigua": len(agregacion) > 1,
        # Para propagar selecciones: los hechos si son puente.
        "asociativa": m.rutas_minimas(desde, hasta, atravesar_hechos=True),
    }


@router.post("/{modelo_id}/probar-metrica")
def probar_metrica(modelo_id: int, cuerpo: ProbarMetrica, sesion: SesionDep,
                   ctx: ContextoDep,
                   _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Prueba una expresion sin guardarla: la ejecuta de verdad sobre los datos.

    Una expresion se puede escribir bien y significar otra cosa. Ver el numero
    antes de guardar es lo que evita publicar una metrica plausible y equivocada.
    """
    v = _version_vigente(sesion, modelo_id)
    m = _cargar_semantico(v.yaml)
    if cuerpo.entidad is not None and cuerpo.entidad not in m.entidades:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"La entidad '{cuerpo.entidad}' no esta en el modelo")

    # Se inyecta como metrica temporal, con el mismo compilador que la definitiva:
    # probar por otro camino no probaria nada.
    provisional = "__prueba__"
    m.metricas[provisional] = MetricaSemantica(
        nombre=provisional, etiqueta="Prueba", entidad=cuerpo.entidad,
        expresion=cuerpo.expresion, formato=cuerpo.formato)
    try:
        res = ejecutar_consulta(m, Consulta(
            dimensiones=cuerpo.dimensiones, metricas=[provisional],
            limite=cuerpo.limite), ctx)
    except ErrorModelo as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    except PoliticaInvalida as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except Exception as e:
        # Un error de SQL aqui es un error del usuario escribiendo la expresion,
        # no una falla del servidor: se devuelve tal cual para que lo lea.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"La expresion no se pudo ejecutar. "
                            f"{en_castellano(e)}")

    return {"columnas": res.columnas, "filas": res.filas, "ms": res.ms,
            "sql": res.sql}


@router.post("/{modelo_id}/vista-previa")
def vista_previa(modelo_id: int, cuerpo: VistaPrevia, sesion: SesionDep,
                 ctx: ContextoDep,
                 _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Ejecuta el modelo que se tiene en pantalla y devuelve la tabla.

    Es lo que cierra el ciclo de escribir una metrica: `revisar-formula` dice si
    esta bien escrita, `probar-metrica` da el numero de UNA, y esto enseña el
    modelo entero funcionando junto —varias metricas, desglosadas por las
    dimensiones que se elijan— sin haber publicado nada.

    No se audita, por lo mismo que no se audita guardar el borrador: esto es
    escribir el modelo, no consultarlo. Lo que queda en la auditoria es
    `consultar`, que es cuando alguien lee una cifra publicada.
    """
    if not cuerpo.metricas:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Elige al menos una metrica. Para ver filas sin agregar, la muestra "
            "de la entidad es la ruta '/muestra'.")

    m = _modelo_en_curso(sesion, modelo_id, cuerpo.definicion)
    try:
        res = ejecutar_consulta(m, Consulta(
            dimensiones=cuerpo.dimensiones, metricas=cuerpo.metricas,
            filtros=cuerpo.filtros, rutas_elegidas=cuerpo.rutas_elegidas,
            limite=cuerpo.limite,
        ), ctx)
    except ErrorModelo as e:
        detalle: dict = {"error": type(e).__name__, "mensaje": str(e)}
        if hasattr(e, "rutas"):
            detalle["rutas"] = [" → ".join(r) for r in e.rutas]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detalle)
    except PoliticaInvalida as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except Exception as e:
        # El modelo puede estar a medio escribir: eso es un error de quien edita,
        # no una falla del servidor, y se devuelve para que lo lea.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"La consulta no se pudo ejecutar. "
                            f"{en_castellano(e)}")

    return {"columnas": res.columnas, "filas": res.filas, "ms": res.ms,
            "sql": res.sql, "politicas_aplicadas": res.politicas_aplicadas}


@router.post("/{modelo_id}/muestra")
def muestra(modelo_id: int, cuerpo: MuestraEntidad, sesion: SesionDep,
            ctx: ContextoDep,
            _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Unas filas de una entidad, sin agregar nada.

    Antes de escribir la primera metrica hay una pregunta mas basica: que trae
    esta tabla. Sin poder mirarla, el rol de cada campo y el tipo de cada columna
    se declaran a ciegas.
    """
    m = _modelo_en_curso(sesion, modelo_id, cuerpo.definicion)
    if cuerpo.entidad not in m.entidades:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"La entidad '{cuerpo.entidad}' no esta en el modelo")
    try:
        res = ejecutar_muestra(m, cuerpo.entidad, cuerpo.limite, ctx)
    except ErrorModelo as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    except PoliticaInvalida as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    except Exception as e:
        # Lo normal aqui es que la tabla del origen todavia no exista en el
        # motor: decirlo tal cual ahorra buscarlo en el modelo.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"No se pudo leer la tabla. {en_castellano(e)}")

    return {"columnas": res.columnas, "filas": res.filas, "ms": res.ms,
            "sql": res.sql, "politicas_aplicadas": res.politicas_aplicadas,
            # Que columnas son datos personales, para poder avisarlo en pantalla.
            "pii": [c.nombre for c in m.entidades[cuerpo.entidad].campos.values()
                    if c.pii and c.visible]}


@router.post("/{modelo_id}/revisar-formula")
def revisar_formula_ruta(modelo_id: int, cuerpo: RevisarFormula, sesion: SesionDep,
                         _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Revisa la formula sin ejecutarla y devuelve los fallos con linea y columna.

    Es lo que subraya en rojo mientras se escribe. No toca los datos: mira la
    formula contra los campos de la entidad, asi que responde en milisegundos y
    se puede llamar en cada pausa del teclado. `probar-metrica`, que si ejecuta,
    sigue siendo el paso siguiente — este dice si esta bien ESCRITA, aquel dice
    si da el numero que se esperaba.
    """
    if cuerpo.entidad is None:
        # Compuesta: no hay entidad ni campos, solo las demas metricas.
        if cuerpo.metricas_del_modelo is not None:
            ctx_c = ContextoCompuesta(metricas=dict(cuerpo.metricas_del_modelo))
        else:
            ctx_c = _cargar_semantico(
                _version_vigente(sesion, modelo_id).yaml).contexto_compuesta()
        fallos = revisar_compuesta(cuerpo.expresion, ctx_c)
        try:
            sql = compilar_compuesta(cuerpo.expresion, ctx_c).sql
        except Exception:
            sql = None
        return {"fallos": fallos,
                "hay_errores": any(f["gravedad"] == "error" for f in fallos),
                "sql": sql}

    if cuerpo.campos is not None:
        contexto = Contexto(campos=set(cuerpo.campos),
                            metricas=dict(cuerpo.metricas or {}))
    else:
        m = _cargar_semantico(_version_vigente(sesion, modelo_id).yaml)
        if cuerpo.entidad not in m.entidades:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"La entidad '{cuerpo.entidad}' no esta en el modelo")
        contexto = m.contexto(cuerpo.entidad)

    fallos = revisar_formula(cuerpo.expresion, contexto)
    try:
        sql = compilar_formula(cuerpo.expresion, contexto)
    except Exception:
        # Que no compile ya lo dice `fallos`, con su posicion. Aqui el SQL es un
        # extra —para poder verlo— y no tener que enseñarlo no es un error.
        sql = None
    return {"fallos": fallos,
            "hay_errores": any(f["gravedad"] == "error" for f in fallos),
            "sql": sql}


@router.get("/{modelo_id}/diagnostico")
def diagnostico(modelo_id: int, sesion: SesionDep, _: UsuarioDep):
    """Problemas del modelo, antes de construir cualquier dashboard."""
    v = _version_vigente(sesion, modelo_id)
    return {"version": v.version,
            "problemas": _cargar_semantico(v.yaml).diagnosticar()}


@router.get("/{modelo_id}/campos")
def campos(modelo_id: int, sesion: SesionDep, _: UsuarioDep):
    """Catalogo de dimensiones y metricas para armar la interfaz."""
    v = _version_vigente(sesion, modelo_id)
    m = _cargar_semantico(v.yaml)
    return {
        "version": v.version,
        "dimensiones": [
            {"clave": f"{e.nombre}.{c.nombre}",
             "etiqueta": c.etiqueta or c.nombre,
             "entidad": e.nombre, "tipo": c.tipo}
            for e in m.entidades.values()
            for c in e.campos.values()
            if c.rol == "dimension" and c.visible
        ],
        "metricas": [
            # Una compuesta no sale de ningun hecho, y en la lista de metricas de
            # un tablero esa nota es lo que dice de donde viene la cifra: se pone
            # «compuesta» y no un hueco, que se leeria como un dato que falta.
            {"clave": mt.nombre, "etiqueta": mt.etiqueta,
             "entidad": mt.entidad or "compuesta", "formato": mt.formato}
            for mt in m.metricas.values()
        ],
    }


@router.post("/{modelo_id}/consultar")
def consultar(modelo_id: int, cuerpo: PeticionConsulta, sesion: SesionDep,
              usuario: UsuarioDep, ctx: ContextoDep, version: int | None = None):
    """
    `version` existe para los tableros: un dashboard esta anclado a una version
    concreta y tiene que consultar ESA, no la vigente. Sin este parametro el
    anclaje seria decorativo — el tablero diria "version 3" y preguntaria por la 7.
    """
    v = (_version_exacta(sesion, modelo_id, version) if version
         else _version_vigente(sesion, modelo_id))
    m = _cargar_semantico(v.yaml)

    try:
        res = ejecutar_consulta(m, Consulta(
            dimensiones=cuerpo.dimensiones, metricas=cuerpo.metricas,
            filtros=cuerpo.filtros, rutas_elegidas=cuerpo.rutas_elegidas,
            limite=cuerpo.limite,
        ), ctx)
    except ErrorModelo as e:
        # Ambiguedad de ruta, metrica no desglosable, metrica inexistente: son
        # decisiones del usuario, no fallos del servidor. 422 con el detalle.
        detalle: dict = {"error": type(e).__name__, "mensaje": str(e)}
        if hasattr(e, "rutas"):
            detalle["rutas"] = [" → ".join(r) for r in e.rutas]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detalle)
    except PoliticaInvalida as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))

    registrar(sesion, accion="consulta", usuario_id=usuario.id,
              email=usuario.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"dimensiones": cuerpo.dimensiones,
                       "metricas": cuerpo.metricas, "ms": res.ms,
                       "filas": len(res.filas), "version": v.version,
                       "filtros": len(cuerpo.filtros),
                       "politicas": res.politicas_aplicadas})

    return {
        "columnas": res.columnas, "filas": res.filas, "ms": res.ms,
        "politicas_aplicadas": res.politicas_aplicadas,
        # El SQL se devuelve solo a quien puede leerlo con provecho.
        "sql": res.sql if usuario.rol in (Rol.administrador, Rol.editor) else None,
    }


@router.post("/{modelo_id}/exportar")
def exportar(modelo_id: int, cuerpo: PeticionExportar, sesion: SesionDep,
             usuario: UsuarioDep, ctx: ContextoDep, version: int | None = None):
    """
    Exporta el resultado a Excel o CSV.

    Pasa por `ejecutar_consulta` como todo lo demas, asi que la seguridad por fila
    se aplica igual: el archivo solo lleva las filas que el usuario puede ver, y el
    archivo mismo lo dice en su hoja de procedencia.
    """
    v = (_version_exacta(sesion, modelo_id, version) if version
         else _version_vigente(sesion, modelo_id))
    m = _cargar_semantico(v.yaml)

    if cuerpo.limite > TOPE_FILAS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"El tope de exportacion es {TOPE_FILAS:,} filas. Un archivo mas "
            f"grande ya no se usa para leer; para reprocesar hay mejores caminos.")

    try:
        res = ejecutar_consulta(m, Consulta(
            dimensiones=cuerpo.dimensiones, metricas=cuerpo.metricas,
            filtros=cuerpo.filtros, rutas_elegidas=cuerpo.rutas_elegidas,
            limite=cuerpo.limite,
        ), ctx)
    except ErrorModelo as e:
        detalle: dict = {"error": type(e).__name__, "mensaje": str(e)}
        if hasattr(e, "rutas"):
            detalle["rutas"] = [" → ".join(r) for r in e.rutas]
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detalle)
    except PoliticaInvalida as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))

    proc = Procedencia(
        modelo=m.nombre, version=v.version, dimensiones=cuerpo.dimensiones,
        metricas=cuerpo.metricas, filtros=cuerpo.filtros,
        rutas_elegidas=cuerpo.rutas_elegidas,
        politicas_aplicadas=res.politicas_aplicadas,
        email_usuario=usuario.email, filas=len(res.filas),
    )

    if cuerpo.formato == "csv":
        contenido, pii = a_csv(m, res.columnas, res.filas)
        tipo = "text/csv; charset=utf-8"
        nombre = nombre_archivo(cuerpo.titulo, "csv")
    else:
        contenido, pii = a_excel(m, res.columnas, res.filas, proc, cuerpo.titulo)
        tipo = ("application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet")
        nombre = nombre_archivo(cuerpo.titulo, "xlsx")

    # Una exportacion es la via natural para que un dato se vaya de la
    # herramienta: queda en auditoria con que columnas personales llevaba.
    registrar(sesion, accion="exportacion", usuario_id=usuario.id,
              email=usuario.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"formato": cuerpo.formato, "filas": len(res.filas),
                       "version": v.version, "titulo": cuerpo.titulo,
                       "metricas": cuerpo.metricas,
                       "dimensiones": cuerpo.dimensiones,
                       "filtros": len(cuerpo.filtros),
                       "columnas_personales": pii,
                       "politicas": res.politicas_aplicadas})
    sesion.commit()

    return Response(
        content=contenido, media_type=tipo,
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            # Sin esto el navegador no deja leer el nombre del archivo al
            # descargarlo por fetch.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post("/{modelo_id}/asociativo")
def asociativo(modelo_id: int, cuerpo: PeticionAsociativa, sesion: SesionDep,
               _: UsuarioDep, ctx: ContextoDep, version: int | None = None):
    v = (_version_exacta(sesion, modelo_id, version) if version
         else _version_vigente(sesion, modelo_id))
    m = _cargar_semantico(v.yaml)
    try:
        return estados_asociativos(m, cuerpo.entidad, cuerpo.campo,
                                   cuerpo.selecciones, ctx)
    except ErrorModelo as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    except PoliticaInvalida as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
