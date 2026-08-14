/**
 * Editor del modelo semántico.
 *
 * Tres estados y no dos, que es lo que distingue guardar de publicar:
 *
 *   1. **En pantalla** — lo que se está tocando. No sale del navegador.
 *   2. **Borrador** — guardado en el servidor, sobrevive a cerrar la pestaña y a
 *      cambiar de máquina, y NO lo ve nadie más que quien edita el modelo. Los
 *      tableros siguen leyendo lo publicado.
 *   3. **Publicado** — una versión inmutable. Los tableros están anclados a una
 *      concreta, así que publicar es lo único que puede cambiarle la cifra a
 *      alguien, y por eso es un acto aparte y con nota.
 *
 * Descartar tira el borrador entero y devuelve el modelo a lo publicado. Esa es
 * la red que permite probar cosas: se puede romper el modelo a gusto sabiendo
 * que hay un botón para volver.
 */

import { useEffect, useMemo, useReducer, useState } from 'react'
import { useParams } from 'react-router-dom'

import { PanelLateral } from '../comunes/Panel'
import { Velo } from '../comunes/Velo'
import {
  useDefinicion,
  useDescartarBorrador,
  useGuardarBorrador,
  usePublicar,
  useVersiones,
} from '../api/hooks'
import type { Entidad, Metrica } from '../api/tipos'
import { DialogoEntidad } from '../modelo/DialogoEntidad'
import { Lienzo, type Seleccion } from '../modelo/Lienzo'
import { PanelDatos } from '../modelo/PanelDatos'
import { PanelDiagnostico } from '../modelo/PanelDiagnostico'
import { PanelEntidad } from '../modelo/PanelEntidad'
import { PanelMetrica } from '../modelo/PanelMetrica'
import { SeccionMetricas, type MetricaAbierta } from '../modelo/PanelMetricas'
import { PanelRelacion } from '../modelo/PanelRelacion'
import { PanelRelaciones } from '../modelo/PanelRelaciones'
import { VistaYaml } from '../modelo/VistaYaml'
import { deshacer, estadoInicial, haCambiado, reducir } from '../modelo/estado'
import { disponer, medidaSupuesta } from '../modelo/disponer'

type Pestana = 'lienzo' | 'relaciones' | 'datos' | 'yaml'

/** Lo que se corre a la derecha cada tabla nueva. Más que el nodo más ancho. */
const ANCHO_COLUMNA = 320
type Panel = 'seleccion' | 'diagnostico'

const METRICA_NUEVA: Metrica = {
  nombre: '',
  etiqueta: '',
  entidad: '',
  expresion: '',
  formato: 'numero',
}

