/**
 * Todas las relaciones del modelo en una tabla.
 *
 * El lienzo enseña la forma —qué cuelga de qué— y para eso no tiene sustituto.
 * Pero para **revisar** cuarenta relaciones es malo: hay que ir nodo por nodo,
 * pulsar cada arista, leer el inspector y volver. Lo que uno quiere saber es de
 * un vistazo y comparando: cuáles apuntan a algo que no es clave primaria,
 * cuáles unen un entero contra un texto, cuál de las tres que van al calendario
 * está activa.
 *
 * Así que aquí está todo junto y editable en el sitio, ordenable por cualquier
 * columna, con los avisos calculados por fila. Y con una línea para crear una
 * relación escribiendo, que es la otra mitad de la queja: arrastrar de columna a
 * columna entre dos nodos que ni siquiera caben juntos en la pantalla.
 *
 * No hay estado propio: cada cambio se despacha al borrador, igual que el lienzo.
 */

import { useMemo, useState } from 'react'

import type { Cardinalidad, Definicion, DireccionFiltro } from '../api/tipos'
import { Combo, type OpcionCombo } from '../comunes/Combo'
import { Th } from '../comunes/Th'
import { useOrden } from '../comunes/orden'
import {
  ETIQUETA_CARDINALIDAD,
  type Accion,
  cardinalidadProbable,
  marcarUnica,
  sinClave,
} from './estado'

const CARDINALIDADES: Cardinalidad[] = ['muchos_a_uno', 'uno_a_uno', 'muchos_a_muchos']

/**
 * Separador para la clave «par de tablas». Un carácter que no puede aparecer en
 * el nombre de una tabla, para que `a|b` y `a` + `|b` no acaben en la misma
 * casilla del contador.
 */
const SEP = '\u0000'

/** Lo que se pinta en cada fila: la relación más lo que hay que decir de ella. */
interface Fila {
  indice: number
  desdeEntidad: string
  desdeCampo: string
  hastaEntidad: string
  hastaCampo: string
  cardinalidad: Cardinalidad
  direccion: DireccionFiltro
  activa: boolean
  /** Vacío si no hay nada que decir. El orden es de peor a menos malo. */
  avisos: string[]
  /**
   * El destino no declara clave primaria y por eso hay aviso. Se guarda aparte
   * porque tiene arreglo de un clic, y un aviso que se puede resolver ahí mismo
   * vale más que uno que solo informa.
   */
  faltaClave: boolean
}

