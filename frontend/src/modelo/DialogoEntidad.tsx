/**
 * Agregar una entidad a partir de una tabla real.
 *
 * Las columnas y sus tipos vienen del catálogo, no se teclean. Ese es el punto: un
 * modelo que apunta a una columna inexistente no falla al guardarse, falla en la
 * primera consulta, lejos de aquí. Si la tabla manda, eso no pasa.
 *
 * El rol de cada columna llega sugerido y editable. Acertar `sucursal_id` es
 * fácil; si `monto_objetivo` es medida o dimensión lo sabe la persona, no una
 * heurística.
 *
 * `CuerpoEntidad` está separado del diálogo porque se usa dos veces: para agregar
 * una entidad a un modelo que ya existe, y para elegir la primera del modelo que se
 * está creando. Son el mismo trabajo y tienen que verse igual.
 */

import { useEffect, useMemo, useState } from 'react'

import { useTabla, useTablas } from '../api/hooks'
import type { Entidad, OrigenTabla, RolCampo, TipoEntidad } from '../api/tipos'
import { ETIQUETA_ROL } from './estado'
import { Velo } from '../comunes/Velo'

const ROLES: RolCampo[] = ['clave', 'clave_externa', 'dimension', 'medida_base']

/**
 * El orden es el del panel de orígenes del ETL: es la misma pregunta en dos
 * pantallas, y quien ya sabe dónde mirar en una no tiene por qué reaprenderlo.
 */
const GRUPOS: { origen: OrigenTabla; titulo: string }[] = [
  { origen: 'motor', titulo: 'Tablas del motor' },
  { origen: 'carga', titulo: 'Datos cargados' },
  { origen: 'resultado', titulo: 'Resultados de transformaciones' },
]

