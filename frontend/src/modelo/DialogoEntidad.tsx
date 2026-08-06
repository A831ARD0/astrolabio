/**
 * Agregar una entidad a partir de una tabla real.
 *
 * Las columnas y sus tipos vienen del motor analítico, no se teclean. Ese es el
 * punto: un modelo que apunta a una columna inexistente no falla al guardarse,
 * falla en la primera consulta, lejos de aquí. Si la tabla manda, eso no pasa.
 *
 * El rol de cada columna llega sugerido y editable. Acertar `sucursal_id` es
 * fácil; si `monto_objetivo` es medida o dimensión lo sabe la persona, no una
 * heurística.
 */

import { useState } from 'react'

import { useTabla, useTablas } from '../api/hooks'
import type { Entidad, RolCampo, TipoEntidad } from '../api/tipos'
import { ETIQUETA_ROL } from './estado'

const ROLES: RolCampo[] = ['clave', 'clave_externa', 'dimension', 'medida_base']

export function DialogoEntidad({
  yaUsadas,
  alAceptar,
  alCerrar,
}: {
  yaUsadas: Set<string>
  alAceptar: (e: Entidad) => void
  alCerrar: () => void
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
    // Un nombre que empieza por fact_ o tbl_hechos suele ser un hecho. Es solo
    // el valor inicial del selector.
    setTipo(/^(fact|hechos?)_/.test(t) ? 'hecho' : 'dimension')
  }

  const columnas = detalle.data?.columnas ?? []
  const clave = detalle.data?.clave_primaria ?? null
  const rolDe = (c: string, sugerido: RolCampo) => roles[c] ?? sugerido

  function aceptar() {
    if (!detalle.data) return
    const entidad: Entidad = {
      nombre: nombre.trim(),
      tipo,
      origen: { tabla: detalle.data.nombre },
      clave_primaria: clave,
      campos: columnas.map((c) => ({
        nombre: c.nombre,
        tipo: c.tipo,
        rol: rolDe(c.nombre, c.rol_sugerido),
      })),
      ...(tipo === 'hecho' ? { grano: clave ? [clave] : [] } : {}),
    }
    alAceptar(entidad)
  }

  const nombreLibre = nombre.trim() && !yaUsadas.has(nombre.trim())

  return (
    <div className="velo" onClick={alCerrar}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>Agregar entidad desde una tabla</header>

        <div className="cont">
          {tablas.isLoading && <div className="vacio">Leyendo el catálogo…</div>}
          {tablas.isError && (
            <div className="error-caja">{(tablas.error as Error).message}</div>
          )}

          <div className="campo">
            <label>Tabla del motor analítico</label>
            <select value={tabla ?? ''} onChange={(e) => elegir(e.target.value)}>
              <option value="">(elige una)</option>
              {tablas.data?.tablas.map((t) => (
                <option key={t.nombre} value={t.nombre}>
                  {t.nombre} — {t.filas.toLocaleString('es-MX')} filas
                </option>
              ))}
            </select>
          </div>

          {detalle.isLoading && <div className="vacio">Leyendo columnas…</div>}

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
        </div>

        <footer>
          <button className="btn" onClick={alCerrar}>
            Cancelar
          </button>
          <button
            className="btn primario"
            disabled={!detalle.data || !nombreLibre}
            onClick={aceptar}
          >
            Agregar
          </button>
        </footer>
      </div>
    </div>
  )
}
