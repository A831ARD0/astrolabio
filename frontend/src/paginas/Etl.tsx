/**
 * El ETL: orígenes, pasos, vista previa.
 *
 * Tres cosas que definen esta pantalla:
 *
 * 1. **La vista previa cuenta filas por paso.** Es lo que convierte un "no cuadra"
 *    en "se pierde en el paso 3". Sin eso, una transformación de seis pasos es una
 *    caja negra.
 * 2. **El SQL generado está a la vista.** Los pasos no son un lenguaje secreto: se
 *    puede leer exactamente qué se va a ejecutar, y copiarlo.
 * 3. **Pegar SQL es de primera clase.** Quien ya tiene su consulta no debería
 *    rearmarla; y si se puede, se convierte a pasos para poder seguir editándola.
 */

import { useEffect, useMemo, useState } from 'react'

import {
  ETIQUETA_PASO,
  type DefinicionTransformacion,
  type Paso,
  type TipoPaso,
  type TransformacionResumen,
  useColumnasOrigen,
  useDesdeSql,
  useEjecutarTransformacion,
  useGuardarTransformacion,
  useOrigenesDisponibles,
  usePrevisualizar,
  useTransformaciones,
} from '../api/etl'
import { PasoEditor } from '../etl/PasoEditor'
import { PanelLateral, Seccion } from '../comunes/Panel'
import { columnasAntesDe } from '../etl/columnas'
import { Velo } from '../comunes/Velo'

const TIPOS: TipoPaso[] = [
  'filtrar', 'columnas', 'derivar', 'agrupar', 'unir', 'apilar', 'renombrar',
  'ordenar', 'distintos', 'limitar',
]

const VACIA: DefinicionTransformacion = {
  nombre: '',
  descripcion: null,
  origenes: [],
  pasos: [],
  sql: null,
}

