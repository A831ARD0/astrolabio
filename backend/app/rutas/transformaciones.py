"""
Transformaciones (el ETL).

Dos modos, y el paso de uno a otro:

  visual  pasos que se compilan a SQL legible, un CTE por paso.
  SQL     una consulta ya escrita. Existe porque mucha gente ya tiene la suya y
          obligarla a rearmarla en una interfaz es tirar su trabajo.

`POST /desde-sql` intenta el camino de vuelta: leer una consulta y reconstruir los
pasos visuales. Cuando no se puede, **lo dice y no adivina**: una conversión
aproximada que cambia lo que la consulta hacía es peor que no convertir.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auditoria import registrar
from app.dependencias import SesionDep, UsuarioDep, exigir_rol
from app.cargas import Actor
from app.materializar import columnas_de, previsualizar, ruta_datos_dataset
from app.modelos_db import (
    Dataset, Rol, Transformacion as TransformacionDB, Usuario, iso,
)
from app.transformar import (
    ErrorEjecucion, ejecutar as ejecutar_transformacion, linaje as _linaje,
)
from semantic.transformacion import (
    ErrorTransformacion, Transformacion, compilar,
)
from semantic.sql_a_visual import desde_sql

router = APIRouter(prefix="/api/transformaciones", tags=["transformaciones"])


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class Guardar(BaseModel):
    definicion: Transformacion


class DesdeSql(BaseModel):
    sql: str = Field(min_length=1)


class Salida(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    definicion: dict
    lee_de: dict
    filas: int
    mb: float
    ultima_ejecucion: str | None
    ultimo_estado: str | None
    tiene_datos: bool


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _salida(t: TransformacionDB) -> Salida:
    ultima = t.ejecuciones[0] if t.ejecuciones else None
    return Salida(
        id=t.id, nombre=t.nombre, descripcion=t.descripcion,
        definicion=t.definicion, lee_de=t.lee_de or {},
        filas=t.filas, mb=round(t.bytes_parquet / 1024 / 1024, 2),
        ultima_ejecucion=iso(t.ultima_ejecucion),
        ultimo_estado=ultima.estado.value if ultima else None,
        tiene_datos=ruta_datos_dataset(t.nombre) is not None,
    )


def _obtener(sesion: SesionDep, id_: int) -> TransformacionDB:
    t = sesion.get(TransformacionDB, id_)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transformación no encontrada")
    return t


def _definicion(t: TransformacionDB) -> Transformacion:
    try:
        return Transformacion.model_validate(t.definicion)
    except Exception as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"La definición guardada no se puede leer: {e}")


def _cadena_ciclica(sesion: SesionDep, nombre: str, definicion: Transformacion) -> None:
    """
    Una transformación no puede leer de sí misma, ni directa ni indirectamente.

    Sin esta comprobación, `a` que lee de `b` que lee de `a` se detecta en tiempo
    de ejecución, después de haber borrado el resultado anterior de una de las dos.
    """
    por_nombre = {
        t.nombre: t for t in sesion.scalars(select(TransformacionDB))
    }

    def leidos(d: Transformacion) -> list[str]:
        return [o.referencia for o in d.origenes if o.tipo == "dataset"]

    vistos: set[str] = set()
    pila = list(leidos(definicion))
    while pila:
        actual = pila.pop()
        if actual == nombre:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"'{nombre}' acabaría leyendo de sí misma. Revisa los orígenes.")
        if actual in vistos:
            continue
        vistos.add(actual)
        otra = por_nombre.get(actual)
        if otra is not None:
            try:
                pila.extend(leidos(Transformacion.model_validate(otra.definicion)))
            except Exception:
                continue          # una definición ilegible no bloquea a las demás


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[Salida])
def listar(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    return [_salida(t) for t in sesion.scalars(
        select(TransformacionDB).order_by(TransformacionDB.nombre))]


@router.get("/origenes")
def origenes_disponibles(sesion: SesionDep,
                         _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Todo lo que se puede usar como entrada: tablas del motor, datasets cargados y
    resultados de otras transformaciones.
    """
    from app.rutas.catalogo import tablas as tablas_catalogo

    tablas = tablas_catalogo(_)["tablas"]
    datasets = [
        {"nombre": d.nombre, "filas": d.filas,
         "tiene_datos": ruta_datos_dataset(d.nombre) is not None}
        for d in sesion.scalars(select(Dataset).order_by(Dataset.nombre))
    ]
    trans = [
        {"nombre": t.nombre, "filas": t.filas,
         "tiene_datos": ruta_datos_dataset(t.nombre) is not None}
        for t in sesion.scalars(select(TransformacionDB)
                                .order_by(TransformacionDB.nombre))
    ]
    # La misma tabla del origen traida por varias conexiones. Es lo que permite
    # decir «Funcionarios de todas las sucursales» en vez de enumerar cuarenta
    # datasets a mano —y acordarse del cuarenta y uno cuando abra una agencia.
    por_tabla: dict[str, list] = {}
    for d in sesion.scalars(select(Dataset)):
        por_tabla.setdefault(d.tabla_origen or "", []).append(d)
    en_varias = sorted(
        ({"tabla": tabla,
          "conexiones": len(ds),
          "cargados": sum(1 for x in ds if ruta_datos_dataset(x.nombre) is not None)}
         for tabla, ds in por_tabla.items() if tabla and len(ds) > 1),
        key=lambda x: x["tabla"].lower())

    return {"tablas": tablas, "datasets": datasets, "transformaciones": trans,
            "en_varias_conexiones": en_varias}


