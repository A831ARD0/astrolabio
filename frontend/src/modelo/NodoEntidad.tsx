/**
 * Una entidad en el lienzo.
 *
 * Cada campo lleva su propio conector a los dos lados. Es lo que permite crear
 * una relación arrastrando de columna a columna, en vez de unir dos cajas y
 * luego elegir campos en un formulario: la relación es entre columnas, y la
 * interfaz debería decir eso.
 *
 * Los hechos y las dimensiones se ven distintos a propósito. No es decoración:
 * de esa diferencia dependen las reglas de agregación del motor —un hecho es
 * terminal, nunca puente—, así que quien mira el lienzo tiene que poder
 * distinguirlos de un vistazo.
 *
 * La lista de campos **no se recorta**. Antes tenía un alto máximo con barra de
 * desplazamiento por dentro, y eso rompía las dos cosas para las que sirve el
 * nodo:
 *
 *   - Un catálogo de veintidós columnas mostraba diez. Las otras doce no se
 *     podían ni ver ni agarrar, así que la relación que iba por una de ellas no
 *     se podía crear arrastrando — y arrastrar es la forma de crearla. Peor
 *     todavía: la rueda del ratón dentro del nodo la caza el lienzo para hacer
 *     zoom, así que la lista tampoco se desplazaba.
 *   - Un conector de un campo recortado sigue existiendo, pero queda fuera de la
 *     caja visible. La línea de esa relación nacía de un punto donde no hay nada.
 *
 * Para que un catálogo largo no se coma el lienzo está el botón de la cabecera,
 * que lo deja en **solo los campos unidos** —los de sus relaciones y su clave—.
 * En los dos estados todo conector que existe se ve, que es la propiedad que
 * hacía falta.
 */

import { Handle, Position } from '@xyflow/react'
import { memo } from 'react'

import type { Entidad } from '../api/tipos'
import { ETIQUETA_ROL } from './estado'

export interface DatosNodo extends Record<string, unknown> {
  entidad: Entidad
  seleccionada: boolean
  /** La menciona un problema crítico: se marca discretamente, con un aviso. */
  conProblema: boolean
  /** El usuario está inspeccionando un problema que la incluye: se enmarca. */
  resaltada: boolean
  huerfana: boolean
  camposEnRelacion: Set<string>
  /** Solo se listan los campos unidos. Es una preferencia de la vista, no del modelo. */
  compacta: boolean
  alCompactar: (entidad: string, compacta: boolean) => void
}

export const NodoEntidad = memo(function NodoEntidad({ data }: { data: DatosNodo }) {
  const {
    entidad,
    seleccionada,
    conProblema,
    resaltada,
    huerfana,
    camposEnRelacion,
    compacta,
    alCompactar,
  } = data

  // Los campos que sostienen algo: los de sus relaciones y la clave primaria. Son
  // los que hay que ver para entender cómo se une esta tabla, y los únicos cuyo
  // conector tiene que seguir estando cuando la tabla se compacta.
  const unidos = entidad.campos.filter(
    (c) => camposEnRelacion.has(c.nombre) || c.nombre === entidad.clave_primaria,
  )
  // Compactar solo tiene sentido si esconde algo y deja algo. Con dos campos, o
  // con todos unidos, el botón haría un cambio invisible o dejaría la tabla vacía.
  const sePuedeCompactar = unidos.length > 0 && unidos.length < entidad.campos.length
  const encogida = compacta && sePuedeCompactar
  const campos = encogida ? unidos : entidad.campos
  // El marco rojo se reserva para lo que el usuario está inspeccionando. Si se
  // pintaran de rojo todas las entidades que aparecen en algún problema, media
  // pantalla sería roja y el color dejaría de señalar nada.
  const clases = [
    'nodo',
    `tipo-${entidad.tipo}`,
    seleccionada && 'sel',
    resaltada && 'problema',
    huerfana && 'huerfana',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={clases}>
      <header>
        <span className={`punto ${entidad.tipo}`} />
        {entidad.nombre}
        {conProblema && (
          <span className="aviso-nodo" title="Aparece en un problema crítico del modelo">
            !
          </span>
        )}
        <span className="tabla">{entidad.origen.tabla}</span>
        {sePuedeCompactar && (
          // `nodrag` para que pulsarlo no arrastre la tabla, y `nopan` para que el
          // clic no se lo lleve el lienzo por debajo.
          <button
            className="plegar-campos nodrag nopan"
            onClick={(e) => {
              e.stopPropagation()
              alCompactar(entidad.nombre, !compacta)
            }}
            title={
              encogida
                ? `Ver los ${entidad.campos.length} campos, para unir por cualquiera`
                : `Dejar solo los ${unidos.length} campos unidos y esconder los otros ` +
                  `${entidad.campos.length - unidos.length}`
            }
          >
            {encogida ? `+${entidad.campos.length - unidos.length}` : '−'}
          </button>
        )}
      </header>

      <ul>
        {campos.map((c) => (
          <li key={c.nombre} className={c.rol}>
            {/* Un conector por campo y por lado: así se puede arrastrar hacia
                cualquier dirección sin pensar en cuál está a la izquierda.

                El tamaño va en el CSS y a propósito no es el del punto que se
                ve: la zona que agarra el ratón ocupa el alto entero de la fila.
                Apuntar a un círculo de ocho píxeles en una lista de treinta
                columnas era la parte difícil de relacionar dos tablas. */}
            <Handle type="target" position={Position.Left} id={c.nombre} />
            <span>{c.nombre}</span>
            {c.pii && <span className="pii" title="Dato personal">PII</span>}
            <span className="rol">
              {camposEnRelacion.has(c.nombre) ? '⇄ ' : ''}
              {ETIQUETA_ROL[c.rol]}
            </span>
            <Handle type="source" position={Position.Right} id={c.nombre} />
          </li>
        ))}
      </ul>

      {entidad.tipo === 'hecho' && entidad.grano && entidad.grano.length > 0 && (
        <footer>grano: {entidad.grano.join(', ')}</footer>
      )}
    </div>
  )
})
