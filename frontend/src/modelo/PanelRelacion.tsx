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

  const tipoDe = (entidad: string, campo: string) =>
    definicion.entidades
      .find((e) => e.nombre === entidad)
      ?.campos.find((c) => c.nombre === campo)?.tipo
  const tipoDesde = tipoDe(r.desde[0], r.desde[1])
  const tipoHasta = tipoDe(r.hasta[0], r.hasta[1])
  // Unir un entero contra un texto compila y devuelve cero filas, sin queja.
  // Avisar aquí es la diferencia entre eso y una tarde buscando el fallo.
  const tiposDistintos = !!tipoDesde && !!tipoHasta && tipoDesde !== tipoHasta

  return (
    <div className="inspector">
      <h3>Relación</h3>

      {/*
        Las columnas se eligen aquí y no sólo arrastrando en el lienzo. Dos
        tablas que se relacionan casi nunca llaman igual a su clave —ID_Sucursal
        contra ID_Quiter— y acertar la tabla y fallar la columna es el error
        corriente. Sin esto había que quitar la relación y volver a hacerla.
      */}
      <div className="campo">
        <label>Une esta columna</label>
        <ElegirColumna
          definicion={definicion}
          entidad={r.desde[0]}
          campo={r.desde[1]}
          alElegir={(campo) =>
            despachar({ t: 'cambiar_relacion', indice, cambios: { desde: [r.desde[0], campo] } })
          }
        />
      </div>

      <div className="tenue mono" style={{ textAlign: 'center' }}>↓</div>

      <div className="campo">
        <label>con esta</label>
        <ElegirColumna
          definicion={definicion}
          entidad={r.hasta[0]}
          campo={r.hasta[1]}
          alElegir={(campo) =>
            despachar({ t: 'cambiar_relacion', indice, cambios: { hasta: [r.hasta[0], campo] } })
          }
        />
      </div>

      {tiposDistintos && (
        <div className="aviso-caja">
          Las dos columnas no son del mismo tipo (<b>{tipoDesde}</b> contra{' '}
          <b>{tipoHasta}</b>). La unión puede no encontrar ninguna coincidencia
          aunque los valores se parezcan al leerlos.
        </div>
      )}

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

/**
 * Un desplegable con las columnas de una entidad.
 *
 * Salen todas y no sólo las claves: en una tabla que llega de un origen ajeno,
 * la columna por la que de verdad se une casi nunca está declarada como clave.
 * Las que sí lo son se marcan, para que la buena sea la fácil de encontrar.
 */
function ElegirColumna({
  definicion,
  entidad,
  campo,
  alElegir,
}: {
  definicion: Definicion
  entidad: string
  campo: string
  alElegir: (campo: string) => void
}) {
  const e = definicion.entidades.find((x) => x.nombre === entidad)
  return (
    <>
      <div className="mono chico tenue">{entidad}</div>
      <select className="mono" value={campo} onChange={(ev) => alElegir(ev.target.value)}>
        {/* Si la relación apunta a una columna que ya no está —renombrada en el
            origen, por ejemplo— se deja visible en vez de saltar sola a otra:
            cambiar la unión sin que nadie lo pida es peor que enseñar el roto. */}
        {!e?.campos.some((c) => c.nombre === campo) && (
          <option value={campo}>{campo} (ya no existe)</option>
        )}
        {e?.campos.map((c) => (
          <option key={c.nombre} value={c.nombre}>
            {c.nombre}
            {c.nombre === e.clave_primaria ? ' · clave primaria' : ''}
            {c.rol === 'clave_externa' ? ' · clave externa' : ''}
          </option>
        ))}
      </select>
    </>
  )
}
