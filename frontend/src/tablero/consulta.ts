/**
 * Cómo un widget pide sus datos.
 *
 * Dos cosas que no son detalles:
 *
 * 1. **Siempre se consulta la versión a la que el tablero está anclado**, no la
 *    vigente. Si no, el anclaje sería decorativo: el tablero diría "versión 3" y
 *    preguntaría por la 7.
 *
 * 2. **Las selecciones del tablero se convierten en filtros y van a TODOS los
 *    widgets.** Es lo que hace que elegir una marca mueva la pantalla entera. El
 *    backend une a la fuerza la tabla del filtro, así que un filtro que no se
 *    puede aplicar hace fallar la consulta en vez de devolver un total sin filtrar.
 */

import { useQuery } from '@tanstack/react-query'

import { ErrorApi, api } from '../api/cliente'
import type { Estados, Filtro, ResultadoConsulta, Widget } from '../api/tipos'

/** Widgets que piden datos al servidor. `texto` y `filtro` no. */
export const PIDE_DATOS: Widget['tipo'][] = [
  'kpi',
  'barras',
  'barras_horizontales',
  'lineas',
  'area',
  'pastel',
  'tabla',
  'tabla_dinamica',
]

export function filtrosDeSelecciones(
  selecciones: Record<string, unknown[]>,
): Filtro[] {
  return Object.entries(selecciones)
    .filter(([, valores]) => valores.length > 0)
    .map(([campo, valores]) => ({ campo, op: 'IN' as const, valor: valores }))
}

export function useDatosWidget(
  modeloId: number,
  version: number,
  widget: Widget,
  selecciones: Record<string, unknown[]>,
  /**
   * Caminos elegidos a nivel del tablero. Una ambigüedad de rutas afecta a todos
   * los widgets a la vez (el filtro es del tablero), así que se resuelve una vez
   * para todo el tablero; un widget puede sobreescribirla si de verdad quiere
   * medir por otro camino.
   */
  rutasTablero: Record<string, string> = {},
) {
  const filtros = [...filtrosDeSelecciones(selecciones), ...(widget.filtros ?? [])]
  const cuerpo = {
    dimensiones: widget.dimensiones ?? [],
    metricas: widget.metricas ?? [],
    filtros,
    rutas_elegidas: { ...rutasTablero, ...(widget.rutas_elegidas ?? {}) },
    limite: widget.limite ?? 1000,
  }

  return useQuery({
    // La clave incluye el cuerpo entero: dos widgets que piden lo mismo comparten
    // una sola consulta, y cambiar una selección invalida solo lo que cambió.
    queryKey: ['consulta', modeloId, version, cuerpo] as const,
    queryFn: () =>
      api.post<ResultadoConsulta>(
        `/modelos/${modeloId}/consultar?version=${version}`,
        cuerpo,
      ),
    enabled:
      PIDE_DATOS.includes(widget.tipo) &&
      (cuerpo.metricas.length > 0 || cuerpo.dimensiones.length > 0),
    // Un error de modelo (ruta ambigua, filtro sin ruta) no se arregla
    // reintentando: se arregla en el modelo.
    retry: false,
  })
}

export function useEstados(
  modeloId: number,
  version: number,
  campo: string | null,
  selecciones: Record<string, unknown[]>,
  /**
   * Un campo colapsado en desplegable no pide sus estados hasta que se abre: su
   * resumen se saca de las selecciones. Con seis campos en un panel, eso es la
   * diferencia entre cero consultas y seis por cada clic en cualquier otro filtro.
   */
  activo = true,
) {
  const [entidad, nombre] = (campo ?? '.').split('.')
  return useQuery({
    queryKey: ['asociativo', modeloId, version, campo, selecciones] as const,
    queryFn: () =>
      api.post<Estados>(`/modelos/${modeloId}/asociativo?version=${version}`, {
        entidad,
        campo: nombre,
        selecciones,
      }),
    enabled: activo && !!campo && !!entidad && !!nombre,
    retry: false,
  })
}

/**
 * Saca las rutas en conflicto del error del servidor, si las trae.
 *
 * El backend responde a una ambigüedad con `{error, mensaje, rutas}`. Tener las
 * rutas es lo que permite ofrecer la decisión en la propia interfaz en vez de
 * dejar al usuario con un mensaje que no puede accionar.
 */
export function rutasDelError(error: unknown): string[] {
  if (!(error instanceof ErrorApi)) return []
  const d = error.detalle as { rutas?: unknown } | undefined
  return Array.isArray(d?.rutas) ? (d!.rutas as string[]) : []
}

/** La clave que espera el backend para un camino elegido: "origen->destino". */
export function claveDeRuta(ruta: string): string {
  const pasos = ruta.split('→').map((p) => p.trim())
  return `${pasos[0]}->${pasos[pasos.length - 1]}`
}

/** Los tipos que se dibujan como gráfico. */
export const TIPOS_GRAFICO: Widget['tipo'][] = [
  'barras',
  'barras_horizontales',
  'lineas',
  'area',
  'pastel',
]
