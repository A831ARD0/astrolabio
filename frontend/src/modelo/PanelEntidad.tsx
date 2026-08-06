/**
 * Inspector de una entidad: su tipo, su clave, su grano y el rol de cada campo.
 *
 * El rol no es una etiqueta descriptiva: decide qué puede hacer el campo. Una
 * `medida_base` se puede sumar dentro de una métrica; una `dimension` sirve para
 * agrupar; una `clave_externa` es por donde pasa un join. Cambiarlo cambia lo que
 * el modelo permite, así que se edita aquí, a la vista, y no en un YAML aparte.
 */

import type { Campo, Entidad, RolCampo, TipoEntidad } from '../api/tipos'
import { ETIQUETA_ROL, type Accion } from './estado'

const ROLES: RolCampo[] = ['clave', 'clave_externa', 'dimension', 'medida_base']

export function PanelEntidad({
  entidad,
  despachar,
  enRelaciones,
}: {
  entidad: Entidad
  despachar: (a: Accion) => void
  /** Cuántas relaciones la usan: borrarla se las lleva. */
  enRelaciones: number
}) {
  const cambiar = (cambios: Partial<Entidad>) =>
    despachar({ t: 'cambiar_entidad', nombre: entidad.nombre, cambios })

  const cambiarCampo = (campo: string, cambios: Partial<Campo>) =>
    despachar({ t: 'cambiar_campo', entidad: entidad.nombre, campo, cambios })

  function quitar() {
    const aviso =
      enRelaciones > 0
        ? `Se quitará '${entidad.nombre}' y con ella ${enRelaciones} relación(es) y sus métricas. ¿Continuar?`
        : `¿Quitar '${entidad.nombre}' del modelo?`
    if (confirm(aviso)) despachar({ t: 'quitar_entidad', nombre: entidad.nombre })
  }

  return (
    <div className="inspector">
      <h3>
        <span className={`punto ${entidad.tipo}`} />
        {entidad.nombre}
      </h3>
      <div className="chico tenue mono">tabla: {entidad.origen.tabla}</div>

      <div className="fila">
        <div className="campo">
          <label>Tipo</label>
          <select
            value={entidad.tipo}
            onChange={(e) => cambiar({ tipo: e.target.value as TipoEntidad })}
          >
            <option value="dimension">dimensión</option>
            <option value="hecho">hecho</option>
          </select>
        </div>
        <div className="campo">
          <label>Clave primaria</label>
          <select
            value={entidad.clave_primaria ?? ''}
            onChange={(e) => cambiar({ clave_primaria: e.target.value || null })}
          >
            <option value="">(ninguna)</option>
            {entidad.campos.map((c) => (
              <option key={c.nombre} value={c.nombre}>
                {c.nombre}
              </option>
            ))}
          </select>
        </div>
      </div>

      {entidad.tipo === 'hecho' && (
        <div className="campo">
          <label>Grano — qué identifica una fila</label>
          <input
            type="text"
            className="mono"
            value={(entidad.grano ?? []).join(', ')}
            placeholder="venta_id"
            onChange={(e) =>
              cambiar({
                grano: e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
          <span className="chico tenue">
            Declararlo es lo que permite detectar que una métrica se está
            duplicando al cruzarla con otra de grano distinto.
          </span>
        </div>
      )}

      <div>
        <div className="chico suave" style={{ marginBottom: 4 }}>
          Campos ({entidad.campos.length})
        </div>
        {/* El panel es angosto y la tabla no se puede comprimir más sin volverse
            ilegible: se desplaza dentro de su caja, no empuja el panel. */}
        <div style={{ overflowX: 'auto' }}>
        <table className="campos">
          <thead>
            <tr>
              <th>campo</th>
              <th>tipo</th>
              <th>rol</th>
              <th title="Visible en la interfaz para quien explora">ver</th>
              <th title="Dato personal">PII</th>
            </tr>
          </thead>
          <tbody>
            {entidad.campos.map((c) => (
              <tr key={c.nombre}>
                <td title={c.etiqueta ?? undefined}>{c.nombre}</td>
                <td className="tenue chico">{c.tipo}</td>
                <td>
                  <select
                    value={c.rol}
                    onChange={(e) =>
                      cambiarCampo(c.nombre, { rol: e.target.value as RolCampo })
                    }
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ETIQUETA_ROL[r]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={c.visible !== false}
                    onChange={(e) =>
                      cambiarCampo(c.nombre, { visible: e.target.checked })
                    }
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={!!c.pii}
                    onChange={(e) => cambiarCampo(c.nombre, { pii: e.target.checked })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      <button className="btn peligro" onClick={quitar}>
        Quitar del modelo
      </button>
    </div>
  )
}
