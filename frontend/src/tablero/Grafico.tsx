/**
 * Gráficos con ECharts.
 *
 * Reglas que no son de gusto:
 *
 * - **El eje de valores empieza en cero** en barras y áreas. Un eje truncado
 *   exagera diferencias: dos sucursales que difieren un 3% parecen el doble una
 *   de otra. En líneas se permite no empezar en cero, porque ahí lo que se lee es
 *   la forma de la serie.
 * - **Nada de rotar etiquetas a 90°.** Si los nombres no caben, el gráfico se
 *   dibuja horizontal. Los nombres de las sucursales son largos.
 * - **Una paleta corta y estable.** Si el color cambia de significado entre dos
 *   gráficos del mismo tablero, el color deja de informar.
 * - Hacer clic en una barra **selecciona** ese valor: el gráfico también es un
 *   filtro, como en Qlik.
 */

import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useMemo } from 'react'

import type { ResultadoConsulta, Widget } from '../api/tipos'
import { type Formato, compacto, exacto } from './formato'
import { useEcharts } from './useEcharts'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  CanvasRenderer,
])

const PALETA = [
  '#4c8dff',
  '#f0a35e',
  '#3fb950',
  '#a371f7',
  '#f2545b',
  '#2dd4bf',
  '#e8b339',
  '#8b949e',
]

function tokens() {
  const cs = getComputedStyle(document.documentElement)
  return {
    texto: cs.getPropertyValue('--texto-suave').trim() || '#98a2b3',
    tenue: cs.getPropertyValue('--texto-tenue').trim() || '#667085',
    borde: cs.getPropertyValue('--borde').trim() || '#2a3240',
    panel: cs.getPropertyValue('--fondo-panel').trim() || '#151a23',
  }
}

export function Grafico({
  widget,
  datos,
  formatoMetrica,
  alSeleccionar,
}: {
  widget: Widget
  datos: ResultadoConsulta
  /** Formato por nombre de métrica, sacado del catálogo del modelo. */
  formatoMetrica: (metrica: string) => Formato
  alSeleccionar?: (campo: string, valor: unknown) => void
}) {
  const dim = widget.dimensiones[0]
  const opciones = useMemo(() => {
    const t = tokens()
    const etiquetas = datos.filas.map((f) => String(f[dim!] ?? '—'))
    const formato = formatoMetrica(widget.metricas[0] ?? '')

    const series = widget.metricas.map((m, i) => ({
      nombre: m,
      valores: datos.filas.map((f) => (f[m] as number) ?? 0),
      color: PALETA[i % PALETA.length]!,
    }))

    const comun = {
      color: PALETA,
      animationDuration: 300,
      grid: { left: 8, right: 16, top: 28, bottom: 4, containLabel: true },
      tooltip: {
        trigger: widget.tipo === 'pastel' ? ('item' as const) : ('axis' as const),
        backgroundColor: t.panel,
        borderColor: t.borde,
        textStyle: { color: t.texto, fontSize: 12 },
        valueFormatter: (v: unknown) => exacto(v, formato),
      },
      legend:
        widget.metricas.length > 1
          ? { top: 0, textStyle: { color: t.texto, fontSize: 11 }, icon: 'roundRect' }
          : undefined,
    }

    if (widget.tipo === 'pastel') {
      return {
        ...comun,
        tooltip: { ...comun.tooltip, trigger: 'item' as const },
        series: [
          {
            type: 'pie' as const,
            radius: ['45%', '72%'],
            itemStyle: { borderColor: t.panel, borderWidth: 2 },
            label: { color: t.texto, fontSize: 11 },
            data: datos.filas.map((f) => ({
              name: String(f[dim!] ?? '—'),
              value: (f[widget.metricas[0]!] as number) ?? 0,
            })),
          },
        ],
      }
    }

    const ejeCategoria = {
      type: 'category' as const,
      data: etiquetas,
      axisLabel: { color: t.tenue, fontSize: 11, hideOverlap: true },
      axisLine: { lineStyle: { color: t.borde } },
      axisTick: { show: false },
    }
    const ejeValor = {
      type: 'value' as const,
      // Cero obligatorio salvo en líneas: un eje truncado exagera diferencias.
      min: widget.tipo === 'lineas' ? undefined : 0,
      axisLabel: {
        color: t.tenue,
        fontSize: 11,
        formatter: (v: number) => compacto(v, formato),
      },
      splitLine: { lineStyle: { color: t.borde, type: 'dashed' as const } },
    }

    const horizontal = widget.tipo === 'barras_horizontales'
    const tipoSerie = widget.tipo === 'lineas' || widget.tipo === 'area' ? 'line' : 'bar'

    return {
      ...comun,
      xAxis: horizontal ? ejeValor : ejeCategoria,
      yAxis: horizontal ? { ...ejeCategoria, inverse: true } : ejeValor,
      series: series.map((s) => ({
        name: s.nombre,
        type: tipoSerie as 'bar' | 'line',
        data: s.valores,
        smooth: widget.tipo === 'area' || widget.tipo === 'lineas' ? 0.2 : undefined,
        areaStyle: widget.tipo === 'area' ? { opacity: 0.18 } : undefined,
        showSymbol: false,
        barMaxWidth: 34,
        itemStyle: { color: s.color, borderRadius: horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0] },
      })),
    }
  }, [widget, datos, dim, formatoMetrica])

  const ref = useEcharts(
    opciones,
    alSeleccionar && dim ? (nombre) => alSeleccionar(dim, nombre) : undefined,
  )

  return <div ref={ref} style={{ height: '100%', width: '100%' }} />
}

