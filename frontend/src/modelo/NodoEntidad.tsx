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
}

export const NodoEntidad = memo(function NodoEntidad({ data }: { data: DatosNodo }) {
  const { entidad, seleccionada, conProblema, resaltada, huerfana, camposEnRelacion } =
    data
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
      </header>

      <ul>
        {entidad.campos.map((c) => (
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
