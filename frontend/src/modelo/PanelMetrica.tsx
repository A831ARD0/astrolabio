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
import { Combo } from '../comunes/Combo'
import { useOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'
import type { Accion } from './estado'
import {
  LENGUAJE, TEMA_CLARO, TEMA_OSCURO, fijarContexto, registrarLenguaje,
} from './formula'

const FORMATOS = ['numero', 'entero', 'moneda', 'porcentaje']

/**
 * El valor del desplegable que significa «ninguna entidad».
 *
 * Un `<select>` no puede llevar `null` como valor —los valores de una opción son
 * cadenas— y la cadena vacía ya significa «no hay hechos que elegir». Así que un
 * centinela, que nunca puede chocar con el nombre de una entidad porque los
 * nombres no llevan espacios ni paréntesis.
 */
const COMPUESTA = '(compuesta)'

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
  /**
   * Si el nombre técnico deja de seguir a la etiqueta.
   *
   * En una métrica que ya existe empieza en `true` sin remedio: su nombre es lo
   * que las demás fórmulas escriben como `[nombre]` y lo que los tableros tienen
   * guardado, así que cambiarlo solo porque se corrigió una tilde de la etiqueta
   * rompería cosas que no se están mirando.
   */
  const [nombreAMano, setNombreAMano] = useState(indice !== null)
  const [agruparPor, setAgruparPor] = useState('')
  const [fallos, setFallos] = useState<FalloFormula[]>([])
  const [sql, setSql] = useState<string | null>(null)
  const [buscar, setBuscar] = useState('')
  const [referencia, setReferencia] = useState(true)

  const prueba = useProbarMetrica(modeloId)
  const revisar = useRevisarFormula(modeloId)
  const funciones = useFunciones()

  // La tabla de la prueba: pocas filas, pero es donde se comprueba si la
  // fórmula dice lo que se quería, y para eso hace falta ver los extremos.
  const ordenPrueba = useOrden(
    prueba.data?.filas ?? [], (f, c) => f[c])

  const monacoRef = useRef<Monaco | null>(null)
  const editorRef = useRef<{ getModel: () => unknown } | null>(null)

  const oscuro = window.matchMedia('(prefers-color-scheme: dark)').matches
  const hechos = definicion.entidades.filter((e) => e.tipo === 'hecho')
  const compuesta = borrador.entidad === null
  const entidad = definicion.entidades.find((e) => e.nombre === borrador.entidad)

  const dimensiones = definicion.entidades.flatMap((e) =>
    e.campos
      .filter((c) => c.rol === 'dimension' && c.visible !== false)
      .map((c) => `${e.nombre}.${c.nombre}`),
  )

  /**
   * Las métricas que se pueden escribir como `[nombre]`.
   *
   * En una métrica normal, solo las de su mismo hecho: pegar aquí la expresión de
   * una que vive en otra tabla daría SQL que compila sobre columnas que no
   * existen. En una compuesta, **todas** — no pega ninguna expresión, nombra la
   * cifra ya calculada, y cruzar hechos es justo para lo que sirve.
   */
  const hermanas = useMemo(
    () =>
      definicion.metricas.filter(
        (m, i) => i !== indice && (compuesta || m.entidad === borrador.entidad),
      ),
    [definicion.metricas, borrador.entidad, compuesta, indice],
  )

  const campos = useMemo(() => (compuesta ? [] : entidad?.campos ?? []), [compuesta, entidad])

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
    if (!borrador.expresion.trim() || (!compuesta && !borrador.entidad)) {
      setFallos([])
      setSql(null)
      return
    }
    const t = setTimeout(() => {
      revisar.mutate(
        compuesta
          ? {
              entidad: null,
              expresion: borrador.expresion,
              // Con su expresión si también son compuestas, y `null` si se
              // agregan desde un hecho: el servidor necesita saber cuáles tiene
              // que meter dentro y cuáles son una columna ya calculada.
              metricas_del_modelo: Object.fromEntries(
                hermanas.map((m) => [
                  m.nombre,
                  m.entidad === null ? m.expresion : null,
                ]),
              ),
            }
          : {
              entidad: borrador.entidad,
              expresion: borrador.expresion,
              campos: campos.map((c) => c.nombre),
              metricas: Object.fromEntries(
                hermanas.map((m) => [m.nombre, m.expresion]),
              ),
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
  }, [borrador.expresion, borrador.entidad, compuesta, campos, hermanas])

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
              {/*
                La etiqueta va primero porque es lo único que se escribe
                pensando: es el texto que va a salir en el tablero. El nombre
                técnico se deduce de ella y solo se toca cuando hace falta.
              */}
              <div className="campo">
                <label>Etiqueta</label>
                <input
                  type="text"
                  autoFocus
                  value={borrador.etiqueta}
                  onChange={(e) => {
                    const etiqueta = e.target.value
                    setBorrador((b) => ({
                      ...b,
                      etiqueta,
                      nombre: nombreAMano ? b.nombre : tecnificar(etiqueta),
                    }))
                  }}
                  placeholder="Utilidad promedio"
                />
              </div>
              <div className="campo">
                <label>
                  Nombre técnico
                  {!nombreAMano && (
                    <span className="chico tenue" style={{ fontWeight: 400, marginLeft: 6 }}>
                      automático
                    </span>
                  )}
                </label>
                <input
                  type="text"
                  className="mono"
                  value={borrador.nombre}
                  onChange={(e) => {
                    // Vaciarlo devuelve el campo al automático: es el único gesto
                    // evidente para deshacer un nombre escrito a mano.
                    const nombre = e.target.value
                    setNombreAMano(nombre.trim() !== '')
                    setBorrador((b) => ({
                      ...b,
                      nombre: nombre.trim() === '' ? tecnificar(b.etiqueta) : nombre,
                    }))
                  }}
                  placeholder="utilidad_promedio"
                />
              </div>
              {/*
                Dos cosas que antes eran una sola, y confundirlas sale caro: el
                hecho decide QUÉ SE CALCULA —es el FROM del SQL, y cambiarlo cambia
                la cifra— y la tabla de medidas solo dice DÓNDE SE VE. Es la
                separación que hace Power BI, y por eso mover una métrica de cajón
                no le toca el número.
              */}
              <div className="campo" style={{ flex: '0 0 190px' }}>
                <label>Calcula desde</label>
                <select
                  value={compuesta ? COMPUESTA : borrador.entidad ?? ''}
                  onChange={(e) =>
                    setBorrador({
                      ...borrador,
                      entidad: e.target.value === COMPUESTA ? null : e.target.value,
                    })
                  }
                >
                  {hechos.length === 0 && <option value="">(no hay hechos)</option>}
                  {hechos.map((e) => (
                    <option key={e.nombre} value={e.nombre}>
                      {e.nombre}
                    </option>
                  ))}
                  {/*
                    La opción que permite cruzar hechos. Va al final y separada
                    porque no es un hecho más: es la ausencia de hecho.
                  */}
                  <option value={COMPUESTA}>· otras métricas (compuesta)</option>
                </select>
              </div>
              <div className="campo" style={{ flex: '0 0 150px' }}>
                <label>Aparece en</label>
                <select
                  value={borrador.tabla_medidas ?? ''}
                  title={
                    compuesta
                      ? 'Una compuesta no tiene hecho debajo del cual ponerse, así que sin cajón aparece en «Compuestas».'
                      : undefined
                  }
                  onChange={(e) =>
                    setBorrador({
                      ...borrador,
                      tabla_medidas: e.target.value || null,
                    })
                  }
                >
                  <option value="">{compuesta ? '(en Compuestas)' : '(bajo su hecho)'}</option>
                  {(definicion.tablas_medidas ?? []).map((t) => (
                    <option key={t.nombre} value={t.nombre}>
                      {t.nombre}
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

            {/*
              Sin `min-height: 0`, a propósito. Un elemento flex no se encoge por
              debajo de su contenido salvo que se le diga, y aquí ese permiso
              hacía que el editor y su pie se salieran de la caja y se pintaran
              encima de la fila de medidas. La columna entera ya tiene scroll.
            */}
            <div className="campo" style={{ flex: 1 }}>
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
                {compuesta ? (
                  <>
                    Solo <code>[otra_metrica]</code>, operaciones y funciones que
                    no agreguen. No lleva columnas —no lee ninguna tabla— ni{' '}
                    <code>SUMA</code>, porque lo que recibe ya viene sumado.{' '}
                    <code>VAR</code>/<code>RETURN</code> y <code>--</code> también
                    valen aquí.
                  </>
                ) : (
                  <>
                    Los campos se escriben sin prefijo de tabla: el motor los
                    califica solo. <code>VAR</code>/<code>RETURN</code> para
                    partirla en pasos, <code>--</code> para comentar,{' '}
                    <code>[otra_metrica]</code> para reutilizar otra.
                  </>
                )}
              </span>
            </div>

            {/* Lo que se puede meter con un clic, sin escribirlo. */}
            {(entidad || compuesta) && (
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
                    <span className="suave">
                      {compuesta ? 'Métricas del modelo: ' : 'Otras métricas: '}
                    </span>
                    {hermanas.map((m) => (
                      <button
                        key={m.nombre}
                        className="btn chico mono"
                        /* De qué hecho sale cada una, que en una compuesta es lo
                           que hay que saber para no dividir peras entre manzanas. */
                        title={
                          compuesta
                            ? `${m.entidad ?? 'compuesta'} · ${m.expresion}`
                            : m.expresion
                        }
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
                <Combo
                  opciones={[
                    { valor: '', etiqueta: '(total, sin agrupar)' },
                    ...dimensiones.map((d) => ({ valor: d, etiqueta: d })),
                  ]}
                  valor={agruparPor}
                  alElegir={setAgruparPor}
                  marcador="(total, sin agrupar)"
                />
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
                          <Th key={c} orden={ordenPrueba} clave={c} titulo={c}>
                            {c === '__prueba__' ? borrador.etiqueta || 'valor' : c}
                          </Th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {ordenPrueba.filas.map((f, i) => (
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
                Para cruzar dos hechos —lo vendido entre lo presupuestado— elige{' '}
                <strong>otras métricas (compuesta)</strong> en «Calcula desde». Se
                calcula después de que cada hecho agregó lo suyo, así que el
                objetivo del mes no se multiplica por el número de facturas.
              </p>
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

/**
 * El nombre técnico que le toca a una etiqueta.
 *
 * El nombre viaja por sitios donde «Utilidad promedio %» no cabe: se escribe
 * como `[nombre]` dentro de otras fórmulas y acaba de alias en el SQL. Así que
 * se le quitan acentos, mayúsculas y todo lo que no sea letra o dígito, y no se
 * deja empezar por dígito, que ningún motor acepta como identificador.
 */
function tecnificar(etiqueta: string): string {
  const base = etiqueta
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return /^\d/.test(base) ? `m_${base}` : base
}

function formatear(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return v.toLocaleString('es-MX', { maximumFractionDigits: 2 })
  return String(v)
}
