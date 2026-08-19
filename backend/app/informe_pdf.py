"""
El PDF de una hoja, hecho en el servidor.

**Por que en el servidor y no en el navegador.** El boton de PDF pone la hoja en modo
informe y llama a `window.print()`, y ahi manda el navegador: el tamaño de pagina que
pide el documento (`@page { size }`) lo respeta Chrome, pero Safari lo ignora y saca
la hoja en tamaño Carta, cortada. Y en todos los casos hay que pasar por el dialogo de
impresion y elegir «Guardar como PDF» a mano, porque ninguna pagina web puede elegir
el destino de impresion — es una decision de seguridad de los navegadores, no algo que
se pueda rodear.

Aqui el navegador es NUESTRO: un Chromium sin ventana que abre la misma pantalla, con
la misma hoja de estilos y el mismo codigo que mide, y devuelve el archivo. Sin
dialogo, igual en Safari que en Chrome, y sirve para el informe que se manda por
correo, donde no hay nadie para pulsar un boton.

**Por que Chromium y no una libreria de PDF.** Lo que hay que dibujar es la hoja tal
como esta: rejilla CSS, `grid-template-columns`, y graficos que echarts pinta en un
`canvas` con JavaScript. WeasyPrint no ejecuta JavaScript, asi que los graficos
saldrian en blanco; wkhtmltopdf usa un WebKit de hace una decada que no entiende la
rejilla. Con un motor distinto al de la pantalla, el informe deja de parecerse al
tablero — y entonces hay dos maquetaciones que mantener.

Licencias, que es lo que se pregunto antes de elegir: Playwright es Apache-2.0
(Microsoft) y Chromium es BSD. Las dos permiten uso comercial sin condiciones sobre el
codigo propio.
"""

from __future__ import annotations

import logging

from app.config import config
from app.seguridad import crear_token

log = logging.getLogger("astrolabio.informe")


class SinNavegador(RuntimeError):
    """Falta Chromium o Playwright. Se dice como se instala, no solo que falta."""


class InformeFallido(RuntimeError):
    """La hoja no se pudo preparar. El mensaje viene de la propia pantalla."""


#: Lo que se espera de la pantalla: o ya midio, o esta pidiendo contraseña.
#:
#: Las dos, y no solo la primera: si el token no vale, la aplicacion dibuja el ingreso
#: y ahi no va a medirse nada nunca. Esperar el tope entero para decir «se agoto el
#: tiempo» esconderia el problema, que es de sesion y se arregla en otro sitio.
GUARDIA = ("() => window.__informe !== undefined || "
           "!!document.querySelector('input[type=password]')")


def _url(dashboard_id: int, hoja: str | None) -> str:
    base = config().url_publica.rstrip("/")
    url = f"{base}/tableros/{dashboard_id}?informe=una-hoja"
    if hoja:
        from urllib.parse import quote
        url += f"&hoja={quote(hoja)}"
    return url


def _sesion_iniciada(pagina, token: str) -> None:
    """
    El token, antes de que la pantalla arranque.

    Se pone en `localStorage` con un script de inicio y no como parametro de la URL a
    proposito: una URL con el token dentro acaba en el historial, en los registros del
    servidor web y en la barra de direcciones de quien la reciba por correo.
    """
    pagina.add_init_script(
        f"localStorage.setItem('astrolabio.token', {token!r})"
    )


def generar(dashboard_id: int, *, hoja: str | None = None, correo: str,
            rol: str, imagen: bool = False) -> bytes:
    """
    El PDF —o el PNG, con `imagen`— de una hoja del tablero.

    `correo` y `rol` son de quien pide el informe: el navegador entra con un token
    suyo, asi que las politicas de seguridad por fila se aplican igual que si lo
    estuviera mirando en pantalla. Un informe que se salta las politicas porque lo
    genero el servidor seria una puerta trasera con formato PDF.
    """
    try:
        from playwright.sync_api import Error as ErrorPlaywright
        from playwright.sync_api import sync_playwright
    except ImportError as e:                                  # pragma: no cover
        raise SinNavegador(
            "Falta Playwright. En el servidor: pip install -r requirements.txt y "
            "despues python -m playwright install chromium."
        ) from e

    c = config()
    token = crear_token(correo, rol)
    espera = c.pdf_segundos * 1000

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(args=["--no-sandbox"])
            try:
                # El ancho de la ventana no decide el del informe —eso lo fija
                # `--ancho-informe`— pero si decide cuanto sitio cree tener la
                # pantalla mientras carga, y con una ventana diminuta algunos widgets
                # nacen colapsados. `escala 2` es para la imagen: en un correo se ve
                # en una pantalla de retina.
                ctx = navegador.new_context(
                    viewport={"width": 1600, "height": 1200},
                    device_scale_factor=2 if imagen else 1,
                )
                pagina = ctx.new_page()
                _sesion_iniciada(pagina, token)
                pagina.goto(_url(dashboard_id, hoja), wait_until="domcontentloaded",
                            timeout=espera)
                pagina.wait_for_function(GUARDIA, timeout=espera)
                estado = pagina.evaluate("() => window.__informe ?? null")
                if estado is None:
                    raise InformeFallido(
                        f"La aplicacion pidio contraseña al abrir el tablero: el "
                        f"usuario del informe ({correo}) no pudo entrar. Revisa que "
                        f"exista y que ASTROLABIO_URL_PUBLICA apunte a esta misma "
                        f"instalacion.")
                if not estado.get("listo"):
                    raise InformeFallido(str(estado.get("error") or
                                             "La hoja no se pudo preparar."))
                ancho, alto = int(estado["ancho"]), int(estado["alto"])
                log.info("Informe del tablero %s: %sx%s px", dashboard_id, ancho, alto)
                if imagen:
                    return pagina.screenshot(full_page=True, type="png")
                return pagina.pdf(
                    width=f"{ancho}px", height=f"{alto}px",
                    print_background=True,
                    margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                )
            finally:
                navegador.close()
    except ErrorPlaywright as e:
        # El error de «no esta instalado el navegador» es el unico que se puede
        # arreglar leyendo el mensaje, asi que se dice como.
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            raise SinNavegador(
                "Chromium no esta instalado para Playwright. En el servidor: "
                "python -m playwright install chromium."
            ) from e
        raise InformeFallido(f"El navegador no pudo generar el informe: {e}") from e
