/**
 * Políticas de seguridad por fila.
 *
 * El predicado se escribe a mano y es SQL de verdad: es lo único de Astrolabio donde
 * un desplegable no alcanza, porque una política real dice cosas como
 * `region_id = {{ usuario.region_id }} OR es_corporativo`. A cambio, se valida en el
 * servidor contra el árbol sintáctico y contra los campos de la entidad, así que un
 * error se ve al guardar y no cuando alguien abre un tablero.
 *
 * Guardar crea una versión nueva del modelo. Que quede historial no es burocracia:
 * «quién podía ver qué, y desde cuándo» es la pregunta de después de un incidente.
 */

import { useEffect, useState } from 'react'

import {
  type Politica,
  type RespuestaPoliticas,
  useGuardarPoliticas,
  usePoliticas,
} from '../api/gobierno'
import { useModelos } from '../api/hooks'
import { Simulador } from './Simulador'

const VACIA: Politica = {
  nombre: '',
  entidad: '',
  predicado: '',
  aplica_a_roles: [],
  descripcion: '',
}

function EditorPolitica({
  politica,
  datos,
  alCambiar,
  alQuitar,
}: {
  politica: Politica
  datos: RespuestaPoliticas
  alCambiar: (p: Politica) => void
  alQuitar: () => void
}) {
  const entidad = datos.entidades.find((e) => e.nombre === politica.entidad)
  const cobertura = datos.cobertura.find((c) => c.politica === politica.nombre)

  return (
    <div className="paso abierto">
      <div className="paso-detalle">
        <div className="paso-cuerpo">
          <div className="fila-campos">
            <div className="campo">
              <label>Nombre</label>
              <input
                type="text"
                value={politica.nombre}
                placeholder="rls_sucursal_por_estado"
                onChange={(e) => alCambiar({ ...politica, nombre: e.target.value })}
              />
            </div>
            <div className="campo">
              <label>Sobre qué entidad</label>
              <select
                value={politica.entidad}
                onChange={(e) => alCambiar({ ...politica, entidad: e.target.value })}
              >
                <option value="">(elige una)</option>
                {datos.entidades.map((e) => (
                  <option key={e.nombre} value={e.nombre}>
                    {e.nombre} ({e.tipo})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="campo">
            <label>Condición</label>
            <input
              type="text"
              className="mono"
              value={politica.predicado}
              placeholder="region_id = {{ usuario.region_id }}"
              onChange={(e) => alCambiar({ ...politica, predicado: e.target.value })}
            />
            <span className="chico tenue">
              Solo columnas de <span className="mono">{politica.entidad || 'la entidad'}</span>
              , y sustituciones <span className="mono">{'{{ usuario.clave }}'}</span>. El
              valor viaja como parámetro, nunca pegado en el SQL.
            </span>
            {entidad && (
              <div className="atributos">
                {entidad.campos.map((c) => (
                  <button
                    key={c}
                    className="chip como-boton"
                    title="Agregar a la condición"
                    onClick={() =>
                      alCambiar({
                        ...politica,
                        predicado: `${politica.predicado}${politica.predicado ? ' ' : ''}${c}`,
                      })
                    }
                  >
                    <span className="mono">{c}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="campo">
            <label>A qué roles aplica</label>
            <div className="casillas">
              {/* Los roles que la política nombra y que ya no existen se muestran
                  igual. Si solo se dibujaran los conocidos, guardar los borraría en
                  silencio y la política cambiaría a quién aplica sin que nadie lo
                  pidiera — que es exactamente el cambio que no se puede hacer solo. */}
              {[
                ...datos.roles,
                ...politica.aplica_a_roles.filter((r) => !datos.roles.includes(r)),
              ].map((r) => (
                <label className="casilla" key={r}>
                  <input
                    type="checkbox"
                    checked={politica.aplica_a_roles.includes(r)}
                    onChange={(e) =>
                      alCambiar({
                        ...politica,
                        aplica_a_roles: e.target.checked
                          ? [...politica.aplica_a_roles, r]
                          : politica.aplica_a_roles.filter((x) => x !== r),
                      })
                    }
                  />
                  {r}
                  {!datos.roles.includes(r) && (
                    <span
                      className="etiqueta aviso"
                      title="La política nombra este rol, pero no existe en Astrolabio. Nadie lo tiene, así que la política no aplica a nadie."
                    >
                      rol inexistente
                    </span>
                  )}
                </label>
              ))}
            </div>
            <span className="chico tenue">
              Sin marcar ninguno aplica a todos menos a administrador. A un
              administrador no se le puede aplicar una política.
            </span>
          </div>

          {cobertura && cobertura.sin_atributo.length > 0 && (
            <div className="aviso-caja">
              <strong>
                {cobertura.sin_atributo.length} persona(s) se quedarían sin ver nada:
              </strong>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {cobertura.sin_atributo.map((s) => (
                  <li key={s.email} className="chico">
                    <span className="mono">{s.email}</span> — le falta{' '}
                    {s.faltan.join(', ')}
                  </li>
                ))}
              </ul>
              <div className="chico" style={{ marginTop: 4 }}>
                No es que vean datos de más: reciben un error. Ponles el atributo en
                Usuarios.
              </div>
            </div>
          )}
          {cobertura && cobertura.usuarios_alcanzados.length === 0 && (
            <div className="chico tenue">
              Hoy no alcanza a nadie: ninguna persona activa tiene un rol de los
              marcados.
            </div>
          )}

          <div style={{ display: 'flex' }}>
            <button className="btn chico peligro" onClick={alQuitar}>
              Quitar política
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function Politicas() {
  const modelos = useModelos()
  const [modeloId, setModeloId] = useState(0)
  useEffect(() => {
    const primero = modelos.data?.[0]
    if (!modeloId && primero) setModeloId(primero.id)
  }, [modelos.data, modeloId])

  const datos = usePoliticas(modeloId)
  const guardar = useGuardarPoliticas(modeloId)

  // Copia local para poder editar varias antes de guardar. Se reinicia cuando llega
  // otra versión del servidor.
  const [borrador, setBorrador] = useState<Politica[] | null>(null)
  useEffect(() => {
    setBorrador(null)
  }, [datos.data?.version, modeloId])

  const lista = borrador ?? datos.data?.politicas ?? []
  const sucio = borrador !== null

  return (
    <>
      <div className="fila-condicion">
        <div className="campo" style={{ flex: '0 0 260px' }}>
          <label>Modelo</label>
          <select value={modeloId} onChange={(e) => setModeloId(Number(e.target.value))}>
            {modelos.data?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.nombre} — v{m.version_actual}
              </option>
            ))}
          </select>
        </div>
        {datos.data && (
          <span className="chico suave" style={{ alignSelf: 'flex-end' }}>
            Versión {datos.data.version} · {lista.length} política(s)
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'flex-end' }}>
          <button
            className="btn chico"
            disabled={!datos.data}
            onClick={() => setBorrador([...lista, { ...VACIA }])}
          >
            + Política
          </button>
          {sucio && (
            <>
              <button className="btn chico" onClick={() => setBorrador(null)}>
                Descartar
              </button>
              <button
                className="btn primario chico"
                disabled={guardar.isPending}
                onClick={() =>
                  guardar.mutate(
                    { politicas: lista },
                    { onSuccess: () => setBorrador(null) },
                  )
                }
              >
                {guardar.isPending ? 'Guardando…' : 'Guardar versión nueva'}
              </button>
            </>
          )}
        </div>
      </div>

      {sucio && (
        <div className="sin-guardar" style={{ marginTop: 8 }}>
          Sin guardar. Guardar crea la versión {(datos.data?.version ?? 0) + 1} del
          modelo; los tableros anclados a la anterior no cambian.
        </div>
      )}

      {datos.isError && (
        <div className="error-caja">{(datos.error as Error).message}</div>
      )}
      {guardar.isError && (
        <div className="error-caja">{(guardar.error as Error).message}</div>
      )}

      {datos.data?.errores.map((e, i) => (
        <div className="error-caja" key={i}>
          {e}
        </div>
      ))}
      {datos.data?.avisos.map((a, i) => (
        <div className="aviso-caja" key={i}>
          {a}
        </div>
      ))}

      {datos.data && lista.length === 0 && (
        <div className="vacio">
          Este modelo no tiene políticas: todo el mundo ve todas las filas. Está bien
          mientras seas el único que entra.
        </div>
      )}

      <div className="pasos" style={{ padding: '10px 0' }}>
        {datos.data && lista.map((p, i) => (
          <EditorPolitica
            key={i}
            politica={p}
            datos={datos.data}
            alCambiar={(np) =>
              setBorrador(lista.map((x, j) => (j === i ? np : x)))
            }
            alQuitar={() => setBorrador(lista.filter((_, j) => j !== i))}
          />
        ))}
      </div>

      {modeloId > 0 && (
        <>
          <h2>Comprobarlo</h2>
          <p className="chico suave" style={{ margin: '0 0 8px' }}>
            Sobre la versión guardada. Si acabas de editar arriba, guarda primero.
          </p>
          <Simulador modeloId={modeloId} />
        </>
      )}
    </>
  )
}
