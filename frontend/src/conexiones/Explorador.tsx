/**
 * Explorar un origen y traerse una tabla.
 *
 * La decisión de diseño: las columnas y una muestra de filas están **a la vista**
 * mientras eliges la columna incremental y la de partición. Esas dos elecciones son
 * las que deciden si la siguiente carga tarda 4 segundos o 4 minutos, y elegirlas de
 * memoria es cómo se acaba particionando por una columna que viene casi toda nula.
 *
 * Las columnas se pueden descartar, y **por defecto se traen todas**. Eso no es
 * pereza: se guarda `null`, no la lista completa. Un dataset creado hoy con las 45
 * columnas de hoy tiene que seguir trayendo la 46 cuando el origen la agregue; si se
 * congelara la lista, la columna nueva no llegaría nunca y nadie sabría por qué.
 *
 * La muestra se vuelve a pedir con las columnas elegidas, no se recorta en el
 * navegador: la vista previa es de lo que se va a traer.
 */

import { useEffect, useMemo, useState } from 'react'

import {
  type ColumnaOrigen,
  useCrearDataset,
  useDescribirTabla,
  useEsquemas,
  useMuestra,
  useTablasOrigen,
} from '../api/conexiones'
import { Velo } from '../comunes/Velo'

/** Tipos que sirven como marca incremental o como partición. */
function esFecha(c: ColumnaOrigen): boolean {
  return /date|time|timestamp|año|anio/i.test(c.tipo) || /fecha|date/i.test(c.nombre)
}
function esOrdenable(c: ColumnaOrigen): boolean {
  return esFecha(c) || /int|serial|num|dec|float|double/i.test(c.tipo)
}

