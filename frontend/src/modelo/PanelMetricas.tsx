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

import type { Definicion } from '../api/tipos'
import type { Accion } from './estado'

/** Qué métrica está abierta: un índice, o una nueva y en qué cajón nace. */
export type MetricaAbierta = number | { nueva: true; tablaMedidas: string | null }

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
            <div key={c.nombre} className="cajon">
              {renombrando === c.nombre ? (
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
              ) : (
                <div className="cabecera-cajon">
                  <span className="punto medidas" />
                  <span className="nom" title="Tabla de medidas">
                    {c.nombre}
                  </span>
                  <span className="dcha">{metricas(c.nombre).length}</span>
                  {/* Las acciones aparecen al pasar por encima: con cinco cajones,
                      tres iconos fijos en cada uno se comen el ancho del nombre,
                      que es lo único que hay que leer. */}
                  <span className="acciones-cajon">
                    <span
                      role="button"
                      tabIndex={0}
                      title="Nueva métrica aquí"
                      onClick={() =>
                        alAbrir({ nueva: true, tablaMedidas: c.nombre })
                      }
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
                </div>
              )}
              {metricas(c.nombre)}
              {metricas(c.nombre).length === 0 && (
                <div className="chico tenue vacio-cajon">
                  Vacío. Pulsa <strong>+</strong> aquí, o abre una métrica que ya
                  exista y elige este cajón en «Aparece en».
                </div>
              )}
            </div>
          ))}

          {/* Lo que no está en ningún cajón, bajo su hecho: es donde estaba antes. */}
          {hechosConMetricas.map((hecho) => (
            <div key={hecho} className="cajon">
              <div className="cabecera-cajon">
                <span className="punto hecho" />
                <span className="nom" title="Métricas sin tabla de medidas">
                  {hecho}
                </span>
                <span className="dcha">{metricas(null, hecho).length}</span>
              </div>
              {metricas(null, hecho)}
            </div>
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
