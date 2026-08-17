/**
 * Formato de cifras.
 *
 * Todo en `es-MX`. Un tablero financiero que muestre `1234567.891` en vez de
 * `1,234,567.89` obliga a contar dígitos con el dedo, y ahí es donde alguien lee
 * un millón donde hay diez.
 */

const MONEDA = new Intl.NumberFormat('es-MX', {
  style: 'currency',
  currency: 'MXN',
  maximumFractionDigits: 0,
})
const MONEDA_EXACTA = new Intl.NumberFormat('es-MX', {
  style: 'currency',
  currency: 'MXN',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const ENTERO = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 0 })
const DECIMAL = new Intl.NumberFormat('es-MX', { maximumFractionDigits: 2 })
const PORCENTAJE = new Intl.NumberFormat('es-MX', {
  style: 'percent',
  maximumFractionDigits: 1,
})

export type Formato = 'moneda' | 'entero' | 'porcentaje' | 'numero'

/** Qué poner en la fila de totales de una columna. */
export type Total = 'suma' | 'promedio' | 'ninguno'

/**
 * El total que se pone solo.
 *
 * Sumar es correcto para dinero y para conteos. Para un porcentaje **no lo es** —la
 * suma de cuarenta porcentajes no significa nada— y para una cifra con decimales
 * tampoco se sabe: casi siempre es un promedio o una razón, y sumarla daría un
 * número que parece bueno y no lo es. En esos dos casos no se pone total, y quien
 * sabe qué es la columna lo elige a mano.
 */
export function totalPorOmision(formato: Formato): Total {
  return formato === 'moneda' || formato === 'entero' ? 'suma' : 'ninguno'
}

/** Aplica la función de totales a los valores de una columna. */
export function totalizar(valores: unknown[], como: Total): number | null {
  if (como === 'ninguno') return null
  const nums = valores.filter(esNumero)
  if (nums.length === 0) return null
  const suma = nums.reduce((a, b) => a + b, 0)
  return como === 'promedio' ? suma / nums.length : suma
}

export function formatear(valor: unknown, formato: Formato = 'numero'): string {
  if (valor === null || valor === undefined) return '—'
  if (typeof valor !== 'number') return String(valor)

  switch (formato) {
    case 'moneda':
      return MONEDA.format(valor)
    case 'entero':
      return ENTERO.format(valor)
    case 'porcentaje':
      return PORCENTAJE.format(valor)
    default:
      return DECIMAL.format(valor)
  }
}

/**
 * Versión compacta para ejes y KPI grandes: `1.2 M` en vez de `1,234,567`.
 * En un eje, la cifra exacta no aporta y estorba; el valor exacto está en el
 * tooltip y en la tabla.
 */
export function compacto(valor: unknown, formato: Formato = 'numero'): string {
  if (typeof valor !== 'number') return formatear(valor, formato)
  if (formato === 'porcentaje') return PORCENTAJE.format(valor)

  const abs = Math.abs(valor)
  const signo = valor < 0 ? '-' : ''
  const pre = formato === 'moneda' ? '$' : ''
  if (abs >= 1e9) return `${signo}${pre}${DECIMAL.format(abs / 1e9)} MM`
  if (abs >= 1e6) return `${signo}${pre}${DECIMAL.format(abs / 1e6)} M`
  if (abs >= 1e4) return `${signo}${pre}${ENTERO.format(abs / 1e3)} k`
  return formatear(valor, formato)
}

/** El valor exacto, para el tooltip. */
export function exacto(valor: unknown, formato: Formato = 'numero'): string {
  if (typeof valor !== 'number') return formatear(valor, formato)
  return formato === 'moneda' ? MONEDA_EXACTA.format(valor) : formatear(valor, formato)
}

export function esNumero(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}
