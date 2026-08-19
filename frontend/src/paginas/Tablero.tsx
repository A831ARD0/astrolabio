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
 *
 * **Un tablero es un libro de hojas.** Los widgets no van dentro de la hoja: cada
 * widget dice a cuál pertenece, y un tablero guardado antes de que existieran las
 * hojas tiene una implícita con todos. Las selecciones son del libro, no de la
 * hoja: filtrar en una hoja y que la de al lado siga en otro mes es la forma más
 * cara de leer dos cifras que no se pueden comparar.
 */

import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
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
import type {
  DefinicionDashboard,
  Hoja,
  Lienzo,
  TipoWidget,
  Widget,
} from '../api/tipos'
import { Exportar } from '../tablero/Exportar'
import { EnvioPorCorreo } from '../tablero/EnvioPorCorreo'
import { Imprimir, PortadaInforme } from '../tablero/Imprimir'
import {
  hojaDeLaUrl,
  informeSiLoPideLaUrl,
  seleccionesDelInforme,
} from '../tablero/informeAutomatico'
import { PanelWidget } from '../tablero/PanelWidget'
import { WidgetVista } from '../tablero/WidgetVista'
import { PIDE_DATOS, filtrosDeSelecciones } from '../tablero/consulta'

const MARGEN = 10
/** Alto de fila cuando la hoja se desplaza. En modo pantalla se calcula. */
const ALTO_FILA_LIBRE = 30
/** Por debajo de esto una fila no cabe ni un número: mejor desplazar. */
const ALTO_FILA_MINIMO = 14

const LIENZO_OMISION: Lienzo = { modo: 'pantalla', columnas: 12, filas: 12 }

/**
 * Las hojas de un tablero, siempre al menos una. Un tablero guardado antes de las
 * hojas no declara ninguna: tiene una implícita con `id` vacío, que es lo que
 * llevan sus widgets en `hoja`.
 */
function hojasDe(d: DefinicionDashboard): Hoja[] {
  if (d.hojas?.length) {
    return d.hojas.map((h) => ({ ...h, lienzo: { ...LIENZO_OMISION, ...h.lienzo } }))
  }
  return [{ id: '', nombre: 'Hoja 1', lienzo: LIENZO_OMISION }]
}

/**
 * Convierte la hoja implícita en una de verdad. Hace falta antes de tocarla —
 * cambiarle el lienzo o agregar una segunda—, y mueve los widgets de golpe para
 * que ninguno quede apuntando a una hoja que ya no es la primera.
 */
function conHojas(d: DefinicionDashboard): DefinicionDashboard {
  if (d.hojas?.length) return d
  const h: Hoja = { id: 'h1', nombre: 'Hoja 1', lienzo: LIENZO_OMISION }
  return { ...d, hojas: [h], widgets: d.widgets.map((w) => ({ ...w, hoja: h.id })) }
}

