/**
 * Un tablero: verlo y editarlo.
 *
 * Igual que en el modelo, **nada se guarda al escribir**: se trabaja sobre un
 * borrador y guardar es explícito. Y guardar un tablero certificado le quita el
 * sello, porque lo que se revisó ya no es esto.
 *
 * Las selecciones NO se guardan al mover: son del momento. Solo se guardan si se
 * pide "guardar como estado inicial" — un tablero que se abre siempre con el filtro
 * de alguien puesto es una trampa.
 */

import { useEffect, useMemo, useState } from 'react'
// En react-grid-layout 2, `Layout` es la lista completa (de solo lectura) y cada
// caja es un `LayoutItem`. En la versión 1 `Layout` era la caja: de ahí el lío.
import GridLayout, { type Layout } from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'
import { useNavigate, useParams } from 'react-router-dom'

import {
  useAccionDashboard,
  useDashboard,
  useGuardarDashboard,
  useVersiones,
  useYo,
} from '../api/hooks'
import { PanelLateral } from '../comunes/Panel'
import type { DefinicionDashboard, TipoWidget, Widget } from '../api/tipos'
import { Exportar } from '../tablero/Exportar'
import { PanelWidget } from '../tablero/PanelWidget'
import { WidgetVista } from '../tablero/WidgetVista'
import { PIDE_DATOS, filtrosDeSelecciones } from '../tablero/consulta'

const COLUMNAS = 12
const ALTO_FILA = 30

const PLANTILLAS: Record<string, { tipo: TipoWidget; ancho: number; alto: number }> = {
  kpi: { tipo: 'kpi', ancho: 3, alto: 4 },
  barras: { tipo: 'barras', ancho: 6, alto: 9 },
  lineas: { tipo: 'lineas', ancho: 6, alto: 9 },
  pastel: { tipo: 'pastel', ancho: 4, alto: 9 },
  tabla: { tipo: 'tabla', ancho: 6, alto: 9 },
  filtro: { tipo: 'filtro', ancho: 3, alto: 9 },
  texto: { tipo: 'texto', ancho: 6, alto: 3 },
}

