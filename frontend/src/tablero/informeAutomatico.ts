/**
 * Preparar la hoja para que se la lleve OTRO: el renderizador del servidor.
 *
 * El PDF que llega por correo lo genera un Chromium sin ventana que abre esta misma
 * pantalla con `?informe=una-hoja`. Al llegar aquí, la pantalla se pone en modo
 * informe, se mide, y deja el tamaño en `window.__informe` — y no llama a imprimir,
 * porque el que imprime es el otro.
 *
 * Sale del MISMO código que el botón (`prepararUnaHoja`) a propósito: dos formas de
 * medir la misma hoja se desvían la primera semana que alguien toque una, y entonces
 * el PDF del correo deja de parecerse al que se ve al pulsar el botón.
 *
 * Lo que hay aquí y no en el botón es la espera: el botón se pulsa cuando el tablero
 * ya está en pantalla, y el renderizador llega a una pantalla recién abierta, con las
 * consultas en el aire. Medirla entonces daría la altura de siete widgets diciendo
 * «Consultando…».
 */

import { prepararUnaHoja } from './medirHoja'

/** Lo que el renderizador lee cuando terminamos. */
export type EstadoInforme =
  | { listo: true; ancho: number; alto: number }
  | { listo: false; error: string }

declare global {
  interface Window {
    __informe?: EstadoInforme
  }
}

/** Tope de espera por los datos. Pasado esto se mide lo que haya y se dice. */
const ESPERA_MAXIMA = 60_000

/** Cada cuánto se comprueba si la pantalla ya se quedó quieta. */
const LATIDO = 400

const dormir = (ms: number) => new Promise((listo) => setTimeout(listo, ms))

/**
 * Espera a que no quede ninguna consulta en el aire y la hoja deje de crecer.
 *
 * Las dos condiciones hacen falta. Solo «no hay consultas» se cumple un instante
 * antes de que el widget dibuje su tabla, y la hoja crece justo después; solo «no
 * crece» se cumple mientras todos los widgets siguen vacíos y del mismo tamaño.
 */
async function esperarDatos(): Promise<void> {
  const empezo = Date.now()
  let anterior = -1
  let quietos = 0
  while (Date.now() - empezo < ESPERA_MAXIMA) {
    await dormir(LATIDO)
    const consultando = document.querySelectorAll('.cuerpo-widget .vacio').length > 0
    const alto = document.querySelector('.centro')?.scrollHeight ?? 0
    quietos = !consultando && alto === anterior ? quietos + 1 : 0
    anterior = alto
    // Dos latidos quieto: uno solo se cumple entre dos consultas de la misma tanda.
    if (quietos >= 2) return
  }
}

/**
 * Si la URL lo pide, prepara la hoja y publica su tamaño. Devuelve si lo hizo.
 *
 * Los errores también se publican: el renderizador tiene que poder decir «la hoja
 * mide más de lo que el navegador puede» en el correo de aviso, en vez de quedarse
 * esperando un tamaño que no va a llegar.
 */
export async function informeSiLoPideLaUrl(): Promise<boolean> {
  const params = new URLSearchParams(window.location.search)
  if (params.get('informe') !== 'una-hoja') return false
  try {
    await esperarDatos()
    const medida = await prepararUnaHoja()
    window.__informe = { listo: true, ...medida }
  } catch (e) {
    window.__informe = {
      listo: false,
      error: e instanceof Error ? e.message : 'No se pudo preparar la hoja',
    }
  }
  return true
}

/** La hoja que pide la URL, por id o por nombre. `null` si no pide ninguna. */
export function hojaDeLaUrl(): string | null {
  return new URLSearchParams(window.location.search).get('hoja')
}
