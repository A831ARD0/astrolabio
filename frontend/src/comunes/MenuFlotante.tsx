/**
 * Un menú colgado de un botón, dibujado FUERA de su contenedor.
 *
 * Existe por un motivo que se repite: los contenedores recortan. La barra del
 * tablero lleva `overflow: hidden` para encogerse en una pantalla angosta en vez de
 * empujar al panel de la derecha, y un widget lo lleva porque es una celda de la
 * rejilla. Un menú colgado dentro de cualquiera de los dos sale cortado — y en un
 * widget bajo o una barra estrecha, cortado a una tira donde no se lee nada.
 *
 * Así que se dibuja en `body`, en un portal, con las coordenadas del botón. Es lo
 * mismo que ya hacía la lista de un filtro colapsado, y por lo mismo.
 *
 * El precio, que conviene saber: al vivir en `body` el menú **no** está dentro del
 * contenedor del botón, así que un manejador de «clic fuera» que solo pregunte por
 * ese contenedor lo cerraría antes de que el clic llegue a la opción. Para eso está
 * `dentroDelMenu`.
 */

import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

import type { Sitio } from './sitioDeMenu'

export function MenuFlotante({
  sitio,
  clase = '',
  children,
}: {
  sitio: Sitio | null
  clase?: string
  children: ReactNode
}) {
  if (!sitio) return null
  return createPortal(
    <div
      className={`menu-flotante ${clase}`}
      style={{ right: sitio.derecha, top: sitio.arriba }}
    >
      {children}
    </div>,
    document.body,
  )
}