export function Etl() {
  const lista = useTransformaciones()
  const disponibles = useOrigenesDisponibles()
  const previa = usePrevisualizar()
  const guardar = useGuardarTransformacion()
  const ejecutar = useEjecutarTransformacion()
  const desdeSql = useDesdeSql()

  const [id, setId] = useState<number | null>(null)
  const [d, setD] = useState<DefinicionTransformacion>(VACIA)
  const [abierto, setAbierto] = useState<number | null>(null)
  const [modoSql, setModoSql] = useState(false)
  const [pegarSql, setPegarSql] = useState(false)
  const [sqlPegado, setSqlPegado] = useState('')

  function cargar(t: TransformacionResumen) {
    setId(t.id)
    setD(t.definicion)
    setModoSql(!!t.definicion.sql)
    setAbierto(null)
    previa.reset()
  }

  function nueva() {
    setId(null)
    setD(VACIA)
    setModoSql(false)
    setAbierto(null)
    previa.reset()
  }

  // El primer origen manda: sus columnas son las que se ofrecen en los pasos.
  const principal = d.origenes[0] ?? null
  const columnasPrincipal = useColumnasOrigen(principal)
  const columnas = useMemo(
    () => (columnasPrincipal.data?.columnas ?? []).map((c) => c.nombre),
    [columnasPrincipal.data],
  )

  /**
   * Las columnas que le ENTRAN a cada paso.
   *
   * Antes aquí había una sola lista —las columnas que devolvía la vista previa— y
   * se le pasaba a todos los pasos por igual. Como la vista previa devuelve la
   * salida de la cadena completa, marcar `Id_Sucursal` en «Elegir columnas» dejaba
   * ese mismo paso con un único cuadro: imposible marcar la segunda. Cualquier
   * paso colocado después de un «Agrupar y resumir» tenía el mismo problema.
   */
  const columnasDePaso = (i: number) => columnasAntesDe(columnas, d.pasos, i)

  // Para el paso que se va a AGREGAR al final manda la vista previa: la calcula el
  // compilador de verdad, así que donde discrepe de la simulación, tiene razón.
  const columnasFinales = previa.data?.columnas?.length
    ? previa.data.columnas
    : columnasAntesDe(columnas, d.pasos, d.pasos.length)

  const pasoUnir = abierto !== null ? d.pasos[abierto] : undefined
  const origenDerecha =
    pasoUnir?.tipo === 'unir' && typeof pasoUnir.con === 'string'
      ? (d.origenes.find((o) => o.nombre === pasoUnir.con) ?? null)
      : null
  const columnasDerecha = useColumnasOrigen(origenDerecha)

  // Previsualizar en cuanto hay algo que previsualizar, y al cambiar los pasos.
  useEffect(() => {
    if (d.origenes.length === 0) return
    if (!d.nombre.trim()) return
    const t = setTimeout(() => previa.mutate(d), 350)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(d)])

  const agregarOrigen = (
    tipo: 'tabla' | 'dataset' | 'tabla_en_conexiones',
    referencia: string,
  ) => {
    const base = referencia.replace(/[^A-Za-z0-9_]/g, '_')
    let nombre = base
    let n = 2
    while (d.origenes.some((o) => o.nombre === nombre)) nombre = `${base}_${n++}`
    setD({ ...d, origenes: [...d.origenes, { nombre, tipo, referencia }] })
  }

  const cambiarPaso = (i: number, cambios: Partial<Paso>) =>
    setD({ ...d, pasos: d.pasos.map((p, j) => (i === j ? { ...p, ...cambios } : p)) })

  const mover = (i: number, delta: number) => {
    const j = i + delta
    if (j < 0 || j >= d.pasos.length) return
    const pasos = [...d.pasos]
    ;[pasos[i], pasos[j]] = [pasos[j]!, pasos[i]!]
    setD({ ...d, pasos })
    setAbierto(j)
  }

  return (
    <div className="editor">
      {/* --------------------------------------------------- izquierda */}
      <PanelLateral clave="etl">
        <Seccion titulo="Transformaciones" clave="etl-lista"
                 extra={lista.data?.length ?? 0}>
          <>
            <div className="lista">
              {lista.data?.map((t) => (
                <button
                  key={t.id}
                  className={id === t.id ? 'sel' : ''}
                  onClick={() => cargar(t)}
                  title={t.descripcion ?? undefined}
                >
                  <span
                    className={`punto ${t.tiene_datos ? 'dimension' : ''}`}
                    style={t.tiene_datos ? undefined : { background: 'var(--borde-fuerte)' }}
                  />
                  <span className="nom">{t.nombre}</span>
                  <span className="dcha">
                    {t.filas ? t.filas.toLocaleString('es-MX') : '—'}
                  </span>
                </button>
              ))}
            </div>
            <button className="btn chico" style={{ marginTop: 8, width: '100%' }}
                    onClick={nueva}>
              + Nueva transformación
            </button>
          </>
        </Seccion>

        {/* `principal`: la lista larga se lleva el espacio que sobre, y el boton
            de «+ Nueva transformación» de arriba se queda a la vista. */}
        <Seccion titulo="Orígenes disponibles" principal clave="etl-origenes">
          <>
            {/* Un panel vacío y callado es lo peor que puede pasar aquí: no se
                distingue «no hay nada cargado» de «no pude leerlo». Antes esta
                pantalla no decía ninguna de las dos cosas. */}
            {disponibles.isLoading && (
              <div className="chico tenue" style={{ padding: '4px 8px' }}>
                Leyendo lo que hay…
              </div>
            )}
            {disponibles.isError && (
              <div className="error-caja chico" style={{ margin: '0 8px 8px' }}>
                No se pudieron leer los orígenes:{' '}
                {(disponibles.error as Error).message}
              </div>
            )}
            {disponibles.data?.avisos.map((a) => (
              <div key={a} className="aviso-caja chico" style={{ margin: '0 8px 8px' }}>
                {a}
              </div>
            ))}
            {disponibles.data
             && disponibles.data.tablas.length === 0
             && disponibles.data.datasets.length === 0
             && disponibles.data.transformaciones.length === 0 && (
              <div className="chico tenue" style={{ padding: '4px 8px' }}>
                No hay nada que usar como origen todavía. Trae una tabla desde
                Conexiones y cárgala; aquí aparecerá.
              </div>
            )}

            {(disponibles.data?.tablas.length ?? 0) > 0 && (
              <div className="chico tenue" style={{ padding: '0 8px 4px' }}>
                Tablas del motor
              </div>
            )}
            <div className="lista">
              {disponibles.data?.tablas.map((t) => (
                <button key={t.nombre} onClick={() => agregarOrigen('tabla', t.nombre)}>
                  <span className="nom mono">{t.nombre}</span>
                  <span className="dcha">{t.filas.toLocaleString('es-MX')}</span>
                </button>
              ))}
            </div>

            {(disponibles.data?.datasets.length ?? 0) > 0 && (
              <>
                <div className="chico tenue" style={{ padding: '8px 8px 4px' }}>
                  Datos cargados
                </div>
                <div className="lista">
                  {disponibles.data?.datasets.map((t) => (
                    <button
                      key={t.nombre}
                      disabled={!t.tiene_datos || !t.usable}
                      title={!t.usable
                        ? 'Su nombre no se puede usar como origen'
                        : t.tiene_datos
                          ? undefined
                          : 'Todavía no tiene datos cargados'}
                      onClick={() => agregarOrigen('dataset', t.nombre)}
                    >
                      <span className="nom mono">{t.nombre}</span>
                      {!t.usable && <span className="dcha">⚠</span>}
                    </button>
                  ))}
                </div>
              </>
            )}

            {(disponibles.data?.en_varias_conexiones.length ?? 0) > 0 && (
              <>
                {/* Una sola entrada por tabla en vez de cuarenta datasets: es
                    lo que en el script de Qlik era un bucle sobre las
                    sucursales. Cada parte llega con las etiquetas de su
                    conexión, así que se sabe de dónde vino cada fila. */}
                <div className="chico tenue" style={{ padding: '8px 8px 4px' }}>
                  La misma tabla en varias conexiones
                </div>
                <div className="lista">
                  {disponibles.data?.en_varias_conexiones.map((t) => {
                    const listo = t.cargados === t.conexiones
                    return (
                      <button
                        key={t.tabla}
                        title={listo
                          ? `Apila las ${t.conexiones} conexiones que traen esta tabla`
                          : `Faltan ${t.conexiones - t.cargados} por cargar; hasta ` +
                            'entonces la transformación se detiene en vez de dejar ' +
                            'sucursales fuera'}
                        onClick={() => agregarOrigen('tabla_en_conexiones', t.tabla)}
                      >
                        <span className="nom mono">{t.tabla}</span>
                        <span className={`dcha${listo ? '' : ' aviso-texto'}`}>
                          {t.cargados}/{t.conexiones}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </>
            )}

            {(disponibles.data?.transformaciones.length ?? 0) > 0 && (
              <>
                <div className="chico tenue" style={{ padding: '8px 8px 4px' }}>
                  Resultados de otras
                </div>
                <div className="lista">
                  {disponibles.data?.transformaciones
                    .filter((t) => t.nombre !== d.nombre)
                    .map((t) => (
                      <button
                        key={t.nombre}
                        disabled={!t.tiene_datos}
                        title={t.tiene_datos ? undefined : 'Todavía no se ha ejecutado'}
                        onClick={() => agregarOrigen('dataset', t.nombre)}
                      >
                        <span className="nom mono">{t.nombre}</span>
                      </button>
                    ))}
                </div>
              </>
            )}
          </>
        </Seccion>
      </PanelLateral>

      {/* ------------------------------------------------------- centro */}
      <div className="centro">
        <div className="barra-editor">
          <input
            type="text"
            className="mono"
            placeholder="nombre_del_resultado"
            value={d.nombre}
            disabled={id !== null}
            title={id !== null ? 'El nombre no se puede cambiar después de crearla' : ''}
            onChange={(e) =>
              setD({ ...d, nombre: e.target.value.replace(/[^A-Za-z0-9_]/g, '_') })
            }
            style={{ maxWidth: 230 }}
          />
          <div className="pestanas">
            <button className={!modoSql ? 'activo' : ''} onClick={() => setModoSql(false)}>
              Pasos
            </button>
            <button className={modoSql ? 'activo' : ''} onClick={() => setModoSql(true)}>
              SQL
            </button>
          </div>

          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, minWidth: 0 }}>
            <button className="btn" onClick={() => setPegarSql(true)}>
              Pegar SQL
            </button>
            <button
              className="btn"
              disabled={!d.nombre.trim() || d.origenes.length === 0 || guardar.isPending}
              onClick={() =>
                guardar.mutate(
                  { id, definicion: { ...d, sql: modoSql ? (d.sql ?? '') : null } },
                  { onSuccess: (t) => setId(t.id) },
                )
              }
            >
              {guardar.isPending ? 'Guardando…' : id === null ? 'Crear' : 'Guardar'}
            </button>
            <button
              className="btn primario"
              disabled={id === null || ejecutar.isPending}
              title={id === null ? 'Guárdala antes de ejecutarla' : undefined}
              onClick={() => ejecutar.mutate(id!)}
            >
              {ejecutar.isPending ? 'Ejecutando…' : 'Ejecutar'}
            </button>
          </div>
        </div>

        {guardar.isError && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {(guardar.error as Error).message}
          </div>
        )}
        {ejecutar.isError && (
          <div className="error-caja" style={{ margin: '10px 12px 0' }}>
            {(ejecutar.error as Error).message}
          </div>
        )}
        {ejecutar.isSuccess && (
          <div className="aviso-caja" style={{ margin: '10px 12px 0' }}>
            Listo: {ejecutar.data.filas.toLocaleString('es-MX')} filas ·{' '}
            {ejecutar.data.mb} MB · {ejecutar.data.ms} ms. Ya se puede usar como
            origen de un modelo o de otra transformación.
          </div>
        )}

        <div className="etl-cuerpo">
          {/* --- orígenes --- */}
          <div className="etl-origenes">
            {d.origenes.length === 0 ? (
              <div className="vacio chico">
                Elige un origen de la lista de la izquierda para empezar.
              </div>
            ) : (
              d.origenes.map((o, i) => (
                <span className="chip" key={o.nombre}>
                  <span className="mono">{o.nombre}</span>
                  <span className="tenue chico">
                    {o.tipo === 'tabla'
                      ? 'tabla'
                      : o.tipo === 'tabla_en_conexiones'
                        ? 'todas'
                        : 'datos'}
                  </span>
                  {i === 0 && <span className="etiqueta dim">principal</span>}
                  <button
                    onClick={() =>
                      setD({
                        ...d,
                        origenes: d.origenes.filter((x) => x.nombre !== o.nombre),
                      })
                    }
                  >
                    ✕
                  </button>
                </span>
              ))
            )}
          </div>

          {/* --- pasos o SQL --- */}
          {modoSql ? (
            <div className="campo" style={{ padding: '0 12px' }}>
              <label>
                Consulta. Los orígenes están disponibles por su alias:{' '}
                <span className="mono">
                  {d.origenes.map((o) => o.nombre).join(', ') || '(agrega uno)'}
                </span>
              </label>
              <textarea
                rows={12}
                value={d.sql ?? ''}
                placeholder={'SELECT sucursal_id, SUM(monto_base) AS venta\nFROM ventas\nGROUP BY sucursal_id'}
                onChange={(e) => setD({ ...d, sql: e.target.value })}
              />
            </div>
          ) : (
            <div className="pasos">
              {d.pasos.map((p, i) => (
                <div className={`paso ${abierto === i ? 'abierto' : ''}`} key={i}>
                  <header onClick={() => setAbierto(abierto === i ? null : i)}>
                    <span className="orden">{i + 1}</span>
                    <span className="nom">{ETIQUETA_PASO[p.tipo]}</span>
                    <span className="tenue chico">{resumen(p)}</span>
                    <span className="acciones">
                      <button className="btn chico" onClick={(e) => { e.stopPropagation(); mover(i, -1) }}>
                        ↑
                      </button>
                      <button className="btn chico" onClick={(e) => { e.stopPropagation(); mover(i, 1) }}>
                        ↓
                      </button>
                      <button
                        className="btn chico peligro"
                        onClick={(e) => {
                          e.stopPropagation()
                          setD({ ...d, pasos: d.pasos.filter((_, j) => j !== i) })
                          setAbierto(null)
                        }}
                      >
                        ✕
                      </button>
                    </span>
                  </header>
                  {abierto === i && (
                    <div className="paso-detalle">
                      <PasoEditor
                        paso={p}
                        columnas={columnasDePaso(i)}
                        origenes={d.origenes.slice(1)}
                        columnasDerecha={(columnasDerecha.data?.columnas ?? []).map(
                          (c) => c.nombre,
                        )}
                        alCambiar={(cambios) => cambiarPaso(i, cambios)}
                      />
                    </div>
                  )}
                </div>
              ))}

              <div className="agregar-paso">
                {TIPOS.map((t) => (
                  <button
                    key={t}
                    className="btn chico"
                    disabled={d.origenes.length === 0}
                    onClick={() => {
                      setD({ ...d, pasos: [...d.pasos, nuevoPaso(t, columnasFinales)] })
                      setAbierto(d.pasos.length)
                    }}
                  >
                    + {ETIQUETA_PASO[t]}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ------------------------------------------------------ derecha */}
      <aside className="der">
        <div className="barra-editor">
          <div className="pestanas">
            <button className="activo">Vista previa</button>
          </div>
          {previa.isPending && <span className="chico tenue">calculando…</span>}
        </div>

        <div className="inspector">
          {previa.isError && (
            <div className="error-caja chico">{(previa.error as Error).message}</div>
          )}

          {previa.data && (
            <>
              {previa.data.conteos.length > 0 && (
                <div>
                  <div className="chico suave" style={{ marginBottom: 4 }}>
                    Filas por paso
                  </div>
                  <table className="campos">
                    <tbody>
                      {previa.data.conteos.map((c, i) => {
                        const anterior = previa.data!.conteos[i - 1]?.filas
                        const cambio =
                          anterior !== undefined && anterior !== c.filas
                            ? c.filas - anterior
                            : null
                        return (
                          <tr key={i}>
                            <td>{c.paso}</td>
                            <td className="num">{c.filas.toLocaleString('es-MX')}</td>
                            <td
                              className="num chico"
                              style={{
                                color: cambio && cambio < 0 ? 'var(--aviso)' : 'var(--texto-tenue)',
                              }}
                            >
                              {cambio === null
                                ? ''
                                : `${cambio > 0 ? '+' : ''}${cambio.toLocaleString('es-MX')}`}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              <div>
                <div className="chico suave" style={{ marginBottom: 4 }}>
                  Resultado ({previa.data.columnas.length} columnas · {previa.data.ms} ms)
                </div>
                <div className="tabla-envoltura" style={{ maxHeight: 320 }}>
                  <table className="datos">
                    <thead>
                      <tr>
                        {previa.data.columnas.map((c) => (
                          <th key={c}>{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previa.data.filas.slice(0, 50).map((f, i) => (
                        <tr key={i}>
                          {previa.data!.columnas.map((c) => {
                            const bruto = f[c] ?? null
                            const n = comoNumero(bruto)
                            return (
                              <td key={c} className={n === null ? '' : 'num'}
                                  title={bruto ?? undefined}>
                                {n === null
                                  ? (bruto ?? "—")
                                  : n.toLocaleString('es-MX', {
                                      maximumFractionDigits: 2,
                                    })}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <details>
                <summary className="chico suave">SQL generado</summary>
                <pre className="mono" style={{ overflow: 'auto', maxHeight: 300 }}>
                  {previa.data.sql}
                </pre>
              </details>
            </>
          )}

          {!previa.data && !previa.isError && (
            <div className="vacio chico">
              Ponle nombre y elige un origen: la vista previa se calcula sola.
            </div>
          )}
        </div>
      </aside>

      {/* ------------------------------------------------------- modal */}
      {pegarSql && (
        <Velo alCerrar={() => setPegarSql(false)}>
          <div className="modal">
            <header>Pegar una consulta</header>
            <div className="cont">
              <p className="chico suave" style={{ margin: 0 }}>
                Si la consulta se puede representar con pasos, se convierte y la
                puedes seguir editando visualmente. Si no, se queda en modo SQL y se
                dice exactamente qué no se pudo convertir.
              </p>
              <textarea
                rows={10}
                value={sqlPegado}
                placeholder="SELECT ... FROM ... WHERE ... GROUP BY ..."
                onChange={(e) => setSqlPegado(e.target.value)}
              />
              {desdeSql.isError && (
                <div className="error-caja">{(desdeSql.error as Error).message}</div>
              )}
              {desdeSql.data && !desdeSql.data.convertible && (
                <div className="aviso-caja">
                  <b>No se puede convertir del todo:</b>
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                    {desdeSql.data.no_representable.map((m) => (
                      <li key={m}>{m}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <footer>
              <button className="btn" onClick={() => setPegarSql(false)}>
                Cancelar
              </button>
              <button
                className="btn"
                disabled={!sqlPegado.trim()}
                onClick={() => {
                  // Modo SQL directo: los orígenes se deducen de las tablas que
                  // la consulta menciona, para que el alias funcione tal cual.
                  desdeSql.mutate(sqlPegado, {
                    onSuccess: (c) => {
                      setD({
                        ...d,
                        origenes: c.origenes.length ? c.origenes : d.origenes,
                        pasos: [],
                        sql: sqlPegado,
                      })
                      setModoSql(true)
                      setPegarSql(false)
                    },
                  })
                }}
              >
                Usar como SQL
              </button>
              <button
                className="btn primario"
                disabled={!sqlPegado.trim() || desdeSql.isPending}
                onClick={() =>
                  desdeSql.mutate(sqlPegado, {
                    onSuccess: (c) => {
                      if (!c.convertible) return
                      setD({ ...d, origenes: c.origenes, pasos: c.pasos, sql: null })
                      setModoSql(false)
                      setPegarSql(false)
                    },
                  })
                }
              >
                {desdeSql.isPending ? 'Analizando…' : 'Convertir a pasos'}
              </button>
            </footer>
          </div>
        </Velo>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- //

function nuevoPaso(tipo: TipoPaso, columnas: string[]): Paso {
  const primera = columnas[0] ?? ''
  switch (tipo) {
    case 'filtrar':
      return { tipo, condiciones: [{ campo: primera, op: '=', valor: '' }], modo: 'y' }
    case 'columnas':
      return { tipo, mantener: [] }
    case 'renombrar':
      return { tipo, cambios: primera ? { [primera]: primera } : {} }
    case 'derivar':
      return { tipo, nombre: 'nueva_columna', expresion: '' }
    case 'agrupar':
      return { tipo, por: [], agregados: [{ nombre: 'total', funcion: 'cuenta', campo: null }] }
    case 'unir':
      return { tipo, con: '', como: 'izquierda', en: [], traer: [] }
    case 'apilar':
      return { tipo, con: [] }
    case 'ordenar':
      return { tipo, por: primera ? [primera] : [], descendente: false }
    case 'limitar':
      return { tipo, n: 1000 }
    default:
      return { tipo }
  }
}

function resumen(p: Paso): string {
  switch (p.tipo) {
    case 'filtrar':
      return `${p.condiciones?.length ?? 0} condición(es)`
    case 'columnas':
      return p.mantener?.length ? `${p.mantener.length} columnas` : 'todas'
    case 'renombrar':
      return `${Object.keys(p.cambios ?? {}).length} renombre(s)`
    case 'derivar':
      return p.nombre ?? ''
    case 'agrupar':
      return `por ${(p.por ?? []).join(', ') || '(total)'}`
    case 'unir':
      return typeof p.con === 'string' && p.con ? `con ${p.con}` : 'sin origen'
    case 'apilar':
      return `${(Array.isArray(p.con) ? p.con : []).length} origen(es)`
    case 'ordenar':
      return (p.por ?? []).join(', ')
    case 'limitar':
      return String(p.n ?? '')
    default:
      return ''
  }
}

/**
 * Un número, o null si el valor no lo es.
 *
 * Los valores llegan como texto desde el servidor a propósito (una previa no debe
 * reinterpretar tipos). Aquí se formatean solo para leerlos: sumar decimales en
 * coma flotante deja restos como `743866138.1200001`, y mostrar ese ruido como si
 * fuera dato preocupa a quien lo lee. El valor tal cual está en el tooltip.
 */
function comoNumero(v: string | null): number | null {
  if (v === null || v === '' ) return null
  if (!/^-?\d+(\.\d+)?$/.test(v)) return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
