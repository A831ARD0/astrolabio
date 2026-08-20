/**
 * Encabezado de columna que ordena al pulsarlo.
 *
 * Es un `<button>` dentro del `<th>` y no un `onClick` sobre el `<th>` a secas:
 * así se llega con el teclado y el lector de pantalla anuncia que es pulsable,
 * que en una tabla de veinte columnas es la diferencia entre poder usarla y no.
 *
 * Y por eso el rotulo va **dos veces**: Chrome, al repetir la cabecera de una tabla
 * en la segunda pagina de una impresion, pinta el fondo de la fila pero no los
 * botones que hay dentro —comprobado contra una pagina minima: texto y `<span>` se
 * repiten, un `<button>` no—, y quedaba una banda gris vacia encima de treinta filas
 * de numeros. La copia solo existe en papel, donde no se ordena nada.
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
  // La alineación del `th` no llega al rótulo por su cuenta: el rótulo vive dentro de
  // un botón que se reparte el ancho con la flecha de ordenar, y un `flex` no atiende a
  // `text-align`. Se traduce a `justify-content`, que es lo que ese botón sí entiende.
  const hacia = style?.textAlign
  const reparto =
    hacia === 'center' ? 'center' : hacia === 'right' ? 'flex-end' : undefined
  return (
    <th className={className} style={style} aria-sort={
      activa ? (orden.dir === 'asc' ? 'ascending' : 'descending') : 'none'
    }>
      <button
        type="button"
        style={reparto ? { justifyContent: reparto } : undefined}
        className={`ordenar${activa ? ' activa' : ''}`}
        title={titulo ?? 'Ordenar por esta columna'}
        onClick={() => orden.alternar(clave)}
      >
        <span>{children}</span>
        <span className="flecha">{!activa ? '↕' : orden.dir === 'asc' ? '↑' : '↓'}</span>
      </button>
      {/* `aria-hidden` para que no se lea dos veces. */}
      <span className="solo-papel" aria-hidden="true">
        {children}
      </span>
    </th>
  )
}
