/**
 * Botón de exportación de un widget.
 *
 * Pide el archivo al servidor y no lo arma aquí a propósito: el navegador solo
 * tiene las filas que el widget cargó para dibujarse, así que un archivo hecho en
 * el cliente saldría recortado con toda la pinta de estar completo. Además el
 * servidor es quien aplica la seguridad por fila.
 *
 * El límite del widget tampoco se hereda: para dibujar un gráfico bastan 15 filas,
 * pero quien exporta quiere el detalle entero.
 */

import { useEffect, useRef, useState } from 'react'

import { ErrorApi, token } from '../api/cliente'
import type { Widget } from '../api/tipos'
import { filtrosDeSelecciones } from './consulta'

const FILAS_EXPORTACION = 50_000

export function Exportar({
  widget,
  modeloId,
  version,
  selecciones,
  rutasElegidas,
}: {
  widget: Widget
  modeloId: number
  version: number
  selecciones: Record<string, unknown[]>
  rutasElegidas: Record<string, string>
}) {
  const [abierto, setAbierto] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const caja = useRef<HTMLDivElement | null>(null)

  // Cerrar al hacer clic fuera y con Escape. Un menú que solo se cierra con el
  // mismo botón se queda abierto tapando el widget de al lado.
  useEffect(() => {
    if (!abierto) return
    const fuera = (e: MouseEvent) => {
      if (!caja.current?.contains(e.target as Node)) setAbierto(false)
    }
    const escape = (e: KeyboardEvent) => e.key === 'Escape' && setAbierto(false)
    document.addEventListener('mousedown', fuera)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', fuera)
      document.removeEventListener('keydown', escape)
    }
  }, [abierto])

  async function descargar(formato: 'xlsx' | 'csv') {
    setOcupado(true)
    setError(null)
    try {
      const r = await fetch(`/api/modelos/${modeloId}/exportar?version=${version}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token.leer()}`,
        },
        body: JSON.stringify({
          dimensiones: widget.dimensiones ?? [],
          metricas: widget.metricas ?? [],
          filtros: [
            ...filtrosDeSelecciones(selecciones),
            ...(widget.filtros ?? []),
          ],
          rutas_elegidas: { ...rutasElegidas, ...(widget.rutas_elegidas ?? {}) },
          formato,
          titulo: widget.titulo || 'Astrolabio',
          limite: FILAS_EXPORTACION,
        }),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        const detalle = d.detail
        throw new ErrorApi(
          r.status,
          typeof detalle === 'string' ? detalle : (detalle?.mensaje ?? 'No se pudo exportar'),
        )
      }

      // El nombre lo decide el servidor (lleva la marca de tiempo y va saneado).
      const cabecera = r.headers.get('content-disposition') ?? ''
      const nombre =
        /filename="?([^"]+)"?/.exec(cabecera)?.[1] ??
        `${widget.titulo || 'astrolabio'}.${formato}`

      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = nombre
      a.click()
      // Sin revoke, cada descarga deja el archivo entero retenido en memoria.
      URL.revokeObjectURL(url)
      setAbierto(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo exportar')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <div className="exportar" ref={caja}>
      <button
        className="btn chico"
        title="Exportar los datos de este widget"
        onClick={() => setAbierto(!abierto)}
        disabled={ocupado}
      >
        {ocupado ? '…' : '↓'}
      </button>
      {abierto && (
        <div className="menu-exportar">
          <button onClick={() => descargar('xlsx')}>Excel (.xlsx)</button>
          <button onClick={() => descargar('csv')}>CSV</button>
          <div className="chico tenue" style={{ padding: '4px 8px 2px' }}>
            Se exporta con los filtros puestos y hasta{' '}
            {FILAS_EXPORTACION.toLocaleString('es-MX')} filas.
          </div>
        </div>
      )}
      {error && <div className="error-caja chico menu-exportar">{error}</div>}
    </div>
  )
}
