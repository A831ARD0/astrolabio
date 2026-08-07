/**
 * Elegir un horario sin saber cron, y decir en qué zona.
 *
 * Antes esta pantalla pedía `0 6 * * *`. Quien programa las cargas de cuarenta
 * sucursales no tiene por qué saber en qué orden van los cinco campos, y el
 * error que se comete —poner la hora en el primero— no falla: programa algo
 * distinto de lo que se quería, todos los días, calladamente.
 *
 * Se elige por partes —cada cuánto, a qué hora, a. m. o p. m.— y el cron se
 * escribe solo. El campo de cron sigue estando, porque hay horarios que solo se
 * pueden decir así («cada 15 minutos», «los días 1 y 15»), y en cuanto se
 * escribe algo que no encaja en las formas de arriba, el selector se pone en
 * *avanzado* en vez de mentir.
 *
 * Y la **zona** se elige. Estaba fija en `America/Mexico_City` —el valor por
 * omisión de la base— sin que se viera de dónde salía ni cómo cambiarla: en un
 * grupo con sucursales en Tijuana y en Cancún eso son tres husos distintos, y
 * «las 6:00» no significa lo mismo en los tres.
 *
 * El cálculo vive aparte, en `cron.ts`: lo usan también las pantallas que solo
 * quieren *leer* un horario en voz alta, sin ofrecer cambiarlo.
 */

import { useMemo } from 'react'

import {
  DIAS, type Frecuencia, type Partes, ZONAS_MX, aCron, aPartes, enDoce,
  enPalabras, todasLasZonas, zonaDelNavegador,
} from './cron'

export function Horario({
  cron,
  zona,
  onCambio,
}: {
  cron: string
  zona: string
  onCambio: (cron: string, zona: string) => void
}) {
  const p = useMemo(() => aPartes(cron), [cron])
  const propia = zonaDelNavegador()
  const otras = useMemo(
    () => todasLasZonas().filter((z) => !ZONAS_MX.some((x) => x.zona === z) && z !== propia),
    [propia],
  )

  const cambia = (cambio: Partial<Partes>) => {
    const nuevo = { ...p, ...cambio }
    onCambio(nuevo.frecuencia === 'avanzado' ? cron : aCron(nuevo), zona)
  }

  // 0–23 en la lista de horas, pero escritas como las lee cualquiera.
  const horas = Array.from({ length: 24 }, (_, h) => h)
  const minutos = [0, 5, 10, 15, 20, 30, 40, 45, 50]

  return (
    <div className="horario">
      <div className="fila-condicion">
        <select
          value={p.frecuencia}
          onChange={(e) => cambia({ frecuencia: e.target.value as Frecuencia })}
        >
          <option value="hora">Cada hora</option>
          <option value="dia">Todos los días</option>
          <option value="lunes_viernes">De lunes a viernes</option>
          <option value="lunes_sabado">De lunes a sábado</option>
          <option value="semana">Un día a la semana</option>
          <option value="mes">Un día del mes</option>
          <option value="avanzado">Avanzado (cron)</option>
        </select>

        {p.frecuencia === 'semana' && (
          <select value={p.diaSemana}
                  onChange={(e) => cambia({ diaSemana: Number(e.target.value) })}>
            {DIAS.map((d, i) => <option key={i} value={i}>{d}</option>)}
          </select>
        )}

        {p.frecuencia === 'mes' && (
          <select value={p.diaMes}
                  onChange={(e) => cambia({ diaMes: Number(e.target.value) })}>
            {/* Hasta 28: el 30 y el 31 no existen todos los meses, y una carga
                que se salta febrero es de las que nadie nota hasta marzo. */}
            {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
              <option key={d} value={d}>día {d}</option>
            ))}
          </select>
        )}

        {p.frecuencia !== 'avanzado' && (
          <>
            <span className="chico suave">a las</span>
            {p.frecuencia !== 'hora' && (
              <select value={p.hora} onChange={(e) => cambia({ hora: Number(e.target.value) })}>
                {horas.map((h) => (
                  <option key={h} value={h}>{enDoce(h, 0).replace(':00', '')}</option>
                ))}
              </select>
            )}
            <select value={p.minuto} onChange={(e) => cambia({ minuto: Number(e.target.value) })}>
              {minutos.map((m) => (
                <option key={m} value={m}>
                  {p.frecuencia === 'hora' ? `minuto ${m}` : `y ${String(m).padStart(2, '0')}`}
                </option>
              ))}
            </select>
          </>
        )}
      </div>

      <div className="fila-condicion" style={{ marginTop: 6 }}>
        <span className="chico suave">Hora de</span>
        <select value={zona} onChange={(e) => onCambio(cron, e.target.value)}>
          <optgroup label="Este navegador">
            <option value={propia}>{propia}</option>
          </optgroup>
          <optgroup label="México">
            {ZONAS_MX.map((z) => (
              <option key={z.zona} value={z.zona}>{z.zona} — {z.donde}</option>
            ))}
          </optgroup>
          <optgroup label="Las demás">
            {otras.map((z) => <option key={z} value={z}>{z}</option>)}
          </optgroup>
        </select>
      </div>

      {/* El cron siempre a la vista: es lo que de verdad se guarda, y hay
          horarios que solo se pueden decir así. */}
      <div className="fila-condicion" style={{ marginTop: 6 }}>
        <span className="chico suave">cron</span>
        <input
          type="text"
          className="mono"
          value={cron}
          placeholder="minuto hora día mes día-semana"
          onChange={(e) => onCambio(e.target.value, zona)}
          style={{ maxWidth: 160 }}
        />
      </div>

      {/* Solo el hecho: cuál es la zona de este navegador. Decir «esta venía
          por omisión» sería inventar — desde aquí no se puede distinguir una
          zona elegida a mano de la que puso la base sola. */}
      <span className="chico tenue">
        {enPalabras(cron, zona)}
        {zona !== propia && <> · Este navegador está en <b>{propia}</b>.</>}
      </span>
    </div>
  )
}
