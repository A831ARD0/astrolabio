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
import { useSearchParams } from 'react-router-dom'

import {
  type CuerpoFlujo,
  type Flujo,
  type PasoFlujo,
  type ResultadoPaso,
  useDisponiblesFlujo,
  useFlujos,
  useGuardarFlujo,
  useHistorialFlujo,
  useDetener,
  useProgramarFlujo,
  useReanudar,
  useSugerirOrden,
} from '../api/flujos'
import { Horario } from '../comunes/Horario'
import { zonaDelNavegador } from '../comunes/cron'
import { PanelLateral, Seccion } from '../comunes/Panel'
import { useLanzador } from '../flujos/Lanzar'

/** «3 días», «5 horas», «12 minutos». Para decidir si reanudar tiene sentido. */
function antiguedad(iso: string): string {
  const min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (min < 60) return `${min} minuto${min === 1 ? '' : 's'}`
  const h = Math.round(min / 60)
  if (h < 48) return `${h} hora${h === 1 ? '' : 's'}`
  return `${Math.round(h / 24)} días`
}

const VACIO: CuerpoFlujo = {
  nombre: '', descripcion: null, pasos: [], al_fallar: 'detener',
  reintentos: 0, espera_reintento_seg: 60,
}

export function Flujos() {
  const lista = useFlujos()
  const disponibles = useDisponiblesFlujo()
  const guardar = useGuardarFlujo()
  const sugerir = useSugerirOrden()
  const detener = useDetener()
  const { lanzar, dialogo, ejecutar, cola } = useLanzador()

  const [busca, setBusca] = useSearchParams()
  const [id, setId] = useState<number | null>(null)
  const [buscaPieza, setBuscaPieza] = useState('')
  const [soloFaltan, setSoloFaltan] = useState(false)
  const [f, setF] = useState<CuerpoFlujo>(VACIO)
  const [avisos, setAvisos] = useState<string[]>([])
  const [cron, setCron] = useState('0 6 * * *')
  // La zona por omisión es la de este navegador, no una escrita en el código: en
  // un grupo con sucursales en Tijuana y en Cancún «las 6:00» son tres horas
  // distintas, y quien programa está en una de ellas.
  const [zona, setZona] = useState(zonaDelNavegador())

  const programacion = useProgramarFlujo(id)
  const historial = useHistorialFlujo(id)
  const reanudar = useReanudar(id)
  const actual: Flujo | undefined = lista.data?.find((x) => x.id === id)

  useEffect(() => {
    if (actual) {
      setAvisos(actual.avisos)
      if (actual.cron) setCron(actual.cron)
      if (actual.programacion_activa) setZona(actual.zona_horaria)
    }
  }, [actual])

  /**
   * Abrir un flujo desde otra pantalla: `/flujos?flujo=12`.
   *
   * Sin esto, «Abrir» en Tareas solo cambiaba de pantalla y había que buscar el
   * flujo a mano entre treinta y ocho con el nombre recortado. El parámetro se
   * quita de la dirección en cuanto se usa, para que recargar no vuelva a
   * arrastrarte al mismo sitio si ya te habías movido a otro.
   */
  useEffect(() => {
    const pedido = Number(busca.get('flujo'))
    if (!pedido || !lista.data) return
    const x = lista.data.find((f) => f.id === pedido)
    if (x) cargar(x)
    setBusca({}, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busca, lista.data])

  function cargar(x: Flujo) {
    setId(x.id)
    setF({
      nombre: x.nombre,
      descripcion: x.descripcion,
      pasos: x.pasos,
      al_fallar: x.al_fallar,
      reintentos: x.reintentos,
      espera_reintento_seg: x.espera_reintento_seg,
    })
    setAvisos(x.avisos)
    setCron(x.cron ?? '0 6 * * *')
    setZona(x.cron ? x.zona_horaria : zonaDelNavegador())
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

  /**
   * Lo que ya está en el flujo que se está editando.
   *
   * Se marca en la lista de la izquierda: con mil datasets, «cuáles ya agregué»
   * no se puede llevar en la cabeza, y agregar la misma dos veces no hace nada
   * —el flujo las ignora— así que sin señal no hay forma de notarlo.
   */
  const puestas = new Set(f.pasos.map((p) => `${p.tipo}-${p.id}`))

  const todasCargas = disponibles.data?.cargas ?? []
  const todasTrans = disponibles.data?.transformaciones ?? []
  const cargasPuestas = todasCargas.filter((c) => puestas.has(`carga-${c.id}`)).length
  const transPuestas = todasTrans
    .filter((t) => puestas.has(`transformacion-${t.id}`)).length

  const filtra = <T extends { id: number; nombre: string }>(xs: T[], tipo: string) => {
    const q = buscaPieza.trim().toLowerCase()
    return xs.filter((x) =>
      (!q || x.nombre.toLowerCase().includes(q)) &&
      (!soloFaltan || !puestas.has(`${tipo}-${x.id}`)))
  }
  const cargas = filtra(todasCargas, 'carga')
  const trans = filtra(todasTrans, 'transformacion')

  const flujosEditables = (lista.data ?? []).filter((x) => !x.es_proyecto)
  const proyectos = (lista.data ?? []).filter((x) => x.es_proyecto)

  /** Qué aviso corresponde a qué paso, para pintarlo donde ocurre. */
  const avisoDe = (paso: PasoFlujo, i: number) =>
    avisos.find((a) => a.startsWith(`Paso ${i + 1} (${paso.nombre}`))

  // Los resultados por paso salen del historial y no de la respuesta de lanzar:
  // desde que la corrida va en segundo plano, lanzar solo dice "queda en cola".
  const resultados: ResultadoPaso[] = historial.data?.ejecuciones[0]?.pasos ?? []

  /** Este flujo, ¿está corriendo o esperando turno ahora mismo? */
  const enMarcha = [...(cola.data?.corriendo ?? []), ...(cola.data?.en_cola ?? [])]
    .find((t) => t.tipo === 'flujo' && t.objeto_id === id)

  return (
    <div className="editor">
      {dialogo}
      {/* --------------------------------------------------- izquierda */}
      <PanelLateral clave="flujos">
        {/* Los proyectos comparten tabla y ejecución con los flujos, pero no se
            editan aquí: sus pasos son secciones y se ordenan en el ETL. Salir en
            esta lista invitaría a editarlos por un camino que no valida lo suyo.
            En Tareas sí se ven, que es donde importa que tienen horario. */}
        <Seccion titulo="Flujos" clave="flujos-lista"
                 extra={flujosEditables.length}>
          <>
            <div className="lista">
              {flujosEditables.map((x) => {
                const dentro = puestas.has(`flujo-${x.id}`)
                return (
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
                    {/* Encadenar: este flujo como paso del que se está
                        editando. No aparece sobre sí mismo —un flujo no puede
                        llamarse a sí mismo— ni sobre los que ya están puestos. */}
                    {x.id !== id && (
                      <span
                        className={`agregar${dentro ? ' puesta' : ''}`}
                        role="button"
                        tabIndex={-1}
                        title={dentro
                          ? 'Ya es un paso de este flujo'
                          : `Encadenar: correr «${x.nombre}» como un paso de este`}
                        onClick={(e) => {
                          e.stopPropagation()   // no cambiar de flujo al agregar
                          if (!dentro) {
                            agregar({ tipo: 'flujo', id: x.id, nombre: x.nombre })
                          }
                        }}
                      >
                        {dentro ? '✓' : '+'}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
            <button className="btn chico" style={{ marginTop: 8, width: '100%' }}
                    onClick={nuevo}>
              + Nuevo flujo
            </button>
          </>
        </Seccion>

        {/* Los proyectos se editan en el ETL, pero sí se encadenan desde aquí: el
            caso útil es un maestro que trae las cuarenta sucursales y después llama
            al proyecto que las transforma. Solo se ofrece la acción de encadenar —
            pulsar el nombre no abre nada, porque aquí no hay nada que abrir. */}
        {proyectos.length > 0 && (
          <Seccion titulo="Proyectos" clave="flujos-proyectos"
                   extra={proyectos.length}>
            <div className="lista">
              {proyectos.map((x) => {
                const dentro = puestas.has(`flujo-${x.id}`)
                return (
                  <button
                    key={x.id}
                    className={dentro ? 'puesta' : ''}
                    title={dentro
                      ? 'Ya es un paso de este flujo'
                      : `Encadenar: correr «${x.nombre}» —sus ${x.pasos.length} `
                        + 'secciones— como un paso de este flujo'}
                    onClick={() => {
                      if (!dentro) {
                        agregar({ tipo: 'flujo', id: x.id, nombre: x.nombre })
                      }
                    }}
                  >
                    <span className="marca">{dentro ? '✓' : ''}</span>
                    <span className="nom">{x.nombre}</span>
                    <span className="dcha">{x.pasos.length} secciones</span>
                  </button>
                )
              })}
            </div>
          </Seccion>
        )}

        {/* `principal`: es la lista larga, la que se lleva el espacio que sobra.
            Las otras dos se quedan arriba y abajo, con sus botones a la vista. */}
        <Seccion
          titulo="Cargas"
          principal
          clave="flujos-cargas"
          extra={`${cargasPuestas} / ${todasCargas.length}`}
          /* Con cuarenta sucursales por veintiocho tablas, la lista es de mil
             renglones: sin buscador y sin saber cuáles ya están, armar un flujo
             es ir contando a ojo. El buscador va fuera de la parte que se
             desplaza, para no tener que subir a por él. */
          fijo={
            <div className="fijo">
              <input type="search" placeholder="Filtrar…" value={buscaPieza}
                     onChange={(e) => setBuscaPieza(e.target.value)} />
              <label className="casilla chico">
                <input type="checkbox" checked={soloFaltan}
                       onChange={(e) => setSoloFaltan(e.target.checked)} />
                Solo las que faltan
              </label>
            </div>
          }
        >
          <>
            <div className="lista">
              {cargas.map((c) => {
                const puesta = puestas.has(`carga-${c.id}`)
                return (
                  <button key={c.id} className={puesta ? 'puesta' : ''}
                          title={puesta ? 'Ya está en este flujo' : undefined}
                          onClick={() =>
                            agregar({ tipo: 'carga', id: c.id, nombre: c.nombre })}>
                    <span className="marca">{puesta ? '✓' : ''}</span>
                    <span className="nom mono">{c.nombre}</span>
                    {c.cron_propio && (
                      <span className="dcha" title="Ya tiene su propio horario">⏱</span>
                    )}
                  </button>
                )
              })}
              {todasCargas.length === 0 && (
                <div className="chico tenue" style={{ padding: '2px 8px' }}>
                  No hay datasets todavía.
                </div>
              )}
              {todasCargas.length > 0 && cargas.length === 0 && (
                <div className="chico tenue" style={{ padding: '2px 8px' }}>
                  {soloFaltan && !buscaPieza.trim()
                    ? 'Ya están todas en el flujo.'
                    : 'Nada con ese nombre.'}
                </div>
              )}
            </div>
          </>
        </Seccion>

        <Seccion titulo="Transformaciones" clave="flujos-trans"
                 extra={`${transPuestas} / ${todasTrans.length}`}>
          <div className="lista">
            {trans.map((t) => {
              const puesta = puestas.has(`transformacion-${t.id}`)
              return (
                <button key={t.id} className={puesta ? 'puesta' : ''}
                        title={puesta ? 'Ya está en este flujo' : undefined}
                        onClick={() =>
                          agregar({ tipo: 'transformacion', id: t.id, nombre: t.nombre })}>
                  <span className="marca">{puesta ? '✓' : ''}</span>
                  <span className="nom mono">{t.nombre}</span>
                </button>
              )
            })}
          </div>
        </Seccion>
      </PanelLateral>

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
            {/* Detener está donde se lanzó: quien echó a andar una cadena de
                treinta y ocho a la una de la tarde vuelve a ESTA pantalla a
                pararla, no a buscarla en Tareas. */}
            {enMarcha ? (
              <button
                className="btn peligro"
                disabled={detener.isPending || enMarcha.parando}
                title="Termina la tabla que está trayendo y se detiene. Lo que falte queda como cancelado."
                onClick={() => {
                  if (confirm(
                    `¿Detener «${f.nombre}»?\n\nSe termina la tabla que está ` +
                    `trayendo —no se corta a la mitad— y los pasos que falten ` +
                    `quedan como cancelados. Lo ya traído se queda.`)) {
                    detener.mutate(enMarcha.id)
                  }
                }}
              >
                {enMarcha.parando ? 'Deteniéndose…'
                  : enMarcha.estado === 'corriendo' ? 'Detener' : 'Quitar de la cola'}
              </button>
            ) : (
              <button
                className="btn primario"
                disabled={id === null || ejecutar.isPending}
                title={id === null ? 'Guárdalo antes de ejecutarlo' : undefined}
                onClick={() => lanzar(id!, f.nombre)}
              >
                Ejecutar ahora
              </button>
            )}
          </div>
        </div>

        {guardar.isError && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {(guardar.error as Error).message}
          </div>
        )}
        {ejecutar.isSuccess && (
          <div className="aviso-caja" style={{ margin: '10px 12px 0' }}>
            {ejecutar.data.esperando_a
              ? `En cola detrás de «${ejecutar.data.esperando_a}».`
              : `Corriendo ${ejecutar.data.pasos} paso(s) en segundo plano.`}{' '}
            Puedes irte de esta pantalla: el resultado queda en el historial. Si
            hace falta pararlo, el botón de arriba lo detiene al terminar la tabla
            en curso.
            {actual?.progreso && <strong> Va por el paso {actual.progreso}.</strong>}
          </div>
        )}
        {reanudar.isSuccess && (
          <div className="aviso-caja" style={{ margin: '10px 12px 0' }}>
            Continuando la corrida #{reanudar.data.continua_de}:{' '}
            {reanudar.data.saltados} paso(s) saltados, {reanudar.data.pasos} por
            correr.{' '}
            {reanudar.data.esperando_a
              ? `En cola detrás de «${reanudar.data.esperando_a}».`
              : 'Corriendo en segundo plano.'}
          </div>
        )}
        {reanudar.isError && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {(reanudar.error as Error).message}
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
              acomodar, y hay un botón que lo propone. Con el <b>+</b> de la lista
              de flujos pones un flujo entero como paso: así uno espera a que el
              anterior termine.
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
                        {p.tipo === 'carga' ? 'cargar'
                          : p.tipo === 'flujo' ? 'flujo' : 'transformar'}
                      </span>
                      <span className="nom mono">{p.nombre}</span>

                      {r && (
                        <span
                          className={`etiqueta ${
                            r.estado === 'exito'
                              ? 'ok'
                              : r.estado === 'error'
                                ? 'critico'
                                : r.estado === 'corriendo'
                                  ? 'aviso'
                                  : ''
                          }`}
                          title={r.mensaje ?? undefined}
                        >
                          {r.estado === 'exito'
                            ? (r.sub_pasos ? `${r.sub_pasos} pasos · ` : '')
                            + `${(r.filas ?? 0).toLocaleString('es-MX')} filas · ${r.ms} ms`
                            + (r.intentos ? ` · ${r.intentos} intentos` : '')
                            : r.estado === 'error'
                              ? `falló${r.intentos ? ` tras ${r.intentos} intentos` : ''}`
                              : r.estado === 'corriendo'
                                ? 'trayendo…'
                                : r.estado === 'cancelado'
                                  ? 'detenido'
                                  : r.estado === 'saltado'
                                    ? 'ya estaba'
                                    : r.estado === 'no_pedido'
                                      ? 'no se pidió'
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

              <div className="campo" style={{ marginTop: 10, maxWidth: 420 }}>
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

                {/* Con cuarenta sucursales, que una esté apagada a las seis de
                    la mañana pasa seguido, y eso a los dos minutos ya no está.
                    Cero por omisión: la primera vez que algo falla hay que
                    verlo, no taparlo con un reintento. */}
                <label style={{ marginTop: 8 }}>Antes de darlo por fallido</label>
                <div className="acciones">
                  <select
                    value={f.reintentos}
                    onChange={(e) =>
                      setF({ ...f, reintentos: Number(e.target.value) })}
                  >
                    {[0, 1, 2, 3, 5, 10].map((n) => (
                      <option key={n} value={n}>
                        {n === 0 ? 'no reintentar' : `reintentar ${n} vez${n === 1 ? '' : 'es'}`}
                      </option>
                    ))}
                  </select>
                  {f.reintentos > 0 && (
                    <>
                      <span className="chico suave">esperando</span>
                      <select
                        value={f.espera_reintento_seg}
                        onChange={(e) =>
                          setF({ ...f, espera_reintento_seg: Number(e.target.value) })}
                      >
                        {[0, 30, 60, 300, 600, 1800].map((s) => (
                          <option key={s} value={s}>
                            {s === 0 ? 'sin esperar'
                              : s < 60 ? `${s} s`
                                : `${s / 60} min`}
                          </option>
                        ))}
                      </select>
                    </>
                  )}
                </div>
                <span className="chico tenue">
                  {f.reintentos === 0
                    ? 'Un fallo se ve a la primera. Súbelo si el origen se cae a ratos.'
                    : `Cada paso se intenta hasta ${f.reintentos + 1} veces. El historial dice cuántas hicieron falta.`}
                </span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------ derecha */}
      <PanelLateral clave="flujos-der" lado="derecha" porOmision={380}>
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
              {/* De quién es paso este flujo. Va arriba del horario a propósito:
                  explica por qué un extractor sin horario propio igual corre
                  cada noche, que es lo que se perdía de vista con treinta y
                  ocho de ellos. */}
              {actual && actual.llamado_por.length > 0 && (
                <div className="aviso-caja chico">
                  Lo llama{' '}
                  <b>{actual.llamado_por.map((n) => `«${n}»`).join(', ')}</b>, así
                  que corre cuando ese flujo corre. No necesita horario
                  propio; si además le pones uno, correrá dos veces.
                </div>
              )}

              <div className="campo">
                <label>Horario</label>
                <Horario
                  cron={cron}
                  zona={zona}
                  onCambio={(c, z) => {
                    setCron(c)
                    setZona(z)
                  }}
                />
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
                      cron, zona_horaria: zona, activa: true,
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
                        cron, zona_horaria: zona, activa: false,
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
                        {/* «cancelado» no va en rojo: no se rompió nada, lo
                            paró alguien. En rojo se confunde con una avería. */}
                        <span
                          className={`etiqueta ${
                            e.estado === 'exito' ? 'ok'
                              : e.estado === 'cancelado' ? '' : 'critico'
                          }`}
                        >
                          {e.estado === 'cancelado' ? 'detenido' : e.estado}
                        </span>{' '}
                        {/* Un tramo. Sin decirlo, tres pasos en verde de treinta y
                            cinco se leen como «todo al día», que es justo la clase
                            de pantalla con la que se decide sobre un número que no
                            se recalculó. */}
                        {e.desde_paso && (
                          <span className="etiqueta aviso"
                                title={`Solo corrió del paso ${e.desde_paso} al `
                                       + 'final. Los anteriores no se pidieron.'}>
                            tramo desde {e.desde_paso}
                          </span>
                        )}{' '}
                        {e.reanuda_a && (
                          <span className="etiqueta dim"
                                title={`Continúa la corrida #${e.reanuda_a}`}>
                            continúa #{e.reanuda_a}
                          </span>
                        )}{' '}
                        <span className="chico">
                          {new Date(e.cuando).toLocaleString('es-MX')} ·{' '}
                          {e.llamado_por ? `desde «${e.llamado_por}»` : e.disparo} ·{' '}
                          {e.ms} ms
                        </span>
                      </summary>
                      <table className="campos">
                        <tbody>
                          {e.pasos.map((p) => (
                            <tr key={p.paso}>
                              <td className="mono">{p.nombre}</td>
                              <td className="chico">
                                {p.estado === 'no_pedido' ? 'no se pidió' : p.estado}
                              </td>
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
                        <div
                          className={`chico ${
                            e.estado === 'cancelado' ? 'aviso-caja' : 'error-caja'
                          }`}
                          style={{ marginTop: 6 }}
                        >
                          {e.mensaje}
                        </div>
                      )}

                      {/* Continuar: se salta lo que ya salió bien. La antigüedad
                          va a la vista y no hay límite que rechace — reanudar
                          mezcla dos momentos y quien decide si eso importa es
                          quien conoce los datos, no nosotros. */}
                      {e.reanudable && (
                        <div className="reanudar">
                          <button
                            className="btn chico primario"
                            disabled={reanudar.isPending || !!enMarcha}
                            onClick={() => {
                              if (confirm(
                                `¿Continuar la corrida #${e.id}?\n\n` +
                                `Se saltan ${e.saltaria} paso(s) que ya salieron ` +
                                `bien y se corren ${e.correria}.\n\n` +
                                `Las transformaciones se rehacen siempre. Lo que ` +
                                `se completó tiene ${antiguedad(e.cuando)}: las ` +
                                `tablas saltadas quedan con los datos de entonces.`)) {
                                reanudar.mutate(e.id)
                              }
                            }}
                          >
                            Continuar
                          </button>
                          <span className="chico suave">
                            salta {e.saltaria} · corre {e.correria} · lo hecho tiene{' '}
                            {antiguedad(e.cuando)}
                          </span>
                          {!!e.ausentes?.length && (
                            <div className="chico aviso-texto">
                              {e.ausentes.length} paso(s) de esa corrida ya no están
                              en el flujo:{' '}
                              {e.ausentes.map((a) => a.nombre).join(', ')}
                            </div>
                          )}
                        </div>
                      )}
                      {e.reanudada_por && (
                        <div className="chico tenue" style={{ marginTop: 4 }}>
                          La continuó la corrida #{e.reanudada_por}.
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
      </PanelLateral>
    </div>
  )
}
