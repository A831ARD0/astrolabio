/**
 * Un widget dibujado.
 *
 * Todos los widgets de datos pasan por el mismo camino de consulta, así que todos
 * responden igual a una selección y todos aplican la seguridad por fila. No hay
 * un tipo de widget "especial" que traiga sus datos por otro lado.
 *
 * Cuando la consulta falla, el widget **muestra el error**. Un panel en blanco o
 * con un cero es peor que un mensaje: parece un dato.
 *
 * Cada tipo vive en su propio componente porque cada uno consulta distinto (un
 * filtro pide estados asociativos, un gráfico pide filas). Los hooks no pueden ir
 * detrás de un `if`.
 */

import { useCampos } from '../api/hooks'
import { useOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'
import type { ResultadoConsulta, Widget } from '../api/tipos'
import { Grafico } from './Grafico'
import { PanelFiltros } from './PanelFiltros'
import {
  type Formato,
  type Total,
  compacto,
  esNumero,
  exacto,
  formatear,
  totalPorOmision,
  totalizar,
} from './formato'
import {
  TIPOS_GRAFICO,
  claveDeRuta,
  rutasDelError,
  useDatosWidget,
} from './consulta'

export interface PropsWidget {
  widget: Widget
  modeloId: number
  version: number
  selecciones: Record<string, unknown[]>
  /** Caminos ya elegidos para las ambigüedades del modelo, a nivel de tablero. */
  rutasElegidas: Record<string, string>
  alAlternar: (campo: string, valor: unknown) => void
  alLimpiar: (campo: string) => void
  alElegirRuta: (clave: string, ruta: string) => void
  /** En modo edición no se filtra al hacer clic: estorbaría al arrastrar. */
  editando: boolean
}

/** Etiquetas y formatos vienen del catálogo del modelo, no del widget. */
function useEtiquetas(modeloId: number) {
  const campos = useCampos(modeloId)
  return {
    formatoDe: (metrica: string): Formato =>
      (campos.data?.metricas.find((x) => x.clave === metrica)?.formato as Formato) ??
      'numero',
    etiquetaDe: (clave: string) =>
      campos.data?.dimensiones.find((d) => d.clave === clave)?.etiqueta ??
      campos.data?.metricas.find((m) => m.clave === clave)?.etiqueta ??
      clave,
  }
}

export function WidgetVista(props: PropsWidget) {
  if (props.widget.tipo === 'texto') {
    return (
      <div className="widget-texto">
        {String(props.widget.texto ?? 'Texto sin escribir')}
      </div>
    )
  }
  if (props.widget.tipo === 'filtro') return <WidgetFiltro {...props} />
  return <WidgetDatos {...props} />
}

// --------------------------------------------------------------------------- //

/**
 * Un panel de filtro lleva TODAS sus dimensiones, no la primera.
 *
 * No hace falta cambiar el esquema del widget: `dimensiones` ya es una lista, y un
 * filtro de un solo campo es el caso de una sola. Los tableros que ya existen se
 * leen igual.
 */
function WidgetFiltro({
  widget,
  modeloId,
  version,
  selecciones,
  alAlternar,
  alLimpiar,
}: PropsWidget) {
  return (
    <PanelFiltros
      campos={widget.dimensiones}
      modeloId={modeloId}
      version={version}
      selecciones={selecciones}
      alAlternar={alAlternar}
      alLimpiar={alLimpiar}
    />
  )
}

function WidgetDatos({
  widget,
  modeloId,
  version,
  selecciones,
  rutasElegidas,
  alAlternar,
  alElegirRuta,
}: PropsWidget) {
  const datos = useDatosWidget(modeloId, version, widget, selecciones, rutasElegidas)
  const { formatoDe: formatoModelo, etiquetaDe: etiquetaModelo } = useEtiquetas(modeloId)

  // El widget puede renombrar una columna y cambiarle el formato **solo para él**.
  // Lo del modelo sigue siendo lo del modelo: es lo que ven los demás tableros, y
  // que un tablero pudiera cambiarlo para todos convertiría un ajuste de estética
  // en un cambio de cifras ajenas.
  const propias = (clave: string) =>
    (widget[clave] as Record<string, string> | undefined) ?? {}
  const etiquetaDe = (c: string) => propias('etiquetas')[c]?.trim() || etiquetaModelo(c)
  const formatoDe = (m: string) =>
    (propias('formatos')[m] as Formato | undefined) ?? formatoModelo(m)

  if (datos.isLoading) return <div className="vacio chico">Consultando…</div>
  if (datos.isError) {
    const rutas = rutasDelError(datos.error)
    // Una ambigüedad de rutas no es un fallo del sistema: es una decisión que
    // nadie ha tomado. El motor se niega a elegir por su cuenta —dos caminos dan
    // cifras distintas— así que aquí se ofrece la decisión en vez de dejar un
    // mensaje que no se puede accionar.
    if (rutas.length > 0) {
      return (
        <div className="elegir-ruta">
          <p>
            Hay {rutas.length} caminos de igual longitud para cruzar estos datos, y
            dan cifras distintas. Elige cuál usar en todo el tablero:
          </p>
          {rutas.map((r) => (
            <button key={r} className="btn" onClick={() => alElegirRuta(claveDeRuta(r), r)}>
              <span className="mono">{r}</span>
            </button>
          ))}
        </div>
      )
    }
    return (
      <div className="error-caja chico" style={{ margin: 8 }}>
        {(datos.error as Error).message}
      </div>
    )
  }
  if (!datos.data) {
    return <div className="vacio chico">Elige una métrica para este widget.</div>
  }
  if (datos.data.filas.length === 0) {
    return <div className="vacio chico">Sin datos para la selección actual.</div>
  }

  if (widget.tipo === 'kpi') {
    return (
      <Kpi widget={widget} datos={datos.data} formatoDe={formatoDe}
           etiquetaDe={etiquetaDe} />
    )
  }
  if (widget.tipo === 'tabla') {
    return (
      <Tabla datos={datos.data} etiquetaDe={etiquetaDe} formatoDe={formatoDe}
             metricas={widget.metricas}
             totalesDe={(m) =>
               (propias('totales_de')[m] as Total | undefined) ??
               totalPorOmision(formatoDe(m))} />
    )
  }
  if (TIPOS_GRAFICO.includes(widget.tipo)) {
    return (
      <Grafico
        widget={widget}
        datos={datos.data}
        formatoMetrica={formatoDe}
        etiquetaMetrica={etiquetaDe}
        alSeleccionar={alAlternar}
      />
    )
  }
  return <div className="vacio chico">Tipo de widget desconocido.</div>
}

// --------------------------------------------------------------------------- //

function Kpi({
  widget,
  datos,
  formatoDe,
  etiquetaDe,
}: {
  widget: Widget
  datos: ResultadoConsulta
  formatoDe: (m: string) => Formato
  etiquetaDe: (c: string) => string
}) {
  // Sin desglose la consulta trae una fila; con desglose se suman las filas,
  // porque un KPI es un total. Sumar aquí solo vale para métricas aditivas: por
  // eso el editor avisa cuando un KPI lleva desglose.
  const total = (metrica: string) =>
    datos.filas.reduce(
      (a, f) => a + (esNumero(f[metrica]) ? (f[metrica] as number) : 0),
      0,
    )

  return (
    <div className={`kpi ${widget.metricas.length > 1 ? 'varios' : ''}`}>
      {widget.metricas.map((m) => (
        <div key={m} className="kpi-uno" title={exacto(total(m), formatoDe(m))}>
          <div className="cifra">{compacto(total(m), formatoDe(m))}</div>
          {widget.metricas.length > 1 && <div className="rotulo">{etiquetaDe(m)}</div>}
        </div>
      ))}
    </div>
  )
}

function Tabla({
  datos,
  etiquetaDe,
  formatoDe,
  metricas,
  totalesDe,
}: {
  datos: ResultadoConsulta
  etiquetaDe: (c: string) => string
  formatoDe: (m: string) => Formato
  metricas: string[]
  totalesDe: (m: string) => Total
}) {
  const orden = useOrden(datos.filas, (f, c) => f[c])

  // El total es de las filas que se trajeron, no del universo: si el widget tiene
  // un máximo de filas y se alcanzó, esto suma esas. Se dice en el pie.
  const totales = metricas.map((m) => totalizar(datos.filas.map((f) => f[m]),
                                                totalesDe(m)))
  const hayTotales = totales.some((t) => t !== null)

  return (
    <div className="tabla-envoltura" style={{ height: '100%', border: 0 }}>
      <table className="datos">
        <thead>
          <tr>
            {datos.columnas.map((c) => (
              <Th
                key={c}
                orden={orden}
                clave={c}
                className={metricas.includes(c) ? 'num' : ''}
                titulo={c}
              >
                {etiquetaDe(c)}
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {orden.filas.map((f, i) => (
            <tr key={i}>
              {datos.columnas.map((c) => (
                <td key={c} className={esNumero(f[c]) ? 'num' : ''}>
                  {esNumero(f[c]) ? formatear(f[c], formatoDe(c)) : String(f[c] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {hayTotales && (
          <tfoot>
            <tr>
              {datos.columnas.map((c, i) => {
                if (!metricas.includes(c)) {
                  // La primera columna de desglose lleva el rótulo; las demás,
                  // nada: repetir «Totales» no informa.
                  return <td key={c}>{i === 0 ? 'Totales' : ''}</td>
                }
                const t = totales[metricas.indexOf(c)]
                return (
                  <td key={c} className="num">
                    {t === null ? '—' : formatear(t, formatoDe(c))}
                  </td>
                )
              })}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  )
}
