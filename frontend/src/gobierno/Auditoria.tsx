/**
 * Visor de auditoría.
 *
 * Solo se lee. No hay botón de borrar y no es un olvido: un registro que se puede
 * limpiar no sirve para lo único que hace, que es contestar «quién vio esto y
 * cuándo» cuando alguien lo pregunta en serio.
 *
 * Se pagina en el servidor: esta tabla crece con cada consulta que hace cualquiera,
 * así que en unas semanas son cientos de miles de filas.
 */

import { useState } from 'react'

import { type Evento, useAuditoria, useResumenAuditoria } from '../api/gobierno'

/** Las acciones que conviene distinguir de un vistazo. */
const COLOR: Record<string, string> = {
  ingreso_fallido: 'critico',
  cambio_contrasena_fallido: 'critico',
  simulacion: 'aviso',
  exportacion: 'aviso',
  politicas_guardadas: 'dim',
  usuario_editado: 'dim',
  usuario_creado: 'dim',
  contrasena_restablecida: 'dim',
}

function hora(iso: string): string {
  return new Date(iso).toLocaleString('es-MX', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** Lo que importa de cada acción, en una línea. El JSON completo va aparte. */
function resumen(e: Evento): string {
  const d = e.detalle ?? {}
  const trozos: string[] = []
  const como = d.como as { email?: string; rol?: string } | undefined
  if (como) trozos.push(`como ${como.email ?? como.rol}`)
  if (typeof d.objetivo === 'string') trozos.push(d.objetivo)
  if (Array.isArray(d.metricas) && d.metricas.length)
    trozos.push((d.metricas as string[]).join(', '))
  if (typeof d.filas === 'number') trozos.push(`${d.filas.toLocaleString('es-MX')} filas`)
  if (typeof d.formato === 'string') trozos.push(String(d.formato))
  if (Array.isArray(d.politicas) && d.politicas.length)
    trozos.push(`políticas: ${(d.politicas as string[]).join(', ')}`)
  if (typeof d.version === 'number') trozos.push(`v${d.version}`)
  if (d.cambios && typeof d.cambios === 'object')
    trozos.push(Object.keys(d.cambios as object).join(', '))
  if (typeof d.ms === 'number') trozos.push(`${d.ms} ms`)
  return trozos.join(' · ')
}

export function Auditoria() {
  const resumenDatos = useResumenAuditoria()
  const [accion, setAccion] = useState('')
  const [email, setEmail] = useState('')
  const [dias, setDias] = useState<number | ''>('')
  const [pagina, setPagina] = useState(1)
  const [abierto, setAbierto] = useState<number | null>(null)

  const datos = useAuditoria({
    accion: accion || undefined,
    email: email || undefined,
    dias: dias || undefined,
    pagina,
  })

  const paginas = datos.data ? Math.ceil(datos.data.total / datos.data.por_pagina) : 1
  const fallidos = resumenDatos.data?.ingresos_fallidos ?? 0

  const cambiar = (fn: () => void) => {
    fn()
    setPagina(1)
  }

  return (
    <>
      {fallidos > 0 && (
        <div className="aviso-caja">
          {fallidos} intento(s) de ingreso fallidos en los últimos{' '}
          {resumenDatos.data?.dias} días.{' '}
          <button
            className="btn chico"
            onClick={() => cambiar(() => setAccion('ingreso_fallido'))}
          >
            Verlos
          </button>
        </div>
      )}

      <div className="fila-condicion">
        <div className="campo" style={{ flex: '1 1 220px' }}>
          <label>Acción</label>
          <select value={accion} onChange={(e) => cambiar(() => setAccion(e.target.value))}>
            <option value="">(todas)</option>
            {resumenDatos.data?.acciones.map((a) => (
              <option key={a.accion} value={a.accion}>
                {a.accion} ({a.veces})
              </option>
            ))}
          </select>
        </div>
        <div className="campo" style={{ flex: '1 1 220px' }}>
          <label>Persona</label>
          <select value={email} onChange={(e) => cambiar(() => setEmail(e.target.value))}>
            <option value="">(todas)</option>
            {resumenDatos.data?.personas.map((p) => (
              <option key={p.email} value={p.email}>
                {p.email} ({p.veces})
              </option>
            ))}
          </select>
        </div>
        <div className="campo" style={{ flex: '0 0 150px' }}>
          <label>Cuándo</label>
          <select
            value={dias}
            onChange={(e) =>
              cambiar(() => setDias(e.target.value ? Number(e.target.value) : ''))
            }
          >
            <option value="">(todo)</option>
            <option value="1">Último día</option>
            <option value="7">Última semana</option>
            <option value="30">Último mes</option>
            <option value="365">Último año</option>
          </select>
        </div>
      </div>

      {datos.isError && (
        <div className="error-caja">{(datos.error as Error).message}</div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
        <span className="chico suave">
          {(datos.data?.total ?? 0).toLocaleString('es-MX')} evento(s)
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <button
            className="btn chico"
            disabled={pagina <= 1}
            onClick={() => setPagina(pagina - 1)}
          >
            ← Anterior
          </button>
          <span className="chico tenue">
            {pagina} de {Math.max(paginas, 1)}
          </span>
          <button
            className="btn chico"
            disabled={pagina >= paginas}
            onClick={() => setPagina(pagina + 1)}
          >
            Siguiente →
          </button>
        </div>
      </div>

      <div className="tabla-envoltura" style={{ marginTop: 8 }}>
        <table className="datos">
          <thead>
            <tr>
              <th>Cuándo</th>
              <th>Quién</th>
              <th>Acción</th>
              <th>Objeto</th>
              <th>Qué pasó</th>
            </tr>
          </thead>
          <tbody>
            {datos.data?.eventos.map((e) => (
              <tr
                key={e.id}
                onClick={() => setAbierto(abierto === e.id ? null : e.id)}
                style={{ cursor: 'pointer' }}
              >
                <td className="mono chico">{hora(e.cuando)}</td>
                <td className="chico">{e.email ?? <span className="tenue">—</span>}</td>
                <td>
                  <span className={`etiqueta ${COLOR[e.accion] ?? ''}`}>{e.accion}</span>
                </td>
                <td className="chico suave">
                  {e.objeto_tipo ? `${e.objeto_tipo} ${e.objeto_id ?? ''}` : '—'}
                </td>
                <td className="chico suave" style={{ whiteSpace: 'normal' }}>
                  {abierto === e.id ? (
                    <pre className="mono detalle-json">
                      {JSON.stringify(e.detalle, null, 2)}
                    </pre>
                  ) : (
                    resumen(e)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {datos.data?.eventos.length === 0 && (
        <div className="vacio">Nada con esos filtros.</div>
      )}
    </>
  )
}
