/**
 * Avisos: a quién se le cuenta cuando algo falla.
 *
 * Tres cosas que esta pantalla tiene que dejar claras, porque son las que hacen
 * que un sistema de avisos sirva o solo lo parezca:
 *
 * 1. **Probar.** El botón está junto a cada regla y no escondido: un canal que
 *    nadie probó no es cobertura, es creer que la hay. Y con avisos uno deja de
 *    mirar el historial, así que la creencia equivocada sale más cara que no
 *    tener avisos.
 * 2. **Si el canal no está configurado, se dice ahí mismo.** Una regla activa
 *    sobre un correo sin servidor SMTP se ve exactamente igual que una que
 *    funciona.
 * 3. **El historial muestra los silenciados.** Son la prueba de que hubo más
 *    fallos que correos; sin ellos el silencio parece que perdió avisos.
 */

import { useState } from 'react'

import {
  type CuerpoRegla,
  type ReglaAviso,
  useAvisos,
  useBorrarAviso,
  useCatalogoAvisos,
  useGuardarAviso,
  useHistorialAvisos,
  useProbarAviso,
} from '../api/avisos'

const VACIA: CuerpoRegla = {
  nombre: '',
  canal: 'correo',
  destino: '',
  // Los dos juntos por omisión: el de recuperación es la otra mitad del silencio.
  eventos: ['carga_fallida', 'carga_recuperada', 'flujo_fallido', 'flujo_recuperado'],
  objeto_tipo: null,
  objeto_id: null,
  silencio_minutos: 60,
  activa: true,
}

const SILENCIOS = [
  { min: 0, etiqueta: 'sin silencio — un aviso por cada fallo' },
  { min: 30, etiqueta: 'uno cada 30 minutos' },
  { min: 60, etiqueta: 'uno cada hora' },
  { min: 240, etiqueta: 'uno cada 4 horas' },
  { min: 1440, etiqueta: 'uno al día' },
]

