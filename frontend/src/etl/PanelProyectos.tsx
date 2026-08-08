/**
 * El panel de proyectos y secciones del ETL.
 *
 * Sale de un problema de volumen, no de potencia. Un script de Qlik con dieciocho
 * secciones se convertía aquí en dieciocho transformaciones sueltas más un flujo que
 * las ordenaba: correcto pieza por pieza e inmanejable en conjunto — la lista de la
 * izquierda no dice qué va con qué, y para probar una hay que ir a otra pantalla. Con
 * cuarenta sucursales eso deja de escalar.
 *
 * Tres cosas que definen este panel:
 *
 * 1. **El orden que se ve es el orden que corre.** Las secciones se numeran y se
 *    mueven con ↑↓; ese número es el paso del proyecto.
 * 2. **«Desde aquí» es la razón de ser de todo esto.** Cuando la sección 12 de
 *    dieciocho es la que se está afinando, rehacer las once anteriores son veinte
 *    minutos por nada. Lo anterior queda anotado como no pedido, no como hecho.
 * 3. **Sacar una sección no la borra.** Sacar algo de una carpeta no es tirarlo, y
 *    su resultado puede estar alimentando un tablero.
 */

import { useState } from 'react'

import type { TransformacionResumen } from '../api/etl'
import {
  useAgregarSeccion,
  useBorrarProyecto,
  useCrearProyecto,
  useEditarProyecto,
  useEjecutarProyecto,
  useProyectos,
  useQuitarSeccion,
  useSueltas,
  type Proyecto,
} from '../api/proyectos'
import { Seccion } from '../comunes/Panel'
import { coincide } from '../comunes/buscar'

