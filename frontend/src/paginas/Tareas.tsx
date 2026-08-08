/**
 * Tareas: todo lo que corre solo, en una sola tabla.
 *
 * Es la respuesta a «¿qué corrió anoche y cómo salió?». Hasta ahora eso estaba
 * repartido: los flujos en su pantalla —y había que abrir cada uno para ver sus
 * pasos y su historial— y las cargas con horario propio dentro de la conexión a
 * la que pertenecen. Con cuarenta sucursales eso no se puede recorrer.
 *
 * Dos decisiones:
 *
 * 1. **Una tarea es cualquier cosa que se dispara sola**: un flujo, o un dataset
 *    con horario propio. Separarlos por su tipo interno le importa al programa,
 *    no a quien mira la pantalla a las 8 de la mañana.
 * 2. **El orden se ve sin abrir nada**: la fila del flujo se despliega y enseña
 *    sus pasos numerados, con el resultado del último que hubo en cada uno.
 *
 * Aquí no se edita. Editar sigue estando en Flujos y en Conexiones, y cada fila
 * lleva a su sitio. Una pantalla de vigilancia que además modifica invita a
 * tocar de madrugada, que es cuando peor se piensa.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { type Dataset, useConexiones, useDatasets } from '../api/conexiones'
import { type Flujo, useDetener, useFlujos } from '../api/flujos'
import { enPalabras } from '../comunes/cron'
import { useLanzador } from '../flujos/Lanzar'

/** Cómo salió la última vez. Es por lo que se filtra al entrar por la mañana. */
type Salida = 'error' | 'corriendo' | 'cancelado' | 'exito' | 'nunca'

type Filtro = 'todas' | Salida | 'sin_horario'

const FILTROS: { clave: Filtro; nombre: string }[] = [
  { clave: 'todas', nombre: 'Todas' },
  { clave: 'error', nombre: 'Fallaron' },
  { clave: 'corriendo', nombre: 'Corriendo' },
  { clave: 'exito', nombre: 'Bien' },
  { clave: 'cancelado', nombre: 'Detenidos' },
  { clave: 'nunca', nombre: 'Sin correr' },
  { clave: 'sin_horario', nombre: 'Sin horario' },
]

interface Paso {
  etiqueta: string
  nombre: string
}

/** Una fila de la tabla, ya sea un flujo o una carga con horario propio. */
interface Tarea {
  clave: string
  tipo: 'flujo' | 'carga'
  /** Solo para los flujos: si en realidad es un proyecto con secciones. */
  esProyecto?: boolean
  nombre: string
  /** De dónde sale, para poder buscarlo: la conexión, o los nombres de los pasos. */
  contexto: string
  pasos: Paso[]
  cron: string | null
  activa: boolean
  zona: string
  ultima: string | null
  salida: Salida
  detalle: string | null
  proxima: string | null
  /** A dónde se va a editarla, con lo que hay que abrir ya en la dirección. */
  destino: string
  flujoId: number | null
  /** Un dataset con horario propio que además es paso de un flujo corre dos veces. */
  tambienEn: string | null
  /** Los flujos que llaman a este. Un flujo así NO corre a mano. */
  llamadoPor: string[]
}

function salidaDe(estado: string | null, cuando: string | null): Salida {
  if (estado === 'error') return 'error'
  if (estado === 'corriendo') return 'corriendo'
  if (estado === 'cancelado') return 'cancelado'
  if (!cuando) return 'nunca'
  return 'exito'
}

/**
 * Cómo se dispara esta tarea, en una línea.
 *
 * Un flujo sin cron pero que otro flujo llama **no corre a mano**: decir «a
 * mano» de los treinta y ocho extractores era falso, y hacía imposible saber si
 * una sucursal se estaba actualizando o se había quedado fuera del maestro.
 */
function horario(t: Tarea): string {
  const dentro = t.llamadoPor.length
    ? `dentro de «${t.llamadoPor.join('», «')}»`
    : null
  if (!t.cron) return dentro ?? 'a mano'
  const propio = enPalabras(t.cron, t.zona) + (t.activa ? '' : ' (pausado)')
  // Con horario propio Y dentro de un maestro corre dos veces. Se dice.
  return dentro ? `${propio} · y ${dentro}` : propio
}

