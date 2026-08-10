/**
 * Ordenar una tabla pulsando su encabezado.
 *
 * Una sola pieza para todas las tablas de la aplicación. Que cada pantalla
 * resolviera lo suyo acabaría en tablas que ordenan distinto: unas dejando los
 * vacíos arriba, otras poniendo «Cliente 10» antes que «Cliente 9», y ninguna
 * pudiendo volver al orden original.
 *
 * **Tres estados y no dos**: ascendente, descendente y *sin orden*. El tercero
 * importa porque el orden de llegada casi siempre significa algo —la auditoría
 * es cronológica, los pasos de un flujo van en su secuencia— y una tabla que no
 * puede volver a él obliga a recargar la página para recuperarlo.
 */

import { useMemo, useState } from 'react'

export type Direccion = 'asc' | 'desc'

/** Lo que necesita el encabezado para pintarse y responder al clic. */
export interface EstadoOrden {
  clave: string | null
  dir: Direccion
  alternar: (clave: string) => void
}

export interface Ordenacion<T> extends EstadoOrden {
  filas: T[]
}

/**
 * @param filas  Las filas tal como llegan.
 * @param valor  Qué se compara para una columna. Recibe la clave que se le puso
 *               al encabezado, así que una columna puede ordenar por algo que no
 *               es lo que enseña: la fecha por su instante y no por su texto.
 * @param inicial Orden de partida, si la tabla debe abrirse ya ordenada.
 */
export function useOrden<T>(
  filas: T[],
  valor: (fila: T, clave: string) => unknown,
  inicial?: { clave: string; dir?: Direccion },
): Ordenacion<T> {
  const [clave, setClave] = useState<string | null>(inicial?.clave ?? null)
  const [dir, setDir] = useState<Direccion>(inicial?.dir ?? 'asc')

  const ordenadas = useMemo(() => {
    if (!clave) return filas
    const signo = dir === 'asc' ? 1 : -1
    // Copia: ordenar la lista que llega mutaría la caché de TanStack Query, y
    // entonces el orden se quedaría pegado aunque se quite.
    return [...filas].sort((a, b) => signo * comparar(valor(a, clave), valor(b, clave)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filas, clave, dir])

  return {
    filas: ordenadas,
    clave,
    dir,
    alternar(nueva: string) {
      if (nueva !== clave) {
        setClave(nueva)
        setDir('asc')
      } else if (dir === 'asc') {
        setDir('desc')
      } else {
        setClave(null) // vuelta al orden original
      }
    },
  }
}

/**
 * Comparación única para toda la aplicación.
 *
 * Los vacíos van SIEMPRE al final, suba o baje el resto: son ausencia de dato,
 * no un valor pequeño, y verlos ocupar las primeras diez filas al ordenar por
 * una columna medio llena no ayuda a nadie.
 */
function comparar(a: unknown, b: unknown): number {
  const vacioA = a === null || a === undefined || a === ''
  const vacioB = b === null || b === undefined || b === ''
  if (vacioA || vacioB) return vacioA && vacioB ? 0 : vacioA ? 1 : -1

  if (typeof a === 'number' && typeof b === 'number') return a - b
  if (typeof a === 'boolean' && typeof b === 'boolean') return Number(a) - Number(b)
  if (a instanceof Date && b instanceof Date) return a.getTime() - b.getTime()

  // `numeric` para que «paso 9» quede antes que «paso 10», y `sensitivity` para
  // que las mayúsculas y los acentos no partan la lista en dos bloques.
  return String(a).localeCompare(String(b), 'es', {
    numeric: true,
    sensitivity: 'base',
  })
}