export function Modelo() {
  const modeloId = Number(useParams().id)
  const cargada = useDefinicion(modeloId)
  const versiones = useVersiones(modeloId)
  const guardar = useGuardarBorrador(modeloId)
  const descartar = useDescartarBorrador(modeloId)
  const publicar = usePublicar(modeloId)

  const [estado, despachar] = useReducer(reducir, estadoInicial)
  const [pestana, setPestana] = useState<Pestana>('lienzo')
  const [panel, setPanel] = useState<Panel>('seleccion')
  const [seleccion, setSeleccion] = useState<Seleccion | null>(null)
  const [resaltadas, setResaltadas] = useState<Set<string> | null>(null)
  const [dialogoEntidad, setDialogoEntidad] = useState(false)
  const [metricaAbierta, setMetricaAbierta] = useState<MetricaAbierta | null>(null)
  const [notas, setNotas] = useState('')
  const [confirmarDescarte, setConfirmarDescarte] = useState(false)

  // Cargar en el borrador. Si el modelo no traía disposición (viene de un YAML
  // escrito a mano), se coloca una inicial para que se pueda leer al abrirlo.
  useEffect(() => {
    if (!cargada.data) return
    const d = cargada.data.definicion
    despachar({
      t: 'cargar',
      definicion:
        Object.keys(d.disposicion ?? {}).length > 0
          ? d
          : {
              ...d,
              // Sin nada dibujado todavía no hay medidas, así que se estiman a
              // partir del número de columnas. Es lo que evita que un modelo
              // escrito a mano en YAML se abra con las tablas unas encima de otras.
              disposicion: disponer(
                d,
                Object.fromEntries(
                  d.entidades.map((e) => [e.nombre, medidaSupuesta(e)]),
                ),
              ),
            },
    })
  }, [cargada.data])

  const d = estado.borrador
  const sucio = haCambiado(estado)
  const borrador = cargada.data?.borrador ?? null
  const hayBorrador = borrador !== null

  // Avisar antes de cerrar la pestaña con trabajo sin guardar.
  useEffect(() => {
    if (!sucio) return
    const aviso = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', aviso)
    return () => window.removeEventListener('beforeunload', aviso)
  }, [sucio])

  const relacionesPorEntidad = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of d?.relaciones ?? []) {
      for (const ent of [r.desde[0], r.hasta[0]]) {
        m.set(ent, (m.get(ent) ?? 0) + 1)
      }
    }
    return m
  }, [d?.relaciones])

  if (cargada.isLoading || !d) return <div className="vacio">Cargando modelo…</div>
  if (cargada.isError) {
    return (
      <div className="pagina">
        <div className="error-caja">{(cargada.error as Error).message}</div>
      </div>
    )
  }

  // El diagnóstico que llega es de la versión guardada. Mientras hay cambios sin
  // guardar puede estar desfasado, y decirlo es mejor que mostrarlo como si
  // correspondiera al borrador.
  const problemas = cargada.data?.problemas ?? []
  const entidadSel =
    seleccion?.tipo === 'entidad'
      ? d.entidades.find((e) => e.nombre === seleccion.id)
      : undefined

  function agregarEntidad(e: Entidad) {
    // A la derecha de todo, en una columna para ella sola. Antes se repartían en
    // una cuadrícula de cuatro por fila separadas 340 en vertical, y una tabla de
    // veintidós columnas mide más de 500: las tablas se solapaban unas encima de
    // otras. Aquí no se puede solapar nada, y para ordenar el conjunto está
    // «Reorganizar» en el lienzo.
    const derecha = Object.values(d?.disposicion ?? {}).reduce(
      (max, p) => Math.max(max, p.x),
      -ANCHO_COLUMNA,
    )
    despachar({ t: 'agregar_entidad', entidad: e })
    despachar({
      t: 'mover',
      entidad: e.nombre,
      x: derecha + ANCHO_COLUMNA,
      y: 0,
    })
    setDialogoEntidad(false)
    setSeleccion({ tipo: 'entidad', id: e.nombre })
  }

  return (
    <div className="editor">
      {/* ------------------------------------------------------ izquierda */}
      <PanelLateral clave="modelo">
        <section className="seccion">
          <header>
            Entidades <span className="cuenta">{d.entidades.length}</span>
          </header>
          <div className="contenido">
            <div className="lista">
              {d.entidades.map((e) => (
                <button
                  key={e.nombre}
                  className={
                    seleccion?.tipo === 'entidad' && seleccion.id === e.nombre ? 'sel' : ''
                  }
                  onClick={() => {
                    setSeleccion({ tipo: 'entidad', id: e.nombre })
                    setPanel('seleccion')
                  }}
                >
                  <span className={`punto ${e.tipo}`} />
                  <span className="nom">{e.nombre}</span>
                  <span className="dcha">{e.campos.length}</span>
                </button>
              ))}
            </div>
            <button
              className="btn chico"
              style={{ marginTop: 8, width: '100%' }}
              onClick={() => setDialogoEntidad(true)}
            >
              + Agregar entidad
            </button>
          </div>
        </section>

        <SeccionMetricas
          definicion={d}
          despachar={despachar}
          alAbrir={setMetricaAbierta}
        />

        <section className="seccion">
          <header>Versiones</header>
          <div className="contenido">
            <div className="lista">
              {versiones.data?.versiones.map((v) => (
                <button
                  key={v.version}
                  style={{ cursor: 'default' }}
                  title={`${v.entidades} entidades · ${v.relaciones} relaciones · ${v.metricas} métricas`}
                >
                  <span className="nom">
                    v{v.version}
                    {v.notas ? ` · ${v.notas}` : ''}
                  </span>
                  <span className="dcha">
                    {new Date(v.creado_en).toLocaleDateString('es-MX')}
                  </span>
                </button>
              ))}
            </div>
            <div className="chico tenue" style={{ padding: '6px 8px 0' }}>
              Las versiones son inmutables: <strong>publicar</strong> crea una
              nueva y no toca las anteriores. Guardar el borrador no crea
              ninguna.
            </div>
          </div>
        </section>
      </PanelLateral>

      {/* --------------------------------------------------------- centro */}
      <div className="centro">
        <div className="barra-editor">
          <strong className="mono">{d.modelo}</strong>
          <span className={`etiqueta${hayBorrador ? ' aviso' : ''}`}>
            {hayBorrador
              ? `borrador · sobre v${cargada.data?.version_vigente}`
              : `v${cargada.data?.version}`}
          </span>

          <div className="pestanas">
            <button
              className={pestana === 'lienzo' ? 'activo' : ''}
              onClick={() => setPestana('lienzo')}
            >
              Lienzo
            </button>
            <button
              className={pestana === 'relaciones' ? 'activo' : ''}
              onClick={() => setPestana('relaciones')}
              title="Todas las relaciones en una tabla, para revisarlas de un vistazo"
            >
              Relaciones <span className="cuenta">{d.relaciones.length}</span>
            </button>
            <button
              className={pestana === 'datos' ? 'activo' : ''}
              onClick={() => setPestana('datos')}
              title="Ejecutar el modelo tal como está en pantalla"
            >
              Datos
            </button>
            <button
              className={pestana === 'yaml' ? 'activo' : ''}
              onClick={() => setPestana('yaml')}
            >
              YAML
            </button>
          </div>

          <div
            style={{
              marginLeft: 'auto',
              display: 'flex',
              gap: 8,
              alignItems: 'center',
              minWidth: 0,
            }}
          >
            {sucio ? (
              <span className="sin-guardar">cambios sin guardar</span>
            ) : (
              hayBorrador && <span className="sin-guardar">sin publicar</span>
            )}
            <button
              className="btn"
              disabled={estado.historial.length === 0}
              onClick={() => despachar({ t: 'cargar', definicion: deshacer(estado).borrador! })}
              title="Deshacer el último cambio"
            >
              Deshacer
            </button>
            {/* Descartar solo cuando hay algo que descartar: un botón que a
                veces no hace nada enseña a no fiarse de los botones. */}
            {(hayBorrador || sucio) && (
              <button
                className="btn peligro"
                disabled={descartar.isPending}
                onClick={() => setConfirmarDescarte(true)}
                title="Tirar todo lo no publicado y volver a la versión vigente"
              >
                Descartar
              </button>
            )}
            <button
              className="btn"
              disabled={!sucio || guardar.isPending}
              onClick={() => guardar.mutate({ definicion: d })}
              title="Guarda el trabajo sin tocar lo que ven los tableros"
            >
              {guardar.isPending ? 'Guardando…' : 'Guardar borrador'}
            </button>
            <input
              type="text"
              placeholder="Nota de la versión"
              value={notas}
              onChange={(e) => setNotas(e.target.value)}
              style={{ flex: '0 1 150px' }}
            />
            <button
              className="btn primario"
              disabled={(!hayBorrador && !sucio) || publicar.isPending || guardar.isPending}
              title={
                sucio
                  ? 'Guarda el borrador y publícalo como versión nueva'
                  : 'Publica el borrador como versión nueva'
              }
              onClick={() => {
                const notaFinal = notas.trim() || undefined
                // Si hay cambios en pantalla se guardan ANTES de publicar: el
                // servidor publica lo que hay en el borrador, no lo que tenga
                // abierto un navegador. Hacerlo en dos pasos aquí es lo que
                // evita que «publicar» se coma cambios que no había visto.
                if (sucio) {
                  guardar.mutate(
                    { definicion: d },
                    {
                      onSuccess: () =>
                        publicar.mutate(
                          { notas: notaFinal },
                          { onSuccess: () => setNotas('') },
                        ),
                    },
                  )
                } else {
                  publicar.mutate({ notas: notaFinal }, { onSuccess: () => setNotas('') })
                }
              }}
            >
              {publicar.isPending ? 'Publicando…' : 'Publicar versión'}
            </button>
          </div>
        </div>

        {(guardar.isError || publicar.isError || descartar.isError) && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {((guardar.error ?? publicar.error ?? descartar.error) as Error).message}
          </div>
        )}

        {hayBorrador && !sucio && (
          <div className="aviso-caja" style={{ margin: '10px 12px 0' }}>
            Estás viendo un borrador guardado
            {borrador?.actualizado_por ? ` por ${borrador.actualizado_por}` : ''}
            {borrador ? ` el ${new Date(borrador.actualizado_en).toLocaleString('es-MX')}` : ''}.
            Los tableros siguen usando la versión {cargada.data?.version_vigente}.
          </div>
        )}

        {pestana === 'datos' ? (
          <PanelDatos modeloId={modeloId} definicion={d} />
        ) : pestana === 'relaciones' ? (
          <PanelRelaciones
            definicion={d}
            despachar={(a) => {
              despachar(a)
              if (a.t === 'quitar_relacion') setSeleccion(null)
            }}
            seleccionada={seleccion?.tipo === 'relacion' ? Number(seleccion.id) : null}
            alSeleccionar={(i) => {
              setSeleccion({ tipo: 'relacion', id: i })
              setPanel('seleccion')
            }}
          />
        ) : pestana === 'lienzo' ? (
          <Lienzo
            definicion={d}
            problemas={problemas}
            seleccion={seleccion}
            alSeleccionar={(s) => {
              setSeleccion(s)
              if (s) setPanel('seleccion')
            }}
            despachar={despachar}
            resaltadas={resaltadas ?? undefined}
          />
        ) : (
          <VistaYaml modeloId={modeloId} hayCambiosSinGuardar={sucio} />
        )}
      </div>

      {/* -------------------------------------------------------- derecha */}
      <aside className="der">
        <div className="barra-editor">
          <div className="pestanas">
            <button
              className={panel === 'seleccion' ? 'activo' : ''}
              onClick={() => setPanel('seleccion')}
            >
              Selección
            </button>
            <button
              className={panel === 'diagnostico' ? 'activo' : ''}
              onClick={() => setPanel('diagnostico')}
            >
              Diagnóstico
              {problemas.some((p) => p.gravedad === 'critico') && (
                <span className="etiqueta critico" style={{ marginLeft: 6 }}>
                  {problemas.filter((p) => p.gravedad === 'critico').length}
                </span>
              )}
            </button>
          </div>
        </div>

        {panel === 'diagnostico' ? (
          <>
            {sucio && (
              <div className="aviso-caja" style={{ margin: '10px 12px 0' }}>
                Este diagnóstico es de la versión guardada. Guarda para revisarlo
                con tus cambios.
              </div>
            )}
            <PanelDiagnostico problemas={problemas} alResaltar={setResaltadas} />
          </>
        ) : entidadSel ? (
          <PanelEntidad
            entidad={entidadSel}
            definicion={d}
            despachar={(a) => {
              despachar(a)
              if (a.t === 'quitar_entidad') setSeleccion(null)
            }}
            enRelaciones={relacionesPorEntidad.get(entidadSel.nombre) ?? 0}
          />
        ) : seleccion?.tipo === 'relacion' ? (
          <PanelRelacion
            definicion={d}
            indice={Number(seleccion.id)}
            despachar={(a) => {
              despachar(a)
              if (a.t === 'quitar_relacion') setSeleccion(null)
            }}
          />
        ) : (
          <div className="vacio">
            Elige una entidad o una relación en el lienzo.
            <br />
            <br />
            Para relacionar dos tablas, arrastra de un campo a otro.
          </div>
        )}
      </aside>

      {dialogoEntidad && (
        <DialogoEntidad
          yaUsadas={new Set(d.entidades.map((e) => e.nombre))}
          alAceptar={agregarEntidad}
          alCerrar={() => setDialogoEntidad(false)}
        />
      )}

      {/* Descartar no se deshace: no hay historial de borradores del que sacarlo
          otra vez. Un clic de más ahí cuesta una tarde de trabajo. */}
      {confirmarDescarte && (
        <Velo alCerrar={() => setConfirmarDescarte(false)}>
          <div className="modal">
            <header>Descartar los cambios sin publicar</header>
            <div className="cont">
              <p>
                Se tira todo lo que no esté publicado y el modelo vuelve a la
                versión {cargada.data?.version_vigente}, que es la que están
                usando los tableros.
              </p>
              <p className="chico tenue">
                Esto no se puede deshacer: un borrador descartado no queda en el
                historial.
              </p>
            </div>
            <footer>
              <button className="btn" onClick={() => setConfirmarDescarte(false)}>
                Cancelar
              </button>
              <button
                className="btn peligro"
                disabled={descartar.isPending}
                onClick={() =>
                  descartar.mutate(undefined, {
                    onSuccess: () => {
                      setConfirmarDescarte(false)
                      setSeleccion(null)
                    },
                    // Si no había borrador en el servidor —solo cambios en
                    // pantalla— la respuesta es 404 y aun así hay que cerrar y
                    // recargar: es exactamente lo que se pidió.
                    onError: () => {
                      setConfirmarDescarte(false)
                      cargada.refetch()
                    },
                  })
                }
              >
                {descartar.isPending ? 'Descartando…' : 'Descartar'}
              </button>
            </footer>
          </div>
        </Velo>
      )}

      {metricaAbierta !== null && (
        <PanelMetrica
          modeloId={modeloId}
          definicion={d}
          indice={typeof metricaAbierta === 'number' ? metricaAbierta : null}
          metrica={
            typeof metricaAbierta === 'number'
              ? d.metricas[metricaAbierta]!
              : {
                  ...METRICA_NUEVA,
                  entidad: d.entidades.find((e) => e.tipo === 'hecho')?.nombre ?? '',
                  // Nace en el cajón desde el que se pulsó «+»: pedirlo otra vez
                  // dentro del diálogo sería preguntar lo que ya se dijo.
                  tabla_medidas: metricaAbierta.tablaMedidas,
                }
          }
          despachar={despachar}
          alCerrar={() => setMetricaAbierta(null)}
        />
      )}
    </div>
  )
}
