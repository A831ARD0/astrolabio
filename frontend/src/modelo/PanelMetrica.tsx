/**
 * Editor de una métrica.
 *
 * Lo importante aquí es el botón de probar: ejecuta la expresión de verdad,
 * contra los datos, con el mismo compilador que usará la métrica guardada. Una
 * expresión puede estar bien escrita y significar otra cosa; ver el número antes
 * de guardar es lo que evita publicar una cifra plausible y equivocada.
 *
 * Probar no guarda nada: la métrica se inyecta en una copia del modelo que se
 * descarta al responder.
 */

import { useState } from 'react'

import { useProbarMetrica } from '../api/hooks'
import type { Definicion, Metrica } from '../api/tipos'
import type { Accion } from './estado'

const FORMATOS = ['numero', 'entero', 'moneda', 'porcentaje']

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
  const prueba = useProbarMetrica(modeloId)

  const hechos = definicion.entidades.filter((e) => e.tipo === 'hecho')
  const entidad = definicion.entidades.find((e) => e.nombre === borrador.entidad)

  const dimensiones = definicion.entidades.flatMap((e) =>
    e.campos
      .filter((c) => c.rol === 'dimension' && c.visible !== false)
      .map((c) => `${e.nombre}.${c.nombre}`),
  )

  const nombreRepetido = definicion.metricas.some(
    (m, i) => m.nombre === borrador.nombre && i !== indice,
  )
  const valida = borrador.nombre.trim() && borrador.expresion.trim() && !nombreRepetido

  return (
    <div className="velo" onClick={alCerrar}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>{indice === null ? 'Nueva métrica' : `Métrica ${metrica.nombre}`}</header>

        <div className="cont">
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
          </div>

          {nombreRepetido && (
            <div className="error-caja">Ya hay otra métrica con ese nombre.</div>
          )}

          <div className="fila">
            <div className="campo">
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
            <div className="campo">
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

          <div className="campo">
            <label>Expresión</label>
            <textarea
              rows={3}
              value={borrador.expresion}
              onChange={(e) => setBorrador({ ...borrador, expresion: e.target.value })}
              placeholder="SUM(monto_base - monto_impuesto)"
            />
            <span className="chico tenue">
              Los campos se escriben sin prefijo de tabla: el motor los califica
              solo, sobre el árbol de la expresión.
            </span>
          </div>

          {entidad && (
            <div className="chico">
              <span className="suave">Medidas de {entidad.nombre}: </span>
              {entidad.campos
                .filter((c) => c.rol === 'medida_base')
                .map((c) => (
                  <button
                    key={c.nombre}
                    className="btn chico mono"
                    style={{ margin: '2px 3px 0 0' }}
                    onClick={() =>
                      setBorrador({
                        ...borrador,
                        expresion: borrador.expresion + c.nombre,
                      })
                    }
                  >
                    {c.nombre}
                  </button>
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
              disabled={!borrador.expresion.trim() || prueba.isPending}
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
              <div className="tabla-envoltura" style={{ maxHeight: 200 }}>
                <table className="datos">
                  <thead>
                    <tr>
                      {prueba.data.columnas.map((c) => (
                        <th key={c}>{c === '__prueba__' ? borrador.etiqueta || 'valor' : c}</th>
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
                <summary className="suave">SQL generado ({prueba.data.ms} ms)</summary>
                <pre className="mono" style={{ overflow: 'auto', maxHeight: 180 }}>
                  {prueba.data.sql}
                </pre>
              </details>
            </>
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
            onClick={() => {
              despachar({ t: 'guardar_metrica', indice, metrica: borrador })
              alCerrar()
            }}
          >
            Aceptar
          </button>
        </footer>
      </div>
    </div>
  )
}

function formatear(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') return v.toLocaleString('es-MX', { maximumFractionDigits: 2 })
  return String(v)
}
