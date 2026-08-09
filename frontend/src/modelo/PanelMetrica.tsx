/**
 * Editor de una métrica.
 *
 * Tres cosas ocurren aquí, y las tres hacen falta:
 *
 *   1. **Se escribe con ayuda.** El editor conoce los campos de la entidad, las
 *      demás métricas y el catálogo de funciones: los ofrece al escribir, los
 *      documenta al pasar por encima y los colorea distinto según lo que sean.
 *
 *   2. **Se revisa mientras se escribe**, sin ejecutar nada. Un campo mal
 *      escrito o un campo suelto fuera de la agregación se subrayan en rojo en
 *      su línea, en cuanto se deja de teclear.
 *
 *   3. **Se prueba contra los datos.** Es lo único que distingue una fórmula
 *      correcta de una fórmula que dice lo que se quería decir. Probar no guarda
 *      nada: la métrica se inyecta en una copia del modelo que se descarta al
 *      responder.
 *
 * El panel de la derecha es la referencia del lenguaje. Está aquí y no en un
 * manual aparte por lo mismo que el botón de probar: lo que hay que consultar en
 * otra ventana no se consulta.
 */

import Editor from '@monaco-editor/react'
import type { Monaco } from '@monaco-editor/react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useFunciones, useProbarMetrica, useRevisarFormula } from '../api/hooks'
import type { Definicion, FalloFormula, FuncionFormula, Metrica } from '../api/tipos'
import { Velo } from '../comunes/Velo'
import type { Accion } from './estado'
import {
  LENGUAJE, TEMA_CLARO, TEMA_OSCURO, fijarContexto, registrarLenguaje,
} from './formula'

const FORMATOS = ['numero', 'entero', 'moneda', 'porcentaje']

const CATEGORIAS: Record<string, string> = {
  agregacion: 'Agregación',
  condicion: 'Condición y lógica',
  matematica: 'Matemáticas',
  texto: 'Texto',
  fecha: 'Fechas',
}

/** Cuánto se espera tras la última tecla antes de pedir la revisión. */
const ESPERA_MS = 400

