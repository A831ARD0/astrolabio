"""
El servicio de carga: un solo camino para traer datos de un origen a Parquet.

Vive fuera de las rutas HTTP a proposito. El programador tiene que ejecutar la
MISMA funcion que el boton, no una copia parecida. Si fueran dos caminos, el
historial y la auditoria de una carga automatica acabarian distintos de los de
una manual, y con eso se pierde justo lo que sirve para depurar por que una
cifra no cuadra a las 3 de la manana.

Tres modos, excluyentes:

    completo      reescribe el dataset entero.
    incremental   trae lo posterior a la marca maxima y agrega.
    particion     recarga un rango de fechas y reemplaza solo esas particiones.

El modo NO se elige a mano en cada corrida: sale del estado del dataset, y por eso
la primera carga es completa sin que nadie lo pida (no hay marca de la cual seguir)
y las siguientes son incrementales solas. Si el dataset tiene una ventana movil
—"siempre el mes actual y el anterior"— gana ella, porque es la unica de las tres
que vuelve a mirar filas que ya se habian traido.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import avisos
from app.auditoria import registrar
from app.conectores import ErrorConector, PeticionIngesta, crear
from app.config import config
from app.modelos_db import CargaEjecucion, Conexion, Dataset, EstadoCarga
from app.seguridad import descifrar
from app.ventanas import VentanaInvalida

log = logging.getLogger(__name__)
from app.ventanas import resolver as resolver_ventana


class ErrorCarga(Exception):
    """La carga no se pudo completar. Ya quedo registrada en el historial."""


@dataclass
class Actor:
    """Quien pide la carga. `id=None` es el programador: nadie la pidio a mano."""
    id: int | None
    email: str
    origen: str = "manual"

    @staticmethod
    def programador() -> Actor:
        return Actor(id=None, email="programador@astrolabio", origen="programado")


def ruta_dataset(nombre: str) -> Path:
    return Path(config().ruta_duckdb).parent / "datasets" / nombre


def ejecutar_carga(
    sesion: Session,
    ds: Dataset,
    actor: Actor,
    *,
    incremental: bool = True,
    limite: int | None = None,
    rango_desde: str | None = None,
    rango_hasta: str | None = None,
    usar_ventana: bool = True,
) -> dict:
    """
    Ejecuta la carga y deja constancia de como salio.

    Lanza `ErrorCarga` si falla, pero solo DESPUES de confirmar el registro del
    fallo: el historial de cargas fallidas es lo que se necesita para depurar, y
    perderlo por un rollback ya paso una vez.

    `usar_ventana=False` es para la carga completa a proposito ("volver a traer
    todo"), que tiene que poder saltarse la ventana del dataset.
    """
    # La ventana se resuelve AHORA, no cuando se guardo. Un rango calculado al
    # configurarla recargaria enero para siempre.
    ventana = ds.ventana if (usar_ventana and ds.ventana
                             and not (rango_desde or rango_hasta)) else None
    error_ventana = None
    if ventana:
        try:
            rango_desde, rango_hasta = resolver_ventana(ventana, ds.zona_horaria)
        except VentanaInvalida as e:
            error_ventana = str(e)

    es_particion = bool(rango_desde or rango_hasta)
    usa_incremental = bool(
        not es_particion and incremental
        and ds.columna_incremental and ds.marca_maxima
    )
    modo = ("particion" if es_particion
            else "incremental" if usa_incremental
            else "completo")

    detalle: dict = {"rango": [rango_desde, rango_hasta]} if es_particion else {}
    if ventana:
        detalle["ventana"] = ventana
    ejec = CargaEjecucion(
        dataset_id=ds.id, estado=EstadoCarga.corriendo, modo=modo,
        origen=actor.origen, iniciado_por=actor.id, detalle=detalle,
    )
    sesion.add(ejec)
    sesion.flush()

    # Como acabo la vez anterior, para saber si esta corrida es una recuperacion.
    # Se lee ANTES de tocar nada: despues ya no se distingue de la actual.
    venia_fallando = _venia_fallando(sesion, ds.id, ejec.id)

    # Confirmar YA, antes de tocar el origen. SQLite admite un escritor a la
    # vez: con la transaccion abierta durante toda la ingesta —minutos, en una
    # tabla grande por el puente— cualquier otra escritura espera el
    # `busy_timeout` y despues falla con «database is locked». Ahi salia el
    # Error 500 al crear un flujo mientras corria una extraccion.
    #
    # Confirmar aqui suelta el candado durante lo que de verdad tarda, que es
    # traer los datos, y de paso deja el renglon 'corriendo' a la vista.
    sesion.commit()

    if error_ventana:
        _fallar(sesion, ejec, ds, actor, error_ventana)

    conexion = sesion.get(Conexion, ds.conexion_id)
    if conexion is None:
        _fallar(sesion, ejec, ds, actor,
                f"El dataset '{ds.nombre}' apunta a una conexion que ya no existe")

    try:
        conector = crear(conexion.tipo, json.loads(descifrar(conexion.config_cifrada)))
    except ErrorConector as e:
        _fallar(sesion, ejec, ds, actor, str(e))
    except Exception as e:
        _fallar(sesion, ejec, ds, actor, _inesperado(e, "al abrir la conexion"))

    try:
        r = conector.ingestar(PeticionIngesta(
            esquema=ds.esquema_origen, tabla=ds.tabla_origen, destino=ds.nombre,
            # None = todas. Guardar la lista completa dejaria fuera para siempre
            # lo que el origen agregue despues.
            columnas=ds.columnas or None,
            # La columna incremental se pasa siempre, aunque la carga sea
            # completa: si no, la primera carga no registra la marca maxima y el
            # modo incremental nunca llega a activarse.
            columna_incremental=ds.columna_incremental,
            desde=ds.marca_maxima if usa_incremental else None,
            particionar_por=ds.particionar_por, limite=limite,
            reemplazar_todo=(modo == "completo"),
            rango_desde=rango_desde, rango_hasta=rango_hasta,
        ), str(ruta_dataset(ds.nombre)))
    except ErrorConector as e:
        _fallar(sesion, ejec, ds, actor, str(e))
    except Exception as e:
        # Lo que el conector no supo traducir: un fallo de pyarrow, de duckdb, un
        # permiso al escribir el Parquet, un driver que devuelve algo raro. Antes
        # se escapaba de aqui, y entonces pasaban DOS cosas malas a la vez: el
        # usuario veia "Error 500" pelado, y el rollback de la sesion se llevaba
        # por delante el registro de la ejecucion, asi que el historial decia
        # "todavia no se ha cargado nunca". Sin mensaje y sin rastro.
        _fallar(sesion, ejec, ds, actor, _inesperado(e, f"al traer {ds.tabla_origen}"))

    ejec.estado = EstadoCarga.exito
    ejec.filas = r.filas
    ejec.bytes_escritos = r.bytes_escritos
    ejec.ms = int(r.ms)
    # El total del dataset solo se suma cuando la carga agrega. En una recarga de
    # particion no se sabe cuantas filas reemplazo, asi que se vuelve a contar
    # sobre el Parquet en vez de inventar una suma.
    if usa_incremental:
        ds.filas = ds.filas + r.filas
    elif es_particion:
        ds.filas = _contar_parquet(ds.nombre)
    else:
        ds.filas = r.filas

    # Todo lo que antes solo viajaba en la respuesta HTTP queda tambien aqui:
    # desde que la carga corre en segundo plano, el historial es el unico sitio
    # donde se puede mirar como salio. Va DESPUES de actualizar `ds.filas`, que
    # es de donde sale el total.
    ejec.detalle = {**ejec.detalle,
                    "particiones": r.particiones_escritas,
                    "archivos": len(r.archivos),
                    "filas_sin_particion": r.filas_sin_particion,
                    "marca_maxima": r.marca_maxima,
                    "filas_totales": ds.filas}

    ds.bytes_parquet = r.bytes_escritos or ds.bytes_parquet
    ds.ultima_carga = datetime.now(timezone.utc)
    if r.marca_maxima:
        ds.marca_maxima = r.marca_maxima

    registrar(sesion, accion="carga", usuario_id=actor.id, email=actor.email,
              objeto_tipo="dataset", objeto_id=ds.id,
              detalle={"modo": modo, "disparo": actor.origen, "ventana": ventana,
                       "filas": r.filas, "ms": r.ms,
                       "particiones": r.particiones_escritas})

    if venia_fallando:
        # La otra mitad del aviso de fallo: sin esto nadie sabe si sigue roto, y
        # la forma de averiguarlo —entrar a mirar— es lo que el aviso evitaba.
        avisos.por_carga_recuperada(sesion, ds, r.filas, actor.origen)

    return {
        "estado": "exito", "modo": modo, "disparo": actor.origen,
        "ventana": ventana, "rango": [rango_desde, rango_hasta] if es_particion else None,
        "filas": r.filas, "mb": round(r.bytes_escritos / 1024 / 1024, 2),
        "ms": r.ms, "archivos": len(r.archivos),
        "marca_maxima": r.marca_maxima, "filas_totales": ds.filas,
        "filas_sin_particion": r.filas_sin_particion,
        "particiones": r.particiones_escritas,
    }


def _venia_fallando(sesion: Session, dataset_id: int, esta: int) -> bool:
    """Si la corrida anterior a `esta` termino en error."""
    previa = sesion.scalar(
        select(CargaEjecucion.estado)
        .where(CargaEjecucion.dataset_id == dataset_id,
               CargaEjecucion.id < esta,
               CargaEjecucion.estado != EstadoCarga.corriendo)
        .order_by(CargaEjecucion.id.desc()).limit(1)
    )
    return previa == EstadoCarga.error


def _inesperado(e: Exception, donde: str) -> str:
    """
    Un fallo que nadie previo, dicho de forma que se pueda actuar.

    El rastro completo va al registro del servidor y NO al mensaje: puede traer
    rutas, consultas y hasta valores de las filas, y eso acaba en la pantalla de
    quien no deberia verlo. Lo que sube es el tipo y el texto de la excepcion,
    que es lo que permite buscar; el rastro esta a un `Get-Content` de distancia
    para quien administra la maquina.
    """
    log.exception("Fallo inesperado %s", donde)
    texto = str(e).strip() or "sin mensaje"
    return (f"Fallo inesperado {donde}: {type(e).__name__}: {texto}. "
            f"El detalle completo esta en el registro del servidor.")


def _fallar(sesion: Session, ejec: CargaEjecucion, ds: Dataset,
            actor: Actor, mensaje: str) -> NoReturn:
    ejec.estado = EstadoCarga.error
    ejec.mensaje = mensaje
    registrar(sesion, accion="carga_fallida", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dataset", objeto_id=ds.id,
              detalle={"error": mensaje, "disparo": actor.origen})
    # Avisar antes del commit, para que el registro del aviso viaje con el del
    # fallo. `notificar` no lanza: un servidor de correo caido no debe cambiar en
    # nada lo que esta funcion le cuenta al usuario.
    avisos.por_carga_fallida(sesion, ds, mensaje, actor.origen)
    # Confirmar ANTES de lanzar: al propagar, la dependencia de sesion hace
    # rollback y se perderia el registro del fallo.
    sesion.commit()
    raise ErrorCarga(mensaje)


def _contar_parquet(nombre: str) -> int:
    ruta = ruta_dataset(nombre)
    if not any(ruta.rglob("*.parquet")):
        return 0
    import duckdb
    con = duckdb.connect()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM read_parquet(?, hive_partitioning=true)",
            [f"{ruta}/**/*.parquet"],
        ).fetchone()[0]
    finally:
        con.close()
