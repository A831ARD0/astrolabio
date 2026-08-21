/**
 * Inspector de un widget: tipo, título, métricas y dimensiones.
 *
 * Las métricas y dimensiones disponibles salen del **catálogo del modelo**, no se
 * teclean. Es lo que hace que el usuario no escriba código: elige de lo que
 * existe, y lo que existe está definido y probado en el modelo.
 *
 * El panel avisa de dos cosas que dan cifras raras sin fallar:
 * un KPI con desglose (suma filas en el navegador) y un gráfico con muchas
 * categorías (ilegible, y casi siempre significa que falta un filtro).
 */

import { useState } from 'react'

import { useCampos } from '../api/hooks'
import type { Hoja, TipoWidget, Widget } from '../api/tipos'
import { coincide } from '../comunes/buscar'
import { Grupo } from '../comunes/Panel'
import {
  type Alineacion,
  type EstiloColumna,
  LADOS,
  LADOS_POR_OMISION,
  tieneEstilo,
} from './estiloColumna'
import { type Formato, type Total, totalPorOmision } from './formato'
import { SEMAFORO_NUEVO, type Semaforo } from './semaforo'

const TIPOS: { valor: TipoWidget; etiqueta: string }[] = [
  { valor: 'kpi', etiqueta: 'KPI — una cifra grande' },
  { valor: 'barras', etiqueta: 'Barras verticales' },
  { valor: 'barras_horizontales', etiqueta: 'Barras horizontales' },
  { valor: 'lineas', etiqueta: 'Líneas' },
  { valor: 'area', etiqueta: 'Área' },
  { valor: 'pastel', etiqueta: 'Pastel' },
  { valor: 'tabla', etiqueta: 'Tabla' },
  { valor: 'tabla_dinamica', etiqueta: 'Tabla dinámica — un desglose en columnas' },
  { valor: 'filtro', etiqueta: 'Filtro' },
  { valor: 'texto', etiqueta: 'Texto' },
]

/**
 * Tipos que se desglosan por UNA dimensión. Un gráfico con dos desgloses no se
 * lee.
 *
 * `filtro` no está: un panel de filtro lleva los campos que quepan, y se agrupan
 * como en Qlik. Si no hay alto para listas, se colapsan en desplegables solos.
 */
const UNA_DIMENSION: TipoWidget[] = [
  'barras',
  'barras_horizontales',
  'lineas',
  'area',
  'pastel',
]

const FORMATOS: { valor: Formato; etiqueta: string; ejemplo: string }[] = [
  { valor: 'entero', etiqueta: 'Entero', ejemplo: '1,235' },
  { valor: 'numero', etiqueta: 'Con decimales', ejemplo: '1,234.57' },
  { valor: 'moneda', etiqueta: 'Moneda', ejemplo: '$1,235' },
  { valor: 'porcentaje', etiqueta: 'Porcentaje', ejemplo: '12.3 %' },
]

const TOTALES: { valor: Total; etiqueta: string }[] = [
  { valor: 'suma', etiqueta: 'Suma' },
  { valor: 'promedio', etiqueta: 'Promedio' },
  { valor: 'ninguno', etiqueta: 'Sin total' },
]

/** Lee un diccionario que el widget guarda como opción propia. */
function mapaDe<T>(widget: Widget, clave: string): Record<string, T> {
  return (widget[clave] as Record<string, T> | undefined) ?? {}
}