/** Un nombre de dataset válido a partir del de la tabla: sin puntos ni espacios. */
function nombreSugerido(tabla: string): string {
  return tabla
    .replace(/\.[^.]+$/, '')
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

export function Explorador({
  conexionId,
  alCerrar,
}: {
  conexionId: number
  alCerrar: () => void
}) {
  const esquemas = useEsquemas(conexionId)
  const [esquema, setEsquema] = useState<string | null>(null)
  const [tabla, setTabla] = useState<string | null>(null)
  const [busqueda, setBusqueda] = useState('')

  const tablas = useTablasOrigen(conexionId, esquema)
  const detalle = useDescribirTabla(conexionId, esquema, tabla)
  const crear = useCrearDataset(conexionId)

  const [nombre, setNombre] = useState('')
  const [incremental, setIncremental] = useState('')
  const [particion, setParticion] = useState('')
  /** null = todas. Es lo que se guarda, no la lista completa. */
  const [elegidas, setElegidas] = useState<string[] | null>(null)

  const muestra = useMuestra(conexionId, esquema, tabla, elegidas)

  // Al cambiar de tabla se propone un nombre y se limpian las elecciones: dejar la
  // columna incremental de la tabla anterior sería un error silencioso.
  useEffect(() => {
    setNombre(tabla ? nombreSugerido(tabla) : '')
    setIncremental('')
    setParticion('')
    setElegidas(null)
    crear.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabla, esquema])

  const filtradas = useMemo(() => {
    const q = busqueda.trim().toLowerCase()
    const lista = tablas.data?.tablas ?? []
    return q ? lista.filter((t) => t.nombre.toLowerCase().includes(q)) : lista
  }, [tablas.data, busqueda])

  const columnas = detalle.data?.columnas ?? []
  const candidatasIncremental = columnas.filter(esOrdenable)
  const candidatasParticion = columnas.filter(esFecha)

  const seTrae = (c: string) => elegidas === null || elegidas.includes(c)
  const cuantas = elegidas === null ? columnas.length : elegidas.length

  const alternar = (c: string) => {
    // Desde "todas" hay que materializar la lista para poder quitar una.
    const base = elegidas ?? columnas.map((x) => x.nombre)
    const sin = base.filter((x) => x !== c)
    if (sin.length === base.length) {
      setElegidas([...base, c])
      return
    }
    if (sin.length === 0) return          // dejarlo todo fuera no trae nada
    setElegidas(sin)
  }

  /**
   * Elegir una columna como incremental o de partición la vuelve a incluir.
   *
   * Es más honesto que rechazarlo después: pedir "parte por fecha" y traer la tabla
   * sin la columna fecha no es lo que nadie quiso decir. El backend lo valida
   * igual, porque un cliente se puede saltar.
   */
  const asegurar = (c: string) => {
    if (c && elegidas !== null && !elegidas.includes(c)) setElegidas([...elegidas, c])
  }

  return (
    <Velo alCerrar={alCerrar}>
      <div className="modal ancho">
        <header>Traer una tabla</header>
        <div className="cont explorador">
          <div className="lado">
            {(esquemas.data?.esquemas.length ?? 0) > 1 && (
              <div className="campo">
                <label>Esquema</label>
                <select
                  value={esquema ?? ''}
                  onChange={(e) => {
                    setEsquema(e.target.value || null)
                    setTabla(null)
                  }}
                >
                  <option value="">(el de la conexión)</option>
                  {esquemas.data?.esquemas.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <input
              type="text"
              className="buscar"
              placeholder={`Buscar entre ${tablas.data?.tablas.length ?? 0} tabla(s)…`}
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
            />

            {tablas.isLoading && <div className="vacio chico">Leyendo el origen…</div>}
            {tablas.isError && (
              <div className="error-caja chico">{(tablas.error as Error).message}</div>
            )}

            <div className="lista lista-tablas">
              {filtradas.map((t) => (
                <button
                  key={`${t.esquema ?? ''}.${t.nombre}`}
                  className={tabla === t.nombre ? 'sel' : ''}
                  onClick={() => setTabla(t.nombre)}
                >
                  <span className="nom" title={t.nombre}>
                    {t.nombre}
                  </span>
                  <span className="dcha">
                    {t.es_vista && 'vista '}
                    {t.filas_estimadas != null
                      ? t.filas_estimadas.toLocaleString('es-MX')
                      : ''}
                  </span>
                </button>
              ))}
              {!tablas.isLoading && filtradas.length === 0 && (
                <div className="vacio chico">Nada con ese nombre.</div>
              )}
            </div>
          </div>

          <div className="lado principal">
            {!tabla && (
              <div className="vacio">
                Elige una tabla para ver sus columnas y una muestra de filas.
              </div>
            )}

            {tabla && detalle.isError && (
              <div className="error-caja">{(detalle.error as Error).message}</div>
            )}

            {tabla && detalle.data && (
              <>
                <div className="chico suave">
                  <strong className="mono">{detalle.data.nombre}</strong> ·{' '}
                  {columnas.length} columnas ·{' '}
                  {detalle.data.filas != null
                    ? `${detalle.data.filas.toLocaleString('es-MX')} filas aprox.`
                    : 'filas desconocidas'}
                  {detalle.data.es_vista && ' · es una vista'}
                </div>

                <div className="entre">
                  <span className="chico suave">
                    Se traen <strong>{cuantas}</strong> de {columnas.length} columnas
                    {elegidas === null && <span className="tenue"> (todas)</span>}
                  </span>
                  <span className="chico">
                    <button className="btn chico" onClick={() => setElegidas(null)}
                            disabled={elegidas === null}>
                      Todas
                    </button>{' '}
                    <button
                      className="btn chico"
                      onClick={() =>
                        setElegidas(
                          columnas
                            .filter((c) => c.es_clave || c.nombre === incremental ||
                                           c.nombre === particion)
                            .map((c) => c.nombre),
                        )
                      }
                      disabled={!columnas.some((c) => c.es_clave)}
                      title="Deja solo la clave y las columnas que usa la carga"
                    >
                      Solo lo mínimo
                    </button>
                  </span>
                </div>

                <div className="tabla-envoltura" style={{ maxHeight: 150 }}>
                  <table className="datos">
                    <thead>
                      <tr>
                        <th style={{ width: 34 }} title="Traer esta columna">
                          Traer
                        </th>
                        <th>Columna</th>
                        <th>Tipo</th>
                        <th>Nulos</th>
                      </tr>
                    </thead>
                    <tbody>
                      {columnas.map((c) => (
                        <tr key={c.nombre} className={seTrae(c.nombre) ? '' : 'fuera'}>
                          <td>
                            <input
                              type="checkbox"
                              checked={seTrae(c.nombre)}
                              onChange={() => alternar(c.nombre)}
                              aria-label={`Traer ${c.nombre}`}
                            />
                          </td>
                          <td className="mono">
                            {c.nombre}
                            {c.es_clave && <span className="etiqueta dim"> clave</span>}
                          </td>
                          <td className="chico suave">{c.tipo}</td>
                          <td className="chico tenue">{c.nulable ? 'sí' : 'no'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {muestra.data && (
                  <div className="tabla-envoltura" style={{ maxHeight: 170 }}>
                    <table className="datos">
                      <thead>
                        <tr>
                          {muestra.data.columnas.map((c) => (
                            <th key={c}>{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {muestra.data.filas.map((f, i) => (
                          <tr key={i}>
                            {muestra.data!.columnas.map((c) => (
                              <td key={c}>
                                {f[c] ?? <span className="tenue">nulo</span>}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <div className="fila-campos">
                  <div className="campo">
                    <label>Nombre en Astrolabio</label>
                    <input
                      type="text"
                      value={nombre}
                      onChange={(e) => setNombre(e.target.value)}
                    />
                  </div>
                  <div className="campo">
                    <label>Columna incremental</label>
                    <select
                      value={incremental}
                      onChange={(e) => {
                        setIncremental(e.target.value)
                        asegurar(e.target.value)
                      }}
                    >
                      <option value="">(traer todo cada vez)</option>
                      {candidatasIncremental.map((c) => (
                        <option key={c.nombre} value={c.nombre}>
                          {c.nombre} — {c.tipo}
                        </option>
                      ))}
                    </select>
                    <span className="chico tenue">
                      Con ella, la siguiente carga trae solo lo posterior a lo que ya
                      hay.
                    </span>
                  </div>
                  <div className="campo">
                    <label>Partir por</label>
                    <select
                      value={particion}
                      onChange={(e) => {
                        setParticion(e.target.value)
                        asegurar(e.target.value)
                      }}
                    >
                      <option value="">(sin partir)</option>
                      {candidatasParticion.map((c) => (
                        <option key={c.nombre} value={c.nombre}>
                          {c.nombre} — {c.tipo}
                        </option>
                      ))}
                    </select>
                    <span className="chico tenue">
                      Una fecha. Es lo que permite recargar un mes suelto sin volver a
                      traer la historia.
                    </span>
                  </div>
                </div>

                {crear.isError && (
                  <div className="error-caja">{(crear.error as Error).message}</div>
                )}
                {crear.isSuccess && (
                  <div className="aviso-caja ok-caja">
                    ✓ Listo: <span className="mono">{crear.data.nombre}</span>. Todavía
                    no tiene datos — cárgalo desde la lista de datasets.
                  </div>
                )}
              </>
            )}
          </div>
        </div>
        <footer>
          <button className="btn" onClick={alCerrar}>
            Cerrar
          </button>
          <button
            className="btn primario"
            disabled={!tabla || !nombre.trim() || crear.isPending}
            onClick={() =>
              crear.mutate({
                nombre: nombre.trim(),
                esquema: esquema ?? detalle.data?.esquema ?? null,
                tabla: tabla!,
                columna_incremental: incremental || null,
                particionar_por: particion || null,
                // null y no la lista completa: así el dataset sigue trayendo las
                // columnas que el origen agregue mañana.
                columnas: elegidas,
              })
            }
          >
            {crear.isPending ? 'Creando…' : 'Crear dataset'}
          </button>
        </footer>
      </div>
    </Velo>
  )
}
