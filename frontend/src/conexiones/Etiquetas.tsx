/**
 * Las etiquetas de todas las conexiones, en una tabla.
 *
 * Una etiqueta es una constante de la sucursal —`id_sucursal = 3`— que sale como
 * columna al leer cualquiera de sus datasets. Es el equivalente de la variable
 * por sucursal de un script de Qlik: lo que permite saber de dónde vino cada
 * fila una vez que cuarenta tablas iguales están apiladas.
 *
 * La pantalla es una tabla y no un formulario por conexión a propósito: son
 * cuarenta agencias, y abrir cuarenta diálogos para escribir cuarenta números es
 * exactamente el trabajo que esto quiere quitar. Puestas en columna, además, se
 * ve de un golpe cuál falta y si hay dos con el mismo número — que es el error
 * que de verdad ocurre.
 *
 * Se guarda todo junto. Lo que se borre de una celda desaparece: no hay un
 * estado intermedio que haya que recordar.
 */

import { useMemo, useState } from 'react'

import { useConexiones, useGuardarEtiquetas } from '../api/conexiones'
import { Velo } from '../comunes/Velo'

/** Un valor de celda: se guarda como número si lo parece, y si no como texto. */
function comoValor(texto: string): string | number | null {
  const t = texto.trim()
  if (!t) return null
  // Solo dígitos: es un id, y un id que viaja como texto no cruza contra una
  // columna numérica del modelo.
  if (/^-?\d+$/.test(t)) return Number(t)
  return t
}

function comoTexto(v: unknown): string {
  return v === null || v === undefined ? '' : String(v)
}

const CLAVE_OK = /^[A-Za-z_][A-Za-z0-9_]{0,39}$/

