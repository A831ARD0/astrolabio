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
  alCambiar,
  alQuitar,
}: {
  widget: Widget
  modeloId: number
  hojas: Hoja[]
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
        <div className="campo">
          <label>Texto</label>
          <textarea
            rows={4}
            value={String(widget.texto ?? '')}
            onChange={(e) => alCambiar({ texto: e.target.value })}
          />
        </div>
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

  const mover = (i: number, paso: -1 | 1) => {
    const j = i + paso
    if (j < 0 || j >= claves.length) return
    const orden = [...claves]
    ;[orden[i], orden[j]] = [orden[j]!, orden[i]!]
    alCambiar({ [campo]: orden } as Partial<Widget>)
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
          return (
            <div key={c} className={`col-elegida ${abierta === c ? 'abierta' : ''}`}>
              <div className="cabeza">
                <button
                  className="titulo"
                  title={c}
                  onClick={() => setAbierta(abierta === c ? null : c)}
                >
                  <span className="pos">{i + 1}</span>
                  <span className="nom">{etiquetas[c] || etiquetaBase(c)}</span>
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
                      Solo cambia el nombre en este widget. En el modelo sigue
                      llamándose igual, y ahí es donde lo ven los demás tableros.
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

/** Desde cuántos elementos vale la pena el buscador. Con menos, estorba. */
const BUSCADOR_DESDE = 8

/**
 * Desde cuántas tablas vale la pena agrupar.
 *
 * Con dos, las cabeceras cuestan más de lo que ordenan: se ve la lista entera de un
 * golpe y la columna de la derecha ya dice de dónde sale cada cosa.
 */
const AGRUPAR_DESDE = 3

/** El grupo de una métrica que no sale de ninguna tabla. Lo pone el servidor. */
const COMPUESTA = 'compuesta'

type Item = { clave: string; etiqueta: string; nota: string }

/**
 * Las métricas por la tabla de la que salen, en el orden en que las da el modelo.
 *
 * `compuesta` va al final y no entre las tablas: no es una tabla, es una cifra
 * calculada sobre otras métricas. Ponerla en medio, con el mismo aspecto que
 * `FACT_VENTAS`, haría pensar que existe un origen con ese nombre.
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
