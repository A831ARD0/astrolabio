/**
 * Lo que se escribe en la casilla de una columna, traducido a un filtro.
 *
 * Una casilla por columna y no un panel de «campo / operador / valor»: con
 * catorce columnas, tres controles cada una son cuarenta y dos, y la pregunta
 * que se hace de verdad —«¿dónde está la factura de agosto?»— se contesta
 * escribiendo `2026-08` encima de la columna.
 *
 * El precio es una mini sintaxis, que es la que usan todas las rejillas de este
 * tipo. Va en el `title` de la casilla, porque una sintaxis que no se explica en
 * el sitio donde se escribe no existe:
 *
 *   - `AOA`        contiene (texto) · igual (número)
 *   - `=AOA`       exactamente igual
 *   - `>100`       `>=`, `<`, `<=`, `<>` y `!=` también
 *   - `a, b, c`    cualquiera de la lista
 *
 * **Los filtros los aplica el servidor**, no esta pantalla. Es la diferencia
 * entre filtrar los datos y filtrar las quinientas filas que llegaron, y las dos
 * cosas se ven igual: el límite corta DESPUÉS del filtro, así que una casilla
 * que sólo mirara lo recibido diría «no hay ninguna» de algo que sí existe.
 */

import type { Filtro } from '../api/tipos'

/** Los prefijos, de más largo a más corto: `>=` antes que `>`. */
const OPERADORES: [string, Filtro['op']][] = [
  ['>=', '>='],
  ['<=', '<='],
  ['<>', '!='],
  ['!=', '!='],
  ['>', '>'],
  ['<', '<'],
  ['=', '='],
]

/**
 * @param campo    Cómo se llama la columna para el servidor.
 * @param texto    Lo que hay escrito en la casilla.
 * @param numerica Si la columna trae números. Cambia sólo el caso sin operador:
 *                 en texto «contiene», en números «igual», porque `ILIKE` sobre
 *                 una cifra no significa nada y `= 65` sí.
 */
export function filtroDeTexto(
  campo: string,
  texto: string,
  numerica: boolean,
): Filtro | null {
  const t = texto.trim()
  if (!t) return null

  for (const [prefijo, op] of OPERADORES) {
    if (t.startsWith(prefijo)) {
      const resto = t.slice(prefijo.length).trim()
      if (!resto) return null
      return { campo, op, valor: valorDe(resto, numerica) }
    }
  }

  // Una lista: «AOA, CAOA». Se parte por comas y se tiran los huecos, para que
  // una coma de más al final no busque un valor vacío.
  if (t.includes(',')) {
    const partes = t.split(',').map((v) => v.trim()).filter((v) => v !== '')
    if (partes.length === 0) return null
    return { campo, op: 'IN', valor: partes.map((v) => valorDe(v, numerica)) }
  }

  if (numerica) return { campo, op: '=', valor: valorDe(t, numerica) }
  // `ILIKE` y no `LIKE`: nadie escribe respetando las mayúsculas de sus propios
  // catálogos, y buscar «volvo» y no encontrar «VOLVO» parece que el dato falta.
  return { campo, op: 'ILIKE', valor: `%${escapar(t)}%` }
}

/**
 * Un número si la columna es numérica y lo escrito lo es.
 *
 * Si no lo es se manda el texto tal cual y que el motor lo diga: inventar un
 * cero, o descartar el filtro por lo bajo, dejaría una tabla que no responde a
 * lo que hay escrito encima.
 */
function valorDe(v: string, numerica: boolean): string | number {
  if (!numerica) return v
  const n = Number(v.replace(/[\s,]/g, ''))
  return v !== '' && Number.isFinite(n) ? n : v
}

/** `%` y `_` son comodines de `LIKE`: buscando un `%` se busca un `%`. */
function escapar(v: string): string {
  return v.replace(/([%_\\])/g, '\\$1')
}

/** Los filtros de todas las columnas, en el orden en que están en la tabla. */
export function filtrosDe(
  columnas: string[],
  texto: Record<string, string>,
  campoDe: (col: string) => string | null,
  esNumerica: (col: string) => boolean,
): Filtro[] {
  const fuera: Filtro[] = []
  for (const col of columnas) {
    const campo = campoDe(col)
    if (!campo) continue
    const f = filtroDeTexto(campo, texto[col] ?? '', esNumerica(col))
    if (f) fuera.push(f)
  }
  return fuera
}
