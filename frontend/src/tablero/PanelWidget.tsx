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
import { type Formato, type Total, totalPorOmision } from './formato'

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

/** Desde cuántos elementos vale la pena el buscador. Con menos, estorba. */
const BUSCADOR_DESDE = 8

function Seleccionables({
  titulo,
  items,
  elegidos,
  alAlternar,
  vacio,
}: {
  titulo: string
  items: { clave: string; etiqueta: string; nota: string }[]
  elegidos: string[]
  alAlternar: (clave: string) => void
  vacio: string
}) {
  const [busca, setBusca] = useState('')

  // Se busca por etiqueta, por nombre técnico y por tabla: con noventa y seis
  // métricas, un trozo del nombre es lo que uno recuerda, no el nombre exacto.
  const visibles = busca.trim()
    ? items.filter((i) => coincide(`${i.etiqueta} ${i.clave} ${i.nota}`, busca))
    : items

  // Lo ya elegido no se esconde nunca: si al buscar desapareciera de la vista,
  // no habría forma de quitarlo sin adivinar cómo se llamaba.
  const fuera = busca.trim()
    ? items.filter((i) => elegidos.includes(i.clave) && !visibles.includes(i))
    : []

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
          {visibles.length === 0 && fuera.length === 0 ? (
            <div className="chico tenue">Nada coincide con «{busca.trim()}».</div>
          ) : (
            <div className="lista">
              {[...visibles, ...fuera].map((i) => (
                <button
                  key={i.clave}
                  className={elegidos.includes(i.clave) ? 'sel' : ''}
                  onClick={() => alAlternar(i.clave)}
                  title={i.clave}
                >
                  <span className="nom">{i.etiqueta}</span>
                  <span className="dcha">{i.nota}</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
