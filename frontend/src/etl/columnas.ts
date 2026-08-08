/**
 * Qué columnas hay disponibles ANTES de cada paso.
 *
 * Parece un detalle y es lo que hacía inusable el editor: los cuadros de «Elegir
 * columnas» se dibujaban con las columnas que devolvía la vista previa, que son
 * las de la **salida** de toda la cadena. Así que al marcar `Id_Sucursal` la
 * salida pasaba a tener una sola columna, y el propio paso se quedaba con un solo
 * cuadro — imposible marcar la segunda. Lo mismo ocurría con cualquier paso
 * colocado después de un «Agrupar y resumir».
 *
 * Lo que cada paso tiene que ofrecer son las columnas que le **entran**: las del
 * origen después de los pasos que van antes de él. Eso se simula aquí, sin ir al
 * servidor: el editor se usa a golpe de clic y una ida y vuelta por cada marca
 * sería insufrible.
 *
 * La simulación es deliberadamente conservadora. Cuando un paso puede traer
 * columnas que desde aquí no se conocen —unir con otro origen sin decir cuáles
 * traer, apilar— **no se quita nada**: se prefiere ofrecer una columna de más,
 * que como mucho da un error al previsualizar, antes que esconder una que sí
 * existe y dejar a alguien sin poder elegirla. Para la salida real manda la vista
 * previa, que la calcula el compilador de verdad.
 */

import type { Paso } from '../api/etl'

/** Aplica a `cols` el efecto de un paso sobre el juego de columnas. */
function tras(cols: string[], p: Paso): string[] {
  switch (p.tipo) {
    case 'columnas': {
      // Igual que dice la pantalla: sin nada marcado se quedan todas.
      if (p.mantener?.length) {
        return p.mantener.filter((c) => cols.includes(c))
      }
      if (p.quitar?.length) {
        return cols.filter((c) => !p.quitar!.includes(c))
      }
      return cols
    }

    case 'renombrar': {
      const cambios = p.cambios ?? {}
      return cols.map((c) => cambios[c] ?? c)
    }

    case 'derivar': {
      const nueva = typeof p.nombre === 'string' ? p.nombre.trim() : ''
      return nueva && !cols.includes(nueva) ? [...cols, nueva] : cols
    }

    case 'agrupar': {
      // Agrupar es el único que reemplaza el juego entero: quedan las columnas
      // por las que se agrupa más los agregados.
      const por = p.por ?? []
      const agregados = (p.agregados ?? [])
        .map((a) => a.nombre)
        .filter((n): n is string => !!n)
      const salida = [...por, ...agregados]
      return salida.length ? salida : cols
    }

    case 'unir': {
      // Lo que se trae del otro lado, si se dijo. Si no se dijo, desde aquí no se
      // sabe qué columnas tiene el otro origen: se dejan las de este lado.
      const renombres = p.renombres ?? {}
      const traidas = (p.traer ?? []).map((c) => renombres[c] ?? c)
      return [...cols, ...traidas.filter((c) => !cols.includes(c))]
    }

    // filtrar, ordenar, limitar, distintos y apilar no quitan columnas de este
    // lado. Apilar puede agregar las de los otros orígenes, que no se conocen.
    default:
      return cols
  }
}

/**
 * Las columnas que le entran al paso número `hasta` (0 = el primero).
 *
 * Con `hasta` igual al número de pasos, devuelve la salida de la cadena completa.
 */
export function columnasAntesDe(
  columnasOrigen: string[],
  pasos: Paso[],
  hasta: number,
): string[] {
  let cols = columnasOrigen
  for (const p of pasos.slice(0, Math.max(0, hasta))) {
    cols = tras(cols, p)
  }
  return cols
}