export function PanelWidget({
  widget,
  modeloId,
  hojas,
  lienzo,
  alCambiar,
  alQuitar,
}: {
  widget: Widget
  modeloId: number
  hojas: Hoja[]
  /** El tamaño de la hoja: es el tope de lo que puede medir un widget. */
  lienzo: { columnas: number; filas: number }
  alCambiar: (cambios: Partial<Widget>) => void
  alQuitar: () => void
}) {
  const campos = useCampos(modeloId)
  const dimensiones = campos.data?.dimensiones ?? []
  const metricas = campos.data?.metricas ?? []

  const soloUna = UNA_DIMENSION.includes(widget.tipo)
  const sinMetricas = widget.tipo === 'filtro' || widget.tipo === 'texto'

  const alternarDim = (clave: string) => {
    const actuales = widget.dimensiones ?? []
    if (actuales.includes(clave)) {
      alCambiar({ dimensiones: actuales.filter((d) => d !== clave) })
    } else {
      alCambiar({ dimensiones: soloUna ? [clave] : [...actuales, clave] })
    }
  }

  const alternarMet = (clave: string) => {
    const actuales = widget.metricas ?? []
    alCambiar({
      metricas: actuales.includes(clave)
        ? actuales.filter((m) => m !== clave)
        : [...actuales, clave],
    })
  }

  return (
    <div className="inspector">
      <div className="campo">
        <label>Tipo</label>
        <select
          value={widget.tipo}
          onChange={(e) => alCambiar({ tipo: e.target.value as TipoWidget })}
        >
          {TIPOS.map((t) => (
            <option key={t.valor} value={t.valor}>
              {t.etiqueta}
            </option>
          ))}
        </select>
      </div>

      <div className="campo">
        <label>Título</label>
        <input
          type="text"
          value={widget.titulo}
          placeholder="Sin título"
          onChange={(e) => alCambiar({ titulo: e.target.value })}
        />
      </div>

      <TamanoYSitio widget={widget} lienzo={lienzo} alCambiar={alCambiar} />

      {hojas.length > 1 && (
        <div className="campo">
          <label>Hoja</label>
          <select
            value={widget.hoja || hojas[0]!.id}
            onChange={(e) => alCambiar({ hoja: e.target.value })}
          >
            {hojas.map((h) => (
              <option key={h.id} value={h.id}>
                {h.nombre}
              </option>
            ))}
          </select>
          <span className="chico tenue">
            Al cambiarla, el widget se va a esa hoja con el mismo tamaño. Si allí
            no cabe, la hoja lo baja de sitio.
          </span>
        </div>
      )}

      {widget.tipo === 'texto' && (
        <>
          <div className="campo">
            <label>Texto</label>
            <textarea
              rows={3}
              value={String(widget.texto ?? '')}
              onChange={(e) => alCambiar({ texto: e.target.value })}
            />
          </div>
          <div className="campo">
            <label>Tamaño</label>
            <select
              value={String(widget.tamano_texto ?? '')}
              onChange={(e) =>
                alCambiar({ tamano_texto: e.target.value ? Number(e.target.value) : null })
              }
            >
              <option value="">Normal</option>
              {TAMANOS.map((x) => (
                <option key={x.px} value={x.px}>
                  {x.nombre} — {x.px} px
                </option>
              ))}
            </select>
          </div>
          <div className="campo">
            <label>Color</label>
            {/* Un selector de color del sistema y un campo al lado: el selector es
                cómodo, y el campo es el que permite escribir el color exacto de la
                marca en vez de acertarlo con el ratón. */}
            <div className="fila-color">
              <input
                type="color"
                value={String(widget.color_texto ?? '#111827')}
                onChange={(e) => alCambiar({ color_texto: e.target.value })}
              />
              <input
                type="text"
                value={String(widget.color_texto ?? '')}
                placeholder="el del tema"
                onChange={(e) => alCambiar({ color_texto: e.target.value || null })}
              />
              {!!widget.color_texto && (
                <button
                  className="btn chico"
                  title="Volver al color del tema"
                  onClick={() => alCambiar({ color_texto: null })}
                >
                  ✕
                </button>
              )}
            </div>
            <span className="chico tenue">
              Sin color puesto sigue el tema, así que se lee igual en claro y en
              oscuro. Con uno puesto, manda el tuyo en los dos.
            </span>
          </div>
          <div className="campo">
            <label>Alineación</label>
            <select
              value={String(widget.alineacion ?? 'left')}
              onChange={(e) => alCambiar({ alineacion: e.target.value })}
            >
              <option value="left">Izquierda</option>
              <option value="center">Centrado</option>
              <option value="right">Derecha</option>
            </select>
          </div>
          <label className="casilla">
            <input
              type="checkbox"
              checked={!!widget.negrita}
              onChange={(e) => alCambiar({ negrita: e.target.checked })}
            />
            Negrita
          </label>
        </>
      )}

      {widget.tipo === 'kpi' && (widget.dimensiones?.length ?? 0) > 0 && (
        <div className="aviso-caja">
          Un KPI con desglose suma las filas en el navegador. Para métricas
          aditivas está bien; para un promedio o un porcentaje da un número
          equivocado. Quita el desglose si dudas.
        </div>
      )}

      {!sinMetricas && (
        <>
          <Elegidas
            titulo="Columnas de cifras"
            campo="metricas"
            claves={widget.metricas ?? []}
            etiquetaBase={(c) =>
              metricas.find((m) => m.clave === c)?.etiqueta ?? c
            }
            formatoBase={(c) =>
              (metricas.find((m) => m.clave === c)?.formato as Formato) ?? 'numero'
            }
            widget={widget}
            conTotales={widget.tipo === 'tabla'}
            alCambiar={alCambiar}
          />
          <Seleccionables
            titulo={`Métricas${widget.metricas?.length ? ` (${widget.metricas.length})` : ''}`}
            clave="metricas"

            items={metricas.map((m) => ({ clave: m.clave, etiqueta: m.etiqueta,
                                          nota: m.entidad }))}
            elegidos={widget.metricas ?? []}
            alAlternar={alternarMet}
            vacio="El modelo no tiene métricas todavía."
          />
        </>
      )}

      {widget.tipo === 'tabla_dinamica' && (
        <>
          <div className="campo">
            <label>Se abre en columnas</label>
            {(widget.dimensiones?.length ?? 0) < 2 ? (
              <span className="chico tenue">
                Elige abajo dos desgloses: uno se queda en las filas y el otro se
                abre a lo ancho. Con uno solo, lo que quieres es una tabla normal.
              </span>
            ) : (
              <>
                <select
                  value={
                    widget.dimensiones.includes(String(widget.pivote))
                      ? String(widget.pivote)
                      : widget.dimensiones[widget.dimensiones.length - 1]
                  }
                  onChange={(e) => alCambiar({ pivote: e.target.value })}
                >
                  {widget.dimensiones.map((d) => (
                    <option key={d} value={d}>
                      {dimensiones.find((x) => x.clave === d)?.etiqueta ?? d}
                    </option>
                  ))}
                </select>
                <span className="chico tenue">
                  Los demás desgloses se quedan a la izquierda, en el orden de la
                  lista de abajo.
                </span>
              </>
            )}
          </div>

          <div className="linea-check">
            <input
              type="checkbox"
              id={`tf-${widget.id}`}
              checked={widget.total_fila !== false}
              onChange={(e) => alCambiar({ total_fila: e.target.checked })}
            />
            <label htmlFor={`tf-${widget.id}`}>
              Columna de total a la derecha
            </label>
          </div>

          {/*
            Una cifra que no es del mes no puede repetirse debajo de cada mes: el
            inventario de hoy no es «el inventario de enero» siete veces, y sumar esa
            fila daría siete veces el inventario. Marcada aquí, sale en su propia
            columna a la derecha, una sola vez, y su cifra la calcula el motor sin el
            mes — no se deduce de las celdas de los meses.
          */}
          {(widget.metricas?.length ?? 0) > 0 && (
            <div className="campo">
              <label>
                Fuera de las columnas
                <span className="chico tenue" style={{ fontWeight: 400, marginLeft: 8 }}>
                  sin marcar nada, cada métrica se abre en todos los meses
                </span>
              </label>
              <div className="atajos">
                {(widget.metricas ?? []).map((m) => {
                  const puestas = (widget.fuera_del_pivote as string[] | undefined) ?? []
                  const ultima = puestas.length === (widget.metricas ?? []).length - 1
                    && !puestas.includes(m)
                  return (
                    <label key={m} className="chico" style={{ display: 'block' }}>
                      <input
                        type="checkbox"
                        checked={puestas.includes(m)}
                        // Dejar la matriz sin ninguna métrica no es una tabla
                        // dinámica: no habría nada que abrir en columnas.
                        disabled={ultima}
                        title={ultima
                          ? 'Al menos una métrica tiene que quedarse en las columnas'
                          : undefined}
                        onChange={(e) =>
                          alCambiar({
                            fuera_del_pivote: e.target.checked
                              ? [...puestas, m]
                              : puestas.filter((x) => x !== m),
                          })
                        }
                      />{' '}
                      {metricas.find((x) => x.clave === m)?.etiqueta ?? m}
                    </label>
                  )
                })}
              </div>
            </div>
          )}
        </>
      )}

      {/* Con un solo desglose no hay orden que elegir. */}
      {!soloUna && widget.tipo !== 'texto' && (
        <Elegidas
          titulo={widget.tipo === 'filtro' ? 'Campos, en este orden' : 'Columnas de desglose'}
          campo="dimensiones"
          claves={widget.dimensiones ?? []}
          etiquetaBase={(c) =>
            dimensiones.find((d) => d.clave === c)?.etiqueta ?? c
          }
          formatoBase={() => 'numero'}
          widget={widget}
          conTotales={false}
          soloEtiqueta
          alCambiar={alCambiar}
        />
      )}

      <Seleccionables
        clave="dimensiones"
        titulo={
          soloUna
            ? 'Desglosar por (una)'
            : `${widget.tipo === 'filtro' ? 'Campos del panel' : 'Dimensiones'}${
                widget.dimensiones?.length ? ` (${widget.dimensiones.length})` : ''
              }`
        }
        items={dimensiones.map((d) => ({ clave: d.clave, etiqueta: d.etiqueta,
                                         nota: d.entidad }))}
        elegidos={widget.dimensiones ?? []}
        alAlternar={alternarDim}
        vacio="El modelo no tiene dimensiones visibles."
      />

      {widget.tipo !== 'filtro' && widget.tipo !== 'texto' && (
        <div className="campo">
          <label>Máximo de filas</label>
          <input
            type="number"
            min={1}
            max={50000}
            value={widget.limite ?? 1000}
            onChange={(e) => alCambiar({ limite: Number(e.target.value) || 1000 })}
          />
          <span className="chico tenue">
            Un gráfico con cientos de categorías no se lee. Si hacen falta todas,
            casi siempre lo que falta es un filtro.
          </span>
        </div>
      )}

      <button className="btn peligro" onClick={alQuitar}>
        Quitar widget
      </button>
    </div>
  )
}

