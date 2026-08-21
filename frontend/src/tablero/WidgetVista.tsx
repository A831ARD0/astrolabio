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

import type { CSSProperties } from 'react'
import { useCampos } from '../api/hooks'
import { useOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'
import type { ResultadoConsulta, Widget } from '../api/tipos'
import { Grafico } from './Grafico'
import { PanelFiltros } from './PanelFiltros'
import { claveCol, claveFila, cruzar } from './pivote'
import {
  type EstiloColumna,
  estiloCabecera,
  estiloCelda,
  estiloTotal,
} from './estiloColumna'
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
    const w = props.widget
    // Un widget de texto es lo que hace de título y de subtítulo de una sección, así
    // que el tamaño y el color son parte del contenido, no un adorno: «1.- VENTAS»
    // en 22 px y en el azul de la casa es lo que separa una sección de la siguiente.
    // Todo opcional: sin nada puesto se ve como se veía.
    const estilo: CSSProperties = {}
    if (w.tamano_texto) estilo.fontSize = `${Number(w.tamano_texto)}px`
    if (w.color_texto) estilo.color = String(w.color_texto)
    if (w.negrita) estilo.fontWeight = 650
    if (w.alineacion) estilo.textAlign = w.alineacion as CSSProperties['textAlign']
    return (
      <div className="widget-texto" style={estilo}>
        {String(w.texto ?? 'Texto sin escribir')}
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
      // Renombrar un campo vale para el filtro igual que para una tabla: el
      // inspector ofrece la etiqueta en los dos, y solo la usaba la tabla.
      etiquetas={(widget.etiquetas as Record<string, string> | undefined) ?? {}}
      ordenPor={(widget.orden_por as Record<string, string> | undefined) ?? {}}
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

  // La clase `cargando` la mira el renderizador del servidor para saber si la hoja ya
  // esta lista. Un widget vacio de verdad —«Sin datos»— tambien es un `.vacio`, y si
  // se contara igual el informe esperaria el tope entero por un widget que ya termino.
  if (datos.isLoading)
    return <div className="vacio chico cargando">Consultando…</div>
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
    // Si lo que falló es una consulta de apoyo de la dinámica, la principal ni se
    // lanzó: decirle a alguien que elija una métrica cuando ya eligió cuatro le
    // manda a buscar donde no está.
    if (datos.errorAyuda)
      return (
        <div className="error-caja chico" style={{ margin: 8 }}>
          {datos.errorAyuda}
        </div>
      )
    return <div className="vacio chico">Elige una métrica para este widget.</div>
  }
  if (datos.data.filas.length === 0) {
    // Vacío se ve igual venga de donde venga —tabla sin cargar, unión que no casa,
    // política, filtros— y cada causa se arregla en otro sitio. Cuando el servidor
    // sabe cuál es, se dice: «Sin datos» a secas manda a buscar a ciegas.
    return (
      <div className="vacio chico">
        {datos.data.vacio_porque ?? 'Sin datos para la selección actual.'}
      </div>
    )
  }

  // Un recorte se avisa SIEMPRE y encima del dato, no en un pie ni en un tooltip.
  // Lo que hay debajo es una cifra parcial con toda la pinta de estar completa, y
  // es la clase de número que acaba en una junta.
  // Con datos, la matriz se dibuja igual y el fallo va encima: las columnas de fuera
  // salen en blanco y en blanco no se distingue de «no hay dato».
  const avisoAyuda = datos.errorAyuda ? (
    <div className="error-caja chico" style={{ margin: '4px 8px' }}>
      {datos.errorAyuda}
    </div>
  ) : null

  const aviso = datos.data.truncado ? (
    <Recortado widget={widget} datos={datos.data} />
  ) : datos.data.mes_usado != null ? (
    // Con qué mes se compararon las cifras de tiempo. Va a la vista y no en un
    // tooltip porque cuando nadie filtró una fecha ese mes lo eligió el dato: la
    // misma tabla dirá otra cosa en cuanto entre el mes siguiente, y quien firma
    // el número tiene que saber de qué mes es.
    <div className="mes-usado" role="status">
      Comparado contra <strong>{String(datos.data.mes_usado)}</strong>
    </div>
  ) : null
  // Un widget que se queda al margen de una selección tiene que DECIRLO, y sólo
  // cuando esa selección está puesta. Alguien elige julio, esta tabla no cambia, y
  // sin este renglón la lectura es «está roto» — o peor, se firma una cifra sin
  // filtrar creyéndola filtrada.
  const alMargen = ((widget.ignora_seleccion as string[] | undefined) ?? [])
    .filter((c) => (selecciones[c]?.length ?? 0) > 0)
  const avisoMargen = alMargen.length > 0 ? (
    <div className="mes-usado" role="status">
      No le afecta la selección de{' '}
      <strong>{alMargen.map(etiquetaDe).join(', ')}</strong>
    </div>
  ) : null

  const encabezado = (avisoAyuda || avisoMargen || aviso) ? (
    <>
      {avisoAyuda}
      {avisoMargen}
      {aviso}
    </>
  ) : null

  if (widget.tipo === 'kpi') {
    return (
      <>
        {encabezado}
        <Kpi widget={widget} datos={datos.data} formatoDe={formatoDe}
             etiquetaDe={etiquetaDe} semDe={semDe} />
      </>
    )
  }
  if (widget.tipo === 'tabla') {
    return (
      <>
        {encabezado}
        <Tabla datos={datos.data} etiquetaDe={etiquetaDe} formatoDe={formatoDe}
               metricas={widget.metricas} semDe={semDe}
               // Aparte del semáforo: uno dice algo del dato y cambia por fila, esto
               // es del informe y es igual en todas. Ver `estiloColumna.ts`.
               estilos={
                 (widget.estilos as Record<string, EstiloColumna> | undefined) ?? {}
               }
               totalesDe={(m) =>
                 (propias('totales_de')[m] as Total | undefined) ??
                 totalPorOmision(formatoDe(m))} />
      </>
    )
  }
  if (widget.tipo === 'tabla_dinamica') {
    return (
      <>
        {encabezado}
        <TablaDinamica
          widget={widget}
          datos={datos.data}
          filasSueltas={datos.data.filas_sueltas}
          ordenColumnas={datos.data.orden_pivote}
          etiquetaDe={etiquetaDe}
          formatoDe={formatoDe}
          semDe={semDe}
          totalesDe={(m) =>
            (propias('totales_de')[m] as Total | undefined) ??
            totalPorOmision(formatoDe(m))}
        />
      </>
    )
  }
  if (TIPOS_GRAFICO.includes(widget.tipo)) {
    return (
      <>
        {encabezado}
        <Grafico
          widget={widget}
          datos={datos.data}
          formatoMetrica={formatoDe}
          etiquetaMetrica={etiquetaDe}
          alSeleccionar={alAlternar}
        />
      </>
    )
  }
  return <div className="vacio chico">Tipo de widget desconocido.</div>
}

