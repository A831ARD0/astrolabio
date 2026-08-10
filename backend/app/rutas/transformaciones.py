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

import logging

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
    ErrorEjecucion, ErrorRenombrar, ejecutar as ejecutar_transformacion,
    linaje as _linaje, renombrar as _renombrar,
)
from semantic.transformacion import (
    ErrorTransformacion, Transformacion, compilar,
)
from semantic.sql_a_visual import desde_sql

log = logging.getLogger("astrolabio.transformaciones")

router = APIRouter(prefix="/api/transformaciones", tags=["transformaciones"])


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class Guardar(BaseModel):
    definicion: Transformacion
    # Andamiaje: el resultado existe para que otra sección lo use, no para
    # graficarlo. Va aquí y no dentro de `definicion` porque no cambia en nada lo
    # que se compila — es una decisión sobre dónde se ofrece, no sobre qué calcula.
    intermedia: bool = False
    # A qué proyecto se agrega al crearla. Solo se usa en el POST: mover una
    # sección de proyecto se hace por las rutas de proyectos, que es donde está la
    # comprobación de que no acabe en dos.
    proyecto_id: int | None = None


class DesdeSql(BaseModel):
    sql: str = Field(min_length=1)


class Renombrar(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)


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
    intermedia: bool
    # De qué proyecto es sección, y en qué posición. La pantalla lo necesita para
    # poder decir «sección 12 de 18 de TRANSFORMADOR_VENTAS» sin pedir la lista de
    # proyectos aparte.
    proyecto_id: int | None = None
    proyecto: str | None = None
    orden: int | None = None


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _donde_vive(sesion: SesionDep) -> dict[int, tuple[int, str, int]]:
    """id de transformación -> (id del proyecto, nombre, posición 1..n)."""
    from app.modelos_db import Flujo

    mapa: dict[int, tuple[int, str, int]] = {}
    for p in sesion.scalars(select(Flujo).where(Flujo.es_proyecto.is_(True))):
        for i, paso in enumerate(p.pasos or [], start=1):
            try:
                mapa[int(paso["id"])] = (p.id, p.nombre, i)
            except (TypeError, ValueError, KeyError):
                pass
    return mapa