@router.get("/columnas")
def columnas(tipo: str, referencia: str,
             _: Usuario = Depends(exigir_rol(Rol.editor))):
    """Columnas de un origen, para no tener que teclear nombres de memoria."""
    if tipo not in ("tabla", "dataset", "tabla_en_conexiones"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "El tipo de origen debe ser 'tabla', 'dataset' o 'tabla_en_conexiones'")
    try:
        return {"columnas": columnas_de(tipo, referencia)}
    except ErrorTransformacion as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"No se pudo leer el origen: {e}")


@router.post("", response_model=Salida, status_code=201)
def crear(cuerpo: Guardar, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    d = cuerpo.definicion
    if sesion.scalar(select(func.count()).select_from(TransformacionDB)
                     .where(TransformacionDB.nombre == d.nombre)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya existe una transformación con ese nombre")
    if sesion.scalar(select(func.count()).select_from(Dataset)
                     .where(Dataset.nombre == d.nombre)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Ya hay un dataset llamado '{d.nombre}'. Los dos escribirían en el "
            f"mismo sitio y uno pisaría al otro.")
    _cadena_ciclica(sesion, d.nombre, d)
    _compila_o_falla(sesion, d)

    t = TransformacionDB(
        nombre=d.nombre, descripcion=d.descripcion,
        definicion=d.model_dump(mode="json"), lee_de=_linaje(sesion, d),
        creado_por=actor.id)
    sesion.add(t)
    sesion.flush()
    registrar(sesion, accion="transformacion_creada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="transformacion", objeto_id=t.id,
              detalle={"nombre": t.nombre, "pasos": len(d.pasos),
                       "modo": "sql" if d.es_sql else "visual"})
    return _salida(t)


@router.put("/{id_}", response_model=Salida)
def actualizar(id_: int, cuerpo: Guardar, sesion: SesionDep,
               actor: Usuario = Depends(exigir_rol(Rol.editor))):
    t = _obtener(sesion, id_)
    d = cuerpo.definicion
    if d.nombre != t.nombre:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Cambiar el nombre dejaría huérfano el resultado ya materializado y "
            "cualquier modelo que apunte a él. Crea otra transformación.")
    _cadena_ciclica(sesion, d.nombre, d)
    _compila_o_falla(sesion, d)

    t.descripcion = d.descripcion
    t.definicion = d.model_dump(mode="json")
    t.lee_de = _linaje(sesion, d)
    registrar(sesion, accion="transformacion_actualizada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="transformacion", objeto_id=t.id,
              detalle={"nombre": t.nombre, "pasos": len(d.pasos)})
    return _salida(t)


def _compila_o_falla(sesion: SesionDep, d: Transformacion) -> None:
    """
    Compilar antes de guardar. No ejecuta: solo comprueba que lo que se guarda
    tiene sentido, para que el error salga aquí y no de madrugada.
    """
    from app.materializar import _resolver

    try:
        compilar(d, _resolver(d))
    except ErrorTransformacion as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))


