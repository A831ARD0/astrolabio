"""
Programador de cargas.

Decisiones que importan, porque un programador mal ajustado hace dano callado:

- **El jobstore vive en la misma base SQLite de metadatos.** Reiniciar el
  servidor no borra las programaciones. Si estuvieran en memoria, un reinicio de
  madrugada dejaria los datos sin actualizar y nadie se enteraria hasta que un
  numero saliera viejo.

- **`coalesce=True` y `misfire_grace_time` acotado.** Si el servidor estuvo
  apagado tres dias, al arrancar NO se disparan las 72 cargas atrasadas: se
  ejecuta una y se sigue. Acumular ejecuciones atrasadas es la forma clasica de
  tumbar el origen justo al volver.

- **`max_instances=1`.** Una carga que tarda mas que su intervalo no se solapa
  consigo misma. Dos ingestas escribiendo el mismo Parquet a la vez es corrupcion.

- **Cada corrida abre su propia sesion** y captura todo. Una excepcion que
  escape del job apagaria el hilo del programador.
"""

from __future__ import annotations

import logging

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.cargas import Actor, ErrorCarga, ejecutar_carga
from app.config import config
from app.db import CrearSesion, motor
from app.modelos_db import Dataset

log = logging.getLogger("astrolabio.programador")

_planificador: BackgroundScheduler | None = None


def _id_trabajo(dataset_id: int) -> str:
    return f"dataset:{dataset_id}"


def _id_flujo(flujo_id: int) -> str:
    return f"flujo:{flujo_id}"


def validar_cron(expresion: str, zona: str = "UTC") -> CronTrigger:
    """
    Valida la expresion antes de guardarla. Un cron invalido tiene que fallar en
    la peticion del usuario, no de madrugada dentro del programador.
    """
    try:
        return CronTrigger.from_crontab(expresion, timezone=zona)
    except Exception as e:
        raise ValueError(
            f"Expresion cron invalida {expresion!r}: {e}. "
            f"Formato: minuto hora dia mes dia_semana (ej. '0 6 * * *')"
        ) from e


# --------------------------------------------------------------------------- #
# El trabajo
# --------------------------------------------------------------------------- #

def correr_dataset(dataset_id: int) -> None:
    """
    Lo que ejecuta el programador. Tiene que ser una funcion de modulo, no un
    closure: APScheduler guarda la referencia por ruta de importacion para poder
    recuperarla despues de un reinicio.
    """
    with CrearSesion() as sesion:
        ds = sesion.get(Dataset, dataset_id)
        if ds is None:
            log.warning("Dataset %s ya no existe; quito su programacion", dataset_id)
            quitar(dataset_id)
            return
        if not ds.programacion_activa:
            log.info("Dataset '%s' con programacion en pausa; no se carga", ds.nombre)
            return

        nombre = ds.nombre
        try:
            r = ejecutar_carga(sesion, ds, Actor.programador())
            sesion.commit()
            log.info("Carga programada de '%s': %s filas en %s ms (%s)",
                     nombre, r["filas"], r["ms"], r["modo"])
        except ErrorCarga as e:
            # ejecutar_carga ya confirmo el registro del fallo. Se traga aqui a
            # proposito: si escapa, APScheduler apaga el trabajo y el dataset
            # deja de actualizarse en silencio.
            log.error("Carga programada de '%s' fallo: %s", nombre, e)
        except Exception:
            sesion.rollback()
            log.exception("Error inesperado en la carga programada de '%s'", nombre)


def correr_flujo(flujo_id: int) -> None:
    """
    Lo que ejecuta el programador para un flujo. Igual que `correr_dataset`: es una
    funcion de modulo porque APScheduler la guarda por su ruta de importacion.
    """
    from app.flujos import ErrorFlujo
    from app.flujos import ejecutar as ejecutar_flujo
    from app.modelos_db import Flujo

    with CrearSesion() as sesion:
        f = sesion.get(Flujo, flujo_id)
        if f is None:
            log.warning("Flujo %s ya no existe; quito su programacion", flujo_id)
            quitar_flujo(flujo_id)
            return
        if not f.programacion_activa:
            log.info("Flujo '%s' en pausa; no se ejecuta", f.nombre)
            return

        nombre = f.nombre
        try:
            r = ejecutar_flujo(sesion, f, Actor.programador())
            sesion.commit()
            log.info("Flujo '%s' completo: %d pasos en %s ms",
                     nombre, len(r["pasos"]), r["ms"])
        except ErrorFlujo as e:
            # Ya quedo registrado y confirmado. Se traga aqui: si escapa,
            # APScheduler apaga el trabajo y el flujo deja de correr en silencio.
            log.error("Flujo '%s' fallo: %s", nombre, e)
        except Exception:
            sesion.rollback()
            log.exception("Error inesperado en el flujo '%s'", nombre)


