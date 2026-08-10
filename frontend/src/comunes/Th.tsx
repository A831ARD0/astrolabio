/**
 * Encabezado de columna que ordena al pulsarlo.
 *
 * Es un `<button>` dentro del `<th>` y no un `onClick` sobre el `<th>` a secas:
 * así se llega con el teclado y el lector de pantalla anuncia que es pulsable,
 * que en una tabla de veinte columnas es la diferencia entre poder usarla y no.
 */

import type { ReactNode } from 'react'

import type { EstadoOrden } from './orden'

export function Th({
  orden,
  clave,
  children,
  className,
  style,
  titulo,
}: {
  orden: EstadoOrden
  /** Con qué se ordena esta columna. La lee la función `valor` de `useOrden`. */
  clave: string
  children: ReactNode
  className?: string
  style?: React.CSSProperties
  titulo?: string
}) {
  const activa = orden.clave === clave
  return (
    <th className={className} style={style} aria-sort={
      activa ? (orden.dir === 'asc' ? 'ascending' : 'descending') : 'none'
    }>
      <button
        type="button"
        className={`ordenar${activa ? ' activa' : ''}`}
        title={titulo ?? 'Ordenar por esta columna'}
        onClick={() => orden.alternar(clave)}
      >
        <span>{children}</span>
        <span className="flecha">{!activa ? '↕' : orden.dir === 'asc' ? '↑' : '↓'}</span>
      </button>
    </th>
  )
}
