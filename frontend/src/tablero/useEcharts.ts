/**
 * Envoltorio propio de ECharts.
 *
 * Existe en vez de usar `echarts-for-react` por una razón concreta: ese paquete
 * es CommonJS y su punto de entrada `lib/core` reventaba en el navegador con
 * "exports is not defined". Escribirlo a mano son cuarenta líneas, quita una
 * dependencia y da control sobre las tres cosas que de verdad importan:
 *
 * - **Redimensionar.** Un widget en una rejilla cambia de tamaño constantemente y
 *   ECharts no se enteraría solo: hace falta un ResizeObserver, no un listener de
 *   la ventana.
 * - **Liberar.** Sin `dispose()` al desmontar, cada widget deja su instancia y su
 *   canvas vivos, y un tablero que se navega varias veces se come la memoria.
 * - **Reemplazar y no fusionar** las opciones: al cambiar de tipo de gráfico o de
 *   métrica, fusionar deja restos de la configuración anterior.
 */

import * as echarts from 'echarts/core'
import { useEffect, useRef } from 'react'

export function useEcharts(
  opciones: unknown,
  alHacerClic?: (nombre: string) => void,
) {
  const contenedor = useRef<HTMLDivElement | null>(null)
  const grafico = useRef<echarts.ECharts | null>(null)
  const clic = useRef(alHacerClic)
  clic.current = alHacerClic

  useEffect(() => {
    if (!contenedor.current) return
    const g = echarts.init(contenedor.current)
    grafico.current = g
    g.on('click', (p: unknown) => {
      const nombre = (p as { name?: string }).name
      if (nombre) clic.current?.(nombre)
    })

    const observador = new ResizeObserver(() => g.resize())
    observador.observe(contenedor.current)

    return () => {
      observador.disconnect()
      g.dispose()
      grafico.current = null
    }
  }, [])

  useEffect(() => {
    // notMerge: al cambiar de tipo de gráfico, fusionar deja restos del anterior.
    grafico.current?.setOption(opciones as never, { notMerge: true })
  }, [opciones])

  return contenedor
}
