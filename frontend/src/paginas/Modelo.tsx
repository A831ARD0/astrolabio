/**
 * Editor del modelo semántico.
 *
 * Una decisión de fondo: **nada se guarda al escribir.** Se trabaja sobre un
 * borrador y guardar es un acto explícito que crea una versión nueva e inmutable.
 * Los dashboards publicados están anclados a una versión concreta, así que editar
 * el modelo no puede cambiarles la cifra por debajo.
 */

import { useEffect, useMemo, useReducer, useState } from 'react'
import { useParams } from 'react-router-dom'

import { useDefinicion, useGuardarDefinicion, useVersiones } from '../api/hooks'
import type { Entidad, Metrica } from '../api/tipos'
import { DialogoEntidad } from '../modelo/DialogoEntidad'
import { Lienzo, type Seleccion } from '../modelo/Lienzo'
import { PanelDiagnostico } from '../modelo/PanelDiagnostico'
import { PanelEntidad } from '../modelo/PanelEntidad'
import { PanelMetrica } from '../modelo/PanelMetrica'
import { PanelRelacion } from '../modelo/PanelRelacion'
import { VistaYaml } from '../modelo/VistaYaml'
import {
  deshacer,
  disponer,
  estadoInicial,
  haCambiado,
  reducir,
} from '../modelo/estado'

type Pestana = 'lienzo' | 'yaml'
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
  const guardar = useGuardarDefinicion(modeloId)

  const [estado, despachar] = useReducer(reducir, estadoInicial)
  const [pestana, setPestana] = useState<Pestana>('lienzo')
  const [panel, setPanel] = useState<Panel>('seleccion')
  const [seleccion, setSeleccion] = useState<Seleccion | null>(null)
  const [resaltadas, setResaltadas] = useState<Set<string> | null>(null)
  const [dialogoEntidad, setDialogoEntidad] = useState(false)
  const [metricaAbierta, setMetricaAbierta] = useState<number | 'nueva' | null>(null)
  const [notas, setNotas] = useState('')

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
          : { ...d, disposicion: disponer(d.entidades) },
    })
  }, [cargada.data])

  const d = estado.borrador
  const sucio = haCambiado(estado)

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
    const columna = d ? Object.keys(d.disposicion).length : 0
    despachar({ t: 'agregar_entidad', entidad: e })
    despachar({
      t: 'mover',
      entidad: e.nombre,
      x: (columna % 4) * 300,
      y: Math.floor(columna / 4) * 340,
    })
    setDialogoEntidad(false)
    setSeleccion({ tipo: 'entidad', id: e.nombre })
  }

  return (
    <div className="editor">
      {/* ------------------------------------------------------ izquierda */}
      <aside className="izq">
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

        <section className="seccion">
          <header>
            Métricas <span className="cuenta">{d.metricas.length}</span>
          </header>
          <div className="contenido">
            <div className="lista">
              {d.metricas.map((m, i) => (
                <button key={m.nombre} onClick={() => setMetricaAbierta(i)}>
                  <span className="nom">{m.etiqueta || m.nombre}</span>
                  <span className="dcha">{m.formato}</span>
                </button>
              ))}
            </div>
            {d.metricas.length === 0 && (
              <div className="chico tenue" style={{ padding: '2px 8px' }}>
                Sin métricas todavía.
              </div>
            )}
            <button
              className="btn chico"
              style={{ marginTop: 8, width: '100%' }}
              disabled={d.entidades.every((e) => e.tipo !== 'hecho')}
              title={
                d.entidades.every((e) => e.tipo !== 'hecho')
                  ? 'Una métrica nace en un hecho: agrega primero una entidad de tipo hecho'
                  : undefined
              }
              onClick={() => setMetricaAbierta('nueva')}
            >
              + Nueva métrica
            </button>
          </div>
        </section>

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
              Las versiones son inmutables: guardar crea una nueva y no toca las
              anteriores.
            </div>
          </div>
        </section>
      </aside>

      {/* --------------------------------------------------------- centro */}
      <div className="centro">
        <div className="barra-editor">
          <strong className="mono">{d.modelo}</strong>
          <span className="etiqueta">v{cargada.data?.version}</span>

          <div className="pestanas">
            <button
              className={pestana === 'lienzo' ? 'activo' : ''}
              onClick={() => setPestana('lienzo')}
            >
              Lienzo
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
            {sucio && <span className="sin-guardar">cambios sin guardar</span>}
            <button
              className="btn"
              disabled={estado.historial.length === 0}
              onClick={() => despachar({ t: 'cargar', definicion: deshacer(estado).borrador! })}
              title="Deshacer el último cambio"
            >
              Deshacer
            </button>
            <input
              type="text"
              placeholder="Nota de la versión"
              value={notas}
              onChange={(e) => setNotas(e.target.value)}
              style={{ flex: '0 1 170px' }}
            />
            <button
              className="btn primario"
              disabled={!sucio || guardar.isPending}
              onClick={() =>
                guardar.mutate(
                  { definicion: d, notas: notas.trim() || undefined },
                  { onSuccess: () => setNotas('') },
                )
              }
            >
              {guardar.isPending ? 'Guardando…' : 'Guardar versión'}
            </button>
          </div>
        </div>

        {guardar.isError && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {(guardar.error as Error).message}
          </div>
        )}

        {pestana === 'lienzo' ? (
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

      {metricaAbierta !== null && (
        <PanelMetrica
          modeloId={modeloId}
          definicion={d}
          indice={metricaAbierta === 'nueva' ? null : metricaAbierta}
          metrica={
            metricaAbierta === 'nueva'
              ? {
                  ...METRICA_NUEVA,
                  entidad: d.entidades.find((e) => e.tipo === 'hecho')?.nombre ?? '',
                }
              : d.metricas[metricaAbierta]!
          }
          despachar={despachar}
          alCerrar={() => setMetricaAbierta(null)}
        />
      )}
    </div>
  )
}