export function CuerpoEntidad({
  yaUsadas,
  alCambiar,
}: {
  yaUsadas: Set<string>
  /** La entidad armada, o null mientras falte algo. */
  alCambiar: (e: Entidad | null) => void
}) {
  const tablas = useTablas()
  const [tabla, setTabla] = useState<string | null>(null)
  const [tipo, setTipo] = useState<TipoEntidad>('dimension')
  const [nombre, setNombre] = useState('')
  const [roles, setRoles] = useState<Record<string, RolCampo>>({})
  const detalle = useTabla(tabla)

  function elegir(t: string) {
    setTabla(t)
    setNombre(t)
    setRoles({})
    // Un nombre que empieza por fact_ o hechos_ suele ser un hecho. Es solo el
    // valor inicial del selector.
    setTipo(/^(fact|hechos?)_/i.test(t) ? 'hecho' : 'dimension')
  }

  const columnas = detalle.data?.columnas ?? []
  const clave = detalle.data?.clave_primaria ?? null
  const rolDe = (c: string, sugerido: RolCampo) => roles[c] ?? sugerido
  const nombreLibre = !!nombre.trim() && !yaUsadas.has(nombre.trim())

  // Se arma al renderizar y se avisa en un efecto: así lo que se construye depende
  // solo de lo que se ve, y avisar al padre no ocurre a media pintada.
  const armada = useMemo<Entidad | null>(() => {
    const datos = detalle.data
    if (!datos || !nombreLibre) return null
    const suClave = datos.clave_primaria
    return {
      nombre: nombre.trim(),
      tipo,
      origen: { tabla: datos.nombre },
      clave_primaria: suClave,
      campos: datos.columnas.map((c) => ({
        nombre: c.nombre,
        tipo: c.tipo,
        rol: roles[c.nombre] ?? c.rol_sugerido,
      })),
      ...(tipo === 'hecho' ? { grano: suClave ? [suClave] : [] } : {}),
    }
  }, [detalle.data, nombre, nombreLibre, tipo, roles])

  useEffect(() => alCambiar(armada), [alCambiar, armada])

  return (
    <>
      {tablas.isLoading && <div className="vacio">Leyendo el catálogo…</div>}
      {tablas.isError && (
        <div className="error-caja">{(tablas.error as Error).message}</div>
      )}

      <div className="campo">
        <label>Tabla</label>
        <select value={tabla ?? ''} onChange={(e) => elegir(e.target.value)}>
          <option value="">(elige una)</option>
          {GRUPOS.map(({ origen, titulo }) => {
            const suyas = (tablas.data?.tablas ?? []).filter(
              (t) => t.origen === origen,
            )
            if (suyas.length === 0) return null
            return (
              <optgroup key={origen} label={titulo}>
                {suyas.map((t) => (
                  <option key={t.nombre} value={t.nombre}>
                    {t.nombre} — {t.filas.toLocaleString('es-MX')} filas
                  </option>
                ))}
              </optgroup>
            )
          })}
        </select>
        <span className="chico tenue">
          Lo que cargaste y lo que produjeron tus transformaciones sale aquí igual
          que las tablas del motor.
        </span>
      </div>

      {detalle.isLoading && <div className="vacio">Leyendo columnas…</div>}
      {detalle.isError && (
        <div className="error-caja">{(detalle.error as Error).message}</div>
      )}

      {detalle.data && (
        <>
          <div className="fila">
            <div className="campo">
              <label>Nombre en el modelo</label>
              <input
                type="text"
                className="mono"
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
              />
            </div>
            <div className="campo">
              <label>Tipo</label>
              <select
                value={tipo}
                onChange={(e) => setTipo(e.target.value as TipoEntidad)}
              >
                <option value="dimension">dimensión — sirve para agrupar</option>
                <option value="hecho">hecho — de aquí nacen las métricas</option>
              </select>
            </div>
          </div>

          {!nombreLibre && nombre.trim() && (
            <div className="error-caja">Ya hay una entidad con ese nombre.</div>
          )}

          <div className="chico suave">
            {columnas.length} columnas · clave primaria detectada:{' '}
            <span className="mono">{clave ?? 'ninguna'}</span>
            {clave === null && detalle.data.origen !== 'motor' && (
              <>
                {' '}
                — un Parquet no la declara: marca cuál es en la lista de abajo.
              </>
            )}
          </div>

          <div className="tabla-envoltura" style={{ maxHeight: 280 }}>
            <table className="campos" style={{ margin: 0 }}>
              <thead>
                <tr>
                  <th>columna</th>
                  <th>tipo</th>
                  <th>rol</th>
                </tr>
              </thead>
              <tbody>
                {columnas.map((c) => (
                  <tr key={c.nombre}>
                    <td>{c.nombre}</td>
                    <td className="tenue chico" title={c.tipo_origen}>
                      {c.tipo}
                    </td>
                    <td>
                      <select
                        value={rolDe(c.nombre, c.rol_sugerido)}
                        onChange={(e) =>
                          setRoles({
                            ...roles,
                            [c.nombre]: e.target.value as RolCampo,
                          })
                        }
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {ETIQUETA_ROL[r]}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  )
}

export function DialogoEntidad({
  yaUsadas,
  alAceptar,
  alCerrar,
}: {
  yaUsadas: Set<string>
  alAceptar: (e: Entidad) => void
  alCerrar: () => void
}) {
  const [entidad, setEntidad] = useState<Entidad | null>(null)

  return (
    <Velo alCerrar={alCerrar}>
      <div className="modal">
        <header>Agregar entidad desde una tabla</header>

        <div className="cont">
          <CuerpoEntidad yaUsadas={yaUsadas} alCambiar={setEntidad} />
        </div>

        <footer>
          <button className="btn" onClick={alCerrar}>
            Cancelar
          </button>
          <button
            className="btn primario"
            disabled={!entidad}
            onClick={() => entidad && alAceptar(entidad)}
          >
            Agregar
          </button>
        </footer>
      </div>
    </Velo>
  )
}
