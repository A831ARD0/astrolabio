"""
Avisos: contar cuando una carga o un flujo falla.

Hasta ahora un fallo quedaba en el historial, que sirve si alguien va a mirarlo.
Un flujo que se rompe un martes a las 3 de la manana no se lo cuenta a nadie, y el
dano no es que falle: es que los tableros siguen abriendo, con las cifras del dia
anterior y sin ninguna senal de que estan viejas. Alguien decide con ellas.

Cuatro decisiones, y cada una viene de un modo de fallar distinto:

- **Un aviso que falla no rompe la carga.** Si el correo no sale, la carga ya
  fallo y ese fallo importa mas; y si la carga salio bien, tumbarla porque el
  servidor de correo no contesta seria absurdo. Todo lo de aqui va envuelto.

- **Se guarda cada intento de envio.** El modo de fallo real de un sistema de
  avisos no es que avise mal: es que uno crea que esta avisando. Sin el registro,
  "no me llego nada" y "no fallo nada" se ven exactamente igual.

- **Silencio entre repeticiones.** Una carga programada cada 15 minutos que esta
  rota manda 96 correos al dia; a los dos dias hay una regla en el buzon que los
  archiva sola y el aviso que si importaba tambien se archiva. Se manda uno y se
  callan los siguientes durante `silencio_minutos`.

- **Tambien se avisa al recuperarse.** Es la otra mitad del silencio: sin el aviso
  de recuperacion nadie sabe si sigue roto, y la respuesta de siempre —entrar a
  mirar— es justo lo que el aviso venia a evitar.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import config
from app.modelos_db import AvisoEnviado, ReglaAviso

log = logging.getLogger("astrolabio.avisos")

CANALES = ("correo", "webhook")

#: Que se avisa. La descripcion es la que se lee en la pantalla.
EVENTOS: dict[str, str] = {
    "carga_fallida": "Una carga falló",
    "carga_recuperada": "Una carga volvió a salir bien después de fallar",
    "flujo_fallido": "Un flujo se detuvo por un paso que falló",
    "flujo_recuperado": "Un flujo volvió a completarse después de fallar",
}

#: Los de recuperacion no se ofrecen solos: sin su fallo correspondiente no
#: llegarian nunca, y una regla que no puede disparar parece cobertura y no lo es.
REQUIERE: dict[str, str] = {
    "carga_recuperada": "carga_fallida",
    "flujo_recuperado": "flujo_fallido",
}


def _ahora() -> datetime:
    """
    Ahora en UTC y **sin tzinfo**.

    SQLite guarda estas fechas sin zona, asi que al leerlas vuelven naive. Comparar
    una fecha con zona contra las que devuelve la base es la clase de error que no
    falla: simplemente el silencio nunca coincide y se manda un aviso por corrida.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- #
# Canales
# --------------------------------------------------------------------------- #

def canal_listo(canal: str) -> tuple[bool, str]:
    """
    Si el canal puede entregar ahora mismo, y si no, que falta.

    Se muestra junto a la regla: una regla guardada sobre un canal sin configurar
    se ve igual que una que funciona, y esa confusion es exactamente el fallo que
    este modulo existe para evitar.
    """
    c = config()
    if canal == "correo":
        if not c.smtp_host:
            return False, ("Falta configurar el servidor de correo "
                           "(ASTROLABIO_SMTP_HOST). Sin eso no se manda nada.")
        if not c.smtp_remitente:
            return False, "Falta el remitente (ASTROLABIO_SMTP_REMITENTE)."
        return True, f"Sale por {c.smtp_host}:{c.smtp_puerto} como {c.smtp_remitente}"
    if canal == "webhook":
        return True, "No necesita configuración del servidor: la URL es el destino."
    return False, f"Canal desconocido: {canal!r}"


def destinatarios(destino: str) -> list[str]:
    """Los correos de `destino`, separados por coma, punto y coma o espacio."""
    bruto = destino.replace(";", ",").replace("\n", ",").replace(" ", ",")
    return [x.strip() for x in bruto.split(",") if x.strip()]