export function PanelRelaciones({
  definicion,
  despachar,
  seleccionada,
  alSeleccionar,
}: {
  definicion: Definicion
  despachar: (a: Accion) => void
  seleccionada: number | null
  alSeleccionar: (indice: number) => void
}) {
  const filas = useMemo<Fila[]>(
    () => definicion.relaciones.map((r, i) => {
      const destino = definicion.entidades.find((e) => e.nombre === r.hasta[0])
      const tipoDe = (ent: string, campo: string) =>
        definicion.entidades
          .find((e) => e.nombre === ent)?.campos
          .find((c) => c.nombre === campo)?.tipo
      const tDesde = tipoDe(r.desde[0], r.desde[1])
      const tHasta = tipoDe(r.hasta[0], r.hasta[1])

      const avisos: string[] = []
      // Falta la columna: la relación apunta a algo que ya no está. Va primero
      // porque no es un riesgo, es una unión que no compila.
      if (!tDesde) avisos.push(`${r.desde[1]} ya no existe en ${r.desde[0]}`)
      if (!tHasta) avisos.push(`${r.hasta[1]} ya no existe en ${r.hasta[0]}`)
      if (tDesde && tHasta && tDesde !== tHasta) {
        avisos.push(`Une ${tDesde} contra ${tHasta}: puede no casar ninguna fila`)
      }
      // Lo que importa del lado «uno» es que no se repita, y eso puede constar
      // de dos maneras: siendo la clave primaria, o estando marcada como única.
      // Una entidad tiene una sola clave primaria y suele traer varios
      // identificadores irrepetibles —el propio, el de Quiter, el del CRM—, uno
      // por cada hecho que se une contra ella.
      const campoDestino = destino?.campos.find((c) => c.nombre === r.hasta[1])
      const consta =
        destino?.clave_primaria === r.hasta[1] || campoDestino?.unico === true
      const faltaClave = r.cardinalidad === 'muchos_a_uno' && !consta
      if (faltaClave) {
        avisos.push(`No consta que ${r.hasta[1]} sea única en ${r.hasta[0]}: si `
          + 'se repite, esta unión infla los totales')
      }
      if (r.cardinalidad === 'muchos_a_muchos') {
        avisos.push('Muchos a muchos: multiplica filas al agregar')
      }
      return {
        indice: i,
        desdeEntidad: r.desde[0],
        desdeCampo: r.desde[1],
        hastaEntidad: r.hasta[0],
        hastaCampo: r.hasta[1],
        cardinalidad: r.cardinalidad,
        direccion: r.direccion_filtro,
        activa: r.activa !== false,
        avisos,
        faltaClave: !!faltaClave && !!tHasta,
      }
    }),
    [definicion],
  )

  const orden = useOrden<Fila>(filas, (f, c) => {
    switch (c) {
      case 'desde': return f.desdeEntidad
      case 'desdeCampo': return f.desdeCampo
      case 'hasta': return f.hastaEntidad
      case 'hastaCampo': return f.hastaCampo
      case 'cardinalidad': return ETIQUETA_CARDINALIDAD[f.cardinalidad]
      case 'direccion': return f.direccion
      case 'activa': return f.activa
      // Por número de avisos y no por su texto: ordenar por esta columna es
      // pedir «enséñame primero lo que está mal».
      case 'avisos': return -f.avisos.length
      default: return null
    }
  })

  /** Cuántas activas hay por par de tablas. Con dos, el modelo no se guarda. */
  const activasPorPar = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of definicion.relaciones) {
      if (r.activa === false) continue
      const par = [r.desde[0], r.hasta[0]].sort().join(SEP)
      m.set(par, (m.get(par) ?? 0) + 1)
    }
    return m
  }, [definicion.relaciones])

  const conflictiva = (f: Fila) =>
    f.activa && (activasPorPar.get([f.desdeEntidad, f.hastaEntidad].sort().join(SEP)) ?? 0) > 1

  const camposDe = (entidad: string): OpcionCombo[] =>
    (definicion.entidades.find((e) => e.nombre === entidad)?.campos ?? []).map((c) => ({
      valor: c.nombre,
      etiqueta: c.nombre,
      detalle: [
        c.tipo,
        definicion.entidades.find((e) => e.nombre === entidad)?.clave_primaria === c.nombre
          ? 'clave primaria'
          : null,
      ].filter(Boolean).join(' · '),
    }))

  const entidades: OpcionCombo[] = definicion.entidades.map((e) => ({
    valor: e.nombre,
    etiqueta: e.nombre,
    detalle: e.tipo,
  }))

  return (
    <div className="relaciones-vista">
      <NuevaRelacion
        definicion={definicion}
        entidades={entidades}
        camposDe={camposDe}
        despachar={despachar}
        alSeleccionar={alSeleccionar}
      />

      {filas.length === 0 ? (
        <div className="vacio">
          Todavía no hay relaciones. Créalas arriba, o arrastrando de columna a
          columna en el lienzo.
        </div>
      ) : (
        <div className="tabla-envoltura">
          <table className="datos relaciones">
            <thead>
              <tr>
                <Th orden={orden} clave="desde">Desde</Th>
                <Th orden={orden} clave="desdeCampo">Columna</Th>
                <Th orden={orden} clave="hasta">Hasta</Th>
                <Th orden={orden} clave="hastaCampo">Columna</Th>
                <Th orden={orden} clave="cardinalidad">Cardinalidad</Th>
                <Th orden={orden} clave="direccion">Filtro</Th>
                <Th orden={orden} clave="activa">Estado</Th>
                <Th orden={orden} clave="avisos" titulo="Ordenar dejando arriba lo que hay que revisar">
                  Avisos
                </Th>
                <th />
              </tr>
            </thead>
            <tbody>
              {orden.filas.map((f) => (
                <tr
                  key={f.indice}
                  className={[
                    seleccionada === f.indice && 'sel',
                    !f.activa && 'inactiva',
                    conflictiva(f) && 'conflicto',
                  ].filter(Boolean).join(' ')}
                  onClick={() => alSeleccionar(f.indice)}
                >
                  <td className="mono" title={f.desdeEntidad}>{f.desdeEntidad}</td>
                  <td>
                    <select
                      className="mono"
                      value={f.desdeCampo}
                      onChange={(e) =>
                        despachar({
                          t: 'cambiar_relacion',
                          indice: f.indice,
                          cambios: { desde: [f.desdeEntidad, e.target.value] },
                        })
                      }
                    >
                      <Opciones
                        definicion={definicion}
                        entidad={f.desdeEntidad}
                        actual={f.desdeCampo}
                      />
                    </select>
                  </td>
                  <td className="mono" title={f.hastaEntidad}>{f.hastaEntidad}</td>
                  <td>
                    <select
                      className="mono"
                      value={f.hastaCampo}
                      onChange={(e) =>
                        despachar({
                          t: 'cambiar_relacion',
                          indice: f.indice,
                          cambios: { hasta: [f.hastaEntidad, e.target.value] },
                        })
                      }
                    >
                      <Opciones
                        definicion={definicion}
                        entidad={f.hastaEntidad}
                        actual={f.hastaCampo}
                      />
                    </select>
                  </td>
                  <td>
                    <select
                      value={f.cardinalidad}
                      onChange={(e) =>
                        despachar({
                          t: 'cambiar_relacion',
                          indice: f.indice,
                          cambios: { cardinalidad: e.target.value as Cardinalidad },
                        })
                      }
                    >
                      {CARDINALIDADES.map((c) => (
                        <option key={c} value={c}>{ETIQUETA_CARDINALIDAD[c]}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      value={f.direccion}
                      onChange={(e) =>
                        despachar({
                          t: 'cambiar_relacion',
                          indice: f.indice,
                          cambios: { direccion_filtro: e.target.value as DireccionFiltro },
                        })
                      }
                    >
                      <option value="ambas">ambas</option>
                      <option value="una">una</option>
                    </select>
                  </td>
                  <td>
                    {/* Una casilla y no un desplegable: con tres fechas contra el
                        calendario, cambiar cuál manda son dos clics seguidos y hay
                        que poder verlos todos a la vez. */}
                    <label className="estado-relacion">
                      <input
                        type="checkbox"
                        checked={f.activa}
                        onChange={(e) =>
                          despachar({
                            t: 'cambiar_relacion',
                            indice: f.indice,
                            cambios: { activa: e.target.checked },
                          })
                        }
                      />
                      {f.activa ? 'activa' : 'inactiva'}
                    </label>
                  </td>
                  <td className="avisos-celda">
                    {conflictiva(f) && (
                      <div className="aviso-fila critico">
                        Otra relación entre estas dos tablas también está activa.
                        Sólo una puede estarlo: el modelo no se guardará así.
                      </div>
                    )}
                    {f.avisos.map((a) => (
                      <div className="aviso-fila" key={a}>{a}</div>
                    ))}
                    {/* El aviso más común tiene arreglo de un clic y casi siempre
                        es el correcto: la columna SÍ es única, simplemente nadie
                        la declaró al traer la tabla. Decirlo sin poder resolverlo
                        obliga a ir a la entidad, buscar el campo y volver. */}
                    {f.faltaClave && (
                      <button
                        className="btn chico"
                        style={{ marginTop: 4 }}
                        title={`Dice que ${f.hastaCampo} no se repite en `
                          + `${f.hastaEntidad}. Es lo que la relación necesita.`}
                        onClick={(e) => {
                          e.stopPropagation()
                          marcarUnica(definicion, f.hastaEntidad, f.hastaCampo,
                                      despachar)
                        }}
                      >
                        {sinClave(definicion, f.hastaEntidad)
                          ? 'Declararla clave primaria'
                          : 'Marcarla como única'}
                      </button>
                    )}
                    {!conflictiva(f) && f.avisos.length === 0 && (
                      <span className="tenue chico">—</span>
                    )}
                  </td>
                  <td>
                    <button
                      className="btn chico peligro"
                      title="Quitar esta relación"
                      onClick={(e) => {
                        e.stopPropagation()
                        despachar({ t: 'quitar_relacion', indice: f.indice })
                      }}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/**
 * Las columnas de una entidad como `<option>`.
 *
 * Salen todas y no sólo las claves: en una tabla que llega de un origen ajeno, la
 * columna por la que de verdad se une casi nunca está declarada como clave. Y si
 * la relación apunta a una que ya no está, se deja visible en vez de saltar sola
 * a otra: cambiar la unión sin que nadie lo pida es peor que enseñar el roto.
 */
function Opciones({
  definicion,
  entidad,
  actual,
}: {
  definicion: Definicion
  entidad: string
  actual: string
}) {
  const e = definicion.entidades.find((x) => x.nombre === entidad)
  return (
    <>
      {!e?.campos.some((c) => c.nombre === actual) && (
        <option value={actual}>{actual} (ya no existe)</option>
      )}
      {e?.campos.map((c) => (
        <option key={c.nombre} value={c.nombre}>
          {c.nombre}
          {c.nombre === e.clave_primaria ? ' · clave primaria' : ''}
        </option>
      ))}
    </>
  )
}

/**
 * Crear una relación escribiendo los cuatro datos.
 *
 * Es lo mismo que arrastrar en el lienzo, pero sin depender de que las dos tablas
 * quepan juntas en la pantalla: con veinte entidades, la que se busca casi nunca
 * está al lado de la otra.
 */
function NuevaRelacion({
  definicion,
  entidades,
  camposDe,
  despachar,
  alSeleccionar,
}: {
  definicion: Definicion
  entidades: OpcionCombo[]
  camposDe: (entidad: string) => OpcionCombo[]
  despachar: (a: Accion) => void
  alSeleccionar: (indice: number) => void
}) {
  const [de, setDe] = useState('')
  const [deCampo, setDeCampo] = useState('')
  const [a, setA] = useState('')
  const [aCampo, setACampo] = useState('')
  /**
   * `null` mientras nadie la haya tocado: entonces manda la sugerencia y se
   * recalcula al cambiar de columna. En cuanto se elige a mano, se respeta.
   *
   * Antes no se preguntaba: se adivinaba y se guardaba lo adivinado. Y adivina
   * mal muy a menudo, porque solo puede decir muchos-a-uno si la columna destino
   * está DECLARADA clave primaria, cosa que casi ninguna tabla traída de un
   * origen ajeno trae. El resultado era relación tras relación naciendo
   * muchos-a-muchos —que multiplica filas al agregar— sin que nadie lo pidiera.
   */
  const [cardinalidad, setCardinalidad] = useState<Cardinalidad | null>(null)

  const destino = definicion.entidades.find((e) => e.nombre === a)
  const esClave = !!destino
    && (destino.clave_primaria === aCampo
      || destino.campos.find((c) => c.nombre === aCampo)?.unico === true)
  const sugerida: Cardinalidad =
    a && aCampo ? cardinalidadProbable(definicion.entidades, a, aCampo) : 'muchos_a_uno'
  const elegida = cardinalidad ?? sugerida

  const completa = de && deCampo && a && aCampo && de !== a
  // La misma unión dos veces no aporta nada y ensucia el diagnóstico.
  const repetida = definicion.relaciones.some(
    (r) =>
      (r.desde[0] === de && r.desde[1] === deCampo && r.hasta[0] === a && r.hasta[1] === aCampo) ||
      (r.desde[0] === a && r.desde[1] === aCampo && r.hasta[0] === de && r.hasta[1] === deCampo),
  )

  return (
    <div className="nueva-relacion">
      <span className="chico tenue">Nueva relación</span>

      <div className="campo-en-linea">
        <Combo
          opciones={entidades}
          valor={de || null}
          alElegir={(v) => { setDe(v); setDeCampo('') }}
          marcador="Tabla…"
        />
        <Combo
          opciones={de ? camposDe(de) : []}
          valor={deCampo || null}
          alElegir={setDeCampo}
          marcador="Columna…"
          vacio="Elige antes la tabla."
        />
      </div>

      <span className="tenue mono">→</span>

      <div className="campo-en-linea">
        <Combo
          opciones={entidades.filter((e) => e.valor !== de)}
          valor={a || null}
          alElegir={(v) => { setA(v); setACampo(''); setCardinalidad(null) }}
          marcador="Tabla…"
        />
        <Combo
          opciones={a ? camposDe(a) : []}
          valor={aCampo || null}
          alElegir={(v) => { setACampo(v); setCardinalidad(null) }}
          marcador="Columna…"
          vacio="Elige antes la tabla."
        />
      </div>

      {/* Se pregunta, no se adivina. La sugerencia sigue ahí —marcada— porque
          acierta cuando la clave primaria está declarada, pero es una propuesta
          y no una decisión tomada a espaldas de nadie. */}
      <select
        value={elegida}
        aria-label="Cardinalidad de la relación nueva"
        onChange={(e) => setCardinalidad(e.target.value as Cardinalidad)}
      >
        {CARDINALIDADES.map((c) => (
          <option key={c} value={c}>
            {ETIQUETA_CARDINALIDAD[c]}
            {c === sugerida ? ' · sugerida' : ''}
          </option>
        ))}
      </select>

      <button
        className="btn primario"
        disabled={!completa || repetida}
        title={repetida ? 'Esa unión ya está en el modelo' : undefined}
        onClick={() => {
          despachar({
            t: 'agregar_relacion',
            desde: [de, deCampo],
            hasta: [a, aCampo],
            cardinalidad: elegida,
          })
          alSeleccionar(definicion.relaciones.length)
          setDeCampo('')
          setACampo('')
          setCardinalidad(null)
        }}
      >
        Agregar
      </button>

      {repetida && (
        <span className="chico tenue">Esa unión ya está en el modelo.</span>
      )}

      {/* Por qué se sugiere lo que se sugiere, y el atajo para que la sugerencia
          sea la buena. Sin esto, «muchos ↔ muchos» aparece sin explicación y hay
          que saberse la regla para entender de dónde salió. */}
      {a && aCampo && !esClave && (
        <span className="chico tenue" style={{ flexBasis: '100%' }}>
          No consta que <b className="mono">{aCampo}</b> sea única en{' '}
          <b className="mono">{a}</b> —ni es su clave primaria ni está marcada
          como única—, así que la sugerencia es la prudente. Si de verdad no se
          repite:{' '}
          <button
            className="btn chico"
            onClick={() => marcarUnica(definicion, a, aCampo, despachar)}
          >
            {sinClave(definicion, a) ? 'declararla clave primaria' : 'marcarla como única'}
          </button>
        </span>
      )}
    </div>
  )
}