export function PanelMetrica({
  modeloId,
  definicion,
  indice,
  metrica,
  despachar,
  alCerrar,
}: {
  modeloId: number
  definicion: Definicion
  /** null = métrica nueva. */
  indice: number | null
  metrica: Metrica
  despachar: (a: Accion) => void
  alCerrar: () => void
}) {
  const [borrador, setBorrador] = useState<Metrica>(metrica)
  const [agruparPor, setAgruparPor] = useState('')
  const [fallos, setFallos] = useState<FalloFormula[]>([])
  const [sql, setSql] = useState<string | null>(null)
  const [buscar, setBuscar] = useState('')
  const [referencia, setReferencia] = useState(true)

  const prueba = useProbarMetrica(modeloId)
  const revisar = useRevisarFormula(modeloId)
  const funciones = useFunciones()
  const monacoRef = useRef<Monaco | null>(null)
  const editorRef = useRef<{ getModel: () => unknown } | null>(null)

  const oscuro = window.matchMedia('(prefers-color-scheme: dark)').matches
  const hechos = definicion.entidades.filter((e) => e.tipo === 'hecho')
  const entidad = definicion.entidades.find((e) => e.nombre === borrador.entidad)

  const dimensiones = definicion.entidades.flatMap((e) =>
    e.campos
      .filter((c) => c.rol === 'dimension' && c.visible !== false)
      .map((c) => `${e.nombre}.${c.nombre}`),
  )

  /** Las otras métricas de ESTA entidad: las únicas que se pueden referenciar. */
  const hermanas = useMemo(
    () =>
      definicion.metricas.filter(
        (m, i) => m.entidad === borrador.entidad && i !== indice,
      ),
    [definicion.metricas, borrador.entidad, indice],
  )

  const campos = useMemo(() => entidad?.campos ?? [], [entidad])

  // El contexto que lee el autocompletado. Se fija en cada render porque cambia
  // al cambiar de entidad, y es una asignación de tres campos.
  fijarContexto({
    campos: campos.map((c) => ({ nombre: c.nombre, tipo: c.tipo, rol: c.rol })),
    metricas: hermanas.map((m) => ({
      nombre: m.nombre,
      etiqueta: m.etiqueta,
      expresion: m.expresion,
    })),
    funciones: funciones.data?.funciones ?? [],
  })

  // Revisión en vivo, con freno: se pide al parar de teclear y no en cada tecla.
  useEffect(() => {
    if (!borrador.expresion.trim() || !borrador.entidad) {
      setFallos([])
      setSql(null)
      return
    }
    const t = setTimeout(() => {
      revisar.mutate(
        {
          entidad: borrador.entidad,
          expresion: borrador.expresion,
          campos: campos.map((c) => c.nombre),
          metricas: Object.fromEntries(hermanas.map((m) => [m.nombre, m.expresion])),
        },
        {
          onSuccess: (r) => {
            setFallos(r.fallos)
            setSql(r.sql)
          },
        },
      )
    }, ESPERA_MS)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [borrador.expresion, borrador.entidad, campos, hermanas])

  // Los subrayados rojos dentro del editor. Van como marcadores de Monaco y no
  // como una lista aparte porque el error hay que verlo DONDE está.
  useEffect(() => {
    const monaco = monacoRef.current
    const modelo = editorRef.current?.getModel()
    if (!monaco || !modelo) return
    monaco.editor.setModelMarkers(modelo as never, 'formula', fallos.map((f) => ({
      severity:
        f.gravedad === 'error'
          ? monaco.MarkerSeverity.Error
          : monaco.MarkerSeverity.Warning,
      message: f.mensaje,
      startLineNumber: f.linea,
      startColumn: f.columna,
      endLineNumber: f.linea,
      endColumn: f.columna + Math.max(f.largo, 1),
    })))
  }, [fallos])

  const nombreRepetido = definicion.metricas.some(
    (m, i) => m.nombre === borrador.nombre && i !== indice,
  )
  const hayErrores = fallos.some((f) => f.gravedad === 'error')
  const valida =
    !!borrador.nombre.trim() &&
    !!borrador.expresion.trim() &&
    !nombreRepetido &&
    !hayErrores

  function insertar(texto: string) {
    setBorrador((b) => ({
      ...b,
      expresion: b.expresion + (b.expresion && !b.expresion.endsWith('\n') ? ' ' : '') + texto,
    }))
  }

  const porCategoria = useMemo(() => {
    const aguja = buscar.trim().toLowerCase()
    const filtradas = (funciones.data?.funciones ?? []).filter(
      (f) =>
        !aguja ||
        f.nombre.toLowerCase().includes(aguja) ||
        f.resumen.toLowerCase().includes(aguja),
    )
    const mapa = new Map<string, FuncionFormula[]>()
    for (const f of filtradas) {
      mapa.set(f.categoria, [...(mapa.get(f.categoria) ?? []), f])
    }
    return [...mapa.entries()]
  }, [funciones.data, buscar])

  return (
    <Velo alCerrar={alCerrar}>
      <div className="modal ancho metrica">
        <header>
          {indice === null ? 'Nueva métrica' : `Métrica ${metrica.nombre}`}
          <button
            className="btn chico"
            style={{ marginLeft: 'auto' }}
            onClick={() => setReferencia((v) => !v)}
          >
            {referencia ? 'Ocultar referencia' : 'Ver referencia'}
          </button>
        </header>

        <div className="cont metrica-cuerpo">
          {/* ------------------------------------------------- izquierda */}
          <div className="metrica-editor">
            <div className="fila">
              <div className="campo">
                <label>Nombre técnico</label>
                <input
                  type="text"
                  className="mono"
                  value={borrador.nombre}
                  onChange={(e) => setBorrador({ ...borrador, nombre: e.target.value })}
                  placeholder="monto_utilidad"
                />
              </div>
              <div className="campo">
                <label>Etiqueta</label>
                <input
                  type="text"
                  value={borrador.etiqueta}
                  onChange={(e) => setBorrador({ ...borrador, etiqueta: e.target.value })}
                  placeholder="Utilidad"
                />
              </div>
              <div className="campo" style={{ flex: '0 0 150px' }}>
                <label>Vive en</label>
                <select
                  value={borrador.entidad}
                  onChange={(e) => setBorrador({ ...borrador, entidad: e.target.value })}
                >
                  {hechos.length === 0 && <option value="">(no hay hechos)</option>}
                  {hechos.map((e) => (
                    <option key={e.nombre} value={e.nombre}>
                      {e.nombre}
                    </option>
                  ))}
                </select>
              </div>
              <div className="campo" style={{ flex: '0 0 130px' }}>
                <label>Formato</label>
                <select
                  value={borrador.formato ?? 'numero'}
                  onChange={(e) => setBorrador({ ...borrador, formato: e.target.value })}
                >
                  {FORMATOS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {nombreRepetido && (
              <div className="error-caja">Ya hay otra métrica con ese nombre.</div>
            )}

            <div className="campo" style={{ flex: 1, minHeight: 0 }}>
              <label>
                Expresión
                <span className="chico tenue" style={{ fontWeight: 400, marginLeft: 8 }}>
                  Ctrl+Espacio para ver qué se puede escribir
                </span>
              </label>
              <div className="caja-formula">
                <Editor
                  height="100%"
                  language={LENGUAJE}
                  theme={oscuro ? TEMA_OSCURO : TEMA_CLARO}
                  value={borrador.expresion}
                  onChange={(v) => setBorrador({ ...borrador, expresion: v ?? '' })}
                  beforeMount={(monaco) => {
                    monacoRef.current = monaco
                    registrarLenguaje(monaco)
                  }}
                  onMount={(editor) => {
                    editorRef.current = editor as never
                  }}
                  options={{
                    minimap: { enabled: false },
                    fontSize: 13,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    wordWrap: 'on',
                    renderLineHighlight: 'none',
                    overviewRulerLanes: 0,
                    padding: { top: 8, bottom: 8 },
                    suggestSelection: 'first',
                    tabSize: 2,
                  }}
                />
              </div>
              <span className="chico tenue">
                Los campos se escriben sin prefijo de tabla: el motor los califica
                solo. <code>VAR</code>/<code>RETURN</code> para partirla en pasos,{' '}
                <code>--</code> para comentar, <code>[otra_metrica]</code> para
                reutilizar otra.
              </span>
            </div>

            {/* Lo que se puede meter con un clic, sin escribirlo. */}
            {entidad && (
              <div className="atajos">
                {campos.filter((c) => c.rol === 'medida_base').length > 0 && (
                  <div className="chico">
                    <span className="suave">Medidas: </span>
                    {campos
                      .filter((c) => c.rol === 'medida_base')
                      .map((c) => (
                        <button
                          key={c.nombre}
                          className="btn chico mono"
                          onClick={() => insertar(c.nombre)}
                        >
                          {c.nombre}
                        </button>
                      ))}
                  </div>
                )}
                {hermanas.length > 0 && (
                  <div className="chico">
                    <span className="suave">Otras métricas: </span>
                    {hermanas.map((m) => (
                      <button
                        key={m.nombre}
                        className="btn chico mono"
                        title={m.expresion}
                        onClick={() => insertar(`[${m.nombre}]`)}
                      >
                        [{m.nombre}]
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Los mismos fallos que van subrayados, en lista: en una fórmula
                larga el error puede estar fuera de la parte visible. */}
            {fallos.length > 0 && (
              <div className={hayErrores ? 'error-caja' : 'aviso-caja'}>
                {fallos.map((f, i) => (
                  <div key={i}>
                    <span className="mono">línea {f.linea}</span> · {f.mensaje}
                  </div>
                ))}
              </div>
            )}

            <div className="fila" style={{ alignItems: 'flex-end' }}>
              <div className="campo">
                <label>Probar agrupando por (opcional)</label>
                <select value={agruparPor} onChange={(e) => setAgruparPor(e.target.value)}>
                  <option value="">(total, sin agrupar)</option>
                  {dimensiones.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
              <button
                className="btn"
                style={{ flex: '0 0 auto' }}
                disabled={!borrador.expresion.trim() || hayErrores || prueba.isPending}
                title={
                  hayErrores ? 'Corrige los errores antes de probar' : undefined
                }
                onClick={() =>
                  prueba.mutate({
                    entidad: borrador.entidad,
                    expresion: borrador.expresion,
                    dimensiones: agruparPor ? [agruparPor] : [],
                    limite: 10,
                  })
                }
              >
                {prueba.isPending ? 'Probando…' : 'Probar'}
              </button>
            </div>

            {prueba.isError && (
              <div className="error-caja">{(prueba.error as Error).message}</div>
            )}

            {prueba.data && (
              <>
                <div className="tabla-envoltura" style={{ maxHeight: 180 }}>
                  <table className="datos">
                    <thead>
                      <tr>
                        {prueba.data.columnas.map((c) => (
                          <th key={c}>
                            {c === '__prueba__' ? borrador.etiqueta || 'valor' : c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {prueba.data.filas.map((f, i) => (
                        <tr key={i}>
                          {prueba.data!.columnas.map((c) => (
                            <td key={c} className={typeof f[c] === 'number' ? 'num' : ''}>
                              {formatear(f[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <details className="chico">
                  <summary className="suave">SQL ejecutado ({prueba.data.ms} ms)</summary>
                  <pre className="mono" style={{ overflow: 'auto', maxHeight: 160 }}>
                    {prueba.data.sql}
                  </pre>
                </details>
              </>
            )}

            {!prueba.data && sql && (
              <details className="chico">
                <summary className="suave">A qué SQL se traduce</summary>
                <pre className="mono" style={{ overflow: 'auto', maxHeight: 120 }}>
                  {sql}
                </pre>
              </details>
            )}
          </div>

          {/* ---------------------------------------------------- derecha */}
          {referencia && (
            <aside className="metrica-referencia">
              <input
                type="search"
                placeholder="Buscar función…"
                value={buscar}
                onChange={(e) => setBuscar(e.target.value)}
              />
              {funciones.isLoading && <div className="vacio">Cargando…</div>}
              {porCategoria.map(([categoria, lista]) => (
                <section key={categoria}>
                  <h5>{CATEGORIAS[categoria] ?? categoria}</h5>
                  {lista.map((f) => (
                    <details key={f.nombre}>
                      <summary>
                        <span className="mono">{f.nombre}</span>
                        {f.agrega && <span className="etiqueta dim">agrega</span>}
                      </summary>
                      <p>{f.resumen}</p>
                      <code className="firma">{f.firma}</code>
                      <div className="ejemplo">
                        <code>{f.ejemplo}</code>
                        <button
                          className="btn chico"
                          onClick={() => insertar(f.ejemplo)}
                        >
                          Usar
                        </button>
                      </div>
                    </details>
                  ))}
                </section>
              ))}
              {!funciones.isLoading && porCategoria.length === 0 && (
                <div className="vacio">Ninguna función se llama así.</div>
              )}
              <p className="chico tenue" style={{ padding: '0 2px' }}>
                No hay inteligencia de tiempo tipo DAX (
                <span className="mono">SAMEPERIODLASTYEAR</span> y compañía): una
                métrica aquí es una agregación dentro del agrupamiento de la
                consulta y no tiene un contexto de filtro que reescribir. La
                comparación contra otro periodo se arma en el tablero.
              </p>
            </aside>
          )}
        </div>

        <footer>
          {indice !== null && (
            <button
              className="btn peligro"
              style={{ marginRight: 'auto' }}
              onClick={() => {
                despachar({ t: 'quitar_metrica', nombre: metrica.nombre })
                alCerrar()
              }}
            >
              Quitar
            </button>
          )}
          <button className="btn" onClick={alCerrar}>
            Cancelar
          </button>
          <button
            className="btn primario"
            disabled={!valida}
            title={hayErrores ? 'La fórmula tiene errores' : undefined}
            onClick={() => {
              despachar({ t: 'guardar_metrica', indice, metrica: borrador })
              alCerrar()
            }}
          >
            Aceptar
          </button>
        </footer>
      </div>
    </Velo>
  )
}

function formatear(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return v.toLocaleString('es-MX', { maximumFractionDigits: 2 })
  return String(v)
}
