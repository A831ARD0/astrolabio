/**
 * El apartado del envío por correo: a quién, cuándo, de qué periodo y qué va dentro.
 *
 * Vive en un diálogo y no en el inspector de la derecha a propósito: el inspector es de
 * la hoja que se está armando, y esto es del tablero entero y se toca una vez cada
 * varios meses. Se llega desde el menú del botón PDF, que es donde uno ya está cuando
 * piensa «esto debería llegarle a dirección cada mes».
 *
 * Lo que la pantalla tiene que dejar claro, y por eso está a la vista:
 *
 * - **De qué periodo es.** Es lo único con criterio de aquí. «El mes anterior» se
 *   resuelve en cada envío, así que el 2 de septiembre manda agosto sin que nadie lo
 *   toque; unos filtros fijos mandarían el mismo mes para siempre.
 * - **Con qué ojos se ve.** El informe se genera con la sesión de quien lo programó, así
 *   que las políticas de seguridad por fila del correo son las de esa persona.
 * - **Si el servidor puede mandar correo.** Un envío guardado sobre un servidor sin
 *   configurar se ve igual que uno que funciona, y esa confusión es la que hace que
 *   nadie reciba nada.
 * - **Cómo fue la última vez.** Un envío que lleva tres meses fallando y no lo dice en
 *   ningún sitio es un informe que nadie recibe y todos creen que llega.
 */

import { useState } from 'react'

import { useAccionEnvio, useEnvios } from '../api/hooks'
import type { EnvioEntrada, EnvioInforme } from '../api/tipos'
import { Horario } from '../comunes/Horario'
import { Velo } from '../comunes/Velo'
import { enPalabras } from '../comunes/cron'

/** El día 2 a las 7:00: el mes cerrado, con un día de margen para la carga del 1. */
const CRON_POR_OMISION = '0 7 2 * *'

const NUEVO: EnvioEntrada = {
  destinatarios: '',
  hoja: null,
  asunto: null,
  cuerpo: 'pdf',
  periodo: 'mes_anterior',
  cron: CRON_POR_OMISION,
  zona_horaria: 'America/Mexico_City',
  activa: false,
}

function comoEntrada(e: EnvioInforme): EnvioEntrada & { id: number } {
  return {
    id: e.id,
    destinatarios: e.destinatarios,
    hoja: e.hoja,
    asunto: e.asunto,
    cuerpo: e.cuerpo,
    periodo: e.periodo,
    cron: e.cron ?? CRON_POR_OMISION,
    zona_horaria: e.zona_horaria,
    activa: e.activa,
  }
}