export function PanelProyectos({
  transformaciones,
  seleccionada,
  alAbrir,
  alNueva,
}: {
  transformaciones: TransformacionResumen[]
  seleccionada: number | null
  alAbrir: (t: TransformacionResumen) => void
  /** Crear una transformación nueva, ya dentro de este proyecto si se da uno. */
  alNueva: (proyectoId: number | null) => void
}) {
  const proyectos = useProyectos()
  const sueltas = useSueltas()
  const crear = useCrearProyecto()
  const editar = useEditarProyecto()
  const agregar = useAgregarSeccion()
  const quitar = useQuitarSeccion()
  const borrar = useBorrarProyecto()
  const ejecutar = useEjecutarProyecto()

  // Qué proyecto está desplegado. Uno solo: con cuarenta proyectos de dieciocho
  // secciones, todos abiertos es la misma lista plana de la que veníamos huyendo.
  const [abierto, setAbierto] = useState<number | null>(null)
  const [nuevo, setNuevo] = useState('')
  const [busca, setBusca] = useState('')
  const [ultimoLanzado, setUltimoLanzado] = useState<string | null>(null)

  const porId = new Map(transformaciones.map((t) => [t.id, t]))

  // Un proyecto sale si coincide su nombre O el de alguna de sus secciones: con
  // dieciocho secciones dentro, buscar «hechos_venta» tiene que llevar al proyecto
  // que la tiene, no obligar a abrirlos uno por uno.
  const buscando = busca.trim() !== ''
  const listaProyectos = (proyectos.data ?? []).filter(
    (p) => !buscando || coincide(p.nombre, busca)
      || p.secciones.some((s) => coincide(s.nombre, busca)))
  const listaSueltas = (sueltas.data?.transformaciones ?? []).filter(
    (t) => !buscando || coincide(t.nombre, busca))

  function lanzar(p: Proyecto, desde?: number) {
    ejecutar.mutate({ id: p.id, desde }, {
      onSuccess: (r) =>
        setUltimoLanzado(
          (desde && desde > 1
            ? `«${p.nombre}» desde la sección ${desde}: ${r.pasos} por correr.`
            : `«${p.nombre}»: ${r.pasos} sección(es).`)
          + (r.esperando_a ? ` Espera turno detrás de ${r.esperando_a}.` : '')
          + ' Se sigue en Tareas.',
        ),
    })
  }

  function reordenar(p: Proyecto, i: number, delta: number) {
    const j = i + delta
    if (j < 0 || j >= p.secciones.length) return
    const ids = p.secciones.map((s) => s.id)
    ;[ids[i], ids[j]] = [ids[j]!, ids[i]!]
    editar.mutate({ id: p.id, nombre: p.nombre, descripcion: p.descripcion,
                    secciones: ids as number[] })
  }

  return (
    <>
      <Seccion
        titulo="Proyectos"
        clave="etl-proyectos"
        extra={buscando
          ? `${listaProyectos.length} de ${proyectos.data?.length ?? 0}`
          : (proyectos.data?.length ?? 0)}
        fijo={
          <div className="fijo">
            <input
              type="search"
              placeholder="Buscar proyecto o sección…"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>
        }
      >
        <>
          {proyectos.isError && (
            <div className="error-caja chico" style={{ marginBottom: 8 }}>
              {(proyectos.error as Error).message}
            </div>
          )}
          {ultimoLanzado && (
            <div className="aviso-caja chico" style={{ marginBottom: 8 }}>
              {ultimoLanzado}
            </div>
          )}
          {(ejecutar.isError || editar.isError || agregar.isError
            || quitar.isError || crear.isError) && (
            <div className="error-caja chico" style={{ marginBottom: 8 }}>
              {((ejecutar.error ?? editar.error ?? agregar.error ?? quitar.error
                 ?? crear.error) as Error).message}
            </div>
          )}

          {(proyectos.data?.length ?? 0) === 0 && (
            <div className="chico tenue" style={{ padding: '2px 8px 6px' }}>
              Un proyecto agrupa transformaciones que corren en orden, con un solo
              horario. Es el equivalente a un script con secciones.
            </div>
          )}

          {listaProyectos.map((p) => {
            const desplegado = abierto === p.id
            return (
              <div key={p.id} style={{ marginBottom: 2 }}>
                <div className="lista">
                  <button
                    className={desplegado ? 'sel' : ''}
                    onClick={() => setAbierto(desplegado ? null : p.id)}
                    title={p.descripcion ?? undefined}
                  >
                    <span className="plegar" aria-hidden="true">
                      {desplegado ? '▾' : '▸'}
                    </span>
                    <span className="nom">{p.nombre}</span>
                    <span className="dcha">
                      {p.secciones.length}
                      {p.programacion_activa ? ' · ⏱' : ''}
                    </span>
                    <span
                      className="agregar"
                      role="button"
                      tabIndex={-1}
                      title={`Ejecutar las ${p.secciones.length} secciones en orden`}
                      onClick={(e) => { e.stopPropagation(); lanzar(p) }}
                    >
                      ▶
                    </span>
                  </button>
                </div>

                {desplegado && (
                  <>
                    {/* Cómo salió la última vez. Está aquí porque un proyecto no
                        sale en la pantalla de flujos —se edita en esta—, y sin esto
                        su historial no se vería en ningún sitio. */}
                    {p.ultimo_estado && (
                      <div className="chico" style={{ padding: '4px 0 2px 10px' }}>
                        <span className={`etiqueta ${
                          p.ultimo_estado === 'exito' ? 'ok'
                            : p.ultimo_estado === 'cancelado' ? '' : 'critico'
                        }`}>
                          {p.ultimo_estado === 'cancelado' ? 'detenido'
                            : p.ultimo_estado}
                        </span>{' '}
                        {p.ultimo_tramo_desde && (
                          <span className="etiqueta aviso"
                                title={`Solo corrió de la sección `
                                       + `${p.ultimo_tramo_desde} al final. Las `
                                       + 'anteriores no se pidieron, así que sus '
                                       + 'datos son de antes.'}>
                            tramo desde {p.ultimo_tramo_desde}
                          </span>
                        )}{' '}
                        <span className="tenue">
                          {p.ultima_ejecucion
                            ? new Date(p.ultima_ejecucion).toLocaleString('es-MX')
                            : ''}
                        </span>
                      </div>
                    )}
                    {p.ultimo_estado === 'error' && p.ultimo_mensaje && (
                      <div className="error-caja chico" style={{ margin: '2px 0' }}>
                        {p.ultimo_mensaje}
                      </div>
                    )}
                    {p.huerfanas.length > 0 && (
                      <div className="aviso-caja chico" style={{ margin: '4px 0' }}>
                        {p.huerfanas.length} sección(es) de este proyecto ya no
                        existen. Se quitan al guardar cualquier cambio.
                      </div>
                    )}
                    <div className="lista" style={{ paddingLeft: 10 }}>
                      {p.secciones.map((s, i) => {
                        const t = porId.get(s.id)
                        return (
                          <button
                            key={s.id}
                            className={seleccionada === s.id ? 'sel' : ''}
                            onClick={() => t && alAbrir(t)}
                            title={s.intermedia
                              ? 'Intermedia: su resultado es andamiaje de este '
                                + 'proyecto y no se ofrece fuera'
                              : (s.descripcion ?? undefined)}
                          >
                            <span className="orden-seccion">{i + 1}</span>
                            {/* Cómo salió esta sección la última vez que corrió,
                                sola o dentro del proyecto. Es lo que permite ver de
                                un golpe cuál de las dieciocho es la que rompe. */}
                            <span
                              className="punto"
                              style={{
                                background: s.ultimo_estado === 'error'
                                  ? 'var(--critico)'
                                  : s.ultimo_estado === 'exito'
                                    ? 'var(--ok)'
                                    : 'var(--borde-fuerte)',
                              }}
                              title={s.ultimo_estado
                                ? `Última vez: ${s.ultimo_estado}`
                                : 'Nunca ha corrido'}
                            />
                            <span className="nom">{s.nombre}</span>
                            {s.intermedia && (
                              <span className="etiqueta dim" title="Intermedia">
                                int
                              </span>
                            )}
                            <span className="dcha">
                              {s.tiene_datos ? s.filas.toLocaleString('es-MX') : '—'}
                            </span>
                            {/* Las cuatro acciones van en una capa que flota sobre
                                el final del renglón y solo aparece al pasar por
                                encima. En línea ocupaban ochenta píxeles de un panel
                                de doscientos treinta y dejaban los nombres en «bo…»
                                y «v…» — y con nombres como SUC_SUR__Orcamento
                                _Produtos, un nombre truncado no distingue nada. */}
                            <span className="acciones-seccion">
                              <span
                                className="agregar"
                                role="button"
                                tabIndex={-1}
                                title={`Ejecutar desde la sección ${i + 1} hasta el `
                                       + 'final. Las anteriores no se tocan.'}
                                onClick={(e) => { e.stopPropagation(); lanzar(p, i + 1) }}
                              >
                                ▶
                              </span>
                              <span
                                className="agregar"
                                role="button"
                                tabIndex={-1}
                                title="Subir"
                                onClick={(e) => { e.stopPropagation(); reordenar(p, i, -1) }}
                              >
                                ↑
                              </span>
                              <span
                                className="agregar"
                                role="button"
                                tabIndex={-1}
                                title="Bajar"
                                onClick={(e) => { e.stopPropagation(); reordenar(p, i, 1) }}
                              >
                                ↓
                              </span>
                              <span
                                className="agregar"
                                role="button"
                                tabIndex={-1}
                                title="Sacar del proyecto. No la borra: queda suelta."
                                onClick={(e) => {
                                  e.stopPropagation()
                                  quitar.mutate({ proyecto: p.id, transformacion: s.id })
                                }}
                              >
                                ✕
                              </span>
                            </span>
                          </button>
                        )
                      })}
                    </div>

                    <div style={{ display: 'flex', gap: 6, padding: '6px 0 8px 10px' }}>
                      <button className="btn chico" onClick={() => alNueva(p.id)}>
                        + Sección
                      </button>
                      <button
                        className="btn chico peligro"
                        title="Borra el proyecto y su horario. Las secciones quedan
                               sueltas, con sus datos."
                        onClick={() => {
                          if (confirm(
                            `¿Borrar el proyecto «${p.nombre}»?\n\n`
                            + `Sus ${p.secciones.length} sección(es) NO se borran: `
                            + 'quedan sueltas con sus datos. Lo que se pierde es el '
                            + 'orden y el horario.')) {
                            borrar.mutate(p.id)
                            setAbierto(null)
                          }
                        }}
                      >
                        Borrar proyecto
                      </button>
                    </div>
                  </>
                )}
              </div>
            )
          })}

          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <input
              type="text"
              className="mono"
              placeholder="nombre_del_proyecto"
              value={nuevo}
              onChange={(e) => setNuevo(e.target.value)}
              style={{ minWidth: 0, flex: 1 }}
            />
            <button
              className="btn chico"
              disabled={!nuevo.trim() || crear.isPending}
              onClick={() =>
                crear.mutate({ nombre: nuevo.trim() }, {
                  onSuccess: (p) => { setNuevo(''); setAbierto(p.id) },
                })
              }
            >
              Crear
            </button>
          </div>
        </>
      </Seccion>

      <Seccion titulo="Sin proyecto" clave="etl-sueltas"
               extra={buscando
                 ? `${listaSueltas.length} de `
                   + `${sueltas.data?.transformaciones.length ?? 0}`
                 : (sueltas.data?.transformaciones.length ?? 0)}>
        <>
          {/* No se migran solas a un proyecto de una sección cada una: eso
              convertiría doscientas transformaciones en doscientos proyectos y el
              desorden sería el mismo con otro nombre. Se mueven cuando alguien
              decide dónde van. */}
          <div className="lista">
            {listaSueltas.map((s) => {
              const t = porId.get(s.id)
              return (
                <button
                  key={s.id}
                  className={seleccionada === s.id ? 'sel' : ''}
                  onClick={() => t && alAbrir(t)}
                >
                  <span className="nom">{s.nombre}</span>
                  <span className="dcha">
                    {s.filas ? s.filas.toLocaleString('es-MX') : '—'}
                  </span>
                  {abierto !== null && (
                    <span
                      className="agregar"
                      role="button"
                      tabIndex={-1}
                      title={`Meterla como última sección del proyecto abierto`}
                      onClick={(e) => {
                        e.stopPropagation()
                        agregar.mutate({ proyecto: abierto, transformacion: s.id })
                      }}
                    >
                      +
                    </span>
                  )}
                </button>
              )
            })}
          </div>
          {abierto === null && listaSueltas.length > 0 && (
            <div className="chico tenue" style={{ padding: '6px 8px 0' }}>
              Despliega un proyecto arriba para poder meter alguna en él.
            </div>
          )}
          <button className="btn chico" style={{ marginTop: 8, width: '100%' }}
                  onClick={() => alNueva(null)}>
            + Nueva transformación
          </button>
        </>
      </Seccion>
    </>
  )
}
