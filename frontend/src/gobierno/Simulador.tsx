/**
 * Simulador: qué vería otra persona.
 *
 * Existe porque a un administrador las políticas no le aplican — quien las escribe
 * es justo quien no puede comprobarlas mirando sus propias consultas. Sin esto, la
 * única forma de verificar una política es publicarla y preguntarle a alguien, que
 * es verificar después de arriesgar.
 *
 * Lo que se muestra es siempre una comparación. «Ve 1 fila» no dice nada; «ve 1 de
 * 40» dice si la política está filtrando o si no hace nada.
 */

import { useState } from 'react'

import { type UsuarioCompleto, useSimular, useUsuarios } from '../api/gobierno'
import { useCampos } from '../api/hooks'

function filas(n: number): string {
  return n === 1 ? '1 fila' : `${n.toLocaleString('es-MX')} filas`
}

function Barra({ visibles, total }: { visibles: number; total: number }) {
  const pct = total > 0 ? Math.round((visibles / total) * 100) : 0
  return (
    <div className="barra-visible" title={`${pct}% de las filas`}>
      <div style={{ width: `${Math.max(pct, visibles > 0 ? 1.5 : 0)}%` }} />
    </div>
  )
}

export function Simulador({ modeloId }: { modeloId: number }) {
  const usuarios = useUsuarios()
  const campos = useCampos(modeloId)
  const simular = useSimular()

  const [modo, setModo] = useState<'usuario' | 'rol'>('usuario')
  const [usuarioId, setUsuarioId] = useState<number | ''>('')
  const [rol, setRol] = useState('lector')
  const [clave, setClave] = useState('')
  const [valor, setValor] = useState('')
  const [metrica, setMetrica] = useState('')
  const [dimension, setDimension] = useState('')

  const d = simular.data
  const puede = modo === 'usuario' ? usuarioId !== '' : !!rol

  const correr = () => {
    simular.mutate({
      modelo_id: modeloId,
      ...(modo === 'usuario'
        ? { usuario_id: Number(usuarioId) }
        : { rol, atributos: clave.trim() ? { [clave.trim()]: valor } : {} }),
      ...(metrica
        ? { consulta: { metricas: [metrica], dimensiones: dimension ? [dimension] : [] } }
        : {}),
    })
  }

  const elegido: UsuarioCompleto | undefined = usuarios.data?.find(
    (u) => u.id === Number(usuarioId),
  )

  return (
    <div className="simulador">
      <div className="fila-condicion">
        <div className="pestanas">
          <button
            className={modo === 'usuario' ? 'activo' : ''}
            onClick={() => setModo('usuario')}
          >
            Una persona
          </button>
          <button
            className={modo === 'rol' ? 'activo' : ''}
            onClick={() => setModo('rol')}
          >
            Un rol a mano
          </button>
        </div>

        {modo === 'usuario' ? (
          <select
            value={usuarioId}
            onChange={(e) => setUsuarioId(Number(e.target.value))}
          >
            <option value="">(elige a quién)</option>
            {usuarios.data?.map((u) => (
              <option key={u.id} value={u.id}>
                {u.nombre} — {u.email} ({u.rol})
              </option>
            ))}
          </select>
        ) : (
          <>
            <select value={rol} onChange={(e) => setRol(e.target.value)}>
              <option value="lector">lector</option>
              <option value="editor">editor</option>
              <option value="administrador">administrador</option>
            </select>
            <input
              type="text"
              placeholder="region_id"
              value={clave}
              onChange={(e) => setClave(e.target.value)}
            />
            <input
              type="text"
              placeholder="3"
              value={valor}
              onChange={(e) => setValor(e.target.value)}
            />
          </>
        )}
      </div>

      {modo === 'rol' && (
        <p className="chico tenue" style={{ margin: '2px 0 0' }}>
          Un usuario que no existe, para probar la política antes de dar de alta a
          nadie.
        </p>
      )}
      {modo === 'usuario' && elegido && (
        <p className="chico tenue" style={{ margin: '2px 0 0' }}>
          Atributos:{' '}
          <span className="mono">
            {Object.entries(elegido.atributos)
              .map(([k, v]) => `${k}=${v}`)
              .join('  ') || 'ninguno'}
          </span>
        </p>
      )}

      <div className="fila-condicion" style={{ marginTop: 8 }}>
        <select value={metrica} onChange={(e) => setMetrica(e.target.value)}>
          <option value="">(sin consulta: solo las filas visibles)</option>
          {campos.data?.metricas.map((m) => (
            <option key={m.clave} value={m.clave}>
              {m.etiqueta}
            </option>
          ))}
        </select>
        <select
          value={dimension}
          onChange={(e) => setDimension(e.target.value)}
          disabled={!metrica}
        >
          <option value="">(total, sin desglose)</option>
          {campos.data?.dimensiones.map((c) => (
            <option key={c.clave} value={c.clave}>
              {c.etiqueta}
            </option>
          ))}
        </select>
        <button
          className="btn primario"
          disabled={!puede || simular.isPending}
          onClick={correr}
        >
          {simular.isPending ? 'Consultando…' : 'Ver qué vería'}
        </button>
      </div>

      {simular.isError && (
        <div className="error-caja">{(simular.error as Error).message}</div>
      )}

      {d && (
        <div className="resultado-sim">
          {d.es_administrador && (
            <div className="aviso-caja">
              Es administrador: las políticas no le aplican y ve todo. No es un
              hueco, es la definición del rol — para comprobar una política, simula
              a alguien que no lo sea.
            </div>
          )}

          {d.error && (
            <div className="error-caja">
              <strong>No vería nada.</strong> {d.error}
              <div className="chico" style={{ marginTop: 4 }}>
                Es lo correcto: sin el atributo, entregar los datos sin filtrar
                sería peor. Pero esta persona verá un error, no un tablero vacío:
                dale el atributo que le falta.
              </div>
            </div>
          )}

          {d.aplicadas.length === 0 && !d.error && !d.es_administrador && (
            <div className="aviso-caja">
              Ninguna política le aplica, así que ve todo. Revisa los roles de las
              políticas si esperabas otra cosa.
            </div>
          )}

          {d.entidades.map((e) => (
            <div className="tarjeta-sim" key={e.politica}>
              <div className="cabeza">
                <span className="etiqueta dim">{e.politica}</span>
                <span className="mono chico">{e.entidad}</span>
                <span className="cifra-sim">
                  {e.filas_visibles.toLocaleString('es-MX')}
                  <span className="tenue">
                    {' '}
                    de {e.filas_totales.toLocaleString('es-MX')} filas
                  </span>
                </span>
              </div>
              <Barra visibles={e.filas_visibles} total={e.filas_totales} />
              <div className="mono chico suave">
                {e.predicado}{' '}
                {e.valores.length > 0 && (
                  <span className="tenue">
                    donde ? = {e.valores.join(', ')}
                  </span>
                )}
              </div>
              {e.filas_visibles === e.filas_totales && (
                <div className="chico" style={{ color: 'var(--aviso)' }}>
                  Deja pasar todas las filas: tal como está, esta política no
                  restringe nada.
                </div>
              )}
              {e.muestra.length > 0 && (
                <div className="atributos">
                  {e.muestra.map((v, i) => (
                    <span className="chip" key={i}>
                      <span className="mono">{String(v)}</span>
                    </span>
                  ))}
                  {e.hay_mas && <span className="chico tenue">y más…</span>}
                </div>
              )}
            </div>
          ))}

          {d.omitidas.length > 0 && (
            <details className="corrida">
              <summary className="chico suave">
                {d.omitidas.length} política(s) que no le aplican
              </summary>
              <ul className="chico suave">
                {d.omitidas.map((o) => (
                  <li key={o.nombre}>
                    <span className="mono">{o.nombre}</span> — {o.motivo}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {d.consulta && (
            <div className="comparacion">
              <div>
                <h4>
                  Lo que vería{' '}
                  <span className="tenue">({filas(d.consulta.cuenta)})</span>
                </h4>
                <Tabla
                  columnas={d.consulta.columnas}
                  filas={d.consulta.filas}
                />
              </div>
              <div>
                <h4>
                  Sin políticas{' '}
                  <span className="tenue">
                    ({filas(d.consulta.cuenta_sin_politicas)})
                  </span>
                </h4>
                <Tabla
                  columnas={d.consulta.columnas}
                  filas={d.consulta.filas_sin_politicas}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Tabla({
  columnas,
  filas,
}: {
  columnas: string[]
  filas: Record<string, unknown>[]
}) {
  return (
    <div className="tabla-envoltura" style={{ maxHeight: 260 }}>
      <table className="datos">
        <thead>
          <tr>
            {columnas.map((c) => (
              <th key={c}>{c.split('.').pop()}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.slice(0, 50).map((f, i) => (
            <tr key={i}>
              {columnas.map((c) => {
                const v = f[c]
                const num = typeof v === 'number'
                return (
                  <td key={c} className={num ? 'num' : undefined}>
                    {num ? v.toLocaleString('es-MX') : String(v ?? '—')}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