def revisar(canal: str, destino: str, eventos: list[str],
            silencio_minutos: int) -> list[str]:
    """Lo que impide guardar la regla. Se valida al guardar, no al disparar."""
    errores: list[str] = []
    if canal not in CANALES:
        errores.append(f"Canal desconocido: '{canal}'. Válidos: {', '.join(CANALES)}.")
    if not eventos:
        errores.append("Elige al menos un evento; si no, la regla no avisa de nada.")
    for e in eventos:
        if e not in EVENTOS:
            errores.append(f"Evento desconocido: '{e}'.")
        elif (base := REQUIERE.get(e)) and base not in eventos:
            errores.append(
                f"'{EVENTOS[e]}' necesita también '{EVENTOS[base]}': un aviso de "
                f"recuperación sin el del fallo no llega nunca.")
    if silencio_minutos < 0:
        errores.append("El silencio no puede ser negativo.")

    if canal == "correo":
        cuentas = destinatarios(destino)
        if not cuentas:
            errores.append("Falta a quién avisar.")
        for x in cuentas:
            if "@" not in x or x.startswith("@") or x.endswith("@"):
                errores.append(f"'{x}' no parece un correo.")
    elif canal == "webhook":
        # Se revisa al guardar y no solo al enviar: enterarse de que la URL no
        # vale cuando algo falla de madrugada es enterarse tarde.
        if (motivo := destino_permitido(destino)):
            errores.append(motivo)
    return errores


def _correo(destino: str, asunto: str, cuerpo: str) -> None:
    c = config()
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = c.smtp_remitente
    msg["To"] = ", ".join(destinatarios(destino))
    msg.set_content(cuerpo)

    # timeout obligatorio: sin el, un servidor de correo que no contesta deja el
    # envio colgado y con el la transaccion de la carga abierta.
    with smtplib.SMTP(c.smtp_host, c.smtp_puerto, timeout=c.smtp_timeout) as s:
        if c.smtp_tls:
            s.starttls()
        if c.smtp_usuario:
            s.login(c.smtp_usuario, c.smtp_contrasena)
        s.send_message(msg)


