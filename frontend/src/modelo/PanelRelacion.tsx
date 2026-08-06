/**
 * Inspector de una relación.
 *
 * Las dos propiedades que aquí se editan son las que deciden si una cifra sale
 * bien, así que van explicadas en la propia interfaz y no en un manual:
 *
 * - **Cardinalidad.** Al agregar, cada salto debe ir del lado "muchos" al lado
 *   "uno". Un muchos-a-muchos multiplica filas y el total sale inflado.
 * - **Dirección del filtro.** Decide si una selección se propaga en los dos
 *   sentidos o solo en uno.
 */

import type { Cardinalidad, DireccionFiltro, Definicion } from '../api/tipos'
import { ETIQUETA_CARDINALIDAD, type Accion } from './estado'

const CARDINALIDADES: Cardinalidad[] = ['muchos_a_uno', 'uno_a_uno', 'muchos_a_muchos']

export function PanelRelacion({
  definicion,
  indice,
  despachar,
}: {
  definicion: Definicion
  indice: number
  despachar: (a: Accion) => void
}) {
  const r = definicion.relaciones[indice]
  if (!r) return <div className="vacio">Esa relación ya no existe.</div>

  const destino = definicion.entidades.find((e) => e.nombre === r.hasta[0])
  const apuntaAClave = destino?.clave_primaria === r.hasta[1]

  return (
    <div className="inspector">
      <h3>Relación</h3>

      <div className="mono chico">
        {r.desde[0]}.<b>{r.desde[1]}</b>
        <div className="tenue" style={{ padding: '2px 0' }}>↓</div>
        {r.hasta[0]}.<b>{r.hasta[1]}</b>
      </div>

      <div className="campo">
        <label>Cardinalidad</label>
        <select
          value={r.cardinalidad}
          onChange={(e) =>
            despachar({
              t: 'cambiar_relacion',
              indice,
              cambios: { cardinalidad: e.target.value as Cardinalidad },
            })
          }
        >
          {CARDINALIDADES.map((c) => (
            <option key={c} value={c}>
              {ETIQUETA_CARDINALIDAD[c]}
            </option>
          ))}
        </select>
      </div>

      {r.cardinalidad === 'muchos_a_uno' && !apuntaAClave && (
        <div className="aviso-caja">
          <b>{r.hasta[1]}</b> no es la clave primaria de <b>{r.hasta[0]}</b>. Si
          tiene valores repetidos, esta relación duplicará filas al agregar y los
          totales saldrán inflados. Declárala como clave primaria si de verdad es
          única.
        </div>
      )}

      {r.cardinalidad === 'muchos_a_muchos' && (
        <div className="aviso-caja">
          Muchos-a-muchos multiplica filas al agregar. Sirve para propagar
          selecciones, pero cualquier suma que la cruce hay que revisarla.
        </div>
      )}

      <div className="campo">
        <label>Dirección del filtro</label>
        <select
          value={r.direccion_filtro}
          onChange={(e) =>
            despachar({
              t: 'cambiar_relacion',
              indice,
              cambios: { direccion_filtro: e.target.value as DireccionFiltro },
            })
          }
        >
          <option value="ambas">ambas — una selección se propaga en los dos sentidos</option>
          <option value="una">una — solo desde el lado "uno" hacia el lado "muchos"</option>
        </select>
      </div>

      <button
        className="btn peligro"
        onClick={() => despachar({ t: 'quitar_relacion', indice })}
      >
        Quitar relación
      </button>
    </div>
  )
}