export function Tablero() {
  const id = Number(useParams().id)
  const navegar = useNavigate()
  const cargado = useDashboard(id)
  const yo = useYo()
  const guardar = useGuardarDashboard(id)
  const acciones = useAccionDashboard(id)

  const [borrador, setBorrador] = useState<DefinicionDashboard | null>(null)
  const [selecciones, setSelecciones] = useState<Record<string, unknown[]>>({})
  const [editando, setEditando] = useState(false)
  const [elegido, setElegido] = useState<string | null>(null)
  const [ancho, setAncho] = useState(1000)

  const versiones = useVersiones(cargado.data?.modelo_id ?? 0)

  useEffect(() => {
    if (!cargado.data) return
    setBorrador(cargado.data.definicion)
    setSelecciones(cargado.data.definicion.selecciones ?? {})
  }, [cargado.data])

  // El ancho de la rejilla se mide: react-grid-layout necesita píxeles.
  useEffect(() => {
    const medir = () => {
      const el = document.getElementById('rejilla')
      if (el) setAncho(el.clientWidth)
    }
    medir()
    window.addEventListener('resize', medir)
    return () => window.removeEventListener('resize', medir)
  }, [borrador, editando])

  const sucio = useMemo(
    () =>
      !!borrador &&
      !!cargado.data &&
      JSON.stringify({ ...borrador, selecciones: undefined }) !==
        JSON.stringify({ ...cargado.data.definicion, selecciones: undefined }),
    [borrador, cargado.data],
  )

  useEffect(() => {
    if (!sucio) return
    const aviso = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', aviso)
    return () => window.removeEventListener('beforeunload', aviso)
  }, [sucio])

  if (cargado.isLoading || !borrador) return <div className="vacio">Cargando…</div>
  if (cargado.isError) {
    return (
      <div className="pagina">
        <div className="error-caja">{(cargado.error as Error).message}</div>
      </div>
    )
  }

  const d = cargado.data!
  const puedeEditar = yo.data?.rol === 'administrador' || yo.data?.rol === 'editor'
  const desfasado = d.version_modelo !== d.version_vigente_del_modelo
  const widget = borrador.widgets.find((w) => w.id === elegido)

  const cambiarWidget = (wid: string, cambios: Partial<Widget>) =>
    setBorrador({
      ...borrador,
      widgets: borrador.widgets.map((w) => (w.id === wid ? { ...w, ...cambios } : w)),
    })

  const agregar = (clave: string) => {
    const p = PLANTILLAS[clave]!
    const nuevo: Widget = {
      id: `w${Date.now().toString(36)}`,
      tipo: p.tipo,
      titulo: '',
      posicion: {
        x: 0,
        // Debajo de todo lo que ya hay: aparecer encima de otro widget y
        // desplazarlo es la forma más rápida de deshacer el trabajo de alguien.
        y: Math.max(0, ...borrador.widgets.map((w) => w.posicion.y + w.posicion.alto)),
        ancho: p.ancho,
        alto: p.alto,
      },
      dimensiones: [],
      metricas: [],
      filtros: [],
      rutas_elegidas: {},
      limite: 1000,
    }
    setBorrador({ ...borrador, widgets: [...borrador.widgets, nuevo] })
    setElegido(nuevo.id)
  }

  const alMoverRejilla = (layout: Layout) =>
    setBorrador({
      ...borrador,
      widgets: borrador.widgets.map((w) => {
        const l = layout.find((x) => x.i === w.id)
        return l
          ? { ...w, posicion: { x: l.x, y: l.y, ancho: l.w, alto: l.h } }
          : w
      }),
    })

  const alternarSeleccion = (campo: string, valor: unknown) =>
    setSelecciones((prev) => {
      const actuales = prev[campo] ?? []
      const nuevas = actuales.includes(valor)
        ? actuales.filter((v) => v !== valor)
        : [...actuales, valor]
      const copia = { ...prev }
      if (nuevas.length === 0) delete copia[campo]
      else copia[campo] = nuevas
      return copia
    })

  const activos = filtrosDeSelecciones(selecciones)

  return (
    <div className="editor">
      {editando && (
        <PanelLateral clave="tablero">
          <section className="seccion">
            <header>Agregar widget</header>
            <div className="contenido">
              <div className="lista">
                {Object.entries(PLANTILLAS).map(([clave]) => (
                  <button key={clave} onClick={() => agregar(clave)}>
                    <span className="nom">+ {clave}</span>
                  </button>
                ))}
              </div>
            </div>
          </section>
          <section className="seccion">
            <header>
              Widgets <span className="cuenta">{borrador.widgets.length}</span>
            </header>
            <div className="contenido">
              <div className="lista">
                {borrador.widgets.map((w) => (
                  <button
                    key={w.id}
                    className={elegido === w.id ? 'sel' : ''}
                    onClick={() => setElegido(w.id)}
                  >
                    <span className="nom">{w.titulo || w.tipo}</span>
                    <span className="dcha">{w.tipo}</span>
                  </button>
                ))}
              </div>
            </div>
          </section>
        </PanelLateral>
      )}

      <div className="centro">
        <div className="barra-editor">
          <button className="btn chico" onClick={() => navegar('/tableros')}>
            ←
          </button>
          <strong>{d.nombre}</strong>
          <span className="etiqueta" title={`Modelo ${d.modelo_nombre}`}>
            {d.modelo_nombre} v{d.version_modelo}
          </span>
          {d.certificado && <span className="etiqueta ok">certificado</span>}
          {!d.publicado && <span className="etiqueta">borrador</span>}

          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8,
                        alignItems: 'center', minWidth: 0 }}>
            {activos.length > 0 && (
              <button className="btn chico" onClick={() => setSelecciones({})}>
                Quitar {activos.length} filtro(s)
              </button>
            )}
            {/* Solo a quien puede guardar. Un lector puede elegir un camino para
                su sesión, pero decirle que tiene cambios pendientes que no puede
                guardar solo confunde. */}
            {sucio && puedeEditar && (
              <span className="sin-guardar">cambios sin guardar</span>
            )}
            {puedeEditar && (
              <button className="btn" onClick={() => setEditando(!editando)}>
                {editando ? 'Ver' : 'Editar'}
              </button>
            )}
            {editando && (
              <>
                <button
                  className="btn"
                  disabled={guardar.isPending}
                  title="Guarda las selecciones actuales como estado inicial del tablero"
                  onClick={() =>
                    guardar.mutate({ definicion: { ...borrador, selecciones } })
                  }
                >
                  Guardar con filtros
                </button>
                <button
                  className="btn primario"
                  disabled={!sucio || guardar.isPending}
                  onClick={() =>
                    guardar.mutate({
                      definicion: { ...borrador, selecciones: d.definicion.selecciones },
                    })
                  }
                >
                  {guardar.isPending ? 'Guardando…' : 'Guardar'}
                </button>
              </>
            )}
          </div>
        </div>

        {guardar.isError && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {(guardar.error as Error).message}
          </div>
        )}

        {desfasado && puedeEditar && (
          <div className="aviso-caja" style={{ margin: '10px 12px 0',
                                               display: 'flex', gap: 10,
                                               alignItems: 'center' }}>
            <span>
              El modelo va por la versión {d.version_vigente_del_modelo} y este
              tablero está anclado a la {d.version_modelo}. Las cifras pueden
              cambiar al adoptarla.
            </span>
            <button
              className="btn chico"
              style={{ marginLeft: 'auto' }}
              onClick={() => acciones.moverAVersion.mutate(d.version_vigente_del_modelo)}
            >
              Adoptar v{d.version_vigente_del_modelo}
            </button>
          </div>
        )}

        <div id="rejilla" className="rejilla">
          {borrador.widgets.length === 0 ? (
            <div className="vacio">
              Tablero vacío.
              {puedeEditar && ' Entra en Editar y agrega un widget.'}
            </div>
          ) : (
            <GridLayout
              className="layout"
              width={ancho}
              gridConfig={{ cols: COLUMNAS, rowHeight: ALTO_FILA, margin: [10, 10] }}
              // Se arrastra por la cabecera: si se arrastrara por cualquier punto,
              // no se podría hacer clic dentro de un gráfico ni de un filtro.
              dragConfig={{ enabled: editando, handle: '.widget > header' }}
              resizeConfig={{ enabled: editando }}
              onLayoutChange={editando ? alMoverRejilla : undefined}
              layout={borrador.widgets.map((w) => ({
                i: w.id,
                x: w.posicion.x,
                y: w.posicion.y,
                w: w.posicion.ancho,
                h: w.posicion.alto,
              }))}
            >
              {borrador.widgets.map((w) => (
                <div
                  key={w.id}
                  className={`widget ${elegido === w.id && editando ? 'sel' : ''}`}
                  onMouseDown={() => editando && setElegido(w.id)}
                >
                  <header>
                    <span className="nom">{w.titulo || <i className="tenue">{w.tipo}</i>}</span>
                    {PIDE_DATOS.includes(w.tipo) && (
                      <Exportar
                        widget={w}
                        modeloId={d.modelo_id}
                        version={d.version_modelo}
                        selecciones={selecciones}
                        rutasElegidas={
                          (borrador.rutas_elegidas as Record<string, string>) ?? {}
                        }
                      />
                    )}
                  </header>
                  <div className="cuerpo-widget">
                    <WidgetVista
                      widget={w}
                      modeloId={d.modelo_id}
                      version={d.version_modelo}
                      selecciones={selecciones}
                      rutasElegidas={
                        (borrador.rutas_elegidas as Record<string, string>) ?? {}
                      }
                      alElegirRuta={(clave, ruta) =>
                        setBorrador({
                          ...borrador,
                          rutas_elegidas: {
                            ...((borrador.rutas_elegidas as Record<string, string>) ??
                              {}),
                            [clave]: ruta,
                          },
                        })
                      }
                      alAlternar={alternarSeleccion}
                      alLimpiar={(campo) =>
                        setSelecciones((p) => {
                          const c = { ...p }
                          delete c[campo]
                          return c
                        })
                      }
                      editando={editando}
                    />
                  </div>
                </div>
              ))}
            </GridLayout>
          )}
        </div>
      </div>

      {editando && (
        <PanelLateral clave="tablero-der" lado="derecha" porOmision={380}>
          <div className="barra-editor">
            <div className="pestanas">
              <button className="activo">
                {widget ? `${widget.tipo}` : 'Tablero'}
              </button>
            </div>
          </div>
          {widget ? (
            <PanelWidget
              widget={widget}
              modeloId={d.modelo_id}
              alCambiar={(cambios) => cambiarWidget(widget.id, cambios)}
              alQuitar={() => {
                setBorrador({
                  ...borrador,
                  widgets: borrador.widgets.filter((w) => w.id !== widget.id),
                })
                setElegido(null)
              }}
            />
          ) : (
            <PanelTablero
              nombre={d.nombre}
              publicado={d.publicado}
              certificado={d.certificado}
              esAdmin={yo.data?.rol === 'administrador'}
              versiones={versiones.data?.versiones.map((v) => v.version) ?? []}
              versionActual={d.version_modelo}
              alRenombrar={(nombre) => guardar.mutate({ nombre })}
              alPublicar={(v) => acciones.publicar.mutate(v)}
              alCertificar={(v) => acciones.certificar.mutate(v)}
              alMover={(v) => acciones.moverAVersion.mutate(v)}
              alBorrar={() => {
                if (confirm(`¿Borrar el tablero "${d.nombre}"?`)) {
                  acciones.borrar.mutate(undefined, {
                    onSuccess: () => navegar('/tableros'),
                  })
                }
              }}
            />
          )}
        </PanelLateral>
      )}
    </div>
  )
}

