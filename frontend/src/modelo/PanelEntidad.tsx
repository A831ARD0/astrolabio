/**
 * Inspector de una entidad: su tipo, su clave, su grano y el rol de cada campo.
 *
 * El rol no es una etiqueta descriptiva: decide qué puede hacer el campo. Una
 * `medida_base` se puede sumar dentro de una métrica; una `dimension` sirve para
 * agrupar; una `clave_externa` es por donde pasa un join. Cambiarlo cambia lo que
 * el modelo permite, así que se edita aquí, a la vista, y no en un YAML aparte.
 */

import { useState } from 'react'

import type { Campo, Entidad, RolCampo, TipoEntidad } from '../api/tipos'
import { useTabla } from '../api/hooks'
import { ETIQUETA_ROL, type Accion, resincronizar } from './estado'
import { useOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'

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

  // Las columnas que tiene el origen AHORA MISMO, para poder compararlas con la
  // copia que guarda la entidad. Se pide siempre: es una consulta cacheada por
  // TanStack y saber que hay desfase importa antes de que alguien lo pregunte.
  const origen = useTabla(entidad.origen.tabla)
  const [resultado, setResultado] = useState<string | null>(null)

  const enOrigen = origen.data?.columnas ?? []
  const desfase = enOrigen.length
    ? resincronizar(entidad, enOrigen)
    : null
  const hayDesfase = !!desfase
    && (desfase.retipados.length > 0 || desfase.nuevas.length > 0
      || desfase.desaparecidas.length > 0)

  const orden = useOrden(entidad.campos, (c, clave) =>
    clave === 'nombre' ? c.nombre
    : clave === 'tipo' ? c.tipo
    : clave === 'rol' ? c.rol
    : clave === 'ver' ? c.visible !== false
    : c.pii === true)

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
            {orden.filas.map((c) => (
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

      {/*
        El desfase con el origen se avisa solo. Es el fallo que no se ve: la
        transformación se cambia, el modelo sigue con la copia vieja y lo único
        que se nota es un tipo raro en una tabla de catorce campos.
      */}
      {hayDesfase && (
        <div className="aviso-caja">
          <b className="mono">{entidad.origen.tabla}</b> ya no es como se leyó al
          agregarla:
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {desfase!.retipados.length > 0 && (
              <li>
                cambió el tipo de {desfase!.retipados.length}:{' '}
                <span className="mono">{desfase!.retipados.join(', ')}</span>
              </li>
            )}
            {desfase!.nuevas.length > 0 && (
              <li>
                {desfase!.nuevas.length} columna(s) nueva(s):{' '}
                <span className="mono">{desfase!.nuevas.join(', ')}</span>
              </li>
            )}
            {desfase!.desaparecidas.length > 0 && (
              <li>
                ya no está(n):{' '}
                <span className="mono">{desfase!.desaparecidas.join(', ')}</span>
                {' '}— no se quitan solas por si alguna relación o métrica las usa.
              </li>
            )}
          </ul>
          <div style={{ marginTop: 8 }}>
            <button
              className="btn chico"
              onClick={() => {
                // El rol, la etiqueta, «ver» y «PII» se conservan: son trabajo
                // hecho a mano y volver a adivinarlos sería tirarlo.
                cambiar({ campos: desfase!.campos })
                setResultado(
                  `${desfase!.retipados.length} tipo(s) al día, `
                  + `${desfase!.nuevas.length} columna(s) agregada(s).`,
                )
              }}
            >
              Actualizar columnas desde el origen
            </button>
          </div>
        </div>
      )}
      {resultado && !hayDesfase && (
        <div className="chico tenue">{resultado} Los roles se conservaron.</div>
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
              <Th orden={orden} clave="nombre">campo</Th>
              <Th orden={orden} clave="tipo">tipo</Th>
              <Th orden={orden} clave="rol">rol</Th>
              <Th orden={orden} clave="ver" titulo="Visible en la interfaz para quien explora">
                ver
              </Th>
              <Th orden={orden} clave="pii" titulo="Dato personal">PII</Th>
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
