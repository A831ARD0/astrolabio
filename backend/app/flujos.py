"""
Flujos: cargar y transformar en cadena.

El ejecutor llama a los MISMOS servicios que los botones —`cargas.ejecutar_carga` y
`transformar.ejecutar`—, así que cada paso deja su propia entrada en su propio
historial además del resumen del flujo. Un paso ejecutado por el flujo y el mismo
paso ejecutado a mano son indistinguibles en el registro salvo por el campo que dice
quién lo disparó, que es justo lo que interesa.

La regla al fallar es **detenerse**. Seguir recalculando una transformación cuando la
carga de la que depende no ocurrió produce un número que parece fresco y no lo es —y
esa es la clase de error que nadie detecta hasta que alguien decide con él.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import avisos
from app.auditoria import registrar
from app.cargas import Actor, ErrorCarga, ejecutar_carga
from app.modelos_db import (
    Dataset, EstadoCarga, Flujo, FlujoEjecucion,
    Transformacion as TransformacionDB,
)
from app.transformar import ErrorEjecucion, definicion_de
from app.transformar import ejecutar as ejecutar_transformacion

log = logging.getLogger("astrolabio.flujos")

TIPOS_PASO = ("carga", "transformacion")


class ErrorFlujo(Exception):
    """El flujo no se completó. Ya quedó registrado."""


# --------------------------------------------------------------------------- #
# Validación del orden
# --------------------------------------------------------------------------- #

def revisar_pasos(sesion: Session, pasos: list[dict]) -> list[str]:
    """
    Errores que impiden guardar el flujo: pasos mal formados o que apuntan a algo
    que no existe.
    """
    errores: list[str] = []
    if not pasos:
        return ["El flujo no tiene ningún paso."]

    vistos: set[tuple[str, int]] = set()
    for i, p in enumerate(pasos, start=1):
        tipo = p.get("tipo")
        if tipo not in TIPOS_PASO:
            errores.append(f"Paso {i}: tipo '{tipo}' desconocido.")
            continue
        try:
            id_ = int(p.get("id"))
        except (TypeError, ValueError):
            errores.append(f"Paso {i}: falta el identificador.")
            continue

        clave = (tipo, id_)
        if clave in vistos:
            errores.append(
                f"Paso {i}: repetido. Ejecutar lo mismo dos veces en el mismo "
                f"flujo solo duplica el trabajo.")
        vistos.add(clave)

        if tipo == "carga":
            if sesion.get(Dataset, id_) is None:
                errores.append(f"Paso {i}: el dataset {id_} ya no existe.")
        elif sesion.get(TransformacionDB, id_) is None:
            errores.append(f"Paso {i}: la transformación {id_} ya no existe.")
    return errores


def revisar_orden(sesion: Session, pasos: list[dict]) -> list[str]:
    """
    Avisos —no errores— sobre el orden, deducidos del linaje.

    Son avisos y no errores porque hay casos legítimos: una transformación puede
    leer de un dataset que se carga en otro flujo, o de una tabla que no se carga
    nunca. Bloquear eso sería adivinar. Pero el caso de verdad frecuente —el paso
    que recalcula ANTES de cargar lo que lee— sí hay que decirlo.
    """
    avisos: list[str] = []

    # Posición en la que cada nombre queda disponible.
    disponible_en: dict[str, int] = {}
    for i, p in enumerate(pasos):
        nombre = _nombre_de(sesion, p)
        if nombre:
            disponible_en[nombre] = i

    for i, p in enumerate(pasos):
        if p.get("tipo") != "transformacion":
            continue
        t = sesion.get(TransformacionDB, int(p["id"]))
        if t is None:
            continue
        try:
            lee = definicion_de(t)
        except Exception:
            continue

        for o in lee.origenes:
            if o.tipo != "dataset":
                continue                     # las tablas del motor están siempre
            posicion = disponible_en.get(o.referencia)
            if posicion is None:
                avisos.append(
                    f"Paso {i + 1} ({t.nombre}) lee de '{o.referencia}', que este "
                    f"flujo no actualiza. Se usará lo que haya de la última vez.")
            elif posicion > i:
                avisos.append(
                    f"Paso {i + 1} ({t.nombre}) lee de '{o.referencia}', que se "
                    f"actualiza en el paso {posicion + 1}, DESPUÉS. Tal como está, "
                    f"trabajará con los datos anteriores.")
    return avisos


def _nombre_de(sesion: Session, paso: dict) -> str | None:
    try:
        id_ = int(paso.get("id"))
    except (TypeError, ValueError):
        return None
    if paso.get("tipo") == "carga":
        ds = sesion.get(Dataset, id_)
        return ds.nombre if ds else None
    t = sesion.get(TransformacionDB, id_)
    return t.nombre if t else None


def sugerir_orden(sesion: Session, pasos: list[dict]) -> list[dict]:
    """
    Reordena los pasos para que cada transformación vaya después de lo que lee, y
    agrega las cargas que faltan de los datasets que las transformaciones necesitan.

    Es una propuesta que el usuario revisa, no un cambio automático: puede haber
    razones para el orden que tenía.
    """
    datasets = {d.nombre: d for d in sesion.scalars(select(Dataset))}
    trans = {t.nombre: t for t in sesion.scalars(select(TransformacionDB))}

    # Qué lee cada transformación (solo lo que este proyecto materializa).
    def lee(nombre: str) -> list[str]:
        t = trans.get(nombre)
        if t is None:
            return []
        try:
            return [o.referencia for o in definicion_de(t).origenes
                    if o.tipo == "dataset"]
        except Exception:
            return []

    pedidos: list[str] = []
    for p in pasos:
        nombre = _nombre_de(sesion, p)
        if nombre:
            pedidos.append(nombre)

    orden: list[str] = []
    visitando: set[str] = set()

    def colocar(nombre: str) -> None:
        if nombre in orden or nombre in visitando:
            return                            # ya está, o hay un ciclo
        visitando.add(nombre)
        for dependencia in lee(nombre):
            if dependencia in trans or dependencia in datasets:
                colocar(dependencia)
        visitando.discard(nombre)
        if nombre not in orden:
            orden.append(nombre)

    for nombre in pedidos:
        colocar(nombre)

    salida: list[dict] = []
    for nombre in orden:
        if nombre in trans:
            salida.append({"tipo": "transformacion", "id": trans[nombre].id,
                           "nombre": nombre})
        elif nombre in datasets:
            salida.append({"tipo": "carga", "id": datasets[nombre].id,
                           "nombre": nombre})
    return salida


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #

def ejecutar(sesion: Session, flujo: Flujo, actor: Actor) -> dict[str, Any]:
    """
    Corre el flujo entero. Devuelve el resumen; lanza `ErrorFlujo` si algún paso
    falló y la política es detenerse.
    """
    total = len(flujo.pasos or [])
    ejec = FlujoEjecucion(flujo_id=flujo.id, estado=EstadoCarga.corriendo,
                          origen=actor.origen, iniciado_por=actor.id,
                          detalle={"pasos": [], "total": total})
    sesion.add(ejec)
    sesion.flush()

    # Como acabo la vez anterior: es lo que distingue "sigue roto" de "ya se
    # arreglo", y solo se puede leer antes de escribir el resultado de esta.
    venia_fallando = sesion.scalar(
        select(FlujoEjecucion.estado)
        .where(FlujoEjecucion.flujo_id == flujo.id, FlujoEjecucion.id < ejec.id,
               FlujoEjecucion.estado != EstadoCarga.corriendo)
        .order_by(FlujoEjecucion.id.desc()).limit(1)
    ) == EstadoCarga.error

    # Confirmar YA, antes del primer paso. Sin esto, la corrida no existe para
    # nadie mas hasta que termina: veintiocho tablas escribiendose en el disco y
    # la pantalla diciendo "todavia no ha corrido". Lo que se ve es lo que esta
    # confirmado.
    sesion.commit()

    t0 = time.perf_counter()
    resultados: list[dict[str, Any]] = []
    fallo: str | None = None

    def _apuntar(en_curso: dict[str, Any] | None = None) -> None:
        """
        Deja el avance en la base y lo confirma.

        Se llama antes y despues de cada paso: antes con el paso marcado como
        'corriendo' —para saber en cual va— y despues con su resultado. Es una
        escritura pequena por paso; al lado de traer una tabla entera no se nota,
        y es la diferencia entre ver avanzar la noche y mirar una pantalla muda.
        """
        ejec.detalle = {"pasos": resultados + ([en_curso] if en_curso else []),
                        "total": total}
        sesion.commit()

    # Cuantas veces se vuelve a intentar un paso, y cuanto se espera. Con cuarenta
    # sucursales, que una este apagada a las seis de la manana pasa seguido, y
    # eso a los dos minutos ya no esta. Cero por omision: la primera vez que algo
    # falla hay que verlo.
    reintentos = max(0, int(flujo.reintentos or 0))
    espera = max(0, int(flujo.espera_reintento_seg or 0))

    for i, paso in enumerate(flujo.pasos or [], start=1):
        nombre = paso.get("nombre") or _nombre_de(sesion, paso) or "?"
        inicio = time.perf_counter()
        ultimo_error: Exception | None = None
        salio: dict[str, Any] | None = None

        for intento in range(1, reintentos + 2):
            _apuntar({"paso": i, "tipo": paso.get("tipo"), "nombre": nombre,
                      "estado": "corriendo",
                      **({"intento": intento} if intento > 1 else {})})
            try:
                if paso.get("tipo") == "carga":
                    ds = sesion.get(Dataset, int(paso["id"]))
                    if ds is None:
                        raise ErrorFlujo(f"el dataset {paso['id']} ya no existe")
                    r = ejecutar_carga(sesion, ds, actor)
                    salio = {"paso": i, "tipo": "carga", "nombre": nombre,
                             "estado": "exito", "filas": r["filas"],
                             "modo": r["modo"], "ms": r["ms"]}
                else:
                    t = sesion.get(TransformacionDB, int(paso["id"]))
                    if t is None:
                        raise ErrorFlujo(
                            f"la transformación {paso['id']} ya no existe")
                    r = ejecutar_transformacion(sesion, t, actor)
                    salio = {"paso": i, "tipo": "transformacion",
                             "nombre": nombre, "estado": "exito",
                             "filas": r["filas"], "ms": r["ms"]}
                # Un exito al tercer intento NO es lo mismo que un exito: queda
                # anotado, o el origen que va mal se esconde detras del reintento.
                if intento > 1:
                    salio["intentos"] = intento
                break
            except (ErrorCarga, ErrorEjecucion, ErrorFlujo) as e:
                ultimo_error = e
                if intento <= reintentos:
                    log.warning("Flujo '%s' paso %s (%s) fallo en el intento %s "
                                "de %s: %s. Reintenta en %ss",
                                flujo.nombre, i, nombre, intento,
                                reintentos + 1, e, espera)
                    if espera:
                        time.sleep(espera)

        if salio is not None:
            resultados.append(salio)
        else:
            e = ultimo_error
            resultados.append({
                "paso": i, "tipo": paso.get("tipo"), "nombre": nombre,
                "estado": "error", "mensaje": str(e),
                "ms": round((time.perf_counter() - inicio) * 1000, 1),
                **({"intentos": reintentos + 1} if reintentos else {}),
            })
            fallo = (f"paso {i} ({nombre}): {e}"
                     + (f" — tras {reintentos + 1} intentos" if reintentos else ""))
            if flujo.al_fallar == "detener":
                # Los pasos que no se llegaron a intentar se anotan como omitidos:
                # un hueco en el historial se lee como "corrió y no hizo nada".
                for j, restante in enumerate(
                        (flujo.pasos or [])[i:], start=i + 1):
                    resultados.append({
                        "paso": j, "tipo": restante.get("tipo"),
                        "nombre": restante.get("nombre"), "estado": "omitido",
                    })
                _apuntar()
                break
        _apuntar()

    ms = round((time.perf_counter() - t0) * 1000, 1)
    ejec.ms = int(ms)
    ejec.detalle = {"pasos": resultados, "total": total}
    ejec.estado = EstadoCarga.error if fallo else EstadoCarga.exito
    ejec.mensaje = fallo
    flujo.ultima_ejecucion = datetime.now(timezone.utc)

    registrar(sesion, accion="flujo_fallido" if fallo else "flujo_ejecutado",
              usuario_id=actor.id, email=actor.email, objeto_tipo="flujo",
              objeto_id=flujo.id,
              detalle={"nombre": flujo.nombre, "disparo": actor.origen,
                       "pasos": len(resultados), "ms": ms, "error": fallo})

    # El aviso del flujo no reemplaza el de cada carga: son dos preguntas
    # distintas —"salio bien la noche" y "cual paso la arruino"— y quien atiende
    # la primera no siempre es quien arregla la segunda. El silencio de la regla
    # es lo que evita que eso se vuelva ruido.
    if fallo:
        avisos.por_flujo_fallido(sesion, flujo, fallo, actor.origen, resultados)
    elif venia_fallando:
        avisos.por_flujo_recuperado(sesion, flujo, len(resultados), actor.origen)

    resumen = {
        "estado": "error" if fallo else "exito",
        "ms": ms, "pasos": resultados, "mensaje": fallo,
    }
    if fallo:
        # Confirmar antes de lanzar: si no, el rollback se lleva el historial del
        # flujo justo cuando más se necesita.
        sesion.commit()
        raise ErrorFlujo(fallo)
    return resumen
