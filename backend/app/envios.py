"""
El informe que llega por correo solo.

Lo que hace este modulo es lo poco que no estaba: resolver DE QUE PERIODO es el
informe, armar el correo y mandarlo. El PDF lo hace `informe_pdf` —el mismo que el
boton de la pantalla— y el horario lo lleva el programador, que ya movia cargas y
flujos.

**El periodo es lo unico con criterio aqui.** Un informe mensual con los filtros
escritos a mano manda el mismo mes para siempre, y nadie lo nota hasta el trimestre
siguiente: la cifra es correcta, el archivo se ve bien, y es de julio en octubre. Asi
que `mes_anterior` se resuelve EN CADA ENVIO contra la columna que el modelo marca como
mes, y el mes va en el asunto — un informe que circula tiene que poder decir de que mes
es sin que nadie pregunte.
"""

from __future__ import annotations

import logging
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

from sqlalchemy.orm import Session

from app.avisos import destinatarios as leer_destinatarios
from app.config import config
from app.exportar import nombre_archivo
from app.modelos_db import Dashboard, EnvioInforme, Usuario, VersionModelo
from app.rutas.modelos import _cargar_semantico          # noqa: PLC2701
from app import informe_pdf

log = logging.getLogger("astrolabio.envios")

#: Periodos que se saben resolver.
PERIODOS = ("guardado", "mes_anterior")

#: Que va en el correo.
CUERPOS = ("pdf", "imagen", "ambos")

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")


class EnvioInvalido(RuntimeError):
    """Lo que impide mandar, dicho de forma que se pueda arreglar."""


def mes_anterior(hoy: datetime | None = None) -> int:
    """El mes de antes, como `AAAAMM`. Es lo que va en el filtro y en el asunto."""
    hoy = hoy or datetime.now(timezone.utc)
    primero = hoy.replace(day=1)
    ultimo_del_anterior = primero - timedelta(days=1)
    return ultimo_del_anterior.year * 100 + ultimo_del_anterior.month


def como_se_lee(anio_mes: int) -> str:
    """`202608` → «agosto de 2026». Para el asunto, que lo leen personas."""
    return f"{MESES[(anio_mes % 100) - 1]} de {anio_mes // 100}"


def columna_de_mes(modelo) -> tuple[str, str]:
    """
    La columna que el modelo marca como mes, o se explica por que no se puede.

    Con ninguna no hay como decir «el mes anterior», y con varias no se sabe cual manda:
    las dos se dicen al guardar el envio, no el dia 2 a las siete.
    """
    marcadas = [(e.nombre, c.nombre) for e in modelo.entidades.values()
                for c in e.campos.values() if c.grano_tiempo == "mes"]
    if len(marcadas) == 1:
        return marcadas[0]
    if not marcadas:
        raise EnvioInvalido(
            "Para mandar «el mes anterior» hace falta una columna marcada como mes en "
            "el modelo —la de «año-mes» del calendario—, y no hay ninguna. Marcala en "
            "el modelo, o elige «los filtros guardados del tablero».")
    cuales = ", ".join(f"{e}.{c}" for e, c in marcadas)
    raise EnvioInvalido(
        f"El modelo marca {len(marcadas)} columnas como mes ({cuales}), asi que no se "
        f"sabe por cual filtrar. Deja una sola.")


def filtros_del_periodo(sesion: Session, envio: EnvioInforme,
                        hoy: datetime | None = None) -> tuple[dict, str]:
    """
    Los filtros del envio y como se llama su periodo.

    Devuelve `({campo: [valor]}, "agosto de 2026")`. Con `guardado`, los filtros son los
    que el tablero tiene guardados y el periodo no se nombra: no lo decide este modulo.
    """
    d = sesion.get(Dashboard, envio.dashboard_id)
    if d is None:
        raise EnvioInvalido(f"El tablero {envio.dashboard_id} ya no existe.")

    if envio.periodo == "guardado":
        return dict((d.definicion or {}).get("selecciones") or {}), ""

    if envio.periodo != "mes_anterior":
        raise EnvioInvalido(f"Periodo desconocido: {envio.periodo!r}")

    version = sesion.get(VersionModelo, d.version_modelo_id)
    if version is None:
        raise EnvioInvalido("La version del modelo a la que apunta el tablero ya no "
                            "existe.")
    m = _cargar_semantico(version.yaml)
    ent, col = columna_de_mes(m)
    mes = mes_anterior(hoy)
    return {f"{ent}.{col}": [mes]}, como_se_lee(mes)


def asunto_de(envio: EnvioInforme, tablero: str, periodo: str) -> str:
    """
    El asunto. Lleva el periodo aunque nadie lo escriba.

    Un PDF que circula por correo tiene que poder decir de que mes es sin que haya que
    abrirlo, y el asunto es lo primero que se ve en la bandeja.
    """
    if envio.asunto:
        return f"{envio.asunto} — {periodo}" if periodo else envio.asunto
    partes = [tablero]
    if envio.hoja:
        partes.append(envio.hoja)
    if periodo:
        partes.append(periodo)
    return " — ".join(partes)