def destino_permitido(url: str) -> str | None:
    """
    Motivo por el que NO se debe llamar a esa URL, o `None` si se puede.

    Un webhook es una URL que el usuario escribe y el **servidor** visita, y eso
    es una puerta clásica: desde dentro de la red, un servidor alcanza cosas que
    el usuario no alcanza —el panel de administración de otro servicio, la base de
    datos, y en la nube el servicio de metadatos (169.254.169.254), que entrega
    credenciales de la máquina a quien las pida sin autenticación—. Bastaría poner
    esa URL como destino y leer la respuesta... o provocarla y mirar el error.

    Por eso las direcciones internas se rechazan salvo que se enciendan a
    propósito con `ASTROLABIO_WEBHOOKS_A_RED_INTERNA=true`, que es lo que hay que
    hacer cuando el destino legítimo es un servicio de la propia red.

    El de metadatos de la nube no se permite ni con eso: no hay ningún webhook
    legítimo ahí, y sí hay credenciales.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    partes = urlparse(url)
    if partes.scheme not in ("http", "https"):
        return "La URL tiene que empezar con http:// o https://."
    if not partes.hostname:
        return "La URL no tiene servidor."

    try:
        # Se resuelve el nombre: 'interno.example.com' puede apuntar a 127.0.0.1,
        # asi que mirar solo el texto de la URL no sirve de nada.
        infos = socket.getaddrinfo(partes.hostname, None)
    except OSError:
        return None          # que no resuelva ya lo dira el envio, con su error

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_link_local:
            # 169.254.0.0/16 — donde viven los metadatos de AWS, Azure y GCP.
            return (f"'{ip}' es una dirección de enlace local. Ahí es donde las "
                    f"nubes publican las credenciales de la máquina, así que "
                    f"nunca se permite como destino.")
        if (ip.is_private or ip.is_loopback) and not config().webhooks_a_red_interna:
            return (f"'{partes.hostname}' resuelve a {ip}, que es de la red "
                    f"interna del servidor. Si el destino es correcto, enciende "
                    f"ASTROLABIO_WEBHOOKS_A_RED_INTERNA=true.")
    return None


def _webhook(destino: str, asunto: str, cuerpo: str) -> None:
    import httpx

    if (motivo := destino_permitido(destino)):
        raise ValueError(motivo)

    # `text` es lo que leen tanto Teams como Slack en un webhook entrante, asi que
    # el mismo cuerpo sirve para los dos sin configurar nada. Los demas campos van
    # aparte para quien conecte esto a algo propio.
    httpx.post(destino, timeout=config().smtp_timeout, json={
        "text": f"{asunto}\n\n{cuerpo}",
        "asunto": asunto, "cuerpo": cuerpo, "origen": "astrolabio",
    }).raise_for_status()


def entregar(canal: str, destino: str, asunto: str, cuerpo: str) -> None:
    """Manda de verdad. Lanza si no pudo; el que llama decide que hacer."""
    if canal == "correo":
        _correo(destino, asunto, cuerpo)
    elif canal == "webhook":
        _webhook(destino, asunto, cuerpo)
    else:
        raise ValueError(f"Canal desconocido: {canal!r}")


# --------------------------------------------------------------------------- #
# Disparo
# --------------------------------------------------------------------------- #

def _aplica(r: ReglaAviso, evento: str, objeto_tipo: str,
            objeto_id: int | None) -> bool:
    if evento not in (r.eventos or []):
        return False
    if r.objeto_tipo is None:
        return True                      # todo
    if r.objeto_tipo != objeto_tipo:
        return False
    return r.objeto_id is None or r.objeto_id == objeto_id


def _silenciado(sesion: Session, r: ReglaAviso, evento: str,
                objeto_tipo: str, objeto_id: int | None) -> datetime | None:
    """Cuando se mando el ultimo igual, si cae dentro del silencio."""
    if not r.silencio_minutos:
        return None
    desde = _ahora() - timedelta(minutes=r.silencio_minutos)
    return sesion.scalar(
        select(AvisoEnviado.creado_en)
        .where(AvisoEnviado.regla_id == r.id, AvisoEnviado.evento == evento,
               AvisoEnviado.objeto_tipo == objeto_tipo,
               AvisoEnviado.objeto_id == objeto_id,
               AvisoEnviado.estado == "enviado",
               AvisoEnviado.creado_en >= desde)
        .order_by(AvisoEnviado.creado_en.desc()).limit(1)
    )


def notificar(sesion: Session, evento: str, *, objeto_tipo: str,
              objeto_id: int | None, asunto: str, cuerpo: str) -> list[dict[str, Any]]:
    """
    Avisa por todas las reglas que apliquen. **No lanza nunca.**

    Se llama desde dentro de la carga y del flujo, asi que una excepcion de aqui
    seria una carga tumbada por el servidor de correo. Los registros se agregan a
    la sesion del que llama; el commit es suyo.
    """
    salida: list[dict[str, Any]] = []
    try:
        reglas = list(sesion.scalars(
            select(ReglaAviso).where(ReglaAviso.activa.is_(True))))
    except Exception:
        log.exception("No se pudieron leer las reglas de aviso")
        return salida

    for r in reglas:
        if not _aplica(r, evento, objeto_tipo, objeto_id):
            continue

        registro = AvisoEnviado(
            regla_id=r.id, evento=evento, objeto_tipo=objeto_tipo,
            objeto_id=objeto_id, asunto=asunto, estado="enviado",
        )
        cuando = _silenciado(sesion, r, evento, objeto_tipo, objeto_id)
        if cuando is not None:
            registro.estado = "silenciado"
            registro.mensaje = (
                f"Ya se avisó de lo mismo a las "
                f"{cuando.strftime('%H:%M')} UTC; el silencio de la regla es de "
                f"{r.silencio_minutos} min.")
        else:
            try:
                entregar(r.canal, r.destino, asunto, cuerpo)
            except Exception as e:
                registro.estado = "error"
                # El texto del error del canal es lo unico que explica por que no
                # llego; guardarlo recortado es peor que guardarlo entero.
                registro.mensaje = f"{type(e).__name__}: {e}"
                log.error("Aviso '%s' por %s a %s fallo: %s",
                          r.nombre, r.canal, r.destino, e)

        sesion.add(registro)
        salida.append({"regla": r.nombre, "canal": r.canal,
                       "estado": registro.estado, "mensaje": registro.mensaje})
    return salida


# --------------------------------------------------------------------------- #
# Los mensajes
# --------------------------------------------------------------------------- #
# El texto vive aqui y no en quien avisa, para que el correo de una carga
# programada y el de una manual digan lo mismo. Y todos contestan las tres
# preguntas que uno se hace al leerlo a las 3 de la manana: que fallo, con que
# datos se estan viendo los tableros mientras tanto, y donde mirar.

def _cuando(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "nunca"


def por_carga_fallida(sesion: Session, ds, mensaje: str,
                      disparo: str) -> list[dict[str, Any]]:
    # Un dataset que nunca cargo bien no tiene "datos viejos": no tiene datos. Una
    # sola frase para los dos casos decia "los tableros muestran datos de nunca".
    estado = (
        f"Ultima carga que si salio bien: {_cuando(ds.ultima_carga)}.\n"
        f"Hasta que se arregle, lo que se ve en los tableros es de esa fecha.\n"
        if ds.ultima_carga else
        "Este dataset no ha cargado bien ninguna vez, asi que todavia no hay "
        "nada que ver en los tableros que lo usen.\n"
    )
    return notificar(
        sesion, "carga_fallida", objeto_tipo="dataset", objeto_id=ds.id,
        asunto=f"[Astrolabio] Falló la carga de {ds.nombre}",
        cuerpo=(
            f"La carga del dataset '{ds.nombre}' falló.\n\n"
            f"  Origen  : {ds.tabla_origen}\n"
            f"  Disparo : {disparo}\n"
            f"  Cuando  : {_cuando(_ahora())}\n"
            f"  Error   : {mensaje}\n\n" + estado
        ),
    )


def por_carga_recuperada(sesion: Session, ds, filas: int,
                         disparo: str) -> list[dict[str, Any]]:
    return notificar(
        sesion, "carga_recuperada", objeto_tipo="dataset", objeto_id=ds.id,
        asunto=f"[Astrolabio] Ya cargó bien {ds.nombre}",
        cuerpo=(
            f"El dataset '{ds.nombre}' volvio a cargar bien despues de fallar.\n\n"
            f"  Filas   : {filas:,}\n"
            f"  Disparo : {disparo}\n"
            f"  Cuando  : {_cuando(_ahora())}\n"
        ),
    )


def por_flujo_fallido(sesion: Session, flujo, mensaje: str, disparo: str,
                      pasos: list[dict]) -> list[dict[str, Any]]:
    omitidos = [p.get("nombre") or "?" for p in pasos if p.get("estado") == "omitido"]
    cola = ""
    if omitidos:
        # Lo que NO corrio es la parte que hace falta para decidir si esto se
        # atiende ahora o al llegar a la oficina.
        cola = ("\nNo se llego a ejecutar: " + ", ".join(omitidos) +
                ".\nEsos datos siguen como estaban.\n")
    return notificar(
        sesion, "flujo_fallido", objeto_tipo="flujo", objeto_id=flujo.id,
        asunto=f"[Astrolabio] Se detuvo el flujo {flujo.nombre}",
        cuerpo=(
            f"El flujo '{flujo.nombre}' no se completo.\n\n"
            f"  Disparo : {disparo}\n"
            f"  Cuando  : {_cuando(_ahora())}\n"
            f"  Fallo   : {mensaje}\n" + cola
        ),
    )


def por_flujo_recuperado(sesion: Session, flujo, pasos: int,
                         disparo: str) -> list[dict[str, Any]]:
    return notificar(
        sesion, "flujo_recuperado", objeto_tipo="flujo", objeto_id=flujo.id,
        asunto=f"[Astrolabio] Ya corrió completo el flujo {flujo.nombre}",
        cuerpo=(
            f"El flujo '{flujo.nombre}' volvio a completarse despues de fallar.\n\n"
            f"  Pasos   : {pasos}\n"
            f"  Disparo : {disparo}\n"
            f"  Cuando  : {_cuando(_ahora())}\n"
        ),
    )


def probar(sesion: Session, r: ReglaAviso) -> dict[str, Any]:
    """
    Manda un aviso de prueba **ahora**, sin silencio y sin importar los eventos.

    Es la parte del modulo que mas se gana: un canal que nadie probo no es
    cobertura, es la creencia de tenerla. Aqui si se devuelve el error tal cual,
    porque hay alguien mirando la pantalla esperandolo.
    """
    asunto = "[Astrolabio] Aviso de prueba"
    cuerpo = (
        f"Este es un aviso de prueba de la regla '{r.nombre}'.\n\n"
        f"Si te llego, los avisos de verdad tambien van a llegar por aqui:\n  "
        + "\n  ".join(EVENTOS[e] for e in (r.eventos or []) if e in EVENTOS)
        + f"\n\nCuando: {_cuando(_ahora())}\n"
    )
    registro = AvisoEnviado(regla_id=r.id, evento="prueba", objeto_tipo=None,
                            objeto_id=None, asunto=asunto, estado="enviado")
    try:
        entregar(r.canal, r.destino, asunto, cuerpo)
        resultado = {"ok": True, "detalle": f"Enviado por {r.canal} a {r.destino}."}
    except Exception as e:
        registro.estado = "error"
        registro.mensaje = f"{type(e).__name__}: {e}"
        resultado = {"ok": False, "detalle": registro.mensaje}
    sesion.add(registro)
    return resultado
