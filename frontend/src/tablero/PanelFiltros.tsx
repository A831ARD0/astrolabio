/**
 * Un panel de filtros con varios campos, que se colapsa en desplegables cuando no
 * hay alto para listas — el comportamiento del panel de filtros de Qlik.
 *
 * La decisión lista-vs-desplegable la toma el **espacio real**, medido con un
 * ResizeObserver, y no una casilla de configuración. Es lo que hace que "hago el
 * widget chico y se vuelve desplegable" funcione sin que nadie configure nada, y
 * además sobrevive a cambiar el tamaño de la ventana.
 *
 * Cada campo es su propio componente porque cada uno pide sus estados por separado
 * y los hooks no pueden ir dentro de un bucle de longitud variable.
 */

import { useEffect, useRef, useState } from 'react'

import { useCampos } from '../api/hooks'
import { FiltroCampo } from './FiltroCampo'
import { FiltroColapsado } from './FiltroColapsado'
import { useEstados } from './consulta'

/**
 * Alto mínimo, por campo, para que una lista abierta valga la pena.
 *
 * La cuenta: cabecera (22) + buscador (34) + cinco valores (22 cada uno) ≈ 165, y
 * se deja en 150 para no colapsar por dos píxeles. Se midió mirando el resultado:
 * con 125 por campo la lista técnicamente cabe pero enseña **un** valor, y ahí el
 * desplegable es mejor — dice lo elegido en una línea y abre la lista completa
 * encima del tablero.
 */
const ALTO_MINIMO = 150

function CampoAbierto({
  campo,
  etiqueta,
  modeloId,
  version,
  selecciones,
  alAlternar,
  alLimpiar,
}: {
  campo: string
  etiqueta: string
  modeloId: number
  version: number
  selecciones: Record<string, unknown[]>
  alAlternar: (campo: string, valor: unknown) => void
  alLimpiar: (campo: string) => void
}) {
  const estados = useEstados(modeloId, version, campo, selecciones)
  return (
    <FiltroCampo
      campo={campo}
      etiqueta={etiqueta}
      estados={estados.data}
      cargando={estados.isLoading}
      error={estados.error as Error | null}
      alAlternar={(v) => alAlternar(campo, v)}
      alLimpiar={() => alLimpiar(campo)}
    />
  )
}

function CampoCerrado({
  campo,
  etiqueta,
  modeloId,
  version,
  selecciones,
  abierto,
  alAbrir,
  alCerrar,
  alAlternar,
  alLimpiar,
}: {
  campo: string
  etiqueta: string
  modeloId: number
  version: number
  selecciones: Record<string, unknown[]>
  abierto: boolean
  alAbrir: () => void
  alCerrar: () => void
  alAlternar: (campo: string, valor: unknown) => void
  alLimpiar: (campo: string) => void
}) {
  // `activo`: los estados se piden solo cuando se abre. El resumen del botón sale
  // de las selecciones, que ya están aquí.
  const estados = useEstados(modeloId, version, campo, selecciones, abierto)
  return (
    <FiltroColapsado
      campo={campo}
      etiqueta={etiqueta}
      elegidos={selecciones[campo] ?? []}
      estados={estados.data}
      cargando={estados.isLoading}
      error={estados.error as Error | null}
      abierto={abierto}
      alAbrir={alAbrir}
      alCerrar={alCerrar}
      alAlternar={(v) => alAlternar(campo, v)}
      alLimpiar={() => alLimpiar(campo)}
    />
  )
}

export function PanelFiltros({
  campos,
  modeloId,
  version,
  selecciones,
  alAlternar,
  alLimpiar,
}: {
  campos: string[]
  modeloId: number
  version: number
  selecciones: Record<string, unknown[]>
  alAlternar: (campo: string, valor: unknown) => void
  alLimpiar: (campo: string) => void
}) {
  const caja = useRef<HTMLDivElement>(null)
  const [alto, setAlto] = useState(0)
  const [abierto, setAbierto] = useState<string | null>(null)
  const catalogo = useCampos(modeloId)

  useEffect(() => {
    const el = caja.current
    if (!el) return
    const obs = new ResizeObserver(([e]) => {
      if (e) setAlto(e.contentRect.height)
    })
    obs.observe(el)
    return () => obs.disconnect()
    // `campos.length` está en las dependencias a propósito. Un filtro recién
    // agregado no tiene campos, y sin campos el contenedor no se dibujaba: el
    // observador se registraba con `null` y no volvía a intentarlo nunca, así que
    // el alto se quedaba en 0 y el panel no colapsaba jamás. Se veía como que el
    // widget salía mal al agregarlo y bien al cambiarle el tipo y volver — porque
    // eso lo vuelve a montar, ya con un campo.
  }, [campos.length])

  const etiquetaDe = (clave: string) =>
    catalogo.data?.dimensiones.find((d) => d.clave === clave)?.etiqueta ??
    clave.split('.').pop() ??
    clave

  // Antes de la primera medida (alto 0) se asume que hay sitio: un parpadeo de
  // lista a desplegable se ve peor que al revés.
  const colapsar = alto > 0 && campos.length > 0 && alto / campos.length < ALTO_MINIMO

  return (
    // El contenedor se dibuja siempre, aunque no haya ni un campo: es lo que
    // mide el observador, y si no existe no hay alto que medir.
    <div ref={caja} className={`panel-filtros ${colapsar ? 'colapsado' : ''}`}>
      {campos.length === 0 && (
        <div className="vacio chico">Agrega una dimensión a este filtro.</div>
      )}
      {campos.map((campo) =>
        colapsar ? (
          <CampoCerrado
            key={campo}
            campo={campo}
            etiqueta={etiquetaDe(campo)}
            modeloId={modeloId}
            version={version}
            selecciones={selecciones}
            abierto={abierto === campo}
            alAbrir={() => setAbierto(campo)}
            alCerrar={() => setAbierto(null)}
            alAlternar={alAlternar}
            alLimpiar={alLimpiar}
          />
        ) : (
          <CampoAbierto
            key={campo}
            campo={campo}
            etiqueta={etiquetaDe(campo)}
            modeloId={modeloId}
            version={version}
            selecciones={selecciones}
            alAlternar={alAlternar}
            alLimpiar={alLimpiar}
          />
        ),
      )}
    </div>
  )
}
