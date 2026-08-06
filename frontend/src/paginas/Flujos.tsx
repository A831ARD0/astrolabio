/**
 * Flujos: qué se carga y qué se recalcula, en orden y a una hora.
 *
 * Dos cosas que la pantalla tiene que dejar claras:
 *
 * 1. **El orden importa.** Si una transformación va antes de la carga de lo que
 *    lee, el aviso se ve en el propio paso, no en un mensaje aparte. Y hay un botón
 *    que propone el orden correcto a partir del linaje.
 * 2. **Al fallar se detiene.** Los pasos que no se intentaron se muestran como
 *    omitidos, para que no parezca que corrieron y no hicieron nada.
 */

import { useEffect, useState } from 'react'

import {
  HORARIOS,
  type CuerpoFlujo,
  type Flujo,
  type PasoFlujo,
  type ResultadoPaso,
  useDisponiblesFlujo,
  useEjecutarFlujo,
  useFlujos,
  useGuardarFlujo,
  useHistorialFlujo,
  useProgramarFlujo,
  useSugerirOrden,
} from '../api/flujos'
import { ErrorApi } from '../api/cliente'

const VACIO: CuerpoFlujo = { nombre: '', descripcion: null, pasos: [], al_fallar: 'detener' }

export function Flujos() {
  const lista = useFlujos()
  const disponibles = useDisponiblesFlujo()
  const guardar = useGuardarFlujo()
  const sugerir = useSugerirOrden()
  const ejecutar = useEjecutarFlujo()

  const [id, setId] = useState<number | null>(null)
  const [f, setF] = useState<CuerpoFlujo>(VACIO)
  const [avisos, setAvisos] = useState<string[]>([])
  const [cron, setCron] = useState('0 6 * * *')

  const programacion = useProgramarFlujo(id)
  const historial = useHistorialFlujo(id)
  const actual: Flujo | undefined = lista.data?.find((x) => x.id === id)

  useEffect(() => {
    if (actual) {
      setAvisos(actual.avisos)
      if (actual.cron) setCron(actual.cron)
    }
  }, [actual])

  function cargar(x: Flujo) {
    setId(x.id)
    setF({
      nombre: x.nombre,
      descripcion: x.descripcion,
      pasos: x.pasos,
      al_fallar: x.al_fallar,
    })
    setAvisos(x.avisos)
    setCron(x.cron ?? '0 6 * * *')
    ejecutar.reset()
  }

  function nuevo() {
    setId(null)
    setF(VACIO)
    setAvisos([])
    ejecutar.reset()
  }

  const agregar = (paso: PasoFlujo) => {
    if (f.pasos.some((p) => p.tipo === paso.tipo && p.id === paso.id)) return
    setF({ ...f, pasos: [...f.pasos, paso] })
  }

  const mover = (i: number, delta: number) => {
    const j = i + delta
    if (j < 0 || j >= f.pasos.length) return
    const pasos = [...f.pasos]
    ;[pasos[i], pasos[j]] = [pasos[j]!, pasos[i]!]
    setF({ ...f, pasos })
  }

  /** Qué aviso corresponde a qué paso, para pintarlo donde ocurre. */
  const avisoDe = (paso: PasoFlujo, i: number) =>
    avisos.find((a) => a.startsWith(`Paso ${i + 1} (${paso.nombre}`))

  const resultados: ResultadoPaso[] =
    ejecutar.data?.pasos ??
    ((ejecutar.error instanceof ErrorApi
      ? ((ejecutar.error.detalle as { pasos?: ResultadoPaso[] })?.pasos ?? [])
      : []) as ResultadoPaso[])

  return (
    <div className="editor">
      {/* --------------------------------------------------- izquierda */}
      <aside className="izq">
        <section className="seccion">
          <header>
            Flujos <span className="cuenta">{lista.data?.length ?? 0}</span>
          </header>
          <div className="contenido">
            <div className="lista">
              {lista.data?.map((x) => (
                <button key={x.id} className={id === x.id ? 'sel' : ''}
                        onClick={() => cargar(x)}>
                  <span
                    className="punto"
                    style={{
                      background: x.programacion_activa
                        ? 'var(--ok)'
                        : 'var(--borde-fuerte)',
                    }}
                    title={x.programacion_activa ? 'Programado' : 'Sin programar'}
                  />
                  <span className="nom">{x.nombre}</span>
                  <span className="dcha">{x.pasos.length} pasos</span>
                </button>
              ))}
            </div>
            <button className="btn chico" style={{ marginTop: 8, width: '100%' }}
                    onClick={nuevo}>
              + Nuevo flujo
            </button>
          </div>
        </section>

        <section className="seccion">
          <header>Cargas</header>
          <div className="contenido">
            <div className="lista">
              {disponibles.data?.cargas.map((c) => (
                <button key={c.id}
                        onClick={() => agregar({ tipo: 'carga', id: c.id, nombre: c.nombre })}>
                  <span className="nom mono">{c.nombre}</span>
                  {c.cron_propio && (
                    <span className="dcha" title="Ya tiene su propio horario">⏱</span>
                  )}
                </button>
              ))}
              {disponibles.data?.cargas.length === 0 && (
                <div className="chico tenue" style={{ padding: '2px 8px' }}>
                  No hay datasets todavía.
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="seccion">
          <header>Transformaciones</header>
          <div className="contenido">
            <div className="lista">
              {disponibles.data?.transformaciones.map((t) => (
                <button
                  key={t.id}
                  onClick={() =>
                    agregar({ tipo: 'transformacion', id: t.id, nombre: t.nombre })
                  }
                >
                  <span className="nom mono">{t.nombre}</span>
                </button>
              ))}
            </div>
          </div>
        </section>
      </aside>

      {/* ------------------------------------------------------- centro */}
      <div className="centro">
        <div className="barra-editor">
          <input
            type="text"
            className="mono"
            placeholder="nombre_del_flujo"
            value={f.nombre}
            onChange={(e) => setF({ ...f, nombre: e.target.value })}
            style={{ maxWidth: 220 }}
          />
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, minWidth: 0 }}>
            <button
              className="btn"
              disabled={f.pasos.length === 0 || sugerir.isPending}
              title="Ordena los pasos según lo que cada transformación lee, y agrega las cargas que falten"
              onClick={() =>
                sugerir.mutate(f, {
                  onSuccess: (r) => {
                    setF({ ...f, pasos: r.pasos })
                    setAvisos(r.avisos)
                  },
                })
              }
            >
              Ordenar solo
            </button>
            <button
              className="btn"
              disabled={!f.nombre.trim() || f.pasos.length === 0 || guardar.isPending}
              onClick={() =>
                guardar.mutate(
                  { id, cuerpo: f },
                  {
                    onSuccess: (x) => {
                      setId(x.id)
                      setAvisos(x.avisos)
                    },
                  },
                )
              }
            >
              {guardar.isPending ? 'Guardando…' : id === null ? 'Crear' : 'Guardar'}
            </button>
            <button
              className="btn primario"
              disabled={id === null || ejecutar.isPending}
              title={id === null ? 'Guárdalo antes de ejecutarlo' : undefined}
              onClick={() => ejecutar.mutate(id!)}
            >
              {ejecutar.isPending ? 'Ejecutando…' : 'Ejecutar ahora'}
            </button>
          </div>
        </div>

        {guardar.isError && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {(guardar.error as Error).message}
          </div>
        )}
        {ejecutar.isSuccess && (
          <div className="aviso-caja" style={{ margin: '10px 12px 0' }}>
            Flujo completo: {ejecutar.data.pasos.length} paso(s) en {ejecutar.data.ms} ms.
          </div>
        )}
        {ejecutar.isError && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {(ejecutar.error as Error).message}
          </div>
        )}

        <div className="etl-cuerpo">
          {f.pasos.length === 0 ? (
            <div className="vacio">
              Elige de la izquierda qué cargar y qué recalcular. El orden se puede
              acomodar, y hay un botón que lo propone.
            </div>
          ) : (
            <div className="pasos">
              {f.pasos.map((p, i) => {
                const aviso = avisoDe(p, i)
                const r = resultados.find((x) => x.paso === i + 1)
                return (
                  <div className={`paso ${aviso ? 'con-aviso' : ''}`} key={`${p.tipo}-${p.id}`}>
                    <header style={{ cursor: 'default' }}>
                      <span className="orden">{i + 1}</span>
                      <span className="etiqueta">
                        {p.tipo === 'carga' ? 'cargar' : 'transformar'}
                      </span>
                      <span className="nom mono">{p.nombre}</span>

                      {r && (
                        <span
                          className={`etiqueta ${
                            r.estado === 'exito'
                              ? 'ok'
                              : r.estado === 'error'
                                ? 'critico'
                                : ''
                          }`}
                          title={r.mensaje ?? undefined}
                        >
                          {r.estado === 'exito'
                            ? `${(r.filas ?? 0).toLocaleString('es-MX')} filas · ${r.ms} ms`
                            : r.estado === 'error'
                              ? 'falló'
                              : 'omitido'}
                        </span>
                      )}

                      <span className="acciones">
                        <button className="btn chico" onClick={() => mover(i, -1)}>↑</button>
                        <button className="btn chico" onClick={() => mover(i, 1)}>↓</button>
                        <button
                          className="btn chico peligro"
                          onClick={() =>
                            setF({ ...f, pasos: f.pasos.filter((_, j) => j !== i) })
                          }
                        >
                          ✕
                        </button>
                      </span>
                    </header>
                    {aviso && <div className="aviso-paso">{aviso}</div>}
                    {r?.estado === 'error' && r.mensaje && (
                      <div className="error-caja chico" style={{ margin: 8 }}>
                        {r.mensaje}
                      </div>
                    )}
                  </div>
                )
              })}

              <div className="campo" style={{ marginTop: 10, maxWidth: 380 }}>
                <label>Si un paso falla</label>
                <select
                  value={f.al_fallar}
                  onChange={(e) =>
                    setF({ ...f, al_fallar: e.target.value as CuerpoFlujo['al_fallar'] })
                  }
                >
                  <option value="detener">
                    detener — no recalcular sobre datos que no se cargaron
                  </option>
                  <option value="continuar">continuar con los demás pasos</option>
                </select>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------ derecha */}
      <aside className="der">
        <div className="barra-editor">
          <div className="pestanas">
            <button className="activo">Horario e historial</button>
          </div>
        </div>

        <div className="inspector">
          {id === null ? (
            <div className="vacio chico">Guarda el flujo para poder programarlo.</div>
          ) : (
            <>
              <div className="campo">
                <label>Horario</label>
                <select
                  value={HORARIOS.some((h) => h.cron === cron) ? cron : ''}
                  onChange={(e) => e.target.value && setCron(e.target.value)}
                >
                  {!HORARIOS.some((h) => h.cron === cron) && (
                    <option value="">(personalizado)</option>
                  )}
                  {HORARIOS.map((h) => (
                    <option key={h.cron} value={h.cron}>
                      {h.etiqueta}
                    </option>
                  ))}
                </select>
                <input
                  type="text"
                  className="mono"
                  value={cron}
                  onChange={(e) => setCron(e.target.value)}
                />
                <span className="chico tenue">
                  minuto hora día mes día-semana · hora de{' '}
                  {actual?.zona_horaria ?? 'America/Mexico_City'}
                </span>
              </div>

              {programacion.programar.isError && (
                <div className="error-caja chico">
                  {(programacion.programar.error as Error).message}
                </div>
              )}

              <div className="fila">
                <button
                  className="btn primario"
                  disabled={programacion.programar.isPending}
                  onClick={() =>
                    programacion.programar.mutate({
                      cron,
                      zona_horaria: actual?.zona_horaria ?? 'America/Mexico_City',
                      activa: true,
                    })
                  }
                >
                  {actual?.programacion_activa ? 'Actualizar horario' : 'Programar'}
                </button>
                {actual?.programacion_activa && (
                  <button
                    className="btn"
                    onClick={() =>
                      programacion.programar.mutate({
                        cron,
                        zona_horaria: actual.zona_horaria,
                        activa: false,
                      })
                    }
                  >
                    Pausar
                  </button>
                )}
              </div>

              {actual?.proxima_corrida && (
                <div className="chico suave">
                  Próxima corrida:{' '}
                  <b>{new Date(actual.proxima_corrida).toLocaleString('es-MX')}</b>
                </div>
              )}

              <div>
                <div className="chico suave" style={{ marginBottom: 4 }}>
                  Historial
                </div>
                {historial.data?.ejecuciones.length === 0 && (
                  <div className="chico tenue">Todavía no ha corrido.</div>
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {historial.data?.ejecuciones.map((e) => (
                    <details key={e.id} className="corrida">
                      <summary>
                        <span
                          className={`etiqueta ${e.estado === 'exito' ? 'ok' : 'critico'}`}
                        >
                          {e.estado}
                        </span>{' '}
                        <span className="chico">
                          {new Date(e.cuando).toLocaleString('es-MX')} · {e.disparo} ·{' '}
                          {e.ms} ms
                        </span>
                      </summary>
                      <table className="campos">
                        <tbody>
                          {e.pasos.map((p) => (
                            <tr key={p.paso}>
                              <td className="mono">{p.nombre}</td>
                              <td className="chico">{p.estado}</td>
                              <td className="num chico">
                                {p.filas !== undefined
                                  ? p.filas.toLocaleString('es-MX')
                                  : ''}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {e.mensaje && (
                        <div className="error-caja chico" style={{ marginTop: 6 }}>
                          {e.mensaje}
                        </div>
                      )}
                    </details>
                  ))}
                </div>
              </div>

              <button
                className="btn peligro"
                onClick={() => {
                  if (confirm(`¿Borrar el flujo "${f.nombre}"?`)) {
                    programacion.borrar.mutate(undefined, { onSuccess: nuevo })
                  }
                }}
              >
                Borrar flujo
              </button>
            </>
          )}
        </div>
      </aside>
    </div>
  )
}
