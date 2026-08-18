/**
 * La hoja como informe en papel (o en PDF).
 *
 * Se imprime la hoja que se está viendo, con los filtros puestos y tal como se ve:
 * los mismos widgets, los mismos semáforos, los mismos avisos. No se vuelve a
 * consultar nada. Eso es deliberado —un informe tiene que ser una foto de lo que
 * alguien miró, no una consulta nueva que podría dar otra cifra— y también es la
 * razón de que la **portada** no sea decorativa: sin ella, un PDF que circula por
 * correo es una tabla de números sin decir de qué mes es ni quién la sacó, y eso se
 * discute en una junta sin poder comprobarlo. Es el mismo motivo por el que cada
 * Excel lleva su hoja de procedencia.
 *
 * El PDF lo hace el navegador (en el diálogo de impresión, «Guardar como PDF»). No
 * lo arma el servidor porque para eso haría falta un navegador headless instalado
 * en el servidor, y aquí el navegador ya tiene la hoja dibujada, con sus gráficos
 * y sus colores, y sale texto de verdad y no una imagen.
 *
 * Cuidado con una cosa: en papel va lo que el widget cargó. Si una tabla venía
 * recortada, la banda ámbar de «faltan filas» se imprime con ella —queda dicho en
 * el papel— pero para el detalle entero lo que hay es el Excel del widget.
 */

import { useEffect, useState } from 'react'

import type { Filtro } from '../api/tipos'

/** Cómo se lee un filtro en la portada. `cat_sucursal.nombre` no le dice nada a nadie. */
function comoSeLee(f: Filtro): { campo: string; valores: string } {
  const campo = f.campo.includes('.') ? f.campo.split('.').slice(1).join('.') : f.campo
  const vs = Array.isArray(f.valor) ? f.valor : [f.valor]
  // Con más de seis valores la lista deja de leerse y solo importa cuántos son;
  // el detalle exacto sigue en el Excel, que lleva los filtros enteros.
  const valores =
    vs.length > 6
      ? `${vs.length} valores`
      : vs.map((v) => (v === null ? '(vacío)' : String(v))).join(', ')
  return { campo, valores }
}

/**
 * La cabecera que solo existe en el papel.
 *
 * Vive siempre en el DOM y oculta; se enseña con `@media print`. Se hizo así y no
 * montándola al pulsar el botón porque `window.print()` es síncrono: lo que no
 * estuviera pintado ya, no saldría.
 */
export function PortadaInforme({
  tablero,
  hoja,
  modelo,
  version,
  certificado,
  publicado,
  filtros,
  usuario,
}: {
  tablero: string
  hoja: string
  modelo: string
  version: number
  certificado: boolean
  publicado: boolean
  filtros: Filtro[]
  usuario: string | undefined
}) {
  // La fecha se sella al imprimir, no al dibujar la pantalla: un tablero abierto
  // desde la mañana pondría la hora de la mañana en un informe de la tarde.
  const [cuando, setCuando] = useState(() => new Date())
  useEffect(() => {
    const sellar = () => setCuando(new Date())
    // `beforeprint` también salta con Ctrl+P, así que la portada sale bien aunque
    // nadie use el botón.
    window.addEventListener('beforeprint', sellar)
    return () => window.removeEventListener('beforeprint', sellar)
  }, [])

  const leidos = filtros.map(comoSeLee)

  return (
    <div className="portada-informe" aria-hidden="true">
      <div className="titulo">
        <h1>{tablero}</h1>
        <span className="hoja">{hoja}</span>
      </div>

      <dl className="procedencia">
        <dt>Filtros</dt>
        <dd>
          {leidos.length === 0 ? (
            <em>sin filtros: todos los datos del modelo</em>
          ) : (
            leidos.map((f) => (
              <span key={f.campo} className="uno">
                <b>{f.campo}</b> {f.valores}
              </span>
            ))
          )}
        </dd>

        <dt>Modelo</dt>
        <dd>
          {modelo} v{version}
          {certificado && ' · certificado'}
          {!publicado && ' · borrador'}
        </dd>

        <dt>Emitido</dt>
        <dd>
          {cuando.toLocaleString('es-MX', {
            dateStyle: 'long',
            timeStyle: 'short',
          })}
          {usuario ? ` · ${usuario}` : ''}
        </dd>
      </dl>
    </div>
  )
}

/** El botón. Abre el diálogo del navegador, donde se elige «Guardar como PDF». */
export function Imprimir({ hoja }: { hoja: string }) {
  return (
    <button
      className="btn chico"
      title={`Imprimir o guardar en PDF la hoja «${hoja}» con los filtros puestos`}
      onClick={() => window.print()}
    >
      PDF
    </button>
  )
}