const PLANTILLAS: Record<string, { tipo: TipoWidget; ancho: number; alto: number }> = {
  kpi: { tipo: 'kpi', ancho: 3, alto: 4 },
  barras: { tipo: 'barras', ancho: 6, alto: 9 },
  lineas: { tipo: 'lineas', ancho: 6, alto: 9 },
  pastel: { tipo: 'pastel', ancho: 4, alto: 9 },
  tabla: { tipo: 'tabla', ancho: 6, alto: 9 },
  // Ancha de origen: una matriz con doce meses a lo ancho en media hoja no se lee.
  'tabla dinámica': { tipo: 'tabla_dinamica', ancho: 12, alto: 9 },
  // Ancho y bajo: un panel de filtros nace como la barra de arriba de una hoja de
  // Qlik —Año, Mes, Sucursal en fila—, no como una columna estrecha. Con este alto
  // colapsa en desplegables desde el primer momento, que es lo que se quiere de
  // una barra; quien quiera listas abiertas lo estira y aparecen.
  filtro: { tipo: 'filtro', ancho: 12, alto: 3 },
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
  const [hojaId, setHojaId] = useState<string | null>(null)
  const [pestanaDer, setPestanaDer] = useState<'hoja' | 'tablero'>('hoja')
  const [correoAbierto, setCorreoAbierto] = useState(false)
  const [caja, setCaja] = useState({ ancho: 1000, alto: 700 })

  const versiones = useVersiones(cargado.data?.modelo_id ?? 0)

  useEffect(() => {
    if (!cargado.data) return
    setBorrador(cargado.data.definicion)
    setSelecciones(cargado.data.definicion.selecciones ?? {})
  }, [cargado.data])

  // El informe que se lleva el servidor: cuando la URL lo pide, la hoja se pone como
  // informe, se mide y publica su tamaño. Va aquí y no en el botón porque hace falta
  // esperar a que las consultas terminen, y eso solo se puede saber desde la pantalla.
  const hojaPedida = hojaDeLaUrl()
  useEffect(() => {
    if (!borrador) return
    // Los filtros de quien pidio el informe, ANTES de medir: una pantalla recien
    // abierta nace con los guardados del tablero, y el informe tiene que ser de lo
    // que se estaba viendo. `informeSiLoPideLaUrl` espera a que las consultas
    // terminen, asi que las de estos filtros entran en esa espera.
    const puestas = seleccionesDelInforme()
    if (puestas) setSelecciones(puestas)
    void informeSiLoPideLaUrl()
  }, [borrador])

  // La rejilla se mide: react-grid-layout necesita píxeles. El alto también, y no
  // solo el ancho, porque en modo pantalla la fila mide lo que sobre del alto
  // visible entre las filas que pida la hoja.
  useEffect(() => {
    const medir = () => {
      const el = document.getElementById('rejilla')
      if (el) setCaja({ ancho: el.clientWidth, alto: el.clientHeight })
    }
    medir()
    window.addEventListener('resize', medir)
    return () => window.removeEventListener('resize', medir)
  }, [borrador, editando, hojaId])

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

  const hojas = hojasDe(borrador)
  // `?hoja=` gana sobre la pestaña elegida: es como el renderizador del servidor dice
  // cuál hoja quiere, y también sirve para mandar un enlace a una hoja concreta. Vale
  // el id o el nombre, porque el que escribe el enlace conoce el nombre.
  const pedida = hojaPedida
    ? hojas.find((h) => h.id === hojaPedida || h.nombre === hojaPedida)
    : undefined
  const activa = pedida ?? hojas.find((h) => h.id === hojaId) ?? hojas[0]!
  const lienzo = activa.lienzo
  // El id vacío de la hoja implícita es el que llevan los widgets de antes.
  const enLaHoja = (w: Widget) => (w.hoja || hojas[0]!.id) === activa.id
  const mios = borrador.widgets.filter(enLaHoja)
  /**
   * Los widgets en orden de lectura: de arriba abajo y de izquierda a derecha.
   *
   * En pantalla no cambia nada —la rejilla los coloca en absoluto por su posicion—
   * pero al imprimir la rejilla se convierte en una columna y entonces el orden del
   * DOM ES el orden del informe. Sin esto, un informe sale en el orden en que se
   * fueron agregando los widgets, que no es ningun orden.
   */
  const enOrden = [...mios].sort(
    (a, b) => a.posicion.y - b.posicion.y || a.posicion.x - b.posicion.x,
  )

  const altoFila =
    lienzo.modo === 'pantalla'
      ? Math.max(
          ALTO_FILA_MINIMO,
          Math.floor((caja.alto - MARGEN * (lienzo.filas + 1)) / lienzo.filas),
        )
      : ALTO_FILA_LIBRE
  // Cuántas filas ocupa de verdad lo que hay puesto.
  const filasUsadas = Math.max(0, ...mios.map((w) => w.posicion.y + w.posicion.alto))

  // Dos formas de no caber: que la fila tocara el mínimo legible, o que haya
  // widgets más abajo de las filas que declara la hoja. En cualquiera de las dos
  // se deja desplazar. Recortar con `overflow: hidden` dejaría widgets que no se
  // pueden ni ver ni alcanzar, y un widget que nadie ve es una cifra que nadie
  // revisa.
  const desborda = filasUsadas > lienzo.filas
  const noCabe =
    lienzo.modo === 'pantalla' &&
    caja.alto > 0 &&
    (altoFila === ALTO_FILA_MINIMO || desborda)

  const cambiarWidget = (wid: string, cambios: Partial<Widget>) =>
    setBorrador({
      ...borrador,
      widgets: borrador.widgets.map((w) => (w.id === wid ? { ...w, ...cambios } : w)),
    })

  /**
   * Sube o baja un widget en la hoja, cambiando de sitio su BANDA con la de al lado.
   *
   * Una banda son los widgets que empiezan en la misma fila —los tres filtros de
   * arriba son una—, y se mueve entera: mover uno solo de los tres lo sacaría de la
   * fila y dejaría un hueco donde estaba. Las dos bandas se reparten el sitio que
   * ocupaban entre las dos, así que nada de lo que hay más arriba o más abajo se
   * mueve; y si había un hueco entre ellas, se cierra.
   *
   * Se mueve por bandas y no por posición en una lista porque la hoja es una rejilla,
   * no una lista: dos widgets pueden estar uno al lado del otro, y en una lista eso
   * no se puede decir.
   */
  const moverWidget = (wid: string, paso: -1 | 1) => {
    const yo = mios.find((w) => w.id === wid)
    if (!yo) return
    const bandas = [...new Set(enOrden.map((w) => w.posicion.y))].sort((a, b) => a - b)
    const i = bandas.indexOf(yo.posicion.y)
    const j = i + paso
    if (i < 0 || j < 0 || j >= bandas.length) return

    const [arriba, abajo] = paso === -1 ? [bandas[j]!, bandas[i]!] : [bandas[i]!, bandas[j]!]
    const de = (y: number) => mios.filter((w) => w.posicion.y === y)
    const altoDe = (y: number) => Math.max(...de(y).map((w) => w.posicion.alto))

    // La de abajo pasa a empezar donde empezaba la de arriba, y la de arriba justo
    // después: el alto de cada una manda, no el hueco que hubiera.
    const nuevos = new Map<string, number>()
    for (const w of de(abajo)) nuevos.set(w.id, arriba)
    for (const w of de(arriba)) nuevos.set(w.id, arriba + altoDe(abajo))

    setBorrador({
      ...borrador,
      widgets: borrador.widgets.map((w) =>
        nuevos.has(w.id)
          ? { ...w, posicion: { ...w.posicion, y: nuevos.get(w.id)! } }
          : w,
      ),
    })
  }

  const cambiarHoja = (hid: string, cambios: Partial<Hoja>) => {
    const base = conHojas(borrador)
    setBorrador({
      ...base,
      hojas: base.hojas.map((h) => (h.id === hid ? { ...h, ...cambios } : h)),
    })
  }

  const agregarHoja = () => {
    const base = conHojas(borrador)
    const nueva: Hoja = {
      id: `h${Date.now().toString(36)}`,
      nombre: `Hoja ${base.hojas.length + 1}`,
      // Nace como la que se estaba viendo: casi siempre es lo que se quiere, y
      // dos hojas del mismo libro con rejillas distintas no se leen igual.
      lienzo: { ...lienzo },
    }
    setBorrador({ ...base, hojas: [...base.hojas, nueva] })
    setHojaId(nueva.id)
    setElegido(null)
    setPestanaDer('hoja')
  }

  const borrarHoja = (hid: string) => {
    const base = conHojas(borrador)
    if (base.hojas.length === 1) return
    const h = base.hojas.find((x) => x.id === hid)!
    const dentro = base.widgets.filter((w) => (w.hoja || base.hojas[0]!.id) === hid)
    const aviso = dentro.length
      ? `¿Borrar la hoja "${h.nombre}" y sus ${dentro.length} widget(s)?`
      : `¿Borrar la hoja "${h.nombre}"?`
    if (!confirm(aviso)) return
    const quedan = base.hojas.filter((x) => x.id !== hid)
    setBorrador({
      ...base,
      hojas: quedan,
      widgets: base.widgets.filter((w) => !dentro.includes(w)),
    })
    setHojaId(quedan[0]!.id)
    setElegido(null)
  }

  const moverHoja = (hid: string, paso: -1 | 1) => {
    const base = conHojas(borrador)
    const i = base.hojas.findIndex((h) => h.id === hid)
    const j = i + paso
    if (j < 0 || j >= base.hojas.length) return
    const orden = [...base.hojas]
    ;[orden[i], orden[j]] = [orden[j]!, orden[i]!]
    setBorrador({ ...base, hojas: orden })
  }

  const agregar = (clave: string) => {
    const p = PLANTILLAS[clave]!
    // Las plantillas están en doceavos. En una hoja de 24 columnas, un KPI de 3
    // sería un sello: se reparte igual de ancho, no igual de columnas.
    const ancho = Math.max(1, Math.min(lienzo.columnas,
                                       Math.round((p.ancho * lienzo.columnas) / 12)))
    // Debajo de todo lo que ya hay EN ESTA HOJA: aparecer encima de otro widget y
    // desplazarlo es la forma más rápida de deshacer el trabajo de alguien.
    const y = filasUsadas
    // Si lo que queda de hoja es menos que la plantilla pero da para algo, se
    // encoge y cabe. Si ya no queda nada, entra igual y la hoja se desplaza — no
    // se descarta ni se apila encima de otro.
    const queda = lienzo.filas - y
    const alto = queda >= 2 && queda < p.alto ? queda : p.alto

    const nuevo: Widget = {
      id: `w${Date.now().toString(36)}`,
      tipo: p.tipo,
      titulo: '',
      hoja: activa.id,
      posicion: { x: 0, y, ancho, alto },
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
              Widgets de {activa.nombre || 'la hoja'}{' '}
              <span className="cuenta">{mios.length}</span>
            </header>
            <div className="contenido">
              {/* En el orden en que se leen —de arriba abajo—, no en el que se
                  fueron agregando: es la lista con la que se ordena la hoja, así que
                  tiene que enseñar el orden que va a salir en el informe. */}
              <div className="lista con-mover">
                {enOrden.map((w, i) => (
                  <div key={w.id} className="fila-widget">
                    <button
                      className={elegido === w.id ? 'sel' : ''}
                      onClick={() => setElegido(w.id)}
                    >
                      <span className="nom">{w.titulo || w.tipo}</span>
                      <span className="dcha">{w.tipo}</span>
                    </button>
                    <button
                      className="mueve"
                      disabled={i === 0}
                      title="Subir en la hoja"
                      onClick={() => moverWidget(w.id, -1)}
                    >
                      ↑
                    </button>
                    <button
                      className="mueve"
                      disabled={i === enOrden.length - 1}
                      title="Bajar en la hoja"
                      onClick={() => moverWidget(w.id, 1)}
                    >
                      ↓
                    </button>
                  </div>
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
            {/* No se esconde al editar: quien acaba de armar la hoja es justo quien
                quiere ver como queda en papel antes de mandarla. */}
            <Imprimir
              hoja={activa.nombre || 'la hoja'}
              dashboardId={id}
              selecciones={selecciones}
              alProgramar={puedeEditar ? () => setCorreoAbierto(true) : undefined}
            />
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

        {/* Las hojas del libro. Se ven siempre, no solo al editar: quien mira un
            tablero de tres hojas tiene que saber que hay tres. */}
        {(hojas.length > 1 || editando) && (
          <div className="hojas">
            <div className="pestanas">
              {hojas.map((h, i) => (
                <button
                  key={h.id || `implicita-${i}`}
                  className={h.id === activa.id ? 'activo' : ''}
                  onClick={() => {
                    setHojaId(h.id)
                    setElegido(null)
                  }}
                >
                  {h.nombre || `Hoja ${i + 1}`}
                </button>
              ))}
            </div>
            {editando && (
              <button className="btn chico" title="Agregar una hoja"
                      onClick={agregarHoja}>
                + Hoja
              </button>
            )}
            <span className="chico tenue" style={{ marginLeft: 'auto' }}>
              {lienzo.modo === 'pantalla'
                ? `${lienzo.columnas} × ${lienzo.filas}, cabe en la pantalla`
                : `${lienzo.columnas} columnas, se desplaza`}
            </span>
          </div>
        )}

        {noCabe && editando && (
          <div className="aviso-caja" style={{ margin: '10px 12px 0' }}>
            {desborda
              ? `Esta hoja dice tener ${lienzo.filas} filas y lo puesto llega a la
                 ${filasUsadas}. Mientras sobre, la hoja se desplaza para que no
                 quede ningún widget escondido: sube las filas de la hoja, o sube
                 los widgets.`
              : `${lienzo.filas} filas no caben en esta pantalla sin dejarlas de
                 menos de ${ALTO_FILA_MINIMO} píxeles. Baja las filas de la hoja,
                 o ponla en «se desplaza».`}
          </div>
        )}

        {/* Solo se ve en el papel. Va aqui dentro, y no fuera del area de la hoja,
            para que encabece el informe sin colarse en la pantalla. */}
        {correoAbierto && (
          <EnvioPorCorreo
            dashboardId={id}
            hojas={hojas.map((h) => ({ id: h.id, nombre: h.nombre || 'Hoja 1' }))}
            quienSoy={yo.data?.email ?? 'quien lo programe'}
            alCerrar={() => setCorreoAbierto(false)}
          />
        )}

        <PortadaInforme
          tablero={d.nombre}
          hoja={activa.nombre || 'Hoja 1'}
          modelo={d.modelo_nombre}
          version={d.version_modelo}
          certificado={d.certificado}
          publicado={d.publicado}
          filtros={activos}
          usuario={yo.data?.email}
        />

        <div
          id="rejilla"
          className={`rejilla ${lienzo.modo === 'pantalla' && !noCabe ? 'fija' : ''}`}
          style={{ '--cols': lienzo.columnas } as CSSProperties}
        >
          {mios.length === 0 ? (
            <div className="vacio">
              {borrador.widgets.length === 0
                ? 'Tablero vacío.'
                : `La hoja "${activa.nombre || 'sin nombre'}" está vacía.`}
              {editando
                ? ' Agrega un widget desde la lista de la izquierda.'
                : puedeEditar && ' Entra en Editar y agrega un widget.'}
            </div>
          ) : (
            <GridLayout
              className="layout"
              width={caja.ancho}
              gridConfig={{
                cols: lienzo.columnas,
                rowHeight: altoFila,
                margin: [MARGEN, MARGEN],
              }}
              // Se arrastra por la cabecera: si se arrastrara por cualquier punto,
              // no se podría hacer clic dentro de un gráfico ni de un filtro.
              dragConfig={{ enabled: editando, handle: '.widget > header' }}
              resizeConfig={{ enabled: editando }}
              onLayoutChange={editando ? alMoverRejilla : undefined}
              layout={enOrden.map((w) => ({
                i: w.id,
                x: w.posicion.x,
                y: w.posicion.y,
                w: w.posicion.ancho,
                h: w.posicion.alto,
              }))}
            >
              {enOrden.map((w) => (
                <div
                  key={w.id}
                  className={
                    `widget tipo-${w.tipo}` +
                    (elegido === w.id && editando ? ' sel' : '') +
                    (editando ? ' editando' : '')
                  }
                  // La posicion en la rejilla, tambien como variables CSS: en el
                  // informe la rejilla se rearma con `grid` y necesita saber la
                  // columna y el ancho de cada widget, y el alto para darselo a un
                  // grafico, que sin alto de rejilla no tiene ninguno. En pantalla
                  // no se usan.
                  style={
                    {
                      '--gx': w.posicion.x,
                      '--gw': w.posicion.ancho,
                      '--gh': w.posicion.alto,
                    } as CSSProperties
                  }
                  onMouseDown={() => editando && setElegido(w.id)}
                >
                  {/* Un texto sin título no lleva cabecera: es un título de
                      sección, no una tarjeta, y una barra que dice «texto» encima de
                      «1.- VENTAS» sobra. Al editar sí se dibuja, porque es el asa
                      con la que se arrastra y sin ella no se podría mover. */}
                  <header hidden={w.tipo === 'texto' && !w.titulo && !editando}>
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
              {widget ? (
                <>
                  <button className="activo">{widget.tipo}</button>
                  <button onClick={() => setElegido(null)}>Hoja</button>
                </>
              ) : (
                <>
                  <button
                    className={pestanaDer === 'hoja' ? 'activo' : ''}
                    onClick={() => setPestanaDer('hoja')}
                  >
                    Hoja
                  </button>
                  <button
                    className={pestanaDer === 'tablero' ? 'activo' : ''}
                    onClick={() => setPestanaDer('tablero')}
                  >
                    Tablero
                  </button>
                </>
              )}
            </div>
          </div>
          {widget ? (
            <PanelWidget
              widget={widget}
              modeloId={d.modelo_id}
              hojas={hojas}
              alCambiar={(cambios) => cambiarWidget(widget.id, cambios)}
              alQuitar={() => {
                setBorrador({
                  ...borrador,
                  widgets: borrador.widgets.filter((w) => w.id !== widget.id),
                })
                setElegido(null)
              }}
            />
          ) : pestanaDer === 'hoja' ? (
            <PanelHoja
              hoja={activa}
              indice={hojas.findIndex((h) => h.id === activa.id)}
              total={hojas.length}
              widgets={mios.length}
              alCambiar={(cambios) => cambiarHoja(activa.id, cambios)}
              alMover={(paso) => moverHoja(activa.id, paso)}
              alBorrar={() => borrarHoja(activa.id)}
            />
          ) : (
            <PanelTablero
              nombre={d.nombre}
              carpeta={d.carpeta}
              publicado={d.publicado}
              certificado={d.certificado}
              esAdmin={yo.data?.rol === 'administrador'}
              versiones={versiones.data?.versiones.map((v) => v.version) ?? []}
              versionActual={d.version_modelo}
              alRenombrar={(nombre) => guardar.mutate({ nombre })}
              alMoverDeCarpeta={(carpeta) => guardar.mutate({ carpeta })}
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

/**
 * Inspector de una hoja: cómo se llama, de qué tamaño es su espacio de trabajo, y
 * dónde va en el libro.
 */
function PanelHoja({
  hoja,
  indice,
  total,
  widgets,
  alCambiar,
  alMover,
  alBorrar,
}: {
  hoja: Hoja
  indice: number
  total: number
  widgets: number
  alCambiar: (cambios: Partial<Hoja>) => void
  alMover: (paso: -1 | 1) => void
  alBorrar: () => void
}) {
  const l = hoja.lienzo
  const poner = (cambios: Partial<Lienzo>) => alCambiar({ lienzo: { ...l, ...cambios } })

  return (
    <div className="inspector">
      <div className="campo">
        <label>Nombre de la hoja</label>
        <input
          type="text"
          value={hoja.nombre}
          placeholder={`Hoja ${indice + 1}`}
          onChange={(e) => alCambiar({ nombre: e.target.value })}
        />
      </div>

      <div className="campo">
        <label>Espacio de trabajo</label>
        <select
          value={l.modo}
          onChange={(e) => poner({ modo: e.target.value as Lienzo['modo'] })}
        >
          <option value="pantalla">Cabe en la pantalla</option>
          <option value="libre">Se desplaza</option>
        </select>
        <span className="chico tenue">
          {l.modo === 'pantalla'
            ? 'La hoja entera se ve de un golpe: el alto se reparte entre las filas. Un widget que nadie ve es una cifra que nadie revisa.'
            : 'La fila mide siempre lo mismo y la página se desplaza. Es para un informe largo que se lee de arriba abajo.'}
        </span>
      </div>

      <div className="fila">
        <div className="campo">
          <label>Columnas</label>
          <input
            type="number"
            min={4}
            max={24}
            value={l.columnas}
            onChange={(e) =>
              poner({ columnas: Math.min(24, Math.max(4, Number(e.target.value) || 12)) })
            }
          />
        </div>
        <div className="campo">
          <label>Filas</label>
          <input
            type="number"
            min={2}
            max={60}
            value={l.filas}
            onChange={(e) =>
              poner({ filas: Math.min(60, Math.max(2, Number(e.target.value) || 12)) })
            }
          />
        </div>
      </div>
      <span className="chico tenue" style={{ marginTop: -8 }}>
        Bajar las columnas no mueve lo que ya está puesto: si algo se sale, guardar
        lo dice y no lo recorta a escondidas.
      </span>

      <div className="campo">
        <label>Orden en el libro</label>
        <div className="fila">
          <button className="btn" disabled={indice === 0} onClick={() => alMover(-1)}>
            ← Antes
          </button>
          <button
            className="btn"
            disabled={indice === total - 1}
            onClick={() => alMover(1)}
          >
            Después →
          </button>
        </div>
        <span className="chico tenue">
          Hoja {indice + 1} de {total} · {widgets} widget(s)
        </span>
      </div>

      <button
        className="btn peligro"
        disabled={total === 1}
        title={total === 1 ? 'Un tablero necesita al menos una hoja' : undefined}
        onClick={alBorrar}
      >
        Borrar hoja
      </button>
    </div>
  )
}

function PanelTablero({
  nombre,
  carpeta,
  publicado,
  certificado,
  esAdmin,
  versiones,
  versionActual,
  alRenombrar,
  alMoverDeCarpeta,
  alPublicar,
  alCertificar,
  alMover,
  alBorrar,
}: {
  nombre: string
  carpeta: string
  publicado: boolean
  certificado: boolean
  esAdmin: boolean
  versiones: number[]
  versionActual: number
  alRenombrar: (n: string) => void
  alMoverDeCarpeta: (c: string) => void
  alPublicar: (v: boolean) => void
  alCertificar: (v: boolean) => void
  alMover: (v: number) => void
  alBorrar: () => void
}) {
  const [texto, setTexto] = useState(nombre)
  const [carp, setCarp] = useState(carpeta)
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
        <label>Carpeta</label>
        <div className="fila">
          <input
            type="text"
            value={carp}
            placeholder="Sin carpeta"
            onChange={(e) => setCarp(e.target.value)}
          />
          <button
            className="btn"
            style={{ flex: '0 0 auto' }}
            disabled={carp.trim() === carpeta}
            onClick={() => alMoverDeCarpeta(carp.trim())}
          >
            Mover
          </button>
        </div>
        <span className="chico tenue">
          Solo ordena el estante. No cambia quién puede ver este tablero, y mover de
          carpeta no le quita la certificación.
        </span>
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
