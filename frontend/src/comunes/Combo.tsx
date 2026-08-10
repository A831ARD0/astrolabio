/**
 * Un desplegable en el que se puede escribir.
 *
 * Un `<select>` con novecientas tablas llamadas `AUDI_OAXACA__Orcamento_Produtos`
 * no se usa: hay que bajar con la rueda hasta encontrarla, y el teclado sólo
 * salta a la primera letra, que en un catálogo donde todo empieza por el mismo
 * prefijo no sirve de nada.
 *
 * Se busca con [[coincide]], así que perdona acentos, mayúsculas y el orden de
 * las palabras: «orcamento audi» encuentra `AUDI_OAXACA__Orcamento_Produtos`.
 */

import { useEffect, useMemo, useRef, useState } from 'react'

import { coincide } from './buscar'

export interface OpcionCombo {
  valor: string
  /** Lo que se enseña y contra lo que se busca. */
  etiqueta: string
  /** A la derecha y en tenue: el número de filas, el tipo, lo que aclare. */
  detalle?: string
  grupo?: string
}

/** Cuántas se pintan a la vez. Mil elementos en el DOM ponen lenta la escritura. */
const TOPE = 200

export function Combo({
  opciones,
  valor,
  alElegir,
  marcador = 'Escribe para buscar…',
  vacio,
  autoFocus,
  id,
}: {
  opciones: OpcionCombo[]
  valor: string | null
  alElegir: (valor: string) => void
  marcador?: string
  /** Qué decir cuando no hay NINGUNA opción, que no es lo mismo que no encontrar. */
  vacio?: string
  autoFocus?: boolean
  id?: string
}) {
  const [abierto, setAbierto] = useState(false)
  const [busca, setBusca] = useState('')
  const [resaltada, setResaltada] = useState(0)
  const caja = useRef<HTMLDivElement>(null)
  const lista = useRef<HTMLDivElement>(null)

  const elegida = opciones.find((o) => o.valor === valor) ?? null

  const filtradas = useMemo(() => {
    const todas = busca.trim()
      ? opciones.filter((o) => coincide(o.etiqueta, busca))
      : opciones
    return { visibles: todas.slice(0, TOPE), total: todas.length }
  }, [opciones, busca])

  // Cerrar al pulsar fuera. Sin esto la lista se queda abierta encima del resto
  // del formulario y hay que volver a pulsar el campo para quitarla.
  useEffect(() => {
    if (!abierto) return
    const fuera = (e: MouseEvent) => {
      if (!caja.current?.contains(e.target as Node)) setAbierto(false)
    }
    document.addEventListener('mousedown', fuera)
    return () => document.removeEventListener('mousedown', fuera)
  }, [abierto])

  // La resaltada tiene que verse: con doscientas en la lista, moverse con las
  // flechas sin que acompañe el scroll es moverse a ciegas.
  useEffect(() => {
    lista.current?.children[resaltada]?.scrollIntoView({ block: 'nearest' })
  }, [resaltada])

  function elegir(o: OpcionCombo) {
    alElegir(o.valor)
    setBusca('')
    setAbierto(false)
  }

  function teclas(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!abierto) return setAbierto(true)
      const paso = e.key === 'ArrowDown' ? 1 : -1
      const n = filtradas.visibles.length
      if (n) setResaltada((i) => (i + paso + n) % n)
    } else if (e.key === 'Enter') {
      const o = filtradas.visibles[resaltada]
      if (abierto && o) {
        e.preventDefault()
        elegir(o)
      }
    } else if (e.key === 'Escape' && abierto) {
      // `stopPropagation` para que Escape cierre la lista y NO el diálogo que la
      // contiene: perder el formulario entero por cerrar un desplegable enfada.
      e.stopPropagation()
      setAbierto(false)
    }
  }

  return (
    <div className="combo" ref={caja}>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={abierto}
        autoFocus={autoFocus}
        className="mono"
        placeholder={elegida ? elegida.etiqueta : marcador}
        value={abierto ? busca : (elegida?.etiqueta ?? '')}
        onFocus={() => setAbierto(true)}
        onChange={(e) => {
          setBusca(e.target.value)
          setResaltada(0)
          setAbierto(true)
        }}
        onKeyDown={teclas}
      />

      {abierto && (
        <div className="combo-lista" ref={lista}>
          {filtradas.visibles.map((o, i) => (
            <button
              key={o.valor}
              type="button"
              className={`combo-opcion${i === resaltada ? ' resaltada' : ''}${
                o.valor === valor ? ' puesta' : ''
              }`}
              onMouseEnter={() => setResaltada(i)}
              onClick={() => elegir(o)}
            >
              <span className="mono">{o.etiqueta}</span>
              {o.detalle && <span className="chico tenue">{o.detalle}</span>}
              {o.grupo && <span className="etiqueta dim">{o.grupo}</span>}
            </button>
          ))}

          {/* Sin nada que ofrecer y sin nada escrito, «ninguna coincide con “”»
              manda a corregir una búsqueda que no se hizo. Lo que pasa es que la
              lista está vacía, y eso es otra cosa. */}
          {filtradas.total === 0 && (
            <div className="vacio chico">
              {opciones.length === 0
                ? (vacio ?? 'No hay nada que elegir todavía.')
                : `Ninguna coincide con «${busca}».`}
            </div>
          )}
          {/* Se dice cuántas quedaron fuera. Una lista recortada en silencio se
              lee como «no existe», y entonces se busca donde no hay que buscar. */}
          {filtradas.total > TOPE && (
            <div className="chico tenue" style={{ padding: '6px 9px' }}>
              y {filtradas.total - TOPE} más. Escribe para acotar.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
