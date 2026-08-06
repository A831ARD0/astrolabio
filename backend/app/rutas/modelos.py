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
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.analitico import ejecutar_consulta, estados_asociativos
from app.auditoria import registrar
from app.exportar import (
    Procedencia, TOPE_FILAS, a_csv, a_excel, nombre_archivo,
)
from app.dependencias import ContextoDep, SesionDep, UsuarioDep, exigir_rol
from app.modelos_db import Modelo as ModeloDB
from app.modelos_db import Rol, Usuario, VersionModelo
from app.politicas import PoliticaInvalida
from semantic.definicion import Definicion, desde_yaml, volcar_yaml
from semantic.politica import PoliticaDef, atributos_requeridos
from semantic.engine import Consulta, ErrorModelo
from semantic.engine import Metrica as MetricaSemantica
from semantic.engine import Modelo as ModeloSemantico

router = APIRouter(prefix="/api/modelos", tags=["modelos"])


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class CrearModelo(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    descripcion: str | None = None
    yaml: str


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


class ProbarMetrica(BaseModel):
    entidad: str
    expresion: str
    formato: str = "numero"
    dimensiones: list[str] = []
    limite: int = Field(default=20, le=500)


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


@router.post("", response_model=ModeloSalida, status_code=201)
def crear(cuerpo: CrearModelo, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    _cargar_semantico(cuerpo.yaml)      # valida antes de guardar

    if sesion.scalar(select(func.count()).select_from(ModeloDB)
                     .where(ModeloDB.nombre == cuerpo.nombre)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un modelo con ese nombre")

    modelo = ModeloDB(nombre=cuerpo.nombre, descripcion=cuerpo.descripcion)
    sesion.add(modelo)
    sesion.flush()
    sesion.add(VersionModelo(modelo_id=modelo.id, version=1, yaml=cuerpo.yaml,
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
                       "creado_en": v.creado_en.isoformat(), **conteo})
    return {"versiones": salida}


@router.get("/{modelo_id}/definicion")
def leer_definicion(modelo_id: int, sesion: SesionDep, _: UsuarioDep,
                    version: int | None = None):
    """
    La definicion estructurada que edita el lienzo, mas su diagnostico.

    Devuelve el YAML crudo tal cual, sin pasar por los objetos del motor: el
    motor ignora jerarquias, perspectivas y la disposicion del lienzo, y
    serializar desde el las borraria en silencio.
    """
    v = (_version_exacta(sesion, modelo_id, version) if version
         else _version_vigente(sesion, modelo_id))
    try:
        definicion = desde_yaml(v.yaml)
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"La version {v.version} no se puede leer: {e}")
    return {
        "version": v.version,
        "es_vigente": v.version == _version_vigente(sesion, modelo_id).version,
        "definicion": definicion.model_dump(exclude_none=True, mode="json"),
        "problemas": _cargar_semantico(v.yaml).diagnosticar(),
    }


@router.put("/{modelo_id}/definicion", status_code=201)
def guardar_definicion(modelo_id: int, cuerpo: GuardarDefinicion,
                       sesion: SesionDep,
                       actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Guarda la definicion como una version nueva.

    Dos validaciones distintas, y las dos hacen falta:
      1. referencias cruzadas — dicen QUE esta mal y donde.
      2. el motor — dice si el modelo compila de verdad.
    """
    if sesion.get(ModeloDB, modelo_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado")

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

    problemas = semantico.diagnosticar()
    registrar(sesion, accion="modelo_version_creada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="modelo", objeto_id=modelo_id,
              detalle={"version": v.version, "notas": cuerpo.notas,
                       "entidades": len(cuerpo.definicion.entidades),
                       "problemas_criticos": sum(
                           1 for p in problemas if p["gravedad"] == "critico")})
    return {"version": v.version, "problemas": problemas, "yaml": texto}


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
    """El texto tal cual. Existe para poder revisarlo, versionarlo y exportarlo."""
    v = (_version_exacta(sesion, modelo_id, version) if version
         else _version_vigente(sesion, modelo_id))
    return {"version": v.version, "yaml": v.yaml}


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
    if cuerpo.entidad not in m.entidades:
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
                            f"La expresion no se pudo ejecutar: {e}")

    return {"columnas": res.columnas, "filas": res.filas, "ms": res.ms,
            "sql": res.sql}


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
            {"clave": mt.nombre, "etiqueta": mt.etiqueta,
             "entidad": mt.entidad, "formato": mt.formato}
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
