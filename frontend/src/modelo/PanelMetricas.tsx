/**
 * Las métricas del panel izquierdo, agrupadas y distinguibles.
 *
 * Eran una lista plana. Con tres se lee; con treinta —que es lo normal en cuanto un
 * modelo se usa de verdad— es un muro de renglones donde no se encuentra ninguna, y
 * además no se distinguía una métrica de una tabla de datos: las dos eran texto con
 * un contador a la derecha.
 *
 * Dos cosas, las mismas que hace Power BI:
 *
 *   1. **Tablas de medidas**: cajones que el usuario inventa —«KPIs de venta»— y que
 *      no son entidades. No tienen datos, no se relacionan con nada y no salen en el
 *      lienzo. Solo ordenan. De dónde sale cada cifra lo sigue diciendo el hecho de
 *      la métrica, y eso es lo que garantiza que mover una métrica de cajón no le
 *      cambie el número.
 *   2. **Un signo propio**: `Σ` para la métrica, y las tablas de medidas arriba y
 *      juntas, separadas de los hechos. Lo que no está en ningún cajón sigue
 *      apareciendo bajo su hecho, así que un modelo de antes no se ve peor: se ve
 *      igual.
 */

import { useState } from 'react'

import { usePlegado } from '../comunes/plegado'
import type { Definicion } from '../api/tipos'
import type { Accion } from './estado'

/** Qué métrica está abierta: un índice, o una nueva y en qué cajón nace. */
export type MetricaAbierta = number | { nueva: true; tablaMedidas: string | null }

/**
 * Un cajón que se pliega desde su cabecera, como los grupos de Flujos.
 *
 * Con cinco cajones de seis métricas, llegar al último pide atravesar treinta
 * renglones que en ese momento no interesan. Se pliega el que no estás usando y se
 * queda plegado — se recuerda por modelo y por cajón, en el navegador, con el mismo
 * mecanismo que los grupos del ETL (`usePlegado`).
 *
 * Lo que se pulsa es **toda la cabecera** y no solo el triángulo: acertarle a nueve
 * píxeles cuarenta veces al día es trabajo de verdad. Las acciones que van dentro
 * —`+`, renombrar, quitar— paran el clic para que no plieguen de paso.
 */
function Cajon({
  clave,
  punto,
  nombre,
  ayuda,
  cuenta,
  acciones,
  enRenombre,
  children,
}: {
  clave: string
  punto: string
  nombre: string
  ayuda: string
  cuenta: number
  acciones?: React.ReactNode
  /** El campo de texto, mientras se le está cambiando el nombre. */
  enRenombre?: React.ReactNode
  children: React.ReactNode
}) {
  const [plegado, alternar] = usePlegado(clave)
  return (
    <div className="cajon">
      {enRenombre ?? (
        <div
          className="cabecera-cajon plegable"
          role="button"
          tabIndex={0}
          title={plegado ? 'Abrir' : 'Plegar'}
          onClick={alternar}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              alternar()
            }
          }}
        >
          <span className="plegar" aria-hidden="true">{plegado ? '▸' : '▾'}</span>
          <span className={`punto ${punto}`} />
          <span className="nom" title={ayuda}>{nombre}</span>
          <span className="dcha">{cuenta}</span>
          {acciones}
        </div>
      )}
      {!plegado && children}
    </div>
  )
}

