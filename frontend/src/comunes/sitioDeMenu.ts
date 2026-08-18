/**
 * Dónde se dibuja un menú colgado de un botón, y cómo saber si un clic cayó dentro.
 *
 * Va en su propio archivo y no junto al componente por la regla de siempre: un
 * archivo que exporta componentes Y funciones rompe el refresco en caliente. Es lo
 * mismo que ya se hizo con `plegado.ts`. Y el nombre no es `menuFlotante` porque en
 * macOS eso choca con `MenuFlotante.tsx`: el sistema de archivos no distingue
 * mayusculas y TypeScript se niega, con razon.
 */

import { useLayoutEffect, useRef, useState } from 'react'

/** Separación entre el botón y el menú. */
const HUECO = 4

/** Alineado a la derecha del botón: es donde viven todos, al final de una barra. */
export type Sitio = { derecha: number; arriba: number }

export function useMenuFlotante(abierto: boolean) {
  const boton = useRef<HTMLButtonElement | null>(null)
  const [sitio, setSitio] = useState<Sitio | null>(null)

  // Antes de pintar, no después: con `useEffect` el menú aparecía un fotograma en
  // la esquina y luego saltaba a su sitio.
  useLayoutEffect(() => {
    if (!abierto || !boton.current) return
    const r = boton.current.getBoundingClientRect()
    setSitio({
      derecha: Math.max(window.innerWidth - r.right, HUECO),
      arriba: r.bottom + HUECO,
    })
  }, [abierto])

  return { boton, sitio }
}

/** Si el clic cayó dentro de un menú flotante, sea de quien sea. */
export function dentroDelMenu(destino: Node): boolean {
  return [...document.querySelectorAll('.menu-flotante')].some((m) =>
    m.contains(destino),
  )
}
