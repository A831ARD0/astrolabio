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

/**
 * Cuántas columnas puede abrir un cruce antes de dejar de ser una tabla.
 *
 * No es una preferencia: doscientas columnas no se leen, se exportan. El tope
 * existe para que la consulta que sólo va a contarlas no se convierta ella misma
 * en el problema.
 */
const TOPE_COLUMNAS = 400

/** El techo que acepta el backend (`limite: le=50_000`). */
const TOPE_MOTOR = 50_000

/**
 * Cuántos valores va a tener la dimensión que se abre en columnas.
 *
 * Hace falta **antes** de la consulta de verdad: en una tabla dinámica el límite
 * que el usuario escribe son filas de la tabla que ve, y el motor limita filas
 * planas (una por cada cruce de fila y columna). Sin este número, un límite de mil
 * sobre cuarenta sucursales y ciento veinticinco meses devuelve ocho sucursales y
 * una tabla que parece entera.
 *
 * Se pide con los mismos filtros que la consulta real: los meses que quedan
 * después de una selección son los que van a salir en columnas, no todos los del
 * calendario.
 */
function useAnchuraDelPivote(
  modeloId: number,
  version: number,
  widget: Widget,
  filtros: Filtro[],
  rutasElegidas: Record<string, string>,
  pivote: string | undefined,
) {
  const cuerpo = {
    dimensiones: pivote ? [pivote] : [],
    // Con la métrica puesta el cruce se hace por el mismo camino: contar los meses
    // por otra ruta podría dar un juego de meses distinto del que luego sale.
    metricas: (widget.metricas ?? []).slice(0, 1),
    filtros,
    rutas_elegidas: rutasElegidas,
    limite: TOPE_COLUMNAS,
  }
  return useQuery({
    queryKey: ['ancho-pivote', modeloId, version, cuerpo] as const,
    queryFn: () =>
      api.post<ResultadoConsulta>(
        `/modelos/${modeloId}/consultar?version=${version}`,
        cuerpo,
      ),
    enabled: !!pivote && cuerpo.metricas.length > 0,
    retry: false,
  })
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
  const rutas = { ...rutasTablero, ...(widget.rutas_elegidas ?? {}) }
  const limite = widget.limite ?? 1000

  // Sólo la dinámica necesita el paso previo. Para los demás, una fila pedida es
  // una fila que se ve, y el límite ya significa lo que parece.
  const pivote =
    widget.tipo === 'tabla_dinamica'
      ? ((widget.pivote as string | undefined) || undefined)
      : undefined
  const ancho = useAnchuraDelPivote(modeloId, version, widget, filtros, rutas, pivote)
  const columnas = ancho.data ? Math.max(1, ancho.data.filas.length) : 1

  const cuerpo = {
    dimensiones: widget.dimensiones ?? [],
    metricas: widget.metricas ?? [],
    filtros,
    rutas_elegidas: rutas,
    // El usuario escribió filas de tabla; el motor cuenta filas planas. La
    // traducción se hace aquí, no en la cabeza de quien lo lee.
    limite: pivote ? Math.min(limite * columnas, TOPE_MOTOR) : limite,
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
    // Una dinámica espera a saber su anchura. Consultar antes daría una tabla
    // recortada, y una tabla recortada que ya se dibujó no se desdibuja.
    enabled:
      PIDE_DATOS.includes(widget.tipo) &&
      (cuerpo.metricas.length > 0 || cuerpo.dimensiones.length > 0) &&
      (!pivote || ancho.isSuccess),
    // Un error de modelo (ruta ambigua, filtro sin ruta) no se arregla
    // reintentando: se arregla en el modelo.
    retry: false,
    select: (d) => ({
      ...d,
      ancho_pivote: pivote ? columnas : undefined,
      // Si la dimensión de columnas no cabía en el tope, el cruce está incompleto
      // por la derecha aunque las filas hayan entrado enteras.
      truncado: d.truncado || (pivote ? !!ancho.data?.truncado : false),
    }),
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