export function SeccionMetricas({
  definicion: d,
  despachar,
  alAbrir,
}: {
  definicion: Definicion
  despachar: (a: Accion) => void
  alAbrir: (cual: MetricaAbierta) => void
}) {
  const [creando, setCreando] = useState(false)
  const [nombreNuevo, setNombreNuevo] = useState('')
  const [renombrando, setRenombrando] = useState<string | null>(null)
  const [nombreEditado, setNombreEditado] = useState('')

  const cajones = d.tablas_medidas ?? []
  const sinCajon = d.metricas
    .map((m, i) => ({ m, i }))
    .filter(({ m }) => !m.tabla_medidas)

  /** Los hechos que tienen métricas sueltas, en el orden en que están las entidades. */
  const hechosConMetricas = d.entidades
    .filter((e) => sinCajon.some(({ m }) => m.entidad === e.nombre))
    .map((e) => e.nombre)

  const nombreLibre = (n: string, salvo?: string) =>
    !!n.trim() &&
    n.trim() !== salvo &&
    !cajones.some((c) => c.nombre === n.trim()) &&
    !d.entidades.some((e) => e.nombre === n.trim())

  function crear() {
    if (!nombreLibre(nombreNuevo)) return
    despachar({ t: 'agregar_tabla_medidas', nombre: nombreNuevo.trim() })
    setNombreNuevo('')
    setCreando(false)
  }

  function renombrar(antes: string) {
    if (nombreLibre(nombreEditado, antes)) {
      despachar({
        t: 'renombrar_tabla_medidas',
        antes,
        despues: nombreEditado.trim(),
      })
    }
    setRenombrando(null)
  }

  const metricas = (cajon: string | null, hecho?: string) =>
    d.metricas
      .map((m, i) => ({ m, i }))
      .filter(({ m }) =>
        cajon !== null
          ? m.tabla_medidas === cajon
          : !m.tabla_medidas && m.entidad === hecho,
      )
      .map(({ m, i }) => (
        <button key={m.nombre} className="metrica" onClick={() => alAbrir(i)}>
          <span className="sigma" aria-hidden="true">
            Σ
          </span>
          <span className="nom">{m.etiqueta || m.nombre}</span>
          <span className="dcha">{m.formato}</span>
        </button>
      ))

  return (
    <section className="seccion">
      <header>
        Métricas <span className="cuenta">{d.metricas.length}</span>
      </header>
      <div className="contenido">
        <div className="lista">
          {cajones.map((c) => (
            <Cajon
              key={c.nombre}
              clave={`metricas.${d.modelo}.${c.nombre}`}
              punto="medidas"
              nombre={c.nombre}
              ayuda="Tabla de medidas"
              cuenta={metricas(c.nombre).length}
              enRenombre={
                renombrando === c.nombre ? (
                  <input
                    className="mono nombre-cajon"
                    autoFocus
                    value={nombreEditado}
                    onChange={(e) => setNombreEditado(e.target.value)}
                    onBlur={() => renombrar(c.nombre)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') renombrar(c.nombre)
                      if (e.key === 'Escape') setRenombrando(null)
                    }}
                  />
                ) : undefined
              }
              acciones={
                /* Las acciones aparecen al pasar por encima: con cinco cajones,
                   tres iconos fijos en cada uno se comen el ancho del nombre, que
                   es lo único que hay que leer.

                   El clic se para aquí: van DENTRO de la cabecera, que ahora
                   pliega, y sin esto renombrar plegaría el cajón de paso. */
                <span
                  className="acciones-cajon"
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <span
                    role="button"
                    tabIndex={0}
                    title="Nueva métrica aquí"
                    onClick={() => alAbrir({ nueva: true, tablaMedidas: c.nombre })}
                    onKeyDown={(e) =>
                      e.key === 'Enter' &&
                      alAbrir({ nueva: true, tablaMedidas: c.nombre })
                    }
                  >
                    +
                  </span>
                  <span
                    role="button"
                    tabIndex={0}
                    title="Cambiar el nombre"
                    onClick={() => {
                      setNombreEditado(c.nombre)
                      setRenombrando(c.nombre)
                    }}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter') return
                      setNombreEditado(c.nombre)
                      setRenombrando(c.nombre)
                    }}
                  >
                    ✎
                  </span>
                  <span
                    role="button"
                    tabIndex={0}
                    title="Quitar el cajón. Sus métricas no se borran: vuelven a verse bajo su hecho."
                    onClick={() =>
                      despachar({ t: 'quitar_tabla_medidas', nombre: c.nombre })
                    }
                    onKeyDown={(e) =>
                      e.key === 'Enter' &&
                      despachar({ t: 'quitar_tabla_medidas', nombre: c.nombre })
                    }
                  >
                    ✕
                  </span>
                </span>
              }
            >
              {metricas(c.nombre)}
              {metricas(c.nombre).length === 0 && (
                <div className="chico tenue vacio-cajon">
                  Vacío. Pulsa <strong>+</strong> aquí, o abre una métrica que ya
                  exista y elige este cajón en «Aparece en».
                </div>
              )}
            </Cajon>
          ))}

          {/* Lo que no está en ningún cajón, bajo su hecho: es donde estaba antes. */}
          {hechosConMetricas.map((hecho) => (
            <Cajon
              key={hecho}
              clave={`metricas.${d.modelo}.${hecho}`}
              punto="hecho"
              nombre={hecho}
              ayuda="Métricas sin tabla de medidas"
              cuenta={metricas(null, hecho).length}
            >
              {metricas(null, hecho)}
            </Cajon>
          ))}
        </div>

        {d.metricas.length === 0 && cajones.length === 0 && (
          <div className="chico tenue" style={{ padding: '2px 8px' }}>
            Sin métricas todavía.
          </div>
        )}

        {creando ? (
          <input
            className="mono nombre-cajon"
            style={{ marginTop: 8 }}
            autoFocus
            placeholder="KPIs de venta"
            value={nombreNuevo}
            onChange={(e) => setNombreNuevo(e.target.value)}
            onBlur={crear}
            onKeyDown={(e) => {
              if (e.key === 'Enter') crear()
              if (e.key === 'Escape') {
                setNombreNuevo('')
                setCreando(false)
              }
            }}
          />
        ) : (
          <button
            className="btn chico"
            style={{ marginTop: 8, width: '100%' }}
            title="Un cajón para tus métricas. No tiene datos ni sale en el lienzo."
            onClick={() => setCreando(true)}
          >
            + Tabla de medidas
          </button>
        )}

        <button
          className="btn chico"
          style={{ marginTop: 6, width: '100%' }}
          disabled={d.entidades.every((e) => e.tipo !== 'hecho')}
          title={
            d.entidades.every((e) => e.tipo !== 'hecho')
              ? 'Una métrica se calcula desde un hecho: agrega primero una entidad de tipo hecho'
              : undefined
          }
          onClick={() => alAbrir({ nueva: true, tablaMedidas: null })}
        >
          + Nueva métrica
        </button>
      </div>
    </section>
  )
}