function cuando(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es-MX', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

export function EnvioPorCorreo({
  dashboardId,
  hojas,
  quienSoy,
  alCerrar,
}: {
  dashboardId: number
  hojas: { id: string; nombre: string }[]
  quienSoy: string
  alCerrar: () => void
}) {
  const envios = useEnvios(dashboardId)
  const acciones = useAccionEnvio(dashboardId)
  const [editando, setEditando] = useState<(EnvioEntrada & { id?: number }) | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dicho, setDicho] = useState<string | null>(null)

  const lista = envios.data ?? []
  const correoListo = lista[0]?.correo_listo
  const correoDice = lista[0]?.correo_dice

  async function guardar() {
    if (!editando) return
    setError(null)
    setDicho(null)
    const { id, ...datos } = editando
    try {
      if (id) await acciones.cambiar.mutateAsync({ id, ...datos })
      else await acciones.crear.mutateAsync(datos)
      setEditando(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo guardar')
    }
  }

  async function probar(id: number) {
    setError(null)
    setDicho(null)
    try {
      const r = await acciones.probar.mutateAsync(id)
      setDicho(
        `Mandado a ${r.destinatarios.join(', ')} en ${(r.ms / 1000).toFixed(1)} s. ` +
          `Asunto: «${r.asunto}»`,
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo mandar')
    }
  }

  return (
    <Velo alCerrar={alCerrar}>
      <div className="modal ancho">
        <header>Enviar este informe por correo</header>
        <div className="cont">
          <p className="chico suave" style={{ margin: 0 }}>
            El servidor genera el informe y lo manda solo. Se ve <b>como lo ves tú</b>:
            se usa la sesión de quien programa el envío, así que si tus políticas te
            limitan a unas sucursales, el correo también irá limitado.
          </p>

          {correoListo === false && (
            <div className="aviso-caja">{correoDice}</div>
          )}
          {error && <div className="error-caja">{error}</div>}
          {dicho && <div className="aviso-caja ok-caja">{dicho}</div>}

          {lista.length > 0 && (
            <table className="datos">
              <thead>
                <tr>
                  <th>Para</th>
                  <th>Hoja</th>
                  <th>Cuándo</th>
                  <th>Periodo</th>
                  <th>Última vez</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {lista.map((e) => (
                  <tr key={e.id}>
                    <td>
                      {e.destinatarios}
                      {!e.activa && <span className="etiqueta"> apagado</span>}
                    </td>
                    <td>{e.hoja ?? 'la primera'}</td>
                    <td>
                      {enPalabras(e.cron ?? '', e.zona_horaria)}
                      {e.activa && (
                        <div className="chico tenue">próxima: {cuando(e.proxima)}</div>
                      )}
                    </td>
                    <td>
                      {e.periodo === 'mes_anterior'
                        ? 'el mes anterior'
                        : 'los filtros guardados'}
                    </td>
                    <td>
                      {e.ultimo_error ? (
                        <span className="mal" title={e.ultimo_error}>
                          falló
                        </span>
                      ) : (
                        cuando(e.ultimo_envio)
                      )}
                    </td>
                    <td className="dcha">
                      <button
                        className="btn chico"
                        onClick={() => setEditando(comoEntrada(e))}
                      >
                        Cambiar
                      </button>{' '}
                      <button
                        className="btn chico"
                        disabled={acciones.probar.isPending}
                        onClick={() => probar(e.id)}
                      >
                        {acciones.probar.isPending ? 'Mandando…' : 'Probar ahora'}
                      </button>{' '}
                      <button
                        className="btn chico peligro"
                        onClick={() => acciones.quitar.mutate(e.id)}
                      >
                        Quitar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* El error del último intento, entero: en la tabla solo cabe «falló». */}
          {lista.some((e) => e.ultimo_error) && (
            <div className="aviso-caja chico">
              {lista.find((e) => e.ultimo_error)?.ultimo_error}
            </div>
          )}

          {!editando && (
            <div className="acciones">
              <button className="btn" onClick={() => setEditando({ ...NUEVO })}>
                + Nuevo envío
              </button>
            </div>
          )}

          {editando && (
            <div className="ficha-envio">
              <div className="campo">
                <label>Para</label>
                <textarea
                  rows={2}
                  placeholder="gerencia@grupo.com, direccion@grupo.com"
                  value={editando.destinatarios}
                  onChange={(ev) =>
                    setEditando({ ...editando, destinatarios: ev.target.value })
                  }
                />
                <span className="chico tenue">
                  Separados por coma. Van todos en el mismo correo.
                </span>
              </div>

              <div className="dos">
                <div className="campo">
                  <label>Hoja</label>
                  <select
                    value={editando.hoja ?? ''}
                    onChange={(ev) =>
                      setEditando({ ...editando, hoja: ev.target.value || null })
                    }
                  >
                    <option value="">La primera</option>
                    {hojas.map((h) => (
                      <option key={h.id} value={h.nombre}>
                        {h.nombre}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="campo">
                  <label>Qué va en el correo</label>
                  <select
                    value={editando.cuerpo}
                    onChange={(ev) =>
                      setEditando({
                        ...editando,
                        cuerpo: ev.target.value as EnvioEntrada['cuerpo'],
                      })
                    }
                  >
                    <option value="pdf">El PDF adjunto</option>
                    <option value="imagen">La hoja en el cuerpo del correo</option>
                    <option value="ambos">Las dos cosas</option>
                  </select>
                  <span className="chico tenue">
                    En el cuerpo se ve sin abrir nada, pero es una imagen: para copiar
                    una cifra hace falta el PDF.
                  </span>
                </div>
              </div>

              <div className="campo">
                <label>De qué periodo</label>
                <select
                  value={editando.periodo}
                  onChange={(ev) =>
                    setEditando({
                      ...editando,
                      periodo: ev.target.value as EnvioEntrada['periodo'],
                    })
                  }
                >
                  <option value="mes_anterior">El mes anterior</option>
                  <option value="guardado">Los filtros guardados del tablero</option>
                </select>
                <span className="chico tenue">
                  {editando.periodo === 'mes_anterior'
                    ? 'Se calcula en cada envío: el 2 de septiembre manda agosto, y el 2 de octubre manda septiembre. Hace falta que el modelo tenga marcada la columna del mes.'
                    : 'Manda siempre con los filtros que el tablero tenga guardados. Si son de un mes concreto, mandará ese mes para siempre.'}
                </span>
              </div>

              <div className="campo">
                <label>Asunto</label>
                <input
                  type="text"
                  placeholder="El nombre del tablero y la hoja"
                  value={editando.asunto ?? ''}
                  onChange={(ev) =>
                    setEditando({ ...editando, asunto: ev.target.value || null })
                  }
                />
                <span className="chico tenue">
                  El periodo se añade solo: un informe que circula tiene que decir de
                  qué mes es sin abrirlo.
                </span>
              </div>

              <div className="campo">
                <label>Cuándo</label>
                <Horario
                  cron={editando.cron}
                  zona={editando.zona_horaria}
                  onCambio={(cron, zona_horaria) =>
                    setEditando({ ...editando, cron, zona_horaria })
                  }
                />
              </div>

              <label className="casilla">
                <input
                  type="checkbox"
                  checked={editando.activa}
                  onChange={(ev) =>
                    setEditando({ ...editando, activa: ev.target.checked })
                  }
                />
                Encendido — mientras esté apagado no sale ningún correo
              </label>

              <div className="acciones">
                <button className="btn primario" onClick={guardar}>
                  {editando.id ? 'Guardar cambios' : 'Crear envío'}
                </button>
                <button className="btn" onClick={() => setEditando(null)}>
                  Cancelar
                </button>
              </div>
            </div>
          )}

          <p className="chico tenue" style={{ marginBottom: 0 }}>
            Se manda con la sesión de <b>{quienSoy}</b>. Prueba con «Probar ahora» antes
            de encenderlo: sale a los mismos destinatarios, así que se comprueba la
            lista entera y no solo que el servidor de correo contesta.
          </p>
        </div>
        <footer>
          <button className="btn" onClick={alCerrar}>
            Cerrar
          </button>
        </footer>
      </div>
    </Velo>
  )
}
