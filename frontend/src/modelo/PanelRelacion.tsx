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
import { ETIQUETA_CARDINALIDAD, type Accion, marcarUnica, sinClave } from './estado'

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
  // Clave primaria O marcada como unica: lo que la relacion necesita del lado
  // «uno» es que la columna no se repita, y eso puede constar de las dos formas.
  const apuntaAClave = destino?.clave_primaria === r.hasta[1]
    || destino?.campos.find((c) => c.nombre === r.hasta[1])?.unico === true

  const tipoDe = (entidad: string, campo: string) =>
    definicion.entidades
      .find((e) => e.nombre === entidad)
      ?.campos.find((c) => c.nombre === campo)?.tipo
  const tipoDesde = tipoDe(r.desde[0], r.desde[1])
  const tipoHasta = tipoDe(r.hasta[0], r.hasta[1])
  // Unir un entero contra un texto compila y devuelve cero filas, sin queja.
  // Avisar aquí es la diferencia entre eso y una tarde buscando el fallo.
  const tiposDistintos = !!tipoDesde && !!tipoHasta && tipoDesde !== tipoHasta

  const otrasEntreLasMismas = definicion.relaciones.filter(
    (o, i) =>
      i !== indice &&
      ((o.desde[0] === r.desde[0] && o.hasta[0] === r.hasta[0]) ||
        (o.desde[0] === r.hasta[0] && o.hasta[0] === r.desde[0])),
  ).length

  return (
    <div className="inspector">
      <h3>Relación</h3>

      {/*
        Las columnas se eligen aquí y no sólo arrastrando en el lienzo. Dos
        tablas que se relacionan casi nunca llaman igual a su clave —ID_Sucursal
        contra Sucursal_Codigo— y acertar la tabla y fallar la columna es el error
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

      {/*
        Activa o no. Dos tablas se relacionan por más de una columna más a menudo
        de lo que parece —un hecho con fecha de alta, de cierre y de entrega toca
        el calendario tres veces— y las tres son ciertas. Al agregar sólo puede
        mandar una: con dos, cada consulta tendría dos caminos igual de válidos y
        el total dependería de cuál eligiera el compilador.
      */}
      <div className="campo">
        <label>Estado</label>
        <select
          value={r.activa === false ? 'inactiva' : 'activa'}
          onChange={(e) =>
            despachar({
              t: 'cambiar_relacion',
              indice,
              cambios: { activa: e.target.value === 'activa' },
            })
          }
        >
          <option value="activa">activa — por aquí se une al agregar</option>
          <option value="inactiva">
            inactiva — queda escrita, pero no se usa
          </option>
        </select>
      </div>

      {r.activa === false && (
        <div className="aviso-caja">
          No se usa por omisión: una consulta que no diga nada pasa por la
          activa. Para que una cifra concreta se una <b>por aquí</b>, ábrela y
          márcala en <b>Se une por</b> — así conviven el tráfico contado por una
          fecha y los leads contados por otra, sin tocar el resto del modelo.
        </div>
      )}

      {otrasEntreLasMismas > 0 && (
        <div className="chico tenue">
          Hay {otrasEntreLasMismas} relación(es) más entre <b>{r.desde[0]}</b> y{' '}
          <b>{r.hasta[0]}</b>. Sólo una puede estar activa.
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
          No consta que <b>{r.hasta[1]}</b> sea única en <b>{r.hasta[0]}</b>.
          Dices que muchas filas de <b>{r.desde[0]}</b> apuntan a una sola de{' '}
          <b>{r.hasta[0]}</b>, pero esa columna ni es la clave primaria ni está
          marcada como única. Si se repitiera, cada fila del origen casaría con
          varias del destino, la unión devolvería más filas de las que hay y las
          sumas saldrían infladas — sin ningún error, solo con la cifra mal.
          {/* El arreglo casi siempre es este y estaba a tres pantallas de aquí:
              ir a la entidad, buscar el campo y marcarlo. Poder resolverlo donde
              se lee el aviso es la diferencia entre corregirlo y convivir con él. */}
          <div style={{ marginTop: 8 }}>
            <button
              className="btn chico"
              onClick={() =>
                marcarUnica(definicion, r.hasta[0], r.hasta[1], despachar)
              }
            >
              {r.hasta[1]} no se repite:{' '}
              {sinClave(definicion, r.hasta[0])
                ? 'declararla clave primaria'
                : 'marcarla como única'}
            </button>
          </div>
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
