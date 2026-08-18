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
import { claveCol, cruzar } from './pivote'
import { type Semaforo, evaluar, flecha, porque } from './semaforo'
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
  const semDe = (m: string) =>
    (widget.semaforos as Record<string, Semaforo> | undefined)?.[m]

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
           etiquetaDe={etiquetaDe} semDe={semDe} />
    )
  }
  if (widget.tipo === 'tabla') {
    return (
      <Tabla datos={datos.data} etiquetaDe={etiquetaDe} formatoDe={formatoDe}
             metricas={widget.metricas} semDe={semDe}
             totalesDe={(m) =>
               (propias('totales_de')[m] as Total | undefined) ??
               totalPorOmision(formatoDe(m))} />
    )
  }
  if (widget.tipo === 'tabla_dinamica') {
    return (
      <TablaDinamica
        widget={widget}
        datos={datos.data}
        etiquetaDe={etiquetaDe}
        formatoDe={formatoDe}
        semDe={semDe}
        totalesDe={(m) =>
          (propias('totales_de')[m] as Total | undefined) ??
          totalPorOmision(formatoDe(m))}
      />
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

/**
 * Una cifra con su semáforo, si lo tiene. La usan la tabla, la tabla dinámica y el
 * KPI: si cada una pintara el suyo, tarde o temprano una diría verde donde otra dice
 * rojo con el mismo dato.
 */
function Cifra({
  valor,
  formato,
  sem,
  fila,
}: {
  valor: unknown
  formato: Formato
  sem: Semaforo | undefined
  /** La fila entera, para poder comparar contra otra métrica. */
  fila?: Record<string, unknown>
}) {
  const texto = esNumero(valor) ? formatear(valor, formato) : '—'
  const d = evaluar(valor, sem, fila)
  if (!d) return <>{texto}</>

  const conFondo = sem!.mostrar === 'fondo' || sem!.mostrar === 'ambos'
  // La marca de «sin dato» se dibuja siempre, aunque se pidiera solo el fondo: es
  // el caso en que el fondo solo no basta para que se note que no es un aprobado.
  const conFlecha = sem!.mostrar !== 'fondo' || d === 'sin_dato'
  return (
    <span className={`sem ${d} ${conFondo ? 'con-fondo' : ''}`}
          title={porque(d, sem!)}>
      {texto}
      {conFlecha && <span className="marca-sem">{flecha(d)}</span>}
    </span>
  )
}

function Kpi({
  widget,
  datos,
  formatoDe,
  etiquetaDe,
  semDe,
}: {
  widget: Widget
  datos: ResultadoConsulta
  formatoDe: (m: string) => Formato
  etiquetaDe: (c: string) => string
  semDe: (m: string) => Semaforo | undefined
}) {
  // Sin desglose la consulta trae una fila; con desglose se suman las filas,
  // porque un KPI es un total. Sumar aquí solo vale para métricas aditivas: por
  // eso el editor avisa cuando un KPI lleva desglose.
  const total = (metrica: string) =>
    datos.filas.reduce(
      (a, f) => a + (esNumero(f[metrica]) ? (f[metrica] as number) : 0),
      0,
    )

  // Los totales de TODAS las metricas, para que un semaforo pueda comparar una
  // contra otra igual que en una fila de tabla: lo facturado contra su objetivo.
  const fila = Object.fromEntries(widget.metricas.map((m) => [m, total(m)]))

  return (
    <div className={`kpi ${widget.metricas.length > 1 ? 'varios' : ''}`}>
      {widget.metricas.map((m) => {
        const d = evaluar(total(m), semDe(m), fila)
        return (
          <div key={m} className="kpi-uno" title={exacto(total(m), formatoDe(m))}>
            <div className={`cifra ${d ? `sem ${d}` : ''}`}>
              {compacto(total(m), formatoDe(m))}
              {d && semDe(m)!.mostrar !== 'fondo' && (
                <span className="marca-sem">{flecha(d)}</span>
              )}
            </div>
            {widget.metricas.length > 1 && <div className="rotulo">{etiquetaDe(m)}</div>}
          </div>
        )
      })}
    </div>
  )
}

/**
 * Tabla dinámica: un desglose en las filas y otro abierto en columnas.
 *
 * La matriz que en Power BI son los meses de arriba y los modelos a la izquierda.
 * El cruce lo hace `cruzar`; aquí solo se dibuja.
 *
 * Una celda vacía se deja **en blanco y no en cero**. No es lo mismo «ese mes no
 * hubo ninguno» que «no hay fila para ese mes»: un cero afirma algo que el dato no
 * dice.
 */
function TablaDinamica({
  widget,
  datos,
  etiquetaDe,
  formatoDe,
  semDe,
  totalesDe,
}: {
  widget: Widget
  datos: ResultadoConsulta
  etiquetaDe: (c: string) => string
  formatoDe: (m: string) => Formato
  semDe: (m: string) => Semaforo | undefined
  totalesDe: (m: string) => Total
}) {
  const dims = widget.dimensiones ?? []
  const metricas = widget.metricas ?? []
  // Por omisión se abre el último desglose: es el que se agregó pensando en las
  // columnas, y así el widget dibuja algo sensato antes de tocar nada.
  const pivote = dims.includes(String(widget.pivote))
    ? String(widget.pivote)
    : dims[dims.length - 1]!
  const dimsFila = dims.filter((d) => d !== pivote)

  if (dimsFila.length === 0 || metricas.length === 0) {
    return (
      <div className="vacio chico">
        Una tabla dinámica necesita dos desgloses —uno en las filas y otro que se
        abra en columnas— y al menos una métrica.
      </div>
    )
  }

  const cruce = cruzar(datos.filas, dimsFila, pivote, metricas)
  const conTotal = widget.total_fila !== false

  /** El total de una métrica a lo largo de una fila. */
  const totalFila = (fila: (typeof cruce.filas)[number], m: string) =>
    totalizar(
      cruce.columnas.map((c) => fila.celdas.get(claveCol(c))?.[m]),
      totalesDe(m),
    )

  /** El total de una métrica en una columna, a lo largo de todas las filas. */
  const totalColumna = (col: unknown, m: string) =>
    totalizar(
      cruce.filas.map((f) => f.celdas.get(claveCol(col))?.[m]),
      totalesDe(m),
    )

  const hayTotales = metricas.some((m) => totalesDe(m) !== 'ninguno')
  const varias = metricas.length > 1

  return (
    <div className="tabla-envoltura pivote" style={{ height: '100%', border: 0 }}>
      {/* Un mes guardado como nombre sale alfabético: abril, agosto, diciembre. Eso
          no es un orden, es un error que parece un orden, así que se dice en vez de
          dejar que alguien lea la matriz de izquierda a derecha creyendo otra cosa. */}
      {cruce.ordenDeLlegada && cruce.columnas.length > 2 && (
        <div className="aviso-orden chico">
          Las columnas van en el orden en que el modelo devuelve «{etiquetaDe(pivote)}»,
          que para texto es alfabético. Si necesitas orden cronológico, abre en columnas
          una columna numérica (el mes como número, o año-mes).
        </div>
      )}
      <table className="datos">
        <thead>
          <tr>
            {dimsFila.map((d) => (
              <th key={d} rowSpan={varias ? 2 : 1} className="fija" title={d}>
                {etiquetaDe(d)}
              </th>
            ))}
            {cruce.columnas.map((c) => (
              <th key={claveCol(c)} colSpan={metricas.length} className="num grupo">
                {c === null || c === undefined ? '—' : String(c)}
              </th>
            ))}
            {conTotal && hayTotales && (
              <th colSpan={metricas.length} rowSpan={varias ? 1 : 1}
                  className="num grupo total">
                Total
              </th>
            )}
          </tr>
          {/* Con una sola métrica no hace falta repetir su nombre en cada columna:
              ya está en el título del widget. */}
          {varias && (
            <tr>
              {cruce.columnas.map((c) =>
                metricas.map((m) => (
                  <th key={`${claveCol(c)}|${m}`} className="num sub">
                    {etiquetaDe(m)}
                  </th>
                )),
              )}
              {conTotal &&
                hayTotales &&
                metricas.map((m) => (
                  <th key={`total|${m}`} className="num sub total">
                    {etiquetaDe(m)}
                  </th>
                ))}
            </tr>
          )}
        </thead>

        <tbody>
          {cruce.filas.map((f, i) => (
            <tr key={i}>
              {f.claves.map((v, j) => (
                <td key={j} className="fija">
                  {v === null || v === undefined ? '—' : String(v)}
                </td>
              ))}
              {cruce.columnas.map((c) =>
                metricas.map((m) => {
                  const celda = f.celdas.get(claveCol(c))
                  const v = celda?.[m]
                  return (
                    <td key={`${claveCol(c)}|${m}`} className="num">
                      {v === undefined ? (
                        ''
                      ) : (
                        // La fila del semaforo es la CELDA: comparar contra otra
                        // metrica del mismo mes, no contra el total de la fila.
                        <Cifra valor={v} formato={formatoDe(m)} sem={semDe(m)}
                               fila={celda} />
                      )}
                    </td>
                  )
                }),
              )}
              {conTotal &&
                hayTotales &&
                metricas.map((m) => {
                  const t = totalFila(f, m)
                  return (
                    <td key={`total|${m}`} className="num total">
                      {t === null ? '—' : formatear(t, formatoDe(m))}
                    </td>
                  )
                })}
            </tr>
          ))}
        </tbody>

        {hayTotales && (
          <tfoot>
            <tr>
              {dimsFila.map((d, i) => (
                <td key={d} className="fija">
                  {i === 0 ? 'Totales' : ''}
                </td>
              ))}
              {cruce.columnas.map((c) =>
                metricas.map((m) => {
                  const t = totalColumna(c, m)
                  return (
                    <td key={`${claveCol(c)}|${m}`} className="num">
                      {t === null ? '—' : formatear(t, formatoDe(m))}
                    </td>
                  )
                }),
              )}
              {conTotal &&
                metricas.map((m) => {
                  const t = totalizar(
                    cruce.filas.flatMap((f) =>
                      cruce.columnas.map((c) => f.celdas.get(claveCol(c))?.[m]),
                    ),
                    totalesDe(m),
                  )
                  return (
                    <td key={`total|${m}`} className="num total">
                      {t === null ? '—' : formatear(t, formatoDe(m))}
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

function Tabla({
  datos,
  etiquetaDe,
  formatoDe,
  metricas,
  semDe,
  totalesDe,
}: {
  datos: ResultadoConsulta
  etiquetaDe: (c: string) => string
  formatoDe: (m: string) => Formato
  metricas: string[]
  semDe: (m: string) => Semaforo | undefined
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
                // Una columna de métrica pasa siempre por `Cifra`, aunque venga
                // vacía: si el nulo no llegara, una sucursal con objetivo y sin
                // ventas se quedaría sin semáforo, que es como decir que va bien.
                <td key={c} className={metricas.includes(c) ? 'num' : ''}>
                  {metricas.includes(c) ? (
                    <Cifra valor={f[c]} formato={formatoDe(c)} sem={semDe(c)} fila={f} />
                  ) : (
                    String(f[c] ?? '—')
                  )}
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