/**
 * Lo elegido, **en el orden en que sale**, con las propiedades de cada columna.
 *
 * Va separado del catálogo a propósito. En el catálogo el orden es alfabético o el
 * del modelo, y lo que importa aquí es otro: el orden de las columnas de la tabla y
 * de las series del gráfico. Mezclar las dos cosas en una lista obliga a elegir
 * entre poder buscar y poder ordenar.
 */
function Elegidas({
  titulo,
  campo,
  claves,
  etiquetaBase,
  formatoBase,
  widget,
  conTotales,
  soloEtiqueta = false,
  alCambiar,
}: {
  titulo: string
  /** En qué lista del widget se guarda el orden. */
  campo: 'metricas' | 'dimensiones'
  claves: string[]
  etiquetaBase: (clave: string) => string
  formatoBase: (clave: string) => Formato
  widget: Widget
  conTotales: boolean
  /** Una dimension no tiene formato de cifra ni total: solo su nombre. */
  soloEtiqueta?: boolean
  alCambiar: (cambios: Partial<Widget>) => void
}) {
  const [abierta, setAbierta] = useState<string | null>(null)

  if (claves.length === 0) return null

  const etiquetas = mapaDe<string>(widget, 'etiquetas')
  const formatos = mapaDe<Formato>(widget, 'formatos')
  const totales = mapaDe<Total>(widget, 'totales_de')
  const semaforos = mapaDe<Semaforo>(widget, 'semaforos')
  const estilos = mapaDe<EstiloColumna>(widget, 'estilos')

  const mover = (i: number, paso: -1 | 1) => {
    const j = i + paso
    if (j < 0 || j >= claves.length) return
    const orden = [...claves]
    ;[orden[i], orden[j]] = [orden[j]!, orden[i]!]
    alCambiar({ [campo]: orden } as Partial<Widget>)
  }

  /**
   * Quita la columna, y con ella lo que se le había puesto.
   *
   * Se limpian sus ajustes —etiqueta, formato, semáforo, totales, estilo— y no solo la
   * clave de la lista: si no, el widget arrastra para siempre el semáforo de una columna
   * que ya no está, y al volver a agregarla reaparece pintada por algo que nadie
   * recuerda haber pedido.
   */
  const quitar = (clave: string) => {
    const cambios: Record<string, unknown> = {
      [campo]: claves.filter((c) => c !== clave),
    }
    for (const mapa of ['etiquetas', 'formatos', 'totales_de', 'semaforos', 'estilos']) {
      const actual = mapaDe<unknown>(widget, mapa)
      if (clave in actual) {
        const copia = { ...actual }
        delete copia[clave]
        cambios[mapa] = copia
      }
    }
    // Y de la lista de las que van fuera de las columnas. Es una lista y no un mapa,
    // pero el motivo es el mismo: si se queda, gobierna una columna que ya no existe
    // y al volver a agregar la métrica sale fuera de la matriz sin que nadie lo pida.
    const fuera = (widget.fuera_del_pivote as string[] | undefined) ?? []
    if (fuera.includes(clave))
      cambios.fuera_del_pivote = fuera.filter((m) => m !== clave)
    alCambiar(cambios as Partial<Widget>)
  }

  /** Guarda una propiedad, y la borra del widget si vuelve a ser la del modelo. */
  const poner = (mapa: string, clave: string, valor: string | undefined) => {
    const copia = { ...mapaDe<string>(widget, mapa) }
    if (valor === undefined) delete copia[clave]
    else copia[clave] = valor
    alCambiar({ [mapa]: copia } as Partial<Widget>)
  }

  return (
    <div>
      <div className="chico suave" style={{ marginBottom: 4 }}>
        {titulo} <span className="tenue">({claves.length}, en este orden)</span>
      </div>
      <div className="columnas-elegidas">
        {claves.map((c, i) => {
          const base = formatoBase(c)
          const formato = formatos[c] ?? base
          const total = totales[c] ?? totalPorOmision(formato)
          // Al renombrar una columna se pierde de vista QUÉ cifra es, y con noventa
          // y seis métricas «% CONV LEAD A TRAF M ANT» no basta para saber cuál de
          // ellas se puso. El nombre del modelo se queda a la vista, atenuado.
          const propia = etiquetas[c]?.trim()
          const delModelo = etiquetaBase(c)
          const renombrada = !!propia && propia !== delModelo
          return (
            <div key={c} className={`col-elegida ${abierta === c ? 'abierta' : ''}`}>
              <div className="cabeza">
                <button
                  className="titulo"
                  title={c}
                  onClick={() => setAbierta(abierta === c ? null : c)}
                >
                  <span className="pos">{i + 1}</span>
                  <span className="nom">{propia || delModelo}</span>
                  {renombrada && <span className="del-modelo">{delModelo}</span>}
                  <span className="flecha">{abierta === c ? '▾' : '▸'}</span>
                </button>
                <button
                  className="mueve"
                  disabled={i === 0}
                  title="Subir"
                  onClick={() => mover(i, -1)}
                >
                  ↑
                </button>
                <button
                  className="mueve"
                  disabled={i === claves.length - 1}
                  title="Bajar"
                  onClick={() => mover(i, 1)}
                >
                  ↓
                </button>
                {/* Aquí y no solo en el catálogo: para quitar una columna había que
                    buscarla en la lista de abajo y volver a pulsarla, y con noventa y
                    seis métricas eso es buscar lo que ya se tiene delante. */}
                <button
                  className="mueve quita"
                  title="Quitar esta columna del widget"
                  onClick={() => quitar(c)}
                >
                  ✕
                </button>
              </div>

              {abierta === c && (
                <div className="cuerpo">
                  <div className="campo">
                    <label>Etiqueta</label>
                    <input
                      type="text"
                      value={etiquetas[c] ?? ''}
                      placeholder={etiquetaBase(c)}
                      onChange={(e) =>
                        poner('etiquetas', c, e.target.value || undefined)
                      }
                    />
                    <span className="chico tenue">
                      Solo cambia el nombre en este widget. En el modelo se llama{' '}
                      <strong>{delModelo}</strong> <code>{c}</code>, y así es como lo
                      ven los demás tableros.
                    </span>
                  </div>

                  {!soloEtiqueta && (
                  <div className="campo">
                    <label>Formato</label>
                    <select
                      value={formato}
                      onChange={(e) =>
                        poner(
                          'formatos',
                          c,
                          e.target.value === base ? undefined : e.target.value,
                        )
                      }
                    >
                      {FORMATOS.map((f) => (
                        <option key={f.valor} value={f.valor}>
                          {f.etiqueta} — {f.ejemplo}
                          {f.valor === base ? ' (del modelo)' : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                  )}

                  {!soloEtiqueta && (
                    <EditorSemaforo
                      clave={c}
                      formato={formato}
                      otras={claves.filter((x) => x !== c)}
                      etiquetaDe={etiquetaBase}
                      sem={semaforos[c]}
                      alCambiar={(s) => {
                        const copia = { ...semaforos }
                        if (s === undefined) delete copia[c]
                        else copia[c] = s
                        alCambiar({ semaforos: copia } as Partial<Widget>)
                      }}
                    />
                  )}

                  {conTotales && (
                    <div className="campo">
                      <label>Fila de totales</label>
                      <select
                        value={total}
                        onChange={(e) =>
                          poner('totales_de', c, e.target.value)
                        }
                      >
                        {TOTALES.map((t) => (
                          <option key={t.valor} value={t.valor}>
                            {t.etiqueta}
                          </option>
                        ))}
                      </select>
                      {formato === 'porcentaje' && total === 'suma' && (
                        <span className="chico aviso-texto">
                          La suma de varios porcentajes no significa nada. Para un
                          logro, el total correcto se calcula con una métrica que
                          divida los dos totales.
                        </span>
                      )}
                    </div>
                  )}

                  <EstiloDeColumna
                    estilo={estilos[c]}
                    alCambiar={(nuevo: EstiloColumna | undefined) => {
                      const copia = { ...estilos }
                      // Sin nada puesto se BORRA la entrada: así el widget no arrastra
                      // un `{}` por cada columna que alguien abrió y dejó como estaba.
                      if (nuevo && tieneEstilo(nuevo)) copia[c] = nuevo
                      else delete copia[c]
                      alCambiar({ estilos: copia } as Partial<Widget>)
                    }}
                  />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/**
 * El semáforo de una columna: contra qué se compara y hacia dónde está bien.
 *
 * El umbral se teclea **en las unidades que se ven**. Si la columna es un
 * porcentaje, quien la configura escribe `100` y no `1`: pedirle que traduzca a la
 * unidad interna es la forma más segura de acabar con un semáforo en verde a un 1 %
 * de logro.
 */
function EditorSemaforo({
  clave,
  formato,
  otras,
  etiquetaDe,
  sem,
  alCambiar,
}: {
  clave: string
  formato: Formato
  /** Las demás columnas del widget: se puede comparar contra una de ellas. */
  otras: string[]
  etiquetaDe: (clave: string) => string
  sem: Semaforo | undefined
  alCambiar: (s: Semaforo | undefined) => void
}) {
  const esPct = formato === 'porcentaje'
  const factor = esPct ? 100 : 1

  return (
    <div className="campo">
      <label>Semáforo</label>
      {!sem ? (
        <button className="btn" onClick={() => alCambiar({ ...SEMAFORO_NUEVO })}>
          Poner semáforo
        </button>
      ) : (
        <>
          <select
            value={sem.comparar}
            onChange={(e) =>
              alCambiar({
                ...sem,
                comparar: e.target.value as Semaforo['comparar'],
                // Al pasar a comparar contra otra columna se propone la primera:
                // dejarlo vacío haría que el semáforo dejara de pintar sin decir
                // por qué.
                metrica: e.target.value === 'metrica' ? otras[0] : sem.metrica,
              })
            }
          >
            <option value="valor">Contra un objetivo fijo</option>
            <option value="metrica" disabled={otras.length === 0}>
              Contra otra columna
            </option>
          </select>

          {sem.comparar === 'valor' ? (
            <div className="fila" style={{ marginTop: 6 }}>
              <input
                type="number"
                step="any"
                value={sem.objetivo === undefined ? '' : sem.objetivo * factor}
                onChange={(e) =>
                  alCambiar({
                    ...sem,
                    objetivo:
                      e.target.value === ''
                        ? undefined
                        : Number(e.target.value) / factor,
                  })
                }
              />
              {esPct && <span className="chico tenue" style={{ alignSelf: 'center' }}>%</span>}
            </div>
          ) : (
            <select
              style={{ marginTop: 6 }}
              value={sem.metrica ?? ''}
              onChange={(e) => alCambiar({ ...sem, metrica: e.target.value })}
            >
              {otras.map((o) => (
                <option key={o} value={o}>
                  {etiquetaDe(o)}
                </option>
              ))}
            </select>
          )}

          <select
            style={{ marginTop: 6 }}
            value={sem.bueno}
            onChange={(e) =>
              alCambiar({ ...sem, bueno: e.target.value as Semaforo['bueno'] })
            }
          >
            <option value="mayor">Más es mejor (verde arriba)</option>
            <option value="menor">Menos es mejor (verde abajo)</option>
          </select>
          <span className="chico tenue">
            «Más es mejor» no vale para todo: los días que un auto lleva en
            inventario suben y eso está mal. Aquí es donde se dice.
          </span>

          <select
            style={{ marginTop: 6 }}
            value={sem.mostrar}
            onChange={(e) =>
              alCambiar({ ...sem, mostrar: e.target.value as Semaforo['mostrar'] })
            }
          >
            <option value="ambos">Flecha y fondo</option>
            <option value="flecha">Solo la flecha</option>
            <option value="fondo">Solo el fondo</option>
          </select>

          <button
            className="btn"
            style={{ marginTop: 6 }}
            onClick={() => alCambiar(undefined)}
          >
            Quitar el semáforo de «{etiquetaDe(clave)}»
          </button>
        </>
      )}
    </div>
  )
}

/**
 * Los tamaños que se ofrecen, con nombre.
 *
 * Una lista y no un número libre: así los títulos de dos hojas distintas salen del
 * mismo juego y la hoja no acaba con seis tamaños que se parecen. Los nombres son
 * los del uso —título, subtítulo— porque es lo que se está buscando al elegir.
 */
const TAMANOS = [
  { nombre: 'Nota', px: 11 },
  { nombre: 'Normal', px: 13 },
  { nombre: 'Subtítulo', px: 16 },
  { nombre: 'Título', px: 22 },
  { nombre: 'Título grande', px: 30 },
  { nombre: 'Portada', px: 42 },
]

/**
 * El formato de una columna: negrita, alineación, colores y marco.
 *
 * Aparte del semáforo, y la pantalla lo dice: son dos cosas que se parecen y no lo son.
 * El semáforo habla del dato y cambia de una fila a otra; esto es del informe y es igual
 * en todas las filas.
 */
function EstiloDeColumna({
  estilo,
  alCambiar,
}: {
  estilo: EstiloColumna | undefined
  alCambiar: (e: EstiloColumna | undefined) => void
}) {
  const e = estilo ?? {}
  const cambia = (parte: Partial<EstiloColumna>) => alCambiar({ ...e, ...parte })

  return (
    <div className="campo">
      <label>Formato de la columna</label>
      <div className="fila-estilo">
        <label className="casilla" title="Toda la columna en negrita">
          <input
            type="checkbox"
            checked={!!e.negrita}
            onChange={(ev) => cambia({ negrita: ev.target.checked || undefined })}
          />
          Negrita
        </label>
        <select
          value={e.alineacion ?? ''}
          title="A qué lado se pega el contenido"
          onChange={(ev) =>
            cambia({
              alineacion: (ev.target.value || undefined) as Alineacion | undefined,
            })
          }
        >
          <option value="">Alineación normal</option>
          <option value="izquierda">Izquierda</option>
          <option value="centro">Centrado</option>
          <option value="derecha">Derecha</option>
        </select>
      </div>

      <div className="fila-estilo">
        <Color rotulo="Letra" valor={e.color} alCambiar={(color) => cambia({ color })} />
        <Color rotulo="Fondo" valor={e.fondo} alCambiar={(fondo) => cambia({ fondo })} />
        <Color rotulo="Marco" valor={e.marco} alCambiar={(marco) => cambia({ marco })} />
      </div>

      {/* Los lados solo se ofrecen con un color puesto: sin color no hay nada que
          dibujar, y cinco casillas que no hacen nada se prueban una por una. */}
      {e.marco && (
        <div className="lados-marco">
          {LADOS.map(({ lado, nombre, ayuda }) => {
            const puestos = e.lados ?? LADOS_POR_OMISION
            const activo = puestos.includes(lado)
            return (
              <button
                key={lado}
                className={`btn chico ${activo ? 'primario' : ''}`}
                title={ayuda}
                onClick={() =>
                  cambia({
                    lados: activo
                      ? puestos.filter((x) => x !== lado)
                      : [...puestos, lado],
                  })
                }
              >
                {nombre}
              </button>
            )
          })}
        </div>
      )}

      <span className="chico tenue">
        Es aparte del semáforo: el semáforo habla del dato y cambia por fila, esto es
        igual en todas. Los dos caben — el semáforo se dibuja dentro de la celda.
        {e.marco
          ? ' «Arriba» y «abajo» son los extremos de la columna, no de cada celda; para las rayas entre renglones está «entre filas».'
          : ''}
      </span>
      {tieneEstilo(e) && (
        <button className="btn chico" onClick={() => alCambiar(undefined)}>
          Quitar el formato
        </button>
      )}
    </div>
  )
}

/** Un color con su nombre, y una ✕ para volver al del tema. */
function Color({
  rotulo,
  valor,
  alCambiar,
}: {
  rotulo: string
  valor: string | undefined
  alCambiar: (v: string | undefined) => void
}) {
  return (
    <span className="color-con-nombre">
      <span className="chico tenue">{rotulo}</span>
      <input
        type="color"
        // Sin color puesto el selector tiene que enseñar ALGO: se enseña el del texto,
        // pero lo que vale es `valor`, que sigue vacío hasta que alguien lo toca.
        value={valor ?? '#111827'}
        onChange={(ev) => alCambiar(ev.target.value)}
      />
      {valor ? (
        <button
          className="quitar-color"
          title={`Sin ${rotulo.toLowerCase()} propio: el del tema`}
          onClick={() => alCambiar(undefined)}
        >
          ✕
        </button>
      ) : (
        <span className="quitar-color vacio" aria-hidden="true" />
      )}
    </span>
  )
}

/**
 * El tamaño y el sitio del widget, en números.
 *
 * Se puede arrastrar y estirar en la hoja, y eso está bien para acomodar; lo que no
 * sirve es para ACERTAR: «esta tabla ocupa media hoja» se hace a ojo, y dos tablas que
 * deberían medir igual acaban con una columna de diferencia. Aquí se escribe.
 *
 * Las cuentas van en columnas y filas de la hoja, no en píxeles, porque es lo que la
 * hoja entiende: una hoja de 12 columnas en una pantalla ancha y en un portátil da
 * píxeles distintos, y el widget mide lo mismo en las dos.
 *
 * Cada número se acota contra la hoja al escribirlo —un widget no puede empezar en la
 * columna 11 y medir 6 de 12— y lo que se recorta es la POSICIÓN, no el tamaño: quien
 * escribe un ancho quiere ese ancho.
 */
function TamanoYSitio({
  widget,
  lienzo,
  alCambiar,
}: {
  widget: Widget
  lienzo: { columnas: number; filas: number }
  alCambiar: (cambios: Partial<Widget>) => void
}) {
  const p = widget.posicion
  const entre = (v: number, min: number, max: number) =>
    Math.max(min, Math.min(max, Number.isFinite(v) ? Math.round(v) : min))

  const mover = (cambio: Partial<typeof p>) => {
    const ancho = entre(cambio.ancho ?? p.ancho, 1, lienzo.columnas)
    const alto = entre(cambio.alto ?? p.alto, 1, lienzo.filas)
    alCambiar({
      posicion: {
        ...p,
        ancho,
        alto,
        x: entre(cambio.x ?? p.x, 0, lienzo.columnas - ancho),
        y: Math.max(0, Math.round(cambio.y ?? p.y)),
      },
    })
  }

  return (
    <div className="campo">
      <label>Tamaño y sitio</label>
      <div className="rejilla-medidas">
        <span className="chico tenue">Ancho</span>
        <input
          type="number"
          min={1}
          max={lienzo.columnas}
          value={p.ancho}
          onChange={(e) => mover({ ancho: e.target.valueAsNumber })}
        />
        <span className="chico tenue">de {lienzo.columnas}</span>

        <span className="chico tenue">Alto</span>
        <input
          type="number"
          min={1}
          max={lienzo.filas}
          value={p.alto}
          onChange={(e) => mover({ alto: e.target.valueAsNumber })}
        />
        <span className="chico tenue">de {lienzo.filas}</span>

        <span className="chico tenue">Columna</span>
        <input
          type="number"
          min={0}
          max={Math.max(0, lienzo.columnas - p.ancho)}
          value={p.x}
          onChange={(e) => mover({ x: e.target.valueAsNumber })}
        />
        <span className="chico tenue">desde 0</span>

        <span className="chico tenue">Fila</span>
        <input
          type="number"
          min={0}
          value={p.y}
          onChange={(e) => mover({ y: e.target.valueAsNumber })}
        />
        <span className="chico tenue">desde 0</span>
      </div>
      <span className="chico tenue">
        En columnas y filas de la hoja, no en píxeles: así el widget mide lo mismo en un
        monitor que en un portátil. Media hoja son {Math.round(lienzo.columnas / 2)}{' '}
        columnas.
      </span>
    </div>
  )
}

/** Desde cuántos elementos vale la pena el buscador. Con menos, estorba. */
const BUSCADOR_DESDE = 8

/**
 * Desde cuántas tablas vale la pena agrupar.
 *
 * Con dos, las cabeceras cuestan más de lo que ordenan: se ve la lista entera de un
 * golpe y la columna de la derecha ya dice de dónde sale cada cosa.
 */
const AGRUPAR_DESDE = 3

/**
 * El grupo de una métrica que no sale de ninguna tabla NI está en una tabla de
 * medidas. Lo pone el servidor.
 *
 * Una compuesta guardada en una tabla de medidas se agrupa por ella —«Medidas
 * Ventas»—, que es como se agrupa en el modelo. Cincuenta y ocho compuestas en un
 * montón llamado «compuesta» dicen de qué NO son, no de qué son.
 */
const COMPUESTA = 'compuesta'

type Item = { clave: string; etiqueta: string; nota: string }

/**
 * Las métricas por la tabla de la que salen, en el orden en que las da el modelo.
 *
 * `compuesta` va al final y no entre las tablas: no es una tabla, es una cifra
 * calculada sobre otras métricas. Ponerla en medio, con el mismo aspecto que
 * `FACT_VENTAS`, haría pensar que existe un origen con ese nombre. Las tablas de
 * medidas sí van entre las demás, en el orden en que el modelo las declara — que
 * las deja después de las métricas de las que dependen.
 */
function porTabla(items: Item[]): [string, Item[]][] {
  const grupos = new Map<string, Item[]>()
  for (const i of items) {
    const tabla = i.nota || 'sin tabla'
    const ya = grupos.get(tabla)
    if (ya) ya.push(i)
    else grupos.set(tabla, [i])
  }
  // `sort` es estable, así que lo único que se mueve es `compuesta`.
  return [...grupos.entries()].sort(
    (a, b) => Number(a[0] === COMPUESTA) - Number(b[0] === COMPUESTA),
  )
}

/**
 * El catálogo: lo que se puede elegir, agrupado por la tabla de la que sale.
 *
 * Con noventa y seis métricas una lista plana es un pozo: para llegar a las de
 * refacciones hay que atravesar las de ventas y las de objetivos con la rueda del ratón,
 * y no hay forma de ver de un golpe qué trae cada tabla. Agrupadas, cada grupo se
 * pliega una vez y se queda plegado —se acuerda en el navegador—, y su cabecera
 * sigue diciendo cuántas hay dentro y cuántas usa este widget aunque esté cerrado.
 * Un grupo plegado que esconde una métrica en uso sería una trampa.
 *
 * Los que no aportan nada a este widget nacen plegados; los que sí, abiertos. Y al
 * buscar se abren todos, porque un grupo cerrado que esconde el único resultado se
 * lee como «no hay nada», que es lo contrario de lo que pasa.
 */
function Seleccionables({
  titulo,
  clave,
  items,
  elegidos,
  alAlternar,
  vacio,
}: {
  titulo: string
  /** Para acordarse de qué grupos están plegados sin confundir dos catálogos. */
  clave: string
  items: Item[]
  elegidos: string[]
  alAlternar: (clave: string) => void
  vacio: string
}) {
  const [busca, setBusca] = useState('')
  const buscando = busca.trim().length > 0

  // Se busca por etiqueta, por nombre técnico y por tabla: con noventa y seis
  // métricas, un trozo del nombre es lo que uno recuerda, no el nombre exacto.
  //
  // Lo ya elegido no se esconde nunca, y se queda en SU sitio en vez de irse al
  // final de la lista: si al buscar desapareciera, no habría forma de quitarlo sin
  // adivinar cómo se llamaba.
  const sale = (i: Item) =>
    !buscando ||
    coincide(`${i.etiqueta} ${i.clave} ${i.nota}`, busca) ||
    elegidos.includes(i.clave)

  const grupos = porTabla(items)
  const agrupado = grupos.length >= AGRUPAR_DESDE

  const lista = (dentro: Item[]) => (
    <div className="lista">
      {dentro.map((i) => (
        <button
          key={i.clave}
          className={elegidos.includes(i.clave) ? 'sel' : ''}
          onClick={() => alAlternar(i.clave)}
          title={i.clave}
        >
          <span className="nom">{i.etiqueta}</span>
          {/* Agrupado, la tabla ya está en la cabecera: repetirla en cada renglón
              es ruido, y el sitio se aprovecha para el nombre. */}
          {!agrupado && <span className="dcha">{i.nota}</span>}
        </button>
      ))}
    </div>
  )

  const visibles = items.filter(sale)

  return (
    <div>
      <div className="chico suave" style={{ marginBottom: 4 }}>
        {titulo}
      </div>
      {items.length === 0 ? (
        <div className="chico tenue">{vacio}</div>
      ) : (
        <>
          {items.length >= BUSCADOR_DESDE && (
            <input
              type="search"
              className="buscar"
              value={busca}
              placeholder={`Buscar entre ${items.length}…`}
              onChange={(e) => setBusca(e.target.value)}
            />
          )}
          {visibles.length === 0 ? (
            <div className="chico tenue">Nada coincide con «{busca.trim()}».</div>
          ) : !agrupado ? (
            lista(visibles)
          ) : (
            grupos.map(([tabla, todos]) => {
              const dentro = todos.filter(sale)
              if (dentro.length === 0) return null
              const usadas = todos.filter((i) => elegidos.includes(i.clave)).length
              return (
                <Grupo
                  key={tabla}
                  clave={`campos.${clave}.${tabla}`}
                  titulo={tabla}
                  cuenta={usadas > 0 ? `${usadas} de ${todos.length}` : todos.length}
                  forzarAbierto={buscando}
                  plegadoPorOmision={usadas === 0}
                >
                  {lista(dentro)}
                </Grupo>
              )
            })
          )}
        </>
      )}
    </div>
  )
}