function PanelTablero({
  nombre,
  publicado,
  certificado,
  esAdmin,
  versiones,
  versionActual,
  alRenombrar,
  alPublicar,
  alCertificar,
  alMover,
  alBorrar,
}: {
  nombre: string
  publicado: boolean
  certificado: boolean
  esAdmin: boolean
  versiones: number[]
  versionActual: number
  alRenombrar: (n: string) => void
  alPublicar: (v: boolean) => void
  alCertificar: (v: boolean) => void
  alMover: (v: number) => void
  alBorrar: () => void
}) {
  const [texto, setTexto] = useState(nombre)
  return (
    <div className="inspector">
      <div className="campo">
        <label>Nombre</label>
        <div className="fila">
          <input type="text" value={texto} onChange={(e) => setTexto(e.target.value)} />
          <button
            className="btn"
            style={{ flex: '0 0 auto' }}
            disabled={texto.trim() === nombre || !texto.trim()}
            onClick={() => alRenombrar(texto.trim())}
          >
            Cambiar
          </button>
        </div>
      </div>

      <div className="campo">
        <label>Versión del modelo</label>
        <select value={versionActual} onChange={(e) => alMover(Number(e.target.value))}>
          {versiones.map((v) => (
            <option key={v} value={v}>
              v{v}
            </option>
          ))}
        </select>
        <span className="chico tenue">
          Cambiarla puede cambiar las cifras, y quita la certificación.
        </span>
      </div>

      <button className="btn" onClick={() => alPublicar(!publicado)}>
        {publicado ? 'Retirar de publicación' : 'Publicar'}
      </button>
      <span className="chico tenue" style={{ marginTop: -8 }}>
        Un lector solo ve lo publicado: un borrador a medias no es una cifra con la
        que nadie deba decidir.
      </span>

      {esAdmin && (
        <>
          <button
            className="btn"
            disabled={!publicado}
            title={publicado ? undefined : 'Hay que publicarlo antes'}
            onClick={() => alCertificar(!certificado)}
          >
            {certificado ? 'Quitar certificación' : 'Certificar'}
          </button>
          <span className="chico tenue" style={{ marginTop: -8 }}>
            Certificar es decir "estas cifras se revisaron". Se pierde al editar.
          </span>
        </>
      )}

      <button className="btn peligro" onClick={alBorrar}>
        Borrar tablero
      </button>
    </div>
  )
}
