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
import { useCampos } from '../api/hooks'
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
  /**
   * Por qué otra columna se ordena la de columnas, si el modelo lo dice.
   *
   * «Enero, Febrero, Marzo» es texto, y ordenado por sí mismo sale *abril, agosto,
   * diciembre*: no es un orden, es un error que parece un orden. Se pide junto a la
   * columna de columnas —esta consulta ya se hacía para saber la anchura, así que no
   * cuesta una consulta más— y el orden que sale de aquí es el que llevan las
   * columnas de la matriz.
   */
  ordenarPor: string | null,
) {
  const cuerpo = {
    dimensiones: pivote ? (ordenarPor ? [pivote, ordenarPor] : [pivote]) : [],
    // Con la métrica puesta el cruce se hace por el mismo camino: contar los meses
    // por otra ruta podría dar un juego de meses distinto del que luego sale.
    metricas: (widget.metricas ?? [])
      .filter((m) => !((widget.fuera_del_pivote as string[] | undefined) ?? [])
        .includes(m))
      .slice(0, 1),
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

/**
 * Las métricas que NO se abren en columnas, pedidas SIN la dimensión de columnas.
 *
 * Una tabla dinámica repite cada métrica debajo de cada columna, y para una cifra que
 * no es del mes eso no vale: el inventario de hoy no es «el inventario de enero» siete
 * veces, y sumar la fila daría siete veces el inventario. Va aparte, en su propia
 * columna, una sola vez.
 *
 * Y va en **otra consulta**, no cruzando lo que ya bajó: la cifra sin el mes la tiene
 * que calcular el motor, que es el único que sabe si esa métrica se suma, se promedia o
 * es una foto. Deducirla en el navegador desde las celdas de los meses es adivinar, y
 * adivinar aquí es multiplicar por siete sin avisar.
 */
function useFueraDelPivote(
  modeloId: number,
  version: number,
  widget: Widget,
  filtros: Filtro[],
  rutasElegidas: Record<string, string>,
  pivote: string | undefined,
  limite: number,
) {
  const fuera = pivote
    ? ((widget.fuera_del_pivote as string[] | undefined) ?? []).filter((m) =>
        (widget.metricas ?? []).includes(m),
      )
    : []
  const dimsFila = (widget.dimensiones ?? []).filter((d) => d !== pivote)
  const cuerpo = {
    dimensiones: dimsFila,
    metricas: fuera,
    filtros,
    rutas_elegidas: rutasElegidas,
    limite,
  }
  return useQuery({
    queryKey: ['fuera-pivote', modeloId, version, cuerpo] as const,
    queryFn: () =>
      api.post<ResultadoConsulta>(
        `/modelos/${modeloId}/consultar?version=${version}`,
        cuerpo,
      ),
    enabled: fuera.length > 0 && dimsFila.length > 0,
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
  const campos = useCampos(modeloId, version)
  /**
   * Campos cuya selección de la hoja NO se aplica a este widget.
   *
   * Hace falta cuando la columna es el EJE de la tabla: una matriz de meses tiene
   * que seguir mostrando los doce aunque alguien seleccione julio, porque los meses
   * son el dibujo y no el recorte. En Power BI eso se consigue con una tabla de
   * encabezados desconectada —a la que el segmentador no llega—; aquí se dice.
   *
   * Se aplica sólo a las selecciones de la hoja, no a los filtros propios del
   * widget: ésos los escribió quien armó el widget, para este widget.
   */
  const inmunes = (widget.ignora_seleccion as string[] | undefined) ?? []
  const filtros = [
    ...filtrosDeSelecciones(selecciones).filter((f) => !inmunes.includes(f.campo)),
    ...(widget.filtros ?? []),
  ]
  const rutas = { ...rutasTablero, ...(widget.rutas_elegidas ?? {}) }
  const limite = widget.limite ?? 1000

  // Sólo la dinámica necesita el paso previo. Para los demás, una fila pedida es
  // una fila que se ve, y el límite ya significa lo que parece.
  const pivote =
    widget.tipo === 'tabla_dinamica'
      ? ((widget.pivote as string | undefined) || undefined)
      : undefined
  // Lo que diga el widget primero, y el modelo como respaldo: el orden de las
  // columnas es de la hoja, y quien la arma no tiene por qué publicar una versión
  // del modelo —que se lo cambia a los demás tableros— para ver los meses en orden.
  const ordenPor = (widget.orden_por as Record<string, string> | undefined) ?? {}
  const ordenarPor = pivote
    ? (ordenPor[pivote] ?? campos.data?.dimensiones
        .find((d) => d.clave === pivote)?.ordenar_por ?? null)
    : null
  const ancho = useAnchuraDelPivote(modeloId, version, widget, filtros, rutas,
                                    pivote, ordenarPor)
  // Los valores distintos de la columna de columnas, en el orden en que van. Con
  // `ordenar_por` la consulta trae dos columnas, así que hay que quedarse con la
  // primera y quitar repetidos: el par no tiene por qué ser uno a uno.
  const ordenColumnas = pivote && ancho.data
    ? [...new Map(
        // El motor ordena por la columna que se abre, que para texto es alfabético:
        // hay que reordenar por la que el modelo señaló. Se compara como número
        // cuando lo es —el mes es 1..12— y como texto si no.
        (ordenarPor
          ? [...ancho.data.filas].sort((a, b) => {
              const x = a[ordenarPor], y = b[ordenarPor]
              if (typeof x === 'number' && typeof y === 'number') return x - y
              return String(x ?? '').localeCompare(String(y ?? ''))
            })
          : ancho.data.filas
        ).map((f) => [String(f[pivote]), f[pivote]] as const),
      ).values()]
    : undefined
  const columnas = ordenColumnas ? Math.max(1, ordenColumnas.length) : 1
  const sueltas = useFueraDelPivote(modeloId, version, widget, filtros, rutas,
                                    pivote, limite)

  // Las que van fuera de las columnas NO se piden aquí: las trae su propia consulta,
  // sin la columna de columnas. Pedirlas también aquí no sería sólo trabajo de más —
  // si una lleva ventana de tiempo, la consulta entera necesita un mes de referencia
  // y la matriz se colapsa al último mes en vez de abrir uno por columna.
  const fuera = pivote
    ? ((widget.fuera_del_pivote as string[] | undefined) ?? [])
    : []
  const enMatriz = (widget.metricas ?? []).filter((m) => !fuera.includes(m))

  const cuerpo = {
    dimensiones: widget.dimensiones ?? [],
    metricas: enMatriz,
    filtros,
    rutas_elegidas: rutas,
    // El usuario escribió filas de tabla; el motor cuenta filas planas. La
    // traducción se hace aquí, no en la cabeza de quien lo lee.
    limite: pivote ? Math.min(limite * columnas, TOPE_MOTOR) : limite,
  }

  const consulta = useQuery({
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
      // El orden de las columnas de la matriz, cuando el modelo dice por qué otra
      // columna se ordena la que se abre. Sin esto, «Enero» sale después de «Abril».
      orden_pivote: ordenColumnas,
      // Las filas de la consulta sin el mes, para las columnas que van una sola vez.
      // `undefined` mientras no haya llegado: la tabla dibuja los meses y deja esas
      // celdas en blanco un instante, en vez de esperar la matriz entera.
      filas_sueltas: sueltas.data?.filas,
      // Si la dimensión de columnas no cabía en el tope, el cruce está incompleto
      // por la derecha aunque las filas hayan entrado enteras.
      truncado: d.truncado || (pivote ? !!ancho.data?.truncado : false),
    }),
  })

  /**
   * Lo que falló en una de las consultas de apoyo de la dinámica.
   *
   * Las dos pueden fallar sin que la principal se entere, y entonces no se ve un
   * error: se ven columnas en blanco —o el widget entero pidiendo una métrica que
   * ya eligió—. Una métrica borrada del modelo que el widget sigue nombrando deja
   * las TRES columnas de fuera vacías, porque viajan juntas en una consulta. Eso
   * hay que decirlo: en blanco es indistinguible de «no hay dato».
   */
  const errorAyuda = ((ancho.error ?? sueltas.error) as Error | null)?.message ?? null
  return Object.assign(consulta, { errorAyuda })
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
  /**
   * Por qué otra columna ordena ESTE widget la lista, si dijo alguna. Gana sobre lo
   * que diga el modelo: el orden de una lista es presentación, y quien arma la hoja
   * tiene que poder cambiarlo sin publicar una versión del modelo para todos.
   */
  ordenarPor?: string | null,
) {
  const [entidad, nombre] = (campo ?? '.').split('.')
  return useQuery({
    queryKey: ['asociativo', modeloId, version, campo, selecciones,
               ordenarPor ?? null] as const,
    queryFn: () =>
      api.post<Estados>(`/modelos/${modeloId}/asociativo?version=${version}`, {
        entidad,
        campo: nombre,
        selecciones,
        // Sólo el nombre pelado: el motor lo busca entre las columnas de esa
        // entidad y no acepta nada de otra tabla.
        ordenar_por: ordenarPor ? ordenarPor.split('.').pop() : null,
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