function fecha(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es-MX', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function Avisos() {
  const lista = useAvisos()
  const catalogo = useCatalogoAvisos()
  const historial = useHistorialAvisos()
  const guardar = useGuardarAviso()
  const probar = useProbarAviso()
  const borrar = useBorrarAviso()

  const [id, setId] = useState<number | null>(null)
  const [r, setR] = useState<CuerpoRegla>(VACIA)
  /** Resultado de la última prueba, por regla: se lee junto a su botón. */
  const [probado, setProbado] = useState<Record<number, { ok: boolean; detalle: string }>>({})

  const editar = (x: ReglaAviso) => {
    setId(x.id)
    setR({
      nombre: x.nombre,
      canal: x.canal,
      destino: x.destino,
      eventos: x.eventos,
      objeto_tipo: x.objeto_tipo,
      objeto_id: x.objeto_id,
      silencio_minutos: x.silencio_minutos,
      activa: x.activa,
    })
    guardar.reset()
  }

  const nueva = () => {
    setId(null)
    setR(VACIA)
    guardar.reset()
  }

  /** Al marcar una recuperación se marca su fallo: sola no llegaría nunca. */
  const alternarEvento = (clave: string) => {
    const requiere = catalogo.data?.eventos.find((e) => e.clave === clave)?.requiere
    const puesto = r.eventos.includes(clave)
    let eventos = puesto
      ? r.eventos.filter((e) => e !== clave)
      : [...r.eventos, clave, ...(requiere && !r.eventos.includes(requiere) ? [requiere] : [])]
    // Y al quitar un fallo se va su recuperación, por lo mismo.
    if (puesto) {
      const dependen = (catalogo.data?.eventos ?? [])
        .filter((e) => e.requiere === clave)
        .map((e) => e.clave)
      eventos = eventos.filter((e) => !dependen.includes(e))
    }
    setR({ ...r, eventos })
  }

  const objetos =
    r.objeto_tipo === 'dataset'
      ? (catalogo.data?.datasets ?? [])
      : r.objeto_tipo === 'flujo'
        ? (catalogo.data?.flujos ?? [])
        : []

  const canal = catalogo.data?.canales.find((c) => c.clave === r.canal)

  return (
    <div className="pagina">
      <h1>Avisos</h1>
      <p className="suave chico">
        Un flujo que se rompe de madrugada no se lo cuenta a nadie: los tableros
        siguen abriendo, con las cifras del día anterior y sin señal de que están
        viejas. Esto es lo que lo cuenta.
      </p>

      <div className="rejilla-dos" style={{ marginTop: 16 }}>
        {/* ------------------------------------------------- las reglas */}
        <section className="tarjeta">
          <header className="entre">
            <span>Reglas {lista.data?.length ? `(${lista.data.length})` : ''}</span>
            <button className="btn chico" onClick={nueva}>
              + Nueva
            </button>
          </header>

          {lista.data?.length === 0 && (
            <div className="vacio chico">
              No hay ninguna regla, así que hoy nadie se entera de un fallo salvo que
              entre a mirar el historial.
            </div>
          )}

          <div className="tabla-envoltura">
            <table className="datos">
              <thead>
                <tr>
                  <th>Regla</th>
                  <th>Por dónde</th>
                  <th>De qué</th>
                  <th>Último</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {lista.data?.map((x) => {
                  const p = probado[x.id]
                  return (
                    <tr key={x.id} className={x.activa ? '' : 'fuera'}>
                      <td>
                        <button className="enlace" onClick={() => editar(x)}>
                          {x.nombre}
                        </button>
                        {!x.activa && <span className="etiqueta"> en pausa</span>}
                        {x.objeto_nombre && (
                          <div className="chico tenue mono">solo {x.objeto_nombre}</div>
                        )}
                      </td>
                      <td>
                        <div className="chico mono">{x.destino}</div>
                        {/* El motivo por el que no puede entregar, ahí mismo. */}
                        {!x.canal_listo && (
                          <div className="chico error-texto">{x.canal_detalle}</div>
                        )}
                      </td>
                      <td className="chico">{x.eventos.length} eventos</td>
                      <td className="chico">
                        {fecha(x.ultimo_envio)}
                        {x.ultimo_estado && (
                          <span
                            className={`etiqueta ${
                              x.ultimo_estado === 'enviado'
                                ? 'ok'
                                : x.ultimo_estado === 'error'
                                  ? 'critico'
                                  : ''
                            }`}
                          >
                            {x.ultimo_estado}
                          </span>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn chico"
                          disabled={probar.isPending}
                          title="Manda un aviso de prueba ahora, sin esperar a que algo falle"
                          onClick={() =>
                            probar.mutate(x.id, {
                              onSuccess: (res) =>
                                setProbado((v) => ({ ...v, [x.id]: res })),
                            })
                          }
                        >
                          Probar
                        </button>
                        {p && (
                          <div className={`chico ${p.ok ? 'ok-texto' : 'error-texto'}`}>
                            {p.ok ? '✓ llegó' : p.detalle}
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        {/* ------------------------------------------------- el editor */}
        <section className="tarjeta">
          <header>{id === null ? 'Nueva regla' : `Editar «${r.nombre}»`}</header>

          <div className="campo">
            <label>Nombre</label>
            <input
              type="text"
              placeholder="avisar_a_sistemas"
              value={r.nombre}
              onChange={(e) => setR({ ...r, nombre: e.target.value })}
            />
          </div>

          <div className="campo">
            <label>Por dónde</label>
            <select
              value={r.canal}
              onChange={(e) =>
                setR({ ...r, canal: e.target.value as CuerpoRegla['canal'] })
              }
            >
              <option value="correo">Correo</option>
              <option value="webhook">Webhook — Teams, Slack o lo que sea</option>
            </select>
            {canal && !canal.listo && (
              <span className="chico error-texto">{canal.detalle}</span>
            )}
          </div>

          <div className="campo">
            <label>{r.canal === 'correo' ? 'A quién' : 'URL del webhook'}</label>
            <input
              type="text"
              className="mono"
              placeholder={
                r.canal === 'correo'
                  ? 'datos@tuempresa.com, sistemas@tuempresa.com'
                  : 'https://…/webhook'
              }
              value={r.destino}
              onChange={(e) => setR({ ...r, destino: e.target.value })}
            />
            {r.canal === 'correo' && (
              <span className="chico tenue">Varios, separados por coma.</span>
            )}
          </div>

          <div className="campo">
            <label>De qué avisar</label>
            {catalogo.data?.eventos.map((e) => (
              <label key={e.clave} className="linea-check">
                <input
                  type="checkbox"
                  checked={r.eventos.includes(e.clave)}
                  onChange={() => alternarEvento(e.clave)}
                />
                <span className="chico">{e.etiqueta}</span>
              </label>
            ))}
          </div>

          <div className="campo">
            <label>Sobre qué</label>
            <select
              value={r.objeto_tipo ?? ''}
              onChange={(e) =>
                setR({
                  ...r,
                  objeto_tipo: (e.target.value || null) as CuerpoRegla['objeto_tipo'],
                  objeto_id: null,
                })
              }
            >
              <option value="">Todo lo que falle</option>
              <option value="dataset">Solo cargas</option>
              <option value="flujo">Solo flujos</option>
            </select>
            {r.objeto_tipo && (
              <select
                value={r.objeto_id ?? ''}
                onChange={(e) =>
                  setR({ ...r, objeto_id: e.target.value ? Number(e.target.value) : null })
                }
              >
                <option value="">Todos los {r.objeto_tipo === 'dataset' ? 'datasets' : 'flujos'}</option>
                {objetos.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.nombre}
                  </option>
                ))}
              </select>
            )}
            <span className="chico tenue">
              «Todo» es lo que conviene: una regla por dataset deja sin cubrir justo
              el que se cree mañana.
            </span>
          </div>

          <div className="campo">
            <label>Repetición</label>
            <select
              value={r.silencio_minutos}
              onChange={(e) => setR({ ...r, silencio_minutos: Number(e.target.value) })}
            >
              {SILENCIOS.map((s) => (
                <option key={s.min} value={s.min}>
                  {s.etiqueta}
                </option>
              ))}
            </select>
            <span className="chico tenue">
              Una carga rota cada 15 minutos manda 96 correos al día y consigue que
              se archiven todos, incluido el que importaba.
            </span>
          </div>

          <label className="linea-check">
            <input
              type="checkbox"
              checked={r.activa}
              onChange={(e) => setR({ ...r, activa: e.target.checked })}
            />
            <span className="chico">Activa</span>
          </label>

          {guardar.isError && (
            <div className="error-caja chico">{(guardar.error as Error).message}</div>
          )}

          <div className="fila">
            <button
              className="btn primario"
              disabled={!r.nombre.trim() || !r.destino.trim() || guardar.isPending}
              onClick={() =>
                guardar.mutate({ id, cuerpo: r }, { onSuccess: (x) => setId(x.id) })
              }
            >
              {guardar.isPending ? 'Guardando…' : id === null ? 'Crear' : 'Guardar'}
            </button>
            {id !== null && (
              <button
                className="btn peligro"
                onClick={() => {
                  if (confirm(`¿Borrar la regla "${r.nombre}"?`)) {
                    borrar.mutate(id, { onSuccess: nueva })
                  }
                }}
              >
                Borrar
              </button>
            )}
          </div>
        </section>
      </div>

      {/* --------------------------------------------------- historial */}
      <section className="tarjeta" style={{ marginTop: 16 }}>
        <header>Avisos mandados</header>
        {historial.data?.envios.length === 0 && (
          <div className="vacio chico">Todavía no se ha mandado ninguno.</div>
        )}
        <div className="tabla-envoltura">
          <table className="datos">
            <thead>
              <tr>
                <th>Cuándo</th>
                <th>Regla</th>
                <th>Qué pasó</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {historial.data?.envios.map((e) => (
                <tr key={e.id}>
                  <td className="chico">{fecha(e.cuando)}</td>
                  <td className="chico">{e.regla}</td>
                  <td className="chico">
                    {e.asunto}
                    {e.mensaje && <div className="chico tenue">{e.mensaje}</div>}
                  </td>
                  <td>
                    <span
                      className={`etiqueta ${
                        e.estado === 'enviado' ? 'ok' : e.estado === 'error' ? 'critico' : ''
                      }`}
                    >
                      {e.estado}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
