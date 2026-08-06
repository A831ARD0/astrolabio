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
    for o in d.origenes:
        if o.tipo == "tabla":
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
