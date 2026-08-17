/**
 * Un campo de filtro colapsado en desplegable, como el panel de filtros de Qlik
 * cuando no tiene alto suficiente.
 *
 * Dos decisiones que valen la pena:
 *
 * 1. **El resumen no consulta al servidor.** «Marca: KIA» o «Año: 2 de 5» se saca
 *    de las selecciones, que ya están en memoria. Los cuatro estados solo se piden
 *    al abrirlo. Un panel con seis campos colapsados hace cero consultas hasta que
 *    tocas uno; si el resumen necesitara los estados, serían seis.
 *
 * 2. **La lista se dibuja en un portal.** El widget recorta lo que desborda —tiene
 *    que hacerlo, es una celda de la rejilla—, así que una lista dentro del widget
 *    saldría cortada justo en los widgets pequeños, que son los únicos que la usan.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import type { Estados } from '../api/tipos'
import { ListaValores } from './FiltroCampo'

/** Lo que dice el botón cerrado. Sale de la selección, no de una consulta. */
function resumen(elegidos: unknown[], posibles: number | null): string {
  if (elegidos.length === 0) return 'todos'
  if (elegidos.length === 1) return String(elegidos[0])
  if (posibles !== null) return `${elegidos.length} de ${posibles}`
  return `${elegidos.length} elegidos`
}

export function FiltroColapsado({
  campo,
  etiqueta,
  elegidos,
  estados,
  cargando,
  error,
  abierto,
  alAbrir,
  alCerrar,
  alAlternar,
  alLimpiar,
}: {
  campo: string
  etiqueta: string
  elegidos: unknown[]
  /** Solo llegan cuando está abierto: antes no se piden. */
  estados: Estados | undefined
  cargando: boolean
  error: Error | null
  abierto: boolean
  alAbrir: () => void
  alCerrar: () => void
  alAlternar: (valor: unknown) => void
  alLimpiar: () => void
}) {
  const boton = useRef<HTMLButtonElement>(null)
  const [caja, setCaja] = useState<{ left: number; top: number; ancho: number } | null>(
    null,
  )

  // useLayoutEffect y no useEffect: se mide antes de pintar, para que la lista no
  // aparezca un fotograma en la esquina y después salte a su sitio.
  useLayoutEffect(() => {
    if (!abierto || !boton.current) return
    const r = boton.current.getBoundingClientRect()
    const ancho = Math.max(r.width, 200)
    setCaja({
      left: Math.min(r.left, window.innerWidth - ancho - 8),
      // Si no cabe abajo, se abre hacia arriba.
      top: r.bottom + 300 > window.innerHeight ? Math.max(r.top - 300, 8) : r.bottom + 2,
      ancho,
    })
  }, [abierto])

  // Cerrar con Escape y al hacer clic fuera. Sin esto, dos desplegables abiertos a
  // la vez tapan el tablero que se está intentando leer.
  useEffect(() => {
    if (!abierto) return
    const fuera = (e: MouseEvent) => {
      const t = e.target as Node
      if (!boton.current?.contains(t) && !document.querySelector('.pop-filtro')?.contains(t)) {
        alCerrar()
      }
    }
    const tecla = (e: KeyboardEvent) => e.key === 'Escape' && alCerrar()
    document.addEventListener('mousedown', fuera)
    document.addEventListener('keydown', tecla)
    return () => {
      document.removeEventListener('mousedown', fuera)
      document.removeEventListener('keydown', tecla)
    }
  }, [abierto, alCerrar])

  const total = estados
    ? estados.seleccionado.length +
      estados.posible.length +
      estados.alternativo.length +
      estados.excluido.length
    : null

  return (
    <div className="filtro-colapsado">
      <button
        ref={boton}
        className={`caja-filtro ${elegidos.length > 0 ? 'con-seleccion' : ''} ${abierto ? 'abierto' : ''}`}
        onClick={() => (abierto ? alCerrar() : alAbrir())}
        title={campo}
      >
        <span className="nom">{etiqueta}</span>
        <span className="valor-resumen">{resumen(elegidos, total)}</span>
        <span className="flecha">▾</span>
      </button>
      {elegidos.length > 0 && (
        <button
          className="limpiar"
          title="Quitar la selección"
          onClick={(e) => {
            e.stopPropagation()
            alLimpiar()
          }}
        >
          ✕
        </button>
      )}

      {abierto &&
        caja &&
        createPortal(
          <div
            className="pop-filtro"
            style={{ left: caja.left, top: caja.top, width: caja.ancho }}
          >
            {/* Abierta, la lista tapa el tablero: si no dijera de qué campo es,
                habría que cerrarla para saberlo. */}
            <header>
              <span className="nom" title={campo}>
                {etiqueta}
              </span>
              {elegidos.length > 0 && (
                <button className="btn chico" onClick={alLimpiar}>
                  {elegidos.length} ✕
                </button>
              )}
            </header>
            <ListaValores
              estados={estados}
              cargando={cargando}
              error={error}
              alAlternar={alAlternar}
            />
          </div>,
          document.body,
        )}
    </div>
  )
}