def _correo(envio: EnvioInforme, asunto: str, texto: str,
            pdf: bytes | None, imagen: bytes | None, nombre: str) -> None:
    """
    Arma el mensaje y lo manda. La imagen va EN el cuerpo, no como adjunto suelto.

    Con `related` y un `cid`, el cliente de correo la dibuja dentro del mensaje. Como
    adjunto se veria como un archivo mas que hay que abrir, que es justo lo que se
    queria evitar al pedir «la hoja en el cuerpo».
    """
    c = config()
    if not c.smtp_host:
        raise EnvioInvalido(
            "Falta configurar el servidor de correo (ASTROLABIO_SMTP_HOST). Sin eso no "
            "se manda nada.")
    if not c.smtp_remitente:
        raise EnvioInvalido("Falta el remitente (ASTROLABIO_SMTP_REMITENTE).")

    quienes = leer_destinatarios(envio.destinatarios)
    if not quienes:
        raise EnvioInvalido("El envio no tiene ni un destinatario.")

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = c.smtp_remitente
    msg["To"] = ", ".join(quienes)
    msg.set_content(texto)

    if imagen is not None:
        cid = "hoja"
        msg.add_alternative(
            f"<html><body style=\"font-family: system-ui, sans-serif\">"
            f"<p style=\"white-space: pre-wrap\">{texto}</p>"
            f"<img src=\"cid:{cid}\" style=\"max-width: 100%; height: auto; "
            f"border: 1px solid #e5e7eb; border-radius: 6px\">"
            f"</body></html>", subtype="html")
        msg.get_payload()[-1].add_related(
            imagen, maintype="image", subtype="png", cid=f"<{cid}>")

    if pdf is not None:
        msg.add_attachment(pdf, maintype="application", subtype="pdf",
                           filename=nombre)

    # timeout obligatorio: esto corre dentro de una tarea programada, y un servidor de
    # correo que no contesta no debe dejarla colgada media hora.
    with smtplib.SMTP(c.smtp_host, c.smtp_puerto, timeout=c.smtp_timeout) as s:
        if c.smtp_tls:
            s.starttls()
        if c.smtp_usuario:
            s.login(c.smtp_usuario, c.smtp_contrasena)
        s.send_message(msg)


def enviar(sesion: Session, envio: EnvioInforme,
           hoy: datetime | None = None) -> dict[str, Any]:
    """
    Genera el informe y lo manda. Devuelve como fue, para dejarlo a la vista.

    Los errores se guardan en el propio envio: un envio que lleva tres meses fallando y
    no lo dice en ningun sitio es un informe que nadie recibe y todos creen que llega.
    """
    t0 = time.perf_counter()
    d = sesion.get(Dashboard, envio.dashboard_id)
    if d is None:
        raise EnvioInvalido(f"El tablero {envio.dashboard_id} ya no existe.")

    duenio = sesion.get(Usuario, envio.creado_por) if envio.creado_por else None
    if duenio is None:
        raise EnvioInvalido(
            "El envio no tiene dueño, y el informe se genera con su sesion para que "
            "las politicas de seguridad por fila sean las de alguien. Vuelve a crearlo.")

    filtros, periodo = filtros_del_periodo(sesion, envio, hoy)
    quiere_pdf = envio.cuerpo in ("pdf", "ambos")
    quiere_imagen = envio.cuerpo in ("imagen", "ambos")

    pdf = imagen = None
    if quiere_pdf:
        pdf = informe_pdf.generar(
            d.id, hoja=envio.hoja, correo=duenio.email, rol=duenio.rol.value,
            selecciones=filtros or None)
    if quiere_imagen:
        imagen = informe_pdf.generar(
            d.id, hoja=envio.hoja, correo=duenio.email, rol=duenio.rol.value,
            imagen=True, selecciones=filtros or None)

    asunto = asunto_de(envio, d.nombre, periodo)
    texto = (f"{asunto}\n\n"
             f"Informe automatico de Astrolabio, generado el "
             f"{datetime.now().strftime('%d/%m/%Y a las %H:%M')}.\n"
             f"Se ve como lo ve {duenio.email}, que es quien lo programo.\n")
    _correo(envio, asunto, texto, pdf, imagen,
            nombre_archivo(f"{d.nombre} {envio.hoja or ''}", "pdf"))

    ms = int((time.perf_counter() - t0) * 1000)
    envio.ultimo_envio = datetime.now(timezone.utc)
    envio.ultimo_error = None
    envio.ultimo_ms = ms
    sesion.commit()
    log.info("Informe del tablero %s mandado a %s en %d ms",
             d.id, envio.destinatarios, ms)
    return {"ok": True, "ms": ms, "asunto": asunto,
            "destinatarios": leer_destinatarios(envio.destinatarios),
            "periodo": periodo, "bytes_pdf": len(pdf) if pdf else 0,
            "bytes_imagen": len(imagen) if imagen else 0}