// --------------------------------------------------------------------------- //

/**
 * La banda que avisa de que lo de abajo está recortado.
 *
 * Dice **por qué** y **qué hacer**, porque «se alcanzó el límite» sin más deja a
 * quien lo lee con la misma duda con la que empezó: si el total que ve es el total.
 * No se puede cerrar: mientras la tabla esté cortada, el aviso está.
 */
function Recortado({
  widget,
  datos,
}: {
  widget: Widget
  datos: ResultadoConsulta
}) {
  const cols = datos.ancho_pivote
  return (
    <div className="recortado" role="status">
      <strong>Faltan filas.</strong>{' '}
      {cols && cols > 1 ? (
        <>
          El cruce abre {cols} columnas, así que cada fila de la tabla cuesta {cols}{' '}
          filas de datos y el máximo se agotó antes de terminar. Sube «Máximo de
          filas» o reduce las columnas —filtrando el desglose que se abre— y las que
          faltan aparecerán.
        </>
      ) : (
        <>
          Se alcanzó el máximo de {widget.limite ?? 1000} filas y hay más. Lo que se
          ve es una parte, y los totales son los de esa parte. Sube el máximo o
          filtra para que quepa.
        </>
      )}
    </div>
  )
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
  filasSueltas,
  ordenColumnas,
  etiquetaDe,
  formatoDe,
  semDe,
  totalesDe,
}: {
  widget: Widget
  datos: ResultadoConsulta
  /**
   * Las filas de la consulta SIN la dimensión de columnas, para las métricas que no
   * se abren en meses. Vienen del motor y no de cruzar lo que ya bajó: ver
   * `useFueraDelPivote`.
   */
  filasSueltas?: Record<string, unknown>[]
  /** El orden de las columnas segun `ordenar_por` del modelo. Ver `cruzar`. */
  ordenColumnas?: unknown[]
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

  // Las que van una sola vez, a la derecha: una cifra que no es del mes no se repite
  // debajo de cada mes. Sólo cuentan las que están pedidas —una que se quitó del
  // widget no puede seguir gobernando una columna— y nunca todas: sin ninguna métrica
  // en la matriz no hay matriz.
  const aparte = ((widget.fuera_del_pivote as string[] | undefined) ?? [])
    .filter((m) => metricas.includes(m))
  const enMatriz = metricas.filter((m) => !aparte.includes(m))

  if (enMatriz.length === 0) {
    return (
      <div className="vacio chico">
        Todas las métricas están puestas fuera de las columnas, así que no queda
        ninguna que abrir por «{etiquetaDe(pivote)}». Deja al menos una dentro.
      </div>
    )
  }

  const cruce = cruzar(datos.filas, dimsFila, pivote, enMatriz, ordenColumnas)
  const conTotal = widget.total_fila !== false

  // Cada fila de la consulta sin el mes, por su clave de desglose, para poder casarla
  // con la fila de la matriz.
  const porFilaSuelta = new Map<string, Record<string, unknown>>()
  for (const f of filasSueltas ?? [])
    porFilaSuelta.set(claveFila(dimsFila.map((d) => f[d])), f)

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

  const hayTotales = enMatriz.some((m) => totalesDe(m) !== 'ninguno')
  const varias = enMatriz.length > 1
  // Aqui el formato va POR METRICA y no por columna: las columnas de la matriz las
  // pone el dato —un mes cada una— y no se pueden formatear de a una.
  const estilos = (widget.estilos as Record<string, EstiloColumna> | undefined) ?? {}

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
              <th key={claveCol(c)} colSpan={enMatriz.length} className="num grupo">
                {c === null || c === undefined ? '—' : String(c)}
              </th>
            ))}
            {conTotal && hayTotales && (
              <th colSpan={enMatriz.length} rowSpan={varias ? 1 : 1}
                  className="num grupo total">
                Total
              </th>
            )}
            {/* Las que van una sola vez. Con su propio nombre en la cabecera de
                arriba: no pertenecen a ningún mes, y ponerlas debajo de uno sería
                decir que sí. */}
            {aparte.map((m) => (
              <th key={`aparte|${m}`} rowSpan={varias ? 2 : 1} className="num grupo"
                  style={estiloCabecera(estilos[m])} title={m}>
                {etiquetaDe(m)}
              </th>
            ))}
          </tr>
          {/* Con una sola métrica no hace falta repetir su nombre en cada columna:
              ya está en el título del widget. */}
          {varias && (
            <tr>
              {cruce.columnas.map((c) =>
                enMatriz.map((m) => (
                  <th key={`${claveCol(c)}|${m}`} className="num sub"
                      style={estiloCabecera(estilos[m])}>
                    {etiquetaDe(m)}
                  </th>
                )),
              )}
              {conTotal &&
                hayTotales &&
                enMatriz.map((m) => (
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
                enMatriz.map((m) => {
                  const celda = f.celdas.get(claveCol(c))
                  const v = celda?.[m]
                  return (
                    <td key={`${claveCol(c)}|${m}`} className="num"
                        style={estiloCelda(estilos[m], {
                          ultima: !hayTotales && i === cruce.filas.length - 1,
                          conFilaDebajo: i < cruce.filas.length - 1,
                        })}>
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
                enMatriz.map((m) => {
                  const t = totalFila(f, m)
                  return (
                    <td key={`total|${m}`} className="num total">
                      {t === null ? '—' : formatear(t, formatoDe(m))}
                    </td>
                  )
                })}
              {aparte.map((m) => {
                const suelta = porFilaSuelta.get(claveFila(f.claves))
                const v = suelta?.[m]
                return (
                  <td key={`aparte|${m}`} className="num"
                      style={estiloCelda(estilos[m], {
                        ultima: !hayTotales && i === cruce.filas.length - 1,
                        conFilaDebajo: i < cruce.filas.length - 1,
                      })}>
                    {esNumero(v) ? (
                      // El semáforo compara contra la fila de SU consulta, la que no
                      // lleva mes: contra las celdas de los meses no significaría lo
                      // mismo.
                      <Cifra valor={v as number} formato={formatoDe(m)} sem={semDe(m)}
                             fila={suelta} />
                    ) : (
                      ''
                    )}
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
                enMatriz.map((m) => {
                  const t = totalColumna(c, m)
                  return (
                    <td key={`${claveCol(c)}|${m}`} className="num"
                        style={estiloTotal(estilos[m])}>
                      {t === null ? '—' : formatear(t, formatoDe(m))}
                    </td>
                  )
                }),
              )}
              {conTotal &&
                enMatriz.map((m) => {
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
              {/* El pie de las columnas de aparte. Sin esto la fila de totales
                  quedaría corta y las columnas se desalinearían por la derecha. */}
              {aparte.map((m) => {
                const t = totalizar(
                  cruce.filas.map(
                    (f) => porFilaSuelta.get(claveFila(f.claves))?.[m]),
                  totalesDe(m),
                )
                return (
                  <td key={`aparte|${m}`} className="num"
                      style={estiloTotal(estilos[m])}>
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
  estilos,
}: {
  datos: ResultadoConsulta
  etiquetaDe: (c: string) => string
  formatoDe: (m: string) => Formato
  metricas: string[]
  semDe: (m: string) => Semaforo | undefined
  totalesDe: (m: string) => Total
  /** El formato de cada columna: negrita, alineación, colores y marco. */
  estilos: Record<string, EstiloColumna>
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
                style={estiloCabecera(estilos[c])}
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
                <td
                  key={c}
                  className={metricas.includes(c) ? 'num' : ''}
                  // El sitio de la celda decide los lados del marco: «abajo» es el
                  // final de la columna, que es la fila de totales cuando la hay.
                  style={estiloCelda(estilos[c], {
                    ultima: !hayTotales && i === orden.filas.length - 1,
                    conFilaDebajo: i < orden.filas.length - 1,
                  })}
                >
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
                  return (
                    <td key={c} style={estiloTotal(estilos[c])}>
                      {i === 0 ? 'Totales' : ''}
                    </td>
                  )
                }
                const t = totales[metricas.indexOf(c)]
                return (
                  <td key={c} className="num" style={estiloTotal(estilos[c])}>
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