export function Etiquetas({ alCerrar }: { alCerrar: () => void }) {
  const conexiones = useConexiones()
  const guardar = useGuardarEtiquetas()

  const cons = useMemo(() => conexiones.data ?? [], [conexiones.data])

  /** clave -> conexion_id -> texto de la celda. */
  const [valores, setValores] = useState<Record<string, Record<number, string>>>(
    {},
  )
  const [claves, setClaves] = useState<string[] | null>(null)
  const [nueva, setNueva] = useState('')
  const [guardado, setGuardado] = useState<number | null>(null)

  // Las columnas salen de lo que ya hay guardado, la primera vez.
  const columnas = useMemo(() => {
    if (claves !== null) return claves
    const vistas = new Set<string>()
    for (const c of cons) for (const k of Object.keys(c.etiquetas ?? {})) vistas.add(k)
    return [...vistas].sort()
  }, [claves, cons])

  function celda(clave: string, id: number): string {
    const puesto = valores[clave]?.[id]
    if (puesto !== undefined) return puesto
    const c = cons.find((x) => x.id === id)
    return comoTexto(c?.etiquetas?.[clave])
  }

  function escribir(clave: string, id: number, texto: string) {
    setGuardado(null)
    setValores((previo) => ({
      ...previo,
      [clave]: { ...(previo[clave] ?? {}), [id]: texto },
    }))
  }

  function agregarColumna() {
    const k = nueva.trim()
    if (!CLAVE_OK.test(k) || columnas.includes(k)) return
    setClaves([...columnas, k])
    setNueva('')
  }

  function quitarColumna(clave: string) {
    setClaves(columnas.filter((c) => c !== clave))
    // Vaciarla es lo que la borra al guardar.
    setValores((previo) => ({
      ...previo,
      [clave]: Object.fromEntries(cons.map((c) => [c.id, ''])),
    }))
  }

  /**
   * Rellena hacia abajo desde la primera con valor. Con cuarenta sucursales y
   * una etiqueta que casi siempre es la misma —el país, la marca— escribirla
   * cuarenta veces es lo que hace que nadie la ponga.
   */
  function rellenar(clave: string) {
    const primera = cons.map((c) => celda(clave, c.id)).find((v) => v.trim())
    if (!primera) return
    setValores((previo) => ({
      ...previo,
      [clave]: Object.fromEntries(
        cons.map((c) => [c.id, celda(clave, c.id).trim() || primera]),
      ),
    }))
  }

  const cambios = useMemo(() => {
    return cons
      .map((c) => {
        const etiquetas: Record<string, string | number | null> = {}
        for (const k of columnas) {
          const v = comoValor(celda(k, c.id))
          if (v !== null) etiquetas[k] = v
        }
        return { conexion_id: c.id, etiquetas }
      })
      .filter((x) => {
        const antes = cons.find((c) => c.id === x.conexion_id)?.etiquetas ?? {}
        return JSON.stringify(antes) !== JSON.stringify(x.etiquetas)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cons, columnas, valores])

  /** Dos sucursales con el mismo valor casi siempre es un dedazo. */
  const repetidos = useMemo(() => {
    const salida: Record<string, Set<string>> = {}
    for (const k of columnas) {
      const cuenta = new Map<string, number>()
      for (const c of cons) {
        const v = celda(k, c.id).trim()
        if (v) cuenta.set(v, (cuenta.get(v) ?? 0) + 1)
      }
      salida[k] = new Set([...cuenta].filter(([, n]) => n > 1).map(([v]) => v))
    }
    return salida
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cons, columnas, valores])

  return (
    <Velo alCerrar={alCerrar}>
      <div className="modal ancho">
        <header>Etiquetas de las conexiones</header>
        <div className="cont">
          <p className="chico suave" style={{ margin: 0 }}>
            Una constante por conexión que sale como <b>columna</b> al leer sus
            datasets. Es de dónde viene cada fila cuando la misma tabla llega de
            varias sucursales. No se escribe en los archivos: cambiar un número
            aquí no obliga a volver a extraer nada.
          </p>

          <div className="acciones">
            <input
              type="text"
              placeholder="nombre_de_la_etiqueta"
              className="mono"
              value={nueva}
              onChange={(e) => setNueva(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && agregarColumna()}
              style={{ maxWidth: 240 }}
            />
            <button className="btn chico" disabled={!CLAVE_OK.test(nueva.trim())}
                    onClick={agregarColumna}>
              + Agregar etiqueta
            </button>
            {nueva.trim() && !CLAVE_OK.test(nueva.trim()) && (
              <span className="chico critico-texto">
                Letras, dígitos y guion bajo, empezando por letra.
              </span>
            )}
          </div>

          {columnas.length === 0 ? (
            <div className="vacio">
              Todavía no hay ninguna. La más útil suele ser <code>id_sucursal</code>.
            </div>
          ) : (
            <div className="tabla-envoltura" style={{ maxHeight: '52vh' }}>
              <table className="datos">
                <thead>
                  <tr>
                    <th>Conexión</th>
                    {columnas.map((k) => (
                      <th key={k}>
                        <div className="acciones">
                          <span className="mono">{k}</span>
                          <button className="btn chico" title="Copiar el primer valor a las vacías"
                                  onClick={() => rellenar(k)}>↓</button>
                          <button className="btn chico peligro" title="Quitar la etiqueta de todas"
                                  onClick={() => quitarColumna(k)}>✕</button>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cons.map((c) => (
                    <tr key={c.id}>
                      <td>
                        {c.nombre} <span className="etiqueta dim">{c.tipo}</span>
                      </td>
                      {columnas.map((k) => {
                        const v = celda(k, c.id).trim()
                        return (
                          <td key={k}>
                            <input
                              type="text"
                              className="mono"
                              value={celda(k, c.id)}
                              onChange={(e) => escribir(k, c.id, e.target.value)}
                              style={{
                                borderColor: repetidos[k]?.has(v)
                                  ? 'var(--aviso)'
                                  : undefined,
                              }}
                              title={repetidos[k]?.has(v)
                                ? 'Otra conexión tiene este mismo valor'
                                : undefined}
                            />
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {guardar.isError && (
            <div className="error-caja chico">{(guardar.error as Error).message}</div>
          )}
          {guardado !== null && (
            <div className="aviso-caja ok-caja chico">
              {guardado === 0
                ? 'No había nada que cambiar.'
                : `${guardado} conexión(es) actualizadas. Las transformaciones que
                   las usen lo verán en su próxima corrida.`}
            </div>
          )}
        </div>
        <footer>
          <span className="pista chico suave">
            {cambios.length === 0
              ? 'Sin cambios sin guardar.'
              : `${cambios.length} conexión(es) con cambios.`}
          </span>
          <button className="btn" onClick={alCerrar}>Cerrar</button>
          <button
            className="btn primario"
            disabled={cambios.length === 0 || guardar.isPending}
            onClick={() =>
              guardar.mutate(cambios, {
                onSuccess: (r) => {
                  setValores({})
                  setGuardado(r.cambiadas)
                },
              })
            }
          >
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </footer>
      </div>
    </Velo>
  )
}
