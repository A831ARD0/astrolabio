/**
 * Un dataset: cargarlo, recargar un rango, ver su historial y ponerle horario.
 *
 * Todo esto ya existía en la API desde la Fase 1 y se usaba por `curl`. Lo que
 * aporta la pantalla es que las tres cosas que hay que mirar juntas —el modo de
 * carga, la marca máxima y el historial— estén juntas: una carga incremental que
 * trae 0 filas puede ser correcta (no hay nada nuevo) o ser un síntoma de que la
 * marca máxima quedó en el futuro, y solo se distingue viendo las dos.
 */

import { useState } from 'react'

import {
  type Dataset,
  useAccionesDataset,
  useDescribirTabla,
  useEditarDataset,
  useHistorialDataset,
  useVentanas,
} from '../api/conexiones'
import { HORARIOS } from '../api/flujos'
import { Velo } from '../comunes/Velo'

function cuando(iso: string | null): string {
  if (!iso) return 'nunca'
  return new Date(iso).toLocaleString('es-MX', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** El primer día del mes de hace n meses, en AAAA-MM-DD. */
function mesRelativo(n: number): string {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - n)
  return d.toISOString().slice(0, 10)
}

/**
 * Elegir qué columnas trae un dataset que ya existe.
 *
 * Cambiar el juego de columnas fuerza una carga completa, y eso se dice ANTES de
 * guardar. El Parquet en disco tiene las columnas viejas: mezclar un lote con otras
 * columnas haría que leer el dataset fallara, o —peor— devolviera nulos donde antes
 * había datos.
 */
function EditorColumnas({ ds }: { ds: Dataset }) {
  const detalle = useDescribirTabla(ds.conexion_id, ds.esquema_origen, ds.tabla_origen)
  const editar = useEditarDataset(ds.id)
  const [elegidas, setElegidas] = useState<string[] | null>(ds.columnas)

  const columnas = detalle.data?.columnas ?? []
  const seTrae = (c: string) => elegidas === null || elegidas.includes(c)
  const cambio =
    JSON.stringify(elegidas ?? []) !== JSON.stringify(ds.columnas ?? [])

  const alternar = (c: string) => {
    const base = elegidas ?? columnas.map((x) => x.nombre)
    const sin = base.filter((x) => x !== c)
    if (sin.length === base.length) return setElegidas([...base, c])
    if (sin.length === 0) return
    // Quitar la columna de partición o la incremental rompería la carga; el
    // backend lo rechaza, así que aquí ni se ofrece.
    if (c === ds.particionado || c === ds.incremental) return
    setElegidas(sin)
  }

  if (detalle.isLoading) return <div className="chico tenue">Leyendo el origen…</div>
  if (detalle.isError) {
    return <div className="error-caja chico">{(detalle.error as Error).message}</div>
  }

  return (
    <>
      <div className="entre">
        <span className="chico suave">
          {elegidas === null
            ? `Todas (${columnas.length}). Las que el origen agregue después también.`
            : `${elegidas.length} de ${columnas.length} columnas.`}
        </span>
        <span>
          <button className="btn chico" disabled={elegidas === null}
                  onClick={() => setElegidas(null)}>
            Todas
          </button>{' '}
          <button className="btn chico primario" disabled={!cambio || editar.isPending}
                  onClick={() => editar.mutate({ columnas: elegidas ?? [] })}>
            {editar.isPending ? 'Guardando…' : 'Guardar columnas'}
          </button>
        </span>
      </div>
      <div className="tabla-envoltura" style={{ maxHeight: 160 }}>
        <table className="datos">
          <tbody>
            {columnas.map((c) => {
              const fija = c.nombre === ds.particionado || c.nombre === ds.incremental
              return (
                <tr key={c.nombre} className={seTrae(c.nombre) ? '' : 'fuera'}>
                  <td style={{ width: 34 }}>
                    {/* Una casilla marcada y bloqueada la dibuja el navegador tan
                        tenue que se lee como desmarcada, y entonces una columna que
                        sí se trae parece que no. Para las fijas, un candado. */}
                    {fija ? (
                      <span title={`Se trae siempre: la usa la carga`}>🔒</span>
                    ) : (
                      <input type="checkbox" checked={seTrae(c.nombre)}
                             onChange={() => alternar(c.nombre)}
                             aria-label={`Traer ${c.nombre}`} />
                    )}
                  </td>
                  <td className="mono">
                    {c.nombre}
                    {fija && <span className="etiqueta dim"> la usa la carga</span>}
                  </td>
                  <td className="chico suave">{c.tipo}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {cambio && (
        <span className="chico">
          Al guardar, la siguiente carga será <strong>completa</strong>: lo que está
          en disco tiene las columnas viejas.
        </span>
      )}
      {editar.data?.avisos?.map((a) => (
        <div key={a} className="aviso-caja">{a}</div>
      ))}
      {editar.isError && (
        <div className="error-caja">{(editar.error as Error).message}</div>
      )}
    </>
  )
}

/** La ventana móvil: qué recargar cada vez, sin que nadie escriba fechas. */
function EditorVentana({ ds }: { ds: Dataset }) {
  const catalogo = useVentanas()
  const editar = useEditarDataset(ds.id)
  // 'ultimos_dias:45' no es una opción de la lista: la opción es 'ultimos_dias:N' y
  // el número va aparte. Sin descomponerlo, un dataset con ventana en días se abría
  // mostrando «(sin ventana)» y parecía no tener ninguna.
  const enDias = /^ultimos_dias:(\d+)$/.exec(ds.ventana ?? '')
  const [clave, setClave] = useState(enDias ? 'ultimos_dias:N' : (ds.ventana ?? ''))
  const [dias, setDias] = useState(enDias?.[1] ?? '45')

  const esN = clave === 'ultimos_dias:N'
  const aGuardar = esN ? `ultimos_dias:${dias}` : clave

  return (
    <>
      <div className="fila-condicion">
        <select value={clave} onChange={(e) => setClave(e.target.value)}>
          <option value="">(sin ventana)</option>
          {catalogo.data?.ventanas.map((v) => (
            <option key={v.clave} value={v.clave}>
              {v.etiqueta}
            </option>
          ))}
        </select>
        {esN && (
          <input type="number" min={1} value={dias}
                 onChange={(e) => setDias(e.target.value)} style={{ maxWidth: 90 }} />
        )}
        <button className="btn" disabled={editar.isPending || aGuardar === (ds.ventana ?? '')}
                onClick={() => editar.mutate({ ventana: aGuardar })}>
          {editar.isPending ? 'Guardando…' : 'Guardar ventana'}
        </button>
      </div>
      <span className="chico tenue">
        {ds.ventana_dicha
          ? `Hoy recargaría: ${ds.ventana_dicha}. Se recalcula en cada corrida.`
          : 'Sin ventana, «Cargar» trae solo lo nuevo por la columna incremental — ' +
            'lo que ya se trajo no se vuelve a mirar, aunque haya cambiado en el origen.'}
      </span>
      {editar.isError && (
        <div className="error-caja">{(editar.error as Error).message}</div>
      )}
    </>
  )
}

export function PanelDataset({
  ds,
  alCerrar,
}: {
  ds: Dataset
  alCerrar: () => void
}) {
  const acc = useAccionesDataset(ds.id)
  const historial = useHistorialDataset(ds.id)

  const [limite, setLimite] = useState('')
  const [desde, setDesde] = useState(mesRelativo(1))
  const [hasta, setHasta] = useState(mesRelativo(0))
  const [cron, setCron] = useState(ds.cron ?? '0 6 * * *')
  const [confirmarBaja, setConfirmarBaja] = useState(false)

  // La carga corre en segundo plano: el resultado sale del historial, no de la
  // respuesta de lanzarla. El error tambien — lo unico que puede fallar en la
  // peticion es que ya haya una carga de este dataset en marcha.
  const ultima = historial.data?.ejecuciones[0] ?? null
  const corriendo = ultima?.estado === 'corriendo'
  const resultado = ultima?.estado === 'exito' ? ultima : null
  const errorCarga =
    (acc.cargar.error as Error | null) ?? (acc.recargarRango.error as Error | null)
  const fallo = ultima?.estado === 'error' ? ultima.mensaje : null

  return (
    <Velo alCerrar={alCerrar}>
      <div className="modal ancho">
        <header>
          {ds.nombre}
          <span className="tenue chico"> · {ds.tabla_origen}</span>
        </header>
        <div className="cont">
          <div className="resumen-ds">
            <div>
              <span className="rotulo">Filas</span>
              <strong>{ds.filas.toLocaleString('es-MX')}</strong>
            </div>
            <div>
              <span className="rotulo">Tamaño</span>
              <strong>{ds.mb} MB</strong>
            </div>
            <div>
              <span className="rotulo">Última carga</span>
              <strong>{cuando(ds.ultima_carga)}</strong>
            </div>
            <div>
              <span className="rotulo">Incremental por</span>
              <strong className="mono">{ds.incremental ?? '—'}</strong>
            </div>
            <div>
              <span className="rotulo">Marca máxima</span>
              <strong className="mono">{ds.marca_maxima ?? '—'}</strong>
            </div>
            <div>
              <span className="rotulo">Partido por</span>
              <strong className="mono">{ds.particionado ?? '—'}</strong>
            </div>
            <div>
              <span className="rotulo">Columnas</span>
              <strong>{ds.columnas ? ds.columnas.length : 'todas'}</strong>
            </div>
          </div>

          {/* ---------------------------------------------------------- cargar */}
          <h4>Cargar</h4>
          <div className="fila-condicion">
            <button
              className="btn primario"
              disabled={acc.cargar.isPending || corriendo}
              onClick={() =>
                acc.cargar.mutate({
                  incremental: true,
                  limite: limite ? Number(limite) : undefined,
                })
              }
            >
              {corriendo ? 'Corriendo…' : acc.cargar.isPending ? 'Lanzando…' : 'Cargar'}
            </button>
            <button
              className="btn"
              disabled={acc.cargar.isPending || corriendo}
              title="Reescribe el dataset entero desde el origen"
              onClick={() =>
                acc.cargar.mutate({
                  incremental: false,
                  limite: limite ? Number(limite) : undefined,
                })
              }
            >
              Recargar completo
            </button>
            <input
              type="number"
              placeholder="límite de filas (para probar)"
              value={limite}
              onChange={(e) => setLimite(e.target.value)}
            />
          </div>
          <span className="chico tenue">
            {ds.ventana
              ? `«Cargar» recarga la ventana: ${ds.ventana_dicha}. «Recargar completo» se la salta y trae todo.`
              : ds.incremental
                ? ds.marca_maxima
                  ? `«Cargar» trae solo lo posterior a ${ds.marca_maxima}.`
                  : '«Cargar» trae todo esta primera vez y guarda la marca para la siguiente.'
                : 'Este dataset no tiene columna incremental: cada carga trae todo.'}
          </span>

          {/* ------------------------------------------------- recargar rango */}
          {ds.particionado && (
            <>
              <h4>Recargar un rango</h4>
              <div className="fila-condicion">
                <input
                  type="date"
                  value={desde}
                  onChange={(e) => setDesde(e.target.value)}
                />
                <input
                  type="date"
                  value={hasta}
                  onChange={(e) => setHasta(e.target.value)}
                />
                <button
                  className="btn"
                  disabled={acc.recargarRango.isPending || corriendo}
                  onClick={() => acc.recargarRango.mutate({ desde, hasta })}
                >
                  {corriendo ? 'Corriendo…' : 'Recargar rango'}
                </button>
              </div>
              <span className="chico tenue">
                Reemplaza solo las particiones que cubre el rango. Las bajas en el
                origen también se reflejan: el rango se deja igual que allá.
              </span>
            </>
          )}

          {corriendo && (
            <div className="aviso-caja">
              Corriendo en segundo plano. Puedes cerrar esta ventana: el
              resultado queda en el historial de abajo.
            </div>
          )}
          {acc.cargar.data?.esperando_a && !corriendo && (
            <div className="aviso-caja">
              En cola detrás de «{acc.cargar.data.esperando_a}».
            </div>
          )}
          {resultado && (
            <div className="aviso-caja ok-caja">
              ✓ {resultado.modo} · {resultado.filas.toLocaleString('es-MX')} fila(s) ·{' '}
              {resultado.mb} MB · {Math.round(resultado.ms)} ms · total{' '}
              {(resultado.filas_totales ?? 0).toLocaleString('es-MX')}
              {resultado.particiones.length > 0 && (
                <div className="chico mono">
                  particiones: {resultado.particiones.join(', ')}
                </div>
              )}
              {(resultado.filas_sin_particion ?? 0) > 0 && (
                <div className="chico">
                  {(resultado.filas_sin_particion ?? 0).toLocaleString('es-MX')} fila(s)
                  sin fecha válida quedaron en la partición «sin_fecha».
                </div>
              )}
            </div>
          )}
          {fallo && <div className="error-caja">{fallo}</div>}
          {errorCarga && <div className="error-caja">{errorCarga.message}</div>}

          {/* --------------------------------------------------------- columnas */}
          <h4>Columnas que se traen</h4>
          <EditorColumnas ds={ds} />

          {/* ---------------------------------------------------------- ventana */}
          {ds.particionado && (
            <>
              <h4>Ventana móvil</h4>
              <EditorVentana ds={ds} />
            </>
          )}

          {/* --------------------------------------------------------- horario */}
          <h4>Horario</h4>
          <div className="fila-condicion">
            <select
              value={HORARIOS.some((h) => h.cron === cron) ? cron : ''}
              onChange={(e) => e.target.value && setCron(e.target.value)}
            >
              <option value="">(a mano)</option>
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
            <button
              className="btn"
              disabled={acc.programar.isPending}
              onClick={() =>
                acc.programar.mutate({
                  cron,
                  zona_horaria: ds.zona_horaria,
                  activa: true,
                })
              }
            >
              Programar
            </button>
            {ds.cron && (
              <button
                className="btn chico"
                onClick={() => acc.quitarHorario.mutate()}
              >
                Quitar
              </button>
            )}
          </div>
          <span className="chico tenue">
            {ds.programacion_activa && ds.proxima_corrida
              ? `Próxima corrida: ${new Date(ds.proxima_corrida).toLocaleString('es-MX')} (${ds.zona_horaria})`
              : 'Sin horario: solo se carga cuando alguien le da al botón.'}
          </span>
          {acc.programar.isError && (
            <div className="error-caja">{(acc.programar.error as Error).message}</div>
          )}

          {/* ------------------------------------------------------- historial */}
          <h4>Historial</h4>
          <div className="tabla-envoltura" style={{ maxHeight: 200 }}>
            <table className="datos">
              <thead>
                <tr>
                  <th>Cuándo</th>
                  <th>Modo</th>
                  <th>Quién</th>
                  <th>Filas</th>
                  <th>ms</th>
                  <th>Resultado</th>
                </tr>
              </thead>
              <tbody>
                {historial.data?.ejecuciones.map((e) => (
                  <tr key={e.id}>
                    <td className="chico">{cuando(e.cuando)}</td>
                    <td className="chico">{e.modo}</td>
                    <td className="chico suave">{e.disparo}</td>
                    <td className="num">{e.filas.toLocaleString('es-MX')}</td>
                    <td className="num">{e.ms}</td>
                    <td className="chico" style={{ whiteSpace: 'normal' }}>
                      {e.estado === 'exito' ? (
                        <span className="etiqueta ok">éxito</span>
                      ) : (
                        <>
                          <span className="etiqueta critico">error</span>{' '}
                          <span className="suave">{e.mensaje}</span>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {historial.data?.ejecuciones.length === 0 && (
            <div className="vacio chico">Todavía no se ha cargado nunca.</div>
          )}

          {/* ------------------------------------------------------------ baja */}
          {confirmarBaja ? (
            <div className="aviso-caja">
              Se da de baja el registro, su historial y su horario.{' '}
              <strong>Los archivos Parquet se quedan donde están</strong> — borrar
              datos no tiene vuelta atrás, así que eso se hace a mano.
              <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                <button className="btn chico" onClick={() => setConfirmarBaja(false)}>
                  Cancelar
                </button>
                <button
                  className="btn chico peligro"
                  disabled={acc.borrar.isPending}
                  onClick={() => acc.borrar.mutate(undefined, { onSuccess: alCerrar })}
                >
                  Dar de baja
                </button>
              </div>
              {acc.borrar.isError && (
                <div className="error-caja">{(acc.borrar.error as Error).message}</div>
              )}
            </div>
          ) : (
            <div>
              <button
                className="btn chico peligro"
                onClick={() => setConfirmarBaja(true)}
              >
                Dar de baja el dataset
              </button>
            </div>
          )}
        </div>
        <footer>
          <button className="btn" onClick={alCerrar}>
            Cerrar
          </button>
        </footer>
      </div>
    </Velo>
  )
}
