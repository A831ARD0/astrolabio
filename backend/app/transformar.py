"""
El servicio de ejecución de transformaciones.

Vive fuera de las rutas HTTP por la misma razón que `app/cargas.py`: el flujo
programado tiene que ejecutar la MISMA función que el botón, no una copia
parecida. Si fueran dos caminos, el historial de una ejecución automática acabaría
distinto del de una manual, y con eso se pierde justo lo que sirve para depurar
por qué una cifra cambió de madrugada.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auditoria import registrar
from app.cargas import Actor
from app.materializar import ejecutar as materializar
from app.modelos_db import (
    Dataset, EstadoCarga, Transformacion as TransformacionDB,
    TransformacionEjecucion,
)
from semantic.transformacion import Transformacion


class ErrorEjecucion(Exception):
    """No se pudo ejecutar. Ya quedó registrada en el historial."""


def linaje(sesion: Session, d: Transformacion) -> dict:
    """
    De qué lee, distinguiendo tablas del motor, datasets cargados y resultados de
    otras transformaciones. Es lo que después permite ordenar un flujo solo.
    """
    nombres_trans = {t.nombre for t in sesion.scalars(select(TransformacionDB))}
    nombres_datasets = {x.nombre for x in sesion.scalars(select(Dataset))}
    salida: dict[str, list[str]] = {"tablas": [], "datasets": [],
                                    "transformaciones": []}
    # La misma tabla en todas las conexiones se resuelve a la lista de datasets
    # que la traen: asi el flujo sabe que hay que cargarlos ANTES, sin que nadie
    # los tenga que enumerar.
    por_tabla: dict[str, list[str]] = {}
    for x in sesion.scalars(select(Dataset)):
        por_tabla.setdefault((x.tabla_origen or "").lower(), []).append(x.nombre)

    for o in d.origenes:
        if o.tipo == "tabla_en_conexiones":
            salida["datasets"].extend(
                sorted(por_tabla.get((o.referencia or "").lower(), [])))
        elif o.tipo == "tabla":
            salida["tablas"].append(o.referencia)
        elif o.referencia in nombres_trans:
            salida["transformaciones"].append(o.referencia)
        elif o.referencia in nombres_datasets:
            salida["datasets"].append(o.referencia)
        else:
            # Un Parquet que está en disco pero no registrado. Se anota como
            # dataset: es lo que es desde el punto de vista de la lectura.
            salida["datasets"].append(o.referencia)
    return salida


def definicion_de(t: TransformacionDB) -> Transformacion:
    return Transformacion.model_validate(t.definicion)


class ErrorRenombrar(Exception):
    """No se puede renombrar. El mensaje es para el usuario."""


def renombrar(sesion: Session, t: TransformacionDB, nuevo: str,
              actor: Actor) -> dict:
    """
    Cambia el nombre, y con él todo lo que dependía de ese nombre.

    El nombre de una transformación no es una etiqueta: es **el directorio del
    Parquet** y **el nombre con el que otras la leen**. Cambiarlo a secas dejaba el
    resultado huérfano en disco y las que lo usaban apuntando a algo que ya no
    estaba, así que hasta ahora simplemente no se podía. Eso era correcto y también
    inservible: dos catálogos que vienen de dos sistemas distintos necesitan llamarse
    distinto, y descubrirlo después de armarla obligaba a rehacerla.

    Así que se renombra de verdad: se mueve el Parquet y se reescriben los orígenes
    de las que la leen. Lo que **no** se toca son las versiones del modelo, que son
    instantáneas inmutables a propósito —un tablero anclado a una versión no puede
    cambiar de significado porque alguien renombró algo—. Si alguna la nombra, se
    para y se dice cuál; renombrar callando eso rompería un tablero publicado.
    """
    from app.materializar import _nombre_simple, ruta_salida
    from app.modelos_db import Dataset, Flujo, VersionModelo

    nuevo = (nuevo or "").strip()
    viejo = t.nombre
    if nuevo == viejo:
        return {"cambiado": False, "nombre": viejo}
    if not _nombre_simple(nuevo):
        raise ErrorRenombrar(
            f"'{nuevo}' no sirve como nombre: también es el nombre de la carpeta en "
            f"disco, así que solo admite letras, dígitos y guion bajo.")

    if sesion.scalar(select(TransformacionDB.id)
                     .where(TransformacionDB.nombre == nuevo,
                            TransformacionDB.id != t.id)):
        raise ErrorRenombrar(f"Ya hay otra transformación llamada '{nuevo}'.")
    if sesion.scalar(select(Dataset.id).where(Dataset.nombre == nuevo)):
        raise ErrorRenombrar(
            f"Ya hay un dataset llamado '{nuevo}'. Los dos escribirían en el mismo "
            f"sitio y uno pisaría al otro.")

    # Las versiones del modelo son inmutables: si alguna lo nombra, no se renombra.
    en_modelos = sorted({
        v.modelo.nombre for v in sesion.scalars(select(VersionModelo))
        if _nombra(v.yaml, viejo)
    })
    if en_modelos:
        raise ErrorRenombrar(
            f"No se puede: {', '.join(repr(m) for m in en_modelos)} tiene una versión "
            f"que lee de '{viejo}', y las versiones del modelo no se reescriben —un "
            f"tablero anclado a una versión no puede cambiar de significado por un "
            f"renombrado—. Saca esa entidad del modelo, o crea otra transformación "
            f"con el nombre nuevo.")

    # Mover el Parquet. Antes de tocar la base: si el disco falla, no queda una fila
    # apuntando a una carpeta que no se movió.
    carpeta = ruta_salida(viejo)
    destino = ruta_salida(nuevo)
    movidos = False
    if carpeta.is_dir():
        if destino.exists():
            raise ErrorRenombrar(
                f"En disco ya existe la carpeta de '{nuevo}' aunque no haya nada "
                f"registrado con ese nombre. Revísala antes: moverla encima "
                f"perdería lo que tenga.")
        carpeta.rename(destino)
        movidos = True

    # Las que la leen. Se les reescribe la REFERENCIA y no el alias: el alias es el
    # nombre con el que la consulta —o el paso de unir— la llama por dentro, y
    # cambiarlo rompería el SQL que alguien escribió a mano.
    dependientes: list[str] = []
    for otra in sesion.scalars(select(TransformacionDB)
                               .where(TransformacionDB.id != t.id)):
        d = dict(otra.definicion or {})
        origenes = [dict(o) for o in d.get("origenes") or []]
        toco = False
        for o in origenes:
            if o.get("tipo") == "dataset" and o.get("referencia") == viejo:
                o["referencia"] = nuevo
                toco = True
        if toco:
            d["origenes"] = origenes
            otra.definicion = d
            lee = dict(otra.lee_de or {})
            lee["transformaciones"] = [nuevo if x == viejo else x
                                       for x in lee.get("transformaciones") or []]
            lee["datasets"] = [nuevo if x == viejo else x
                               for x in lee.get("datasets") or []]
            otra.lee_de = lee
            dependientes.append(otra.nombre)

    # La etiqueta que los flujos y proyectos guardan junto al id, para que su
    # historial siga siendo legible. El id no cambia, así que nada deja de correr;
    # lo que cambia es lo que se lee en la pantalla.
    pasos_tocados = 0
    for f in sesion.scalars(select(Flujo)):
        pasos = [dict(p) for p in f.pasos or []]
        toco = False
        for p in pasos:
            if p.get("tipo") == "transformacion" and str(p.get("id")) == str(t.id):
                p["nombre"] = nuevo
                toco = True
        if toco:
            f.pasos = pasos
            pasos_tocados += 1

    d = dict(t.definicion or {})
    d["nombre"] = nuevo
    t.definicion = d
    t.nombre = nuevo

    registrar(sesion, accion="transformacion_renombrada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="transformacion", objeto_id=t.id,
              detalle={"de": viejo, "a": nuevo, "datos_movidos": movidos,
                       "dependientes": dependientes,
                       "flujos_tocados": pasos_tocados})
    return {"cambiado": True, "nombre": nuevo, "antes": viejo,
            "datos_movidos": movidos, "dependientes": dependientes,
            "flujos_tocados": pasos_tocados}


def _nombra(yaml_texto: str, nombre: str) -> bool:
    """
    Si el YAML de un modelo usa esa tabla.

    Se compara sobre el texto y con los límites de palabra puestos a mano: parsear el
    YAML aquí obligaría a que una versión vieja e ilegible bloqueara el renombrado, y
    lo que hace falta saber es más simple —¿aparece este nombre?—. Se prefiere un
    falso positivo, que como mucho obliga a explicarse, a un falso negativo, que
    rompe un tablero publicado.
    """
    import re

    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(nombre)}(?![A-Za-z0-9_])",
                     yaml_texto or "") is not None


def ejecutar(sesion: Session, t: TransformacionDB, actor: Actor) -> dict:
    """
    Materializa la transformación y deja constancia de cómo salió.

    Lanza `ErrorEjecucion` si falla, pero solo DESPUÉS de confirmar el registro
    del fallo: perder el historial de fallos por un rollback ya pasó una vez.
    """
    ejec = TransformacionEjecucion(
        transformacion_id=t.id, estado=EstadoCarga.corriendo,
        iniciado_por=actor.id)
    sesion.add(ejec)
    sesion.flush()
    # Igual que en las cargas: soltar el candado de escritura de SQLite antes de
    # ponerse a materializar, que es lo que tarda.
    sesion.commit()

    try:
        d = definicion_de(t)
    except Exception as e:
        _fallar(sesion, ejec, t, actor,
                f"La definición guardada no se puede leer: {e}")

    try:
        r = materializar(d)
    except Exception as e:
        _fallar(sesion, ejec, t, actor, str(e))

    ejec.estado = EstadoCarga.exito
    ejec.filas = r.filas
    ejec.bytes_escritos = r.bytes_escritos
    ejec.ms = int(r.ms)
    ejec.sql = r.sql

    t.filas = r.filas
    t.bytes_parquet = r.bytes_escritos
    t.ultima_ejecucion = datetime.now(timezone.utc)
    t.lee_de = linaje(sesion, d)

    registrar(sesion, accion="transformacion_ejecutada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="transformacion", objeto_id=t.id,
              detalle={"nombre": t.nombre, "filas": r.filas, "ms": r.ms,
                       "disparo": actor.origen, "columnas": len(r.columnas)})

    return {"estado": "exito", "filas": r.filas, "columnas": r.columnas,
            "mb": round(r.bytes_escritos / 1024 / 1024, 2), "ms": r.ms,
            "archivos": r.archivos}


def _fallar(sesion: Session, ejec: TransformacionEjecucion,
            t: TransformacionDB, actor: Actor, mensaje: str) -> NoReturn:
    ejec.estado = EstadoCarga.error
    ejec.mensaje = mensaje
    registrar(sesion, accion="transformacion_fallida", usuario_id=actor.id,
              email=actor.email, objeto_tipo="transformacion", objeto_id=t.id,
              detalle={"error": mensaje, "disparo": actor.origen})
    sesion.commit()
    raise ErrorEjecucion(mensaje)