# --------------------------------------------------------------------------- #
# Ciclo de vida
# --------------------------------------------------------------------------- #

def planificador() -> BackgroundScheduler:
    global _planificador
    if _planificador is None:
        _planificador = BackgroundScheduler(
            # Comparte el motor de la app, no uno propio: asi hereda los PRAGMA
            # de SQLite (WAL, busy_timeout) y no compite consigo mismo por el
            # candado de escritura del archivo.
            jobstores={"default": SQLAlchemyJobStore(engine=motor,
                                                     tablename="tarea_programada")},
            job_defaults={
                "coalesce": True,       # una sola corrida por atraso acumulado
                "max_instances": 1,     # nunca dos cargas del mismo dataset a la vez
                "misfire_grace_time": 3600,
            },
            timezone="UTC",             # cada trabajo lleva su propia zona
        )
    return _planificador


def arrancar() -> None:
    if not config().programador_activo:
        log.info("Programador desactivado por configuracion")
        return
    p = planificador()
    if p.running:
        return
    p.start()
    sincronizar()
    log.info("Programador arriba — %d cargas programadas", len(p.get_jobs()))


def detener() -> None:
    global _planificador
    if _planificador is not None and _planificador.running:
        _planificador.shutdown(wait=False)
    _planificador = None


def sincronizar() -> None:
    """
    Alinea los trabajos con lo que dice la base. La base manda: si un trabajo
    quedo huerfano (dataset borrado a mano, cron cambiado por otra via), aqui se
    corrige. Se llama al arrancar.
    """
    from app.modelos_db import Flujo

    p = planificador()
    with CrearSesion() as sesion:
        vivos = set()
        for ds in sesion.query(Dataset).all():
            if ds.cron and ds.programacion_activa:
                vivos.add(_id_trabajo(ds.id))
                _programar(ds)
        for f in sesion.query(Flujo).all():
            if f.cron and f.programacion_activa:
                vivos.add(_id_flujo(f.id))
                _programar_flujo(f)
        for t in p.get_jobs():
            if (t.id.startswith("dataset:") or t.id.startswith("flujo:")) \
                    and t.id not in vivos:
                p.remove_job(t.id)


def _programar(ds: Dataset) -> None:
    planificador().add_job(
        correr_dataset, trigger=validar_cron(ds.cron, ds.zona_horaria),
        args=[ds.id], id=_id_trabajo(ds.id), name=f"carga {ds.nombre}",
        replace_existing=True,
    )


def _programar_flujo(f) -> None:
    planificador().add_job(
        correr_flujo, trigger=validar_cron(f.cron, f.zona_horaria),
        args=[f.id], id=_id_flujo(f.id), name=f"flujo {f.nombre}",
        replace_existing=True,
    )


def aplicar_flujo(f) -> None:
    if not config().programador_activo:
        return
    if f.cron and f.programacion_activa:
        _programar_flujo(f)
    else:
        quitar_flujo(f.id)


def quitar_flujo(flujo_id: int) -> None:
    if not config().programador_activo:
        return
    try:
        planificador().remove_job(_id_flujo(flujo_id))
    except Exception:
        pass


def proxima_corrida_flujo(flujo_id: int):
    if not config().programador_activo:
        return None
    t = planificador().get_job(_id_flujo(flujo_id))
    return t.next_run_time if t else None


def aplicar(ds: Dataset) -> None:
    """
    Refleja en el programador la programacion guardada del dataset.

    Con el programador apagado no hace nada: la programacion igual queda en la
    base y se aplica sola al siguiente arranque, via `sincronizar()`.
    """
    if not config().programador_activo:
        return
    if ds.cron and ds.programacion_activa:
        _programar(ds)
    else:
        quitar(ds.id)


def quitar(dataset_id: int) -> None:
    if not config().programador_activo:
        return
    try:
        planificador().remove_job(_id_trabajo(dataset_id))
    except Exception:
        pass    # no estaba programado; nada que quitar


def proxima_corrida(dataset_id: int):
    if not config().programador_activo:
        return None
    t = planificador().get_job(_id_trabajo(dataset_id))
    return t.next_run_time if t else None


def listar() -> list[dict]:
    if not config().programador_activo:
        return []
    return [
        {"id": t.id, "nombre": t.name,
         "proxima": t.next_run_time.isoformat() if t.next_run_time else None,
         "disparador": str(t.trigger)}
        for t in sorted(planificador().get_jobs(), key=lambda t: t.id)
    ]