function cuando(iso: string | null): string {
  if (!iso) return 'nunca'
  return new Date(iso).toLocaleString('es-MX', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function duracion(ms: number | null): string {
  if (ms === null || ms === undefined) return ''
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  return `${Math.round(ms / 60_000)} min`
}

function Marca({ s }: { s: Salida }) {
  if (s === 'error') return <span className="etiqueta critico">falló</span>
  if (s === 'corriendo') return <span className="etiqueta aviso">corriendo</span>
  // Detenido a propósito: ni verde ni rojo. No se rompió nada, pero tampoco
  // acabó, y el que mire por la mañana tiene que poder distinguirlo.
  if (s === 'cancelado') return <span className="etiqueta">detenido</span>
  if (s === 'nunca') return <span className="etiqueta">sin correr</span>
  return <span className="etiqueta ok">bien</span>
}

function deFlujo(f: Flujo): Tarea {
  return {
    clave: `f${f.id}`,
    tipo: 'flujo',
    nombre: f.nombre,
    contexto: f.pasos.map((p) => p.nombre ?? '').join(' '),
    pasos: f.pasos.map((p) => ({
      etiqueta: p.tipo === 'carga' ? 'cargar'
        : p.tipo === 'flujo' ? 'flujo' : 'transformar',
      nombre: p.nombre ?? `#${p.id}`,
    })),
    // Un proyecto es un flujo restringido a transformaciones. Aqui sale igual
    // —tiene horario y corre de madrugada— pero dicho por su nombre: quien mira
    // esta pantalla tiene que poder ir al sitio donde de verdad se edita.
    esProyecto: f.es_proyecto,
    cron: f.cron,
    activa: f.programacion_activa,
    zona: f.zona_horaria,
    ultima: f.ultima_ejecucion,
    salida: salidaDe(f.ultimo_estado, f.ultima_ejecucion),
    // Mientras corre, lo util es por que paso va; el mensaje de la vez anterior
    // solo estorba.
    detalle: f.progreso ?? f.ultimo_mensaje ?? (duracion(f.ultima_ms) || null),
    proxima: f.proxima_corrida,
    destino: f.es_proyecto ? '/etl' : `/flujos?flujo=${f.id}`,
    flujoId: f.id,
    tambienEn: null,
    llamadoPor: f.llamado_por,
  }
}

function deCarga(ds: Dataset, conexion: string, enFlujo: string | null): Tarea {
  return {
    clave: `d${ds.id}`,
    tipo: 'carga',
    nombre: ds.nombre,
    contexto: `${conexion} ${ds.tabla_origen}`,
    pasos: [{ etiqueta: 'cargar', nombre: `${conexion} · ${ds.tabla_origen}` }],
    cron: ds.cron,
    activa: ds.programacion_activa,
    zona: ds.zona_horaria,
    ultima: ds.ultima_carga,
    salida: salidaDe(ds.ultimo_estado, ds.ultima_carga),
    detalle: ds.filas ? `${ds.filas.toLocaleString('es-MX')} filas` : null,
    proxima: ds.proxima_corrida,
    destino: `/conexiones?dataset=${ds.id}`,
    flujoId: null,
    tambienEn: enFlujo,
    llamadoPor: [],
  }
}

export function Tareas() {
  const flujos = useFlujos()
  const datasets = useDatasets()
  const conexiones = useConexiones()
  const { lanzar, dialogo, ejecutar, cola } = useLanzador()
  const detener = useDetener()

  const [busca, setBusca] = useState('')
  const [filtro, setFiltro] = useState<Filtro>('todas')
  const [abierta, setAbierta] = useState<string | null>(null)

  const tareas = useMemo<Tarea[]>(() => {
    const fs = flujos.data ?? []
    const ds = datasets.data?.datasets ?? []
    const nombreCon = new Map((conexiones.data ?? []).map((c) => [c.id, c.nombre]))

    // Qué dataset es paso de qué flujo. Un dataset puede estar en varios; con el
    // primero basta para avisar de que no solo corre por su cuenta.
    const enFlujo = new Map<number, string>()
    for (const f of fs) {
      for (const p of f.pasos) {
        if (p.tipo === 'carga' && !enFlujo.has(p.id)) enFlujo.set(p.id, f.nombre)
      }
    }

    return [
      ...fs.map(deFlujo),
      // Solo las cargas con horario propio: las que corren dentro de un flujo ya
      // están representadas por su flujo, y repetirlas duplicaría la lista.
      ...ds
        .filter((d) => d.cron)
        .map((d) => deCarga(d, nombreCon.get(d.conexion_id) ?? '?',
                            enFlujo.get(d.id) ?? null)),
    ]
  }, [flujos.data, datasets.data, conexiones.data])

  const visibles = useMemo(() => {
    const q = busca.trim().toLowerCase()
    return tareas
      .filter((t) => {
        // Un flujo al que llama un maestro SÍ corre solo, aunque no tenga cron:
        // meterlo en «sin horario» manda a revisar treinta y ocho tareas que
        // estan bien y esconde la que de verdad se quedo fuera.
        if (filtro === 'sin_horario') {
          return (!t.cron || !t.activa) && t.llamadoPor.length === 0
        }
        if (filtro !== 'todas' && t.salida !== filtro) return false
        return true
      })
      .filter((t) =>
        !q || t.nombre.toLowerCase().includes(q) || t.contexto.toLowerCase().includes(q))
      // Lo que falló arriba: es lo único de la pantalla que pide algo.
      .sort((a, b) => {
        const peso = { error: 0, corriendo: 1, cancelado: 2, nunca: 3, exito: 4 }
        if (peso[a.salida] !== peso[b.salida]) return peso[a.salida] - peso[b.salida]
        return a.nombre.localeCompare(b.nombre, 'es')
      })
  }, [tareas, busca, filtro])

  const fallaron = tareas.filter((t) => t.salida === 'error').length

  // Lo que esta vivo AHORA. La columna «Resultado» dice como salio la vez
  // anterior; sin esto, un flujo lanzado hace un minuto sigue diciendo «bien»
  // de anoche mientras corre, que es justo lo que confunde.
  const enMarcha = new Set<number | null>(
    [...(cola.data?.corriendo ?? []), ...(cola.data?.en_cola ?? [])]
      .filter((t) => t.tipo === 'flujo').map((t) => t.objeto_id))
  const enCola = new Set<number | null>(
    (cola.data?.en_cola ?? []).filter((t) => t.tipo === 'flujo')
      .map((t) => t.objeto_id))
  const cargando = flujos.isLoading || datasets.isLoading

  return (
    <div className="pagina pegada">
      {dialogo}
      <div className="cabecera-pagina">
        <h1>Tareas</h1>
        <p className="suave chico">
          Todo lo que corre solo: los flujos y las cargas con horario propio. Qué
          hace cada uno, en qué orden, cuándo corrió y cómo salió.
        </p>
      </div>

      {flujos.isError && <div className="error-caja">{(flujos.error as Error).message}</div>}

      <div className="barra-filtros">
        <input
          type="search"
          placeholder="Buscar tarea, tabla o conexión…"
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          style={{ flex: '1 1 240px' }}
        />
        <div className="acciones">
          {FILTROS.map((f) => (
            <button
              key={f.clave}
              className={`btn chico${filtro === f.clave ? ' primario' : ''}`}
              onClick={() => setFiltro(f.clave)}
            >
              {f.nombre}
            </button>
          ))}
        </div>
        <span className="chico suave">
          {visibles.length} de {tareas.length}
          {fallaron > 0 && <span className="critico-texto"> · {fallaron} con fallo</span>}
        </span>
        <div className="acciones" style={{ marginLeft: 'auto' }}>
          <Link className="btn chico" to="/flujos">Editar flujos</Link>
        </div>
      </div>

      {ejecutar.isError && (
        <div className="error-caja">{(ejecutar.error as Error).message}</div>
      )}

      {/* La cola: lo unico que responde «¿sigue viva la extraccion de anoche?».
          Solo aparece cuando hay algo, para no ocupar sitio el resto del dia. */}
      {(cola.data?.corriendo.length || cola.data?.en_cola.length) ? (
        <div className="aviso-caja">
          {cola.data.corriendo.map((t) => (
            <div key={t.id} className="fila-cola">
              <span className="etiqueta aviso">
                {t.parando ? 'deteniéndose' : 'corriendo'}
              </span>
              <strong>{t.nombre}</strong>
              <span className="chico suave">
                desde {t.iniciado_en ? cuando(t.iniciado_en) : '—'} · {t.quien}
                {t.a_la_par && ' · a la par'}
                {t.parando && ' · termina la tabla en curso y para'}
              </span>
              {/* Solo los flujos: una carga suelta no tiene pasos donde pararse.
                  Ofrecer el botón y que conteste 409 sería peor que no tenerlo. */}
              {t.tipo === 'flujo' && !t.parando && (
                <button className="btn chico peligro" style={{ marginLeft: 'auto' }}
                        disabled={detener.isPending}
                        title="Termina la tabla que está trayendo y se detiene. Lo que falte queda como cancelado."
                        onClick={() => {
                          if (confirm(
                            `¿Detener «${t.nombre}»?\n\nSe termina la tabla que ` +
                            `está trayendo —no se corta a la mitad— y los pasos ` +
                            `que falten quedan como cancelados. Lo ya traído se ` +
                            `queda.`)) {
                            detener.mutate(t.id)
                          }
                        }}>
                  Detener
                </button>
              )}
            </div>
          ))}
          {cola.data.en_cola.map((t, i) => (
            <div key={t.id} className="fila-cola">
              <span className="etiqueta">turno {i + 1}</span>
              <strong>{t.nombre}</strong>
              <span className="chico suave">pedido por {t.quien}</span>
              <button className="btn chico" style={{ marginLeft: 'auto' }}
                      disabled={detener.isPending}
                      onClick={() => detener.mutate(t.id)}>
                Sacar de la cola
              </button>
            </div>
          ))}
          {detener.data && (
            <div className="chico suave" style={{ marginTop: 4 }}>
              {detener.data.mensaje}
            </div>
          )}
          {detener.isError && (
            <div className="error-caja chico" style={{ marginTop: 4 }}>
              {(detener.error as Error).message}
            </div>
          )}
        </div>
      ) : null}

      {cargando ? (
        <div className="vacio">Cargando…</div>
      ) : tareas.length === 0 ? (
        <div className="vacio">
          Todavía no hay nada programado. Un flujo reúne varias cargas y
          transformaciones bajo un solo horario.
          <div style={{ marginTop: 10 }}>
            <Link className="btn primario" to="/flujos">Crear un flujo</Link>
          </div>
        </div>
      ) : visibles.length === 0 ? (
        <div className="vacio">Ninguna tarea coincide con el filtro.</div>
      ) : (
        <div className="tabla-envoltura">
          <table className="datos">
            <thead>
              <tr>
                <th style={{ width: 24 }} />
                <th>Tarea</th>
                <th>Qué hace</th>
                <th>Horario</th>
                <th>Última</th>
                <th>Resultado</th>
                <th>Próxima</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visibles.map((t) => {
                const abierto = abierta === t.clave
                return [
                  <tr key={t.clave}>
                    <td>
                      <button
                        className="plegar"
                        aria-expanded={abierto}
                        title={abierto ? 'Plegar' : 'Ver los pasos'}
                        onClick={() => setAbierta(abierto ? null : t.clave)}
                      >
                        {abierto ? '▾' : '▸'}
                      </button>
                    </td>
                    <td>
                      <strong>{t.nombre}</strong>{' '}
                      {/* «proyecto» y no «flujo» aunque por dentro sea lo mismo:
                          quien lee esta pantalla necesita saber dónde se edita. */}
                      <span className="etiqueta dim">
                        {t.esProyecto ? 'proyecto' : t.tipo}
                      </span>
                      {t.tambienEn && (
                        <div className="chico aviso-texto">
                          también corre dentro de «{t.tambienEn}»
                        </div>
                      )}
                      {t.llamadoPor.length > 0 && (
                        <div className="chico suave">
                          lo llama {t.llamadoPor.map((n) => `«${n}»`).join(', ')}
                        </div>
                      )}
                    </td>
                    <td className="chico suave">
                      {t.tipo === 'flujo'
                        ? t.esProyecto
                          ? `${t.pasos.length} `
                            + `secci${t.pasos.length === 1 ? 'ón' : 'ones'}`
                          : `${t.pasos.length} paso${t.pasos.length === 1 ? '' : 's'}`
                        : t.contexto}
                    </td>
                    <td className="chico">{horario(t)}</td>
                    <td className="chico">{cuando(t.ultima)}</td>
                    <td>
                      {enMarcha.has(t.flujoId) ? (
                        <span className="etiqueta aviso">
                          {enCola.has(t.flujoId) ? 'en cola' : 'corriendo'}
                        </span>
                      ) : (
                        <Marca s={t.salida} />
                      )}{' '}
                      {t.detalle && <span className="chico suave">{t.detalle}</span>}
                    </td>
                    <td className="chico suave">
                      {t.proxima ? cuando(t.proxima) : '—'}
                    </td>
                    <td className="acciones">
                      {t.flujoId !== null && (
                        <button
                          className="btn chico"
                          disabled={ejecutar.isPending || enMarcha.has(t.flujoId)}
                          onClick={() => lanzar(t.flujoId!, t.nombre)}
                        >
                          Ejecutar
                        </button>
                      )}
                      <Link className="btn chico" to={t.destino}>Abrir</Link>
                    </td>
                  </tr>,
                  abierto && (
                    <tr key={`${t.clave}-pasos`}>
                      <td />
                      <td colSpan={7}>
                        <ol className="pasos-tarea">
                          {t.pasos.map((p, i) => (
                            <li key={i}>
                              <span className="etiqueta dim">{p.etiqueta}</span>{' '}
                              <span className="mono chico">{p.nombre}</span>
                            </li>
                          ))}
                        </ol>
                        {t.tipo === 'flujo' && (
                          <p className="chico tenue">
                            Corren en este orden. Si uno falla, el flujo decide si
                            sigue o se detiene.
                          </p>
                        )}
                      </td>
                    </tr>
                  ),
                ]
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
