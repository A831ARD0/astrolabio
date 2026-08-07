/**
 * Cron legible: de cinco campos a «los lunes a las 7 a. m.», y al revés.
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
 */

/** La zona de este navegador. Es la mejor conjetura para un horario nuevo. */
export function zonaDelNavegador(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Mexico_City'
  } catch {
    return 'America/Mexico_City'
  }
}

/** Las de México, que son las que se usan aquí, arriba y por su nombre de a pie. */
export const ZONAS_MX: { zona: string; donde: string }[] = [
  { zona: 'America/Mexico_City', donde: 'Centro — CDMX, Puebla, Oaxaca, Veracruz' },
  { zona: 'America/Cancun', donde: 'Quintana Roo — Cancún' },
  { zona: 'America/Merida', donde: 'Yucatán, Campeche' },
  { zona: 'America/Monterrey', donde: 'Nuevo León, Coahuila' },
  { zona: 'America/Matamoros', donde: 'Frontera de Tamaulipas' },
  { zona: 'America/Mazatlan', donde: 'Sinaloa, Nayarit' },
  { zona: 'America/Chihuahua', donde: 'Chihuahua' },
  { zona: 'America/Ciudad_Juarez', donde: 'Ciudad Juárez' },
  { zona: 'America/Hermosillo', donde: 'Sonora' },
  { zona: 'America/Tijuana', donde: 'Baja California' },
  { zona: 'America/Bahia_Banderas', donde: 'Bahía de Banderas' },
]

/** Todas las demás, si hace falta. Sin esto no se puede salir de México. */
export function todasLasZonas(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone') as string[]
  } catch {
    return ['UTC']
  }
}

export type Frecuencia =
  | 'hora' | 'dia' | 'lunes_viernes' | 'lunes_sabado' | 'semana' | 'mes' | 'avanzado'

export const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']

export interface Partes {
  frecuencia: Frecuencia
  minuto: number
  hora: number          // 0–23
  diaSemana: number     // 0–6
  diaMes: number        // 1–28
}

const POR_OMISION: Partes = {
  frecuencia: 'dia', minuto: 0, hora: 6, diaSemana: 1, diaMes: 1,
}

/**
 * De cron a partes. Devuelve `avanzado` en cuanto algo no encaja.
 *
 * Adivinar de menos es lo correcto: si el cron dice `*&#47;15 * * * *` y el selector
 * dijera «cada hora», guardar desde la interfaz cambiaría el horario sin que
 * nadie lo pidiera.
 */
export function aPartes(cron: string): Partes {
  const c = (cron || '').trim().split(/\s+/)
  if (c.length !== 5) return { ...POR_OMISION, frecuencia: 'avanzado' }
  const [m, h, dom, mes, dow] = c
  const num = (x: string) => (/^\d+$/.test(x) ? Number(x) : null)
  const minuto = num(m!)
  const hora = num(h!)
  if (minuto === null || mes !== '*') return { ...POR_OMISION, frecuencia: 'avanzado' }

  if (h === '*' && dom === '*' && dow === '*') {
    return { ...POR_OMISION, frecuencia: 'hora', minuto }
  }
  if (hora === null) return { ...POR_OMISION, frecuencia: 'avanzado' }

  if (dom === '*' && dow === '*') {
    return { ...POR_OMISION, frecuencia: 'dia', minuto, hora }
  }
  if (dom === '*' && dow === '1-5') {
    return { ...POR_OMISION, frecuencia: 'lunes_viernes', minuto, hora }
  }
  if (dom === '*' && dow === '1-6') {
    return { ...POR_OMISION, frecuencia: 'lunes_sabado', minuto, hora }
  }
  if (dom === '*' && num(dow!) !== null) {
    return { ...POR_OMISION, frecuencia: 'semana', minuto, hora, diaSemana: num(dow!)! }
  }
  if (dow === '*' && num(dom!) !== null) {
    return { ...POR_OMISION, frecuencia: 'mes', minuto, hora, diaMes: num(dom!)! }
  }
  return { ...POR_OMISION, frecuencia: 'avanzado' }
}

export function aCron(p: Partes): string {
  const { minuto: m, hora: h } = p
  switch (p.frecuencia) {
    case 'hora': return `${m} * * * *`
    case 'dia': return `${m} ${h} * * *`
    case 'lunes_viernes': return `${m} ${h} * * 1-5`
    case 'lunes_sabado': return `${m} ${h} * * 1-6`
    case 'semana': return `${m} ${h} * * ${p.diaSemana}`
    case 'mes': return `${m} ${h} ${p.diaMes} * *`
    default: return ''
  }
}

/** «6:05 a. m.» a partir de la hora de 24. */
export function enDoce(hora: number, minuto: number): string {
  const suf = hora < 12 ? 'a. m.' : 'p. m.'
  const h = hora % 12 === 0 ? 12 : hora % 12
  return `${h}:${String(minuto).padStart(2, '0')} ${suf}`
}

/** La frase que se lee en voz alta, para confirmar que es lo que se quería. */
export function enPalabras(cron: string, zona: string): string {
  const p = aPartes(cron)
  if (p.frecuencia === 'avanzado') return `Cron: ${cron || '(sin horario)'}`
  const hora = enDoce(p.hora, p.minuto)
  const cuando = {
    hora: `Cada hora, al minuto ${p.minuto}`,
    dia: `Todos los días a las ${hora}`,
    lunes_viernes: `De lunes a viernes a las ${hora}`,
    lunes_sabado: `De lunes a sábado a las ${hora}`,
    semana: `Los ${DIAS[p.diaSemana]} a las ${hora}`,
    mes: `El día ${p.diaMes} de cada mes a las ${hora}`,
  }[p.frecuencia]
  return `${cuando}, hora de ${zona}`
}

