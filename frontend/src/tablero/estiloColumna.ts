/**
 * El formato de una columna de una tabla: negrita, alineación, colores y marco.
 *
 * Es **aparte del semáforo** y no lo pisa. Son dos cosas distintas y conviene tenerlo
 * claro: el semáforo dice algo del dato —va bien, va mal, no hay— y cambia de una fila
 * a otra; esto es del informe, es igual en todas las filas, y lo que hace es que una
 * columna se distinga de la de al lado. Un semáforo se dibuja dentro de la celda, así
 * que los dos caben: el fondo de la columna y la pastilla del semáforo encima.
 *
 * Tres decisiones que valen la pena:
 *
 * 1. **La alineación va también en la cabecera; los colores, no.** Una columna centrada
 *    con el título a la izquierda se lee torcida. Los colores de la cabecera son los de
 *    la cabecera: si cada columna pintara la suya, la primera fila de la tabla dejaría
 *    de leerse como una fila de títulos.
 * 2. **La fila de totales toma el marco y la alineación, pero no los colores.** El marco
 *    es la columna y tiene que llegar abajo; el color de fondo de los totales es lo que
 *    hace que se lean como totales, y perderlo por columna sería cambiar de sitio la
 *    información para ganar un adorno.
 * 3. **Los lados del marco se eligen, como en una hoja de cálculo.** «Arriba» y «abajo»
 *    son los extremos de la COLUMNA —el borde de arriba de la cabecera y el de abajo de
 *    la última fila, que es la de totales cuando la hay—, no de cada celda. Para las
 *    rayas entre filas está «entre filas», que es lo que en Excel se llama borde
 *    interior horizontal.
 */

import type { CSSProperties } from 'react'

export type Alineacion = 'izquierda' | 'centro' | 'derecha'

export type Lado = 'izquierda' | 'derecha' | 'arriba' | 'abajo' | 'entre'

/** Lo que se dibuja cuando se elige un color y no se dice de qué lados. */
export const LADOS_POR_OMISION: Lado[] = ['izquierda', 'derecha']

export const LADOS: { lado: Lado; nombre: string; ayuda: string }[] = [
  { lado: 'izquierda', nombre: 'Izq', ayuda: 'El lado izquierdo de la columna' },
  { lado: 'derecha', nombre: 'Der', ayuda: 'El lado derecho de la columna' },
  { lado: 'arriba', nombre: 'Arriba', ayuda: 'Encima del encabezado' },
  { lado: 'abajo', nombre: 'Abajo', ayuda: 'Debajo de la última fila' },
  { lado: 'entre', nombre: 'Entre filas', ayuda: 'Una raya entre cada dos filas' },
]

export interface EstiloColumna {
  negrita?: boolean
  alineacion?: Alineacion
  /** Color de la letra. Vacío = el del tema, que se lee en claro y en oscuro. */
  color?: string
  /** Color del fondo de la celda. */
  fondo?: string
  /** Color del marco. Sin color no se dibuja ningún lado. */
  marco?: string
  /** De qué lados. Sin decir nada: los dos lados de la columna. */
  lados?: Lado[]
}

const HACIA: Record<Alineacion, CSSProperties['textAlign']> = {
  izquierda: 'left',
  centro: 'center',
  derecha: 'right',
}

/** Dónde está la celda dentro de la columna. Decide «arriba», «abajo» y «entre». */
export interface Sitio {
  cabecera?: boolean
  /** La última celda de la columna: la de totales si hay, y si no la última fila. */
  ultima?: boolean
  /** Una fila de datos que tiene otra debajo. */
  conFilaDebajo?: boolean
}

function marco(e: EstiloColumna, s: Sitio): CSSProperties {
  if (!e.marco) return {}
  const lados = e.lados ?? LADOS_POR_OMISION
  const raya = `1px solid ${e.marco}`
  const css: CSSProperties = {}
  if (lados.includes('izquierda')) css.borderLeft = raya
  if (lados.includes('derecha')) css.borderRight = raya
  if (lados.includes('arriba') && s.cabecera) css.borderTop = raya
  if (lados.includes('abajo') && s.ultima) css.borderBottom = raya
  // «Entre filas» solo donde hay otra fila debajo: en la última seria el borde de
  // abajo de la tabla, que es otra cosa y ya tiene su propia casilla.
  if (lados.includes('entre') && s.conFilaDebajo) css.borderBottom = raya
  return css
}

/** Para una celda del cuerpo: todo. */
export function estiloCelda(
  e: EstiloColumna | undefined,
  sitio: Sitio = {},
): CSSProperties | undefined {
  if (!e) return undefined
  const s: CSSProperties = { ...marco(e, sitio) }
  if (e.negrita) s.fontWeight = 650
  if (e.alineacion) s.textAlign = HACIA[e.alineacion]
  if (e.color) s.color = e.color
  if (e.fondo) s.background = e.fondo
  return Object.keys(s).length ? s : undefined
}

/** Para la cabecera: la alineación y el marco. Ver la nota de arriba. */
export function estiloCabecera(e: EstiloColumna | undefined): CSSProperties | undefined {
  if (!e) return undefined
  const s: CSSProperties = { ...marco(e, { cabecera: true }) }
  if (e.alineacion) s.textAlign = HACIA[e.alineacion]
  return Object.keys(s).length ? s : undefined
}

/** Para la fila de totales: como la cabecera, y es la última de la columna. */
export function estiloTotal(e: EstiloColumna | undefined): CSSProperties | undefined {
  if (!e) return undefined
  const s: CSSProperties = { ...marco(e, { ultima: true }) }
  if (e.alineacion) s.textAlign = HACIA[e.alineacion]
  return Object.keys(s).length ? s : undefined
}

/** Si la columna tiene algo puesto. Sirve para ofrecer «quitar el formato». */
export function tieneEstilo(e: EstiloColumna | undefined): boolean {
  if (!e) return false
  return Object.entries(e).some(([clave, v]) => {
    if (clave === 'lados') return false        // solos no pintan nada: hace falta color
    return v !== undefined && v !== '' && v !== false
  })
}