def _salida(t: TransformacionDB,
            vive: dict[int, tuple[int, str, int]] | None = None) -> Salida:
    ultima = t.ejecuciones[0] if t.ejecuciones else None
    # `vive` se calcula una vez para toda la lista; suelto, cada transformación
    # volvería a recorrer todos los proyectos.
    casa = (vive or {}).get(t.id)
    return Salida(
        id=t.id, nombre=t.nombre, descripcion=t.descripcion,
        definicion=t.definicion, lee_de=t.lee_de or {},
        filas=t.filas, mb=round(t.bytes_parquet / 1024 / 1024, 2),
        ultima_ejecucion=iso(t.ultima_ejecucion),
        ultimo_estado=ultima.estado.value if ultima else None,
        tiene_datos=ruta_datos_dataset(t.nombre) is not None,
        intermedia=bool(t.intermedia),
        proyecto_id=casa[0] if casa else None,
        proyecto=casa[1] if casa else None,
        orden=casa[2] if casa else None,
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
    vive = _donde_vive(sesion)
    return [_salida(t, vive) for t in sesion.scalars(
        select(TransformacionDB).order_by(TransformacionDB.nombre))]


@router.get("/origenes")
def origenes_disponibles(sesion: SesionDep, proyecto_id: int | None = None,
                         _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Todo lo que se puede usar como entrada: tablas del motor, datasets cargados y
    resultados de otras transformaciones.

    **Cada bloque se calcula por separado y ningun fallo tumba la lista entera.**
    Antes no era asi y el resultado era el peor posible: `ruta_datos_dataset`
    lanza si un nombre trae un caracter raro, esa excepcion subia hasta aqui, la
    peticion contestaba 500 y la pantalla se quedaba con el panel de origenes
    VACIO —sin decir por que—. Con mil sesenta y cinco datasets, uno con un
    nombre raro dejaba sin poder transformar nada.

    Lo que no se puede usar se dice: sale en `avisos` y el origen queda marcado.

    `proyecto_id` es el proyecto que se está editando. Cambia una sola cosa, y es la
    que hace usable la lista con dieciocho secciones por sucursal: las secciones
    marcadas como **intermedias** solo se ofrecen dentro de su propio proyecto. Un
    mapeo de códigos o una tabla de series es andamiaje del proyecto que lo armó;
    fuera de ahí solo estorba. Las de este proyecto llegan marcadas con su número de
    sección, para que se puedan encadenar en orden sin adivinar.
    """
    from app.rutas.catalogo import tablas as tablas_catalogo

    avisos: list[str] = []

    # El motor analitico puede no estar disponible —archivo bloqueado, disco
    # lleno—. Eso no debe impedir armar una transformacion sobre los Parquet.
    try:
        # `sesion` y no `_`: el primer parametro de esa funcion es la sesion de
        # base de datos y el segundo el usuario. Cambiados de sitio, el bloque
        # del motor fallaba SIEMPRE con «'Usuario' object has no attribute
        # 'scalars'» y el panel se quedaba solo con los datasets — sin 500 y sin
        # que se notara que faltaba media lista.
        tablas = tablas_catalogo(sesion, _)["tablas"]
    except Exception as e:
        log.exception("No se pudieron listar las tablas del motor")
        tablas = []
        avisos.append(f"No se pudieron leer las tablas del motor: {e}")

    def con_datos(nombre: str) -> bool | None:
        """True/False si se pudo mirar; None si el nombre no sirve como origen."""
        try:
            return ruta_datos_dataset(nombre) is not None
        except Exception as e:
            avisos.append(f"'{nombre}' no se puede usar como origen: {e}")
            return None

    # Se mira UNA vez por dataset y se reutiliza: la comprobacion recorre
    # directorios, y con mil sesenta y cinco datasets hacerla dos veces —aqui y
    # en el bloque de «la misma tabla en varias conexiones»— se nota.
    listos: dict[str, bool | None] = {}
    orden = list(sesion.scalars(select(Dataset).order_by(Dataset.nombre)))
    for d in orden:
        listos[d.nombre] = con_datos(d.nombre)

    datasets = [
        {"nombre": d.nombre, "filas": d.filas,
         "tiene_datos": listos[d.nombre] is True,
         "usable": listos[d.nombre] is not None}
        for d in orden
    ]
    vive = _donde_vive(sesion)
    trans = []
    for t in sesion.scalars(select(TransformacionDB).order_by(TransformacionDB.nombre)):
        casa = vive.get(t.id)
        mio = casa is not None and proyecto_id is not None and casa[0] == proyecto_id
        if t.intermedia and not mio:
            continue                  # andamiaje de otro proyecto: no es de nadie más
        hay = con_datos(t.nombre)
        trans.append({"nombre": t.nombre, "filas": t.filas,
                      "tiene_datos": hay is True, "usable": hay is not None,
                      "intermedia": bool(t.intermedia),
                      "proyecto": casa[1] if casa else None,
                      "seccion": casa[2] if mio else None})

    # La misma tabla del origen traida por varias conexiones. Es lo que permite
    # decir «Funcionarios de todas las sucursales» en vez de enumerar cuarenta
    # datasets a mano —y acordarse del cuarenta y uno cuando abra una agencia.
    por_tabla: dict[str, list] = {}
    for d in orden:
        por_tabla.setdefault(d.tabla_origen or "", []).append(d)
    en_varias = sorted(
        ({"tabla": tabla,
          "conexiones": len(ds),
          "cargados": sum(1 for x in ds if listos.get(x.nombre) is True)}
         for tabla, ds in por_tabla.items() if tabla and len(ds) > 1),
        key=lambda x: x["tabla"].lower())

    return {"tablas": tablas, "datasets": datasets, "transformaciones": trans,
            "en_varias_conexiones": en_varias, "avisos": avisos}


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
        intermedia=cuerpo.intermedia, creado_por=actor.id)
    sesion.add(t)
    sesion.flush()

    if cuerpo.proyecto_id is not None:
        # Nace ya dentro del proyecto, al final. Crear la sección y luego tener que
        # ir a otra pantalla a meterla es exactamente el paso de más que este
        # cambio venía a quitar.
        from app.rutas.proyectos import agregar as agregar_seccion

        agregar_seccion(cuerpo.proyecto_id, t.id, sesion, actor)

    registrar(sesion, accion="transformacion_creada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="transformacion", objeto_id=t.id,
              detalle={"nombre": t.nombre, "pasos": len(d.pasos),
                       "modo": "sql" if d.es_sql else "visual",
                       "intermedia": cuerpo.intermedia,
                       "proyecto_id": cuerpo.proyecto_id})
    return _salida(t, _donde_vive(sesion))


@router.put("/{id_}", response_model=Salida)
def actualizar(id_: int, cuerpo: Guardar, sesion: SesionDep,
               actor: Usuario = Depends(exigir_rol(Rol.editor))):
    t = _obtener(sesion, id_)
    d = cuerpo.definicion
    if d.nombre != t.nombre:
        # Guardar no renombra. Renombrar mueve el Parquet y reescribe los orígenes de
        # las que la leen, y eso no puede colarse dentro de un «Guardar» que alguien
        # pulsó para cambiar un filtro: va por su propia ruta, que además dice qué
        # tocó. Para eso está POST /{id}/renombrar.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Este guardado cambiaría el nombre de '{t.nombre}' a '{d.nombre}'. "
            f"Renombrar mueve los datos en disco y arregla a quien la lee, así que "
            f"se pide aparte: usa el botón «Renombrar».")
    _cadena_ciclica(sesion, d.nombre, d)
    _compila_o_falla(sesion, d)

    t.descripcion = d.descripcion
    t.definicion = d.model_dump(mode="json")
    t.lee_de = _linaje(sesion, d)
    t.intermedia = cuerpo.intermedia
    registrar(sesion, accion="transformacion_actualizada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="transformacion", objeto_id=t.id,
              detalle={"nombre": t.nombre, "pasos": len(d.pasos),
                       "intermedia": cuerpo.intermedia})
    return _salida(t, _donde_vive(sesion))


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


@router.post("/{id_}/renombrar")
def renombrar(id_: int, cuerpo: Renombrar, sesion: SesionDep,
              actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Cambia el nombre, y con él lo que dependía de ese nombre.

    Mueve el directorio Parquet y reescribe los orígenes de las transformaciones que
    la leen; **no toca las versiones del modelo**, que son inmutables a propósito, y
    si alguna la nombra se para en vez de romper un tablero publicado.

    Devuelve qué tocó. No es un detalle: renombrar algo que otras cuatro cosas leen y
    que la pantalla no diga cuáles es pedirle a alguien que confíe a ciegas.
    """
    t = _obtener(sesion, id_)
    try:
        r = _renombrar(sesion, t, cuerpo.nombre, Actor(id=actor.id, email=actor.email))
    except ErrorRenombrar as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return r


@router.get("/{id_}/historial")
def historial(id_: int, sesion: SesionDep,
              _: Usuario = Depends(exigir_rol(Rol.editor))):
    t = _obtener(sesion, id_)
    return {"ejecuciones": [
        {"id": e.id, "estado": e.estado.value, "filas": e.filas, "ms": e.ms,
         "mensaje": e.mensaje, "cuando": iso(e.creado_en)}
        for e in t.ejecuciones[:50]
    ]}


def _catalogo_de_origenes(sesion: SesionDep,
                          actor: Usuario) -> dict[str, str]:
    """
    Nombre -> tipo de todo lo que se puede usar como origen.

    Es lo que permite que una consulta pegada diga `FROM cat_zonas` sin que
    nadie tenga que saber si detrás hay una tabla del motor, un Parquet o el
    resultado de otra transformación. Antes se suponía que todo era una tabla del
    motor, y cuando no lo era la consulta moría con un «Catalog Error» de DuckDB.
    """
    catalogo: dict[str, str] = {}

    # Se llenan en orden inverso a la preferencia: lo mas especifico gana.
    por_tabla: dict[str, int] = {}
    for d in sesion.scalars(select(Dataset)):
        por_tabla[d.tabla_origen or ""] = por_tabla.get(d.tabla_origen or "", 0) + 1
    for tabla, cuantas in por_tabla.items():
        if tabla and cuantas > 1:
            catalogo[tabla] = "tabla_en_conexiones"

    for t in sesion.scalars(select(TransformacionDB)):
        catalogo[t.nombre] = "dataset"
    for d in sesion.scalars(select(Dataset)):
        catalogo[d.nombre] = "dataset"

    try:
        from app.rutas.catalogo import tablas as tablas_catalogo

        for t in tablas_catalogo(sesion, actor)["tablas"]:
            # Solo las del motor entran como "tabla": las cargas y los resultados
            # ya se apuntaron arriba como "dataset", que es como se leen —por su
            # Parquet— cuando una transformación los usa.
            if t["origen"] == "motor":
                catalogo[t["nombre"]] = "tabla"
    except Exception:
        log.exception("No se pudieron listar las tablas del motor para el catalogo")
    return catalogo


@router.post("/desde-sql")
def convertir_desde_sql(cuerpo: DesdeSql, sesion: SesionDep,
                        _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Intenta reconstruir los pasos visuales de una consulta escrita a mano.

    Cuando algo no se puede representar, se dice cuál y por qué. Devolver una
    conversión aproximada que cambia lo que la consulta hacía sería peor que no
    convertir: el usuario creería que ya está y la cifra cambiaría en silencio.
    """
    try:
        r = desde_sql(cuerpo.sql, _catalogo_de_origenes(sesion, _))
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

    # Sacarla del proyecto que la lista como sección. Sin esto el proyecto queda con
    # un paso que apunta a nada: la pantalla lo diría como huérfana, pero al guardar
    # cualquier otro cambio la validación lo rechazaría y no habría forma de
    # arreglarlo desde ahí.
    from app.modelos_db import Flujo

    salio_de = None
    for p in sesion.scalars(select(Flujo).where(Flujo.es_proyecto.is_(True))):
        quedan = [x for x in (p.pasos or []) if str(x.get("id")) != str(id_)]
        if len(quedan) != len(p.pasos or []):
            p.pasos = quedan
            salio_de = p.nombre

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
              detalle={"nombre": nombre, "datos_borrados": borrados,
                       **({"salio_de": salio_de} if salio_de else {})})