@router.post("/previsualizar")
def vista_previa(cuerpo: Guardar, _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Corre la transformación acotada, sin escribir nada, y devuelve el conteo de
    filas por paso: es lo que convierte un "no cuadra" en "se pierde en el paso 3".
    """
    try:
        r = previsualizar(cuerpo.definicion)
    except ErrorTransformacion as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"La transformación no se pudo ejecutar: {e}")
    return {
        "columnas": r.columnas,
        "filas": [{k: (str(v) if v is not None else None) for k, v in f.items()}
                  for f in r.filas],
        "ms": r.ms, "sql": r.sql,
        "conteos": [{"paso": p, "filas": n} for p, n in r.conteos],
    }


@router.post("/{id_}/ejecutar")
def ejecutar(id_: int, sesion: SesionDep,
             actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Ejecuta ahora. Pasa por el mismo servicio que usa el flujo programado, para
    que el historial de una ejecución manual y una automática sean comparables.
    """
    t = _obtener(sesion, id_)
    try:
        return ejecutar_transformacion(
            sesion, t, Actor(id=actor.id, email=actor.email))
    except ErrorEjecucion as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"La transformación falló: {e}")


@router.get("/{id_}/historial")
def historial(id_: int, sesion: SesionDep,
              _: Usuario = Depends(exigir_rol(Rol.editor))):
    t = _obtener(sesion, id_)
    return {"ejecuciones": [
        {"id": e.id, "estado": e.estado.value, "filas": e.filas, "ms": e.ms,
         "mensaje": e.mensaje, "cuando": iso(e.creado_en)}
        for e in t.ejecuciones[:50]
    ]}


@router.post("/desde-sql")
def convertir_desde_sql(cuerpo: DesdeSql,
                        _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Intenta reconstruir los pasos visuales de una consulta escrita a mano.

    Cuando algo no se puede representar, se dice cuál y por qué. Devolver una
    conversión aproximada que cambia lo que la consulta hacía sería peor que no
    convertir: el usuario creería que ya está y la cifra cambiaría en silencio.
    """
    try:
        r = desde_sql(cuerpo.sql)
    except ErrorTransformacion as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))
    return {
        "convertible": r.convertible,
        "origenes": [o.model_dump(mode="json") for o in r.origenes],
        "pasos": [p.model_dump(mode="json") for p in r.pasos],
        "no_representable": r.no_representable,
    }


@router.delete("/{id_}", status_code=204)
def borrar(id_: int, sesion: SesionDep, borrar_datos: bool = False,
           actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Borra la definición. Los datos materializados solo se borran si se pide
    explícitamente: el resultado puede estar alimentando un modelo, y perderlo por
    borrar una definición sería una sorpresa caras.
    """
    t = _obtener(sesion, id_)
    nombre = t.nombre
    sesion.delete(t)

    borrados = False
    if borrar_datos:
        from shutil import rmtree

        from app.materializar import ruta_salida

        carpeta = ruta_salida(nombre)
        if carpeta.is_dir():
            rmtree(carpeta)
            borrados = True

    registrar(sesion, accion="transformacion_borrada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="transformacion", objeto_id=id_,
              detalle={"nombre": nombre, "datos_borrados": borrados})
