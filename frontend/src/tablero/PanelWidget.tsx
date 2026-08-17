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

const TIPOS: { valor: TipoWidget; etiqueta: string }[] = [
  { valor: 'kpi', etiqueta: 'KPI — una cifra grande' },
  { valor: 'barras', etiqueta: 'Barras verticales' },
  { valor: 'barras_horizontales', etiqueta: 'Barras horizontales' },
  { valor: 'lineas', etiqueta: 'Líneas' },
  { valor: 'area', etiqueta: 'Área' },
  { valor: 'pastel', etiqueta: 'Pastel' },
  { valor: 'tabla', etiqueta: 'Tabla' },
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
        <Seleccionables
          titulo={`Métricas${widget.metricas?.length ? ` (${widget.metricas.length})` : ''}`}
          items={metricas.map((m) => ({ clave: m.clave, etiqueta: m.etiqueta,
                                        nota: m.entidad }))}
          elegidos={widget.metricas ?? []}
          alAlternar={alternarMet}
          vacio="El modelo no tiene métricas todavía."
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
