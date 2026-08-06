/**
 * Cliente de la API.
 *
 * Un solo lugar que hable con el backend, por dos razones concretas: el token
 * viaja siempre (nunca se olvida en una llamada nueva) y los errores llegan a la
 * interfaz con su mensaje del servidor, no como un "algo fallo" genérico. Los
 * mensajes del backend están escritos para leerse — perderlos sería tirar el
 * trabajo de haberlos escrito.
 */

const CLAVE_TOKEN = 'astrolabio.token'

export class ErrorApi extends Error {
  constructor(
    readonly estado: number,
    mensaje: string,
    /** Detalle estructurado: rutas de una ambigüedad, lista de errores... */
    readonly detalle?: unknown,
  ) {
    super(mensaje)
  }
}

export const token = {
  leer: () => localStorage.getItem(CLAVE_TOKEN),
  guardar: (t: string) => localStorage.setItem(CLAVE_TOKEN, t),
  borrar: () => localStorage.removeItem(CLAVE_TOKEN),
}

/** Convierte el `detail` de FastAPI en algo que se pueda mostrar. */
function mensajeDe(detalle: unknown, estado: number): string {
  if (typeof detalle === 'string') return detalle

  // Errores de validación de Pydantic: [{loc, msg}, ...]
  if (Array.isArray(detalle)) {
    return detalle
      .map((e) => {
        const x = e as { loc?: unknown[]; msg?: string }
        const donde = Array.isArray(x.loc) ? x.loc.slice(1).join('.') : ''
        return donde ? `${donde}: ${x.msg}` : (x.msg ?? '')
      })
      .join('\n')
  }

  if (detalle && typeof detalle === 'object') {
    const d = detalle as Record<string, unknown>
    if (typeof d.mensaje === 'string') return d.mensaje
    if (Array.isArray(d.errores)) return d.errores.join('\n')
  }
  return `Error ${estado}`
}

async function peticion<T>(
  ruta: string,
  opciones: RequestInit & { cuerpo?: unknown } = {},
): Promise<T> {
  const { cuerpo, ...resto } = opciones
  const cabeceras = new Headers(resto.headers)
  const t = token.leer()
  if (t) cabeceras.set('Authorization', `Bearer ${t}`)
  if (cuerpo !== undefined) cabeceras.set('Content-Type', 'application/json')

  const r = await fetch(`/api${ruta}`, {
    ...resto,
    headers: cabeceras,
    body: cuerpo !== undefined ? JSON.stringify(cuerpo) : resto.body,
  })

  if (r.status === 401) {
    // El token caducó o no sirve. Borrarlo aquí evita que la interfaz se quede
    // reintentando con una credencial muerta.
    token.borrar()
    throw new ErrorApi(401, 'La sesión expiró. Vuelve a entrar.')
  }
  if (!r.ok) {
    let detalle: unknown
    try {
      detalle = (await r.json()).detail
    } catch {
      detalle = await r.text().catch(() => undefined)
    }
    throw new ErrorApi(r.status, mensajeDe(detalle, r.status), detalle)
  }
  if (r.status === 204) return undefined as T
  return (await r.json()) as T
}

export const api = {
  get: <T>(ruta: string) => peticion<T>(ruta),
  post: <T>(ruta: string, cuerpo?: unknown) =>
    peticion<T>(ruta, { method: 'POST', cuerpo }),
  put: <T>(ruta: string, cuerpo?: unknown) =>
    peticion<T>(ruta, { method: 'PUT', cuerpo }),
  patch: <T>(ruta: string, cuerpo?: unknown) =>
    peticion<T>(ruta, { method: 'PATCH', cuerpo }),
  del: <T>(ruta: string) => peticion<T>(ruta, { method: 'DELETE' }),

  /** El ingreso usa formulario, no JSON: es lo que espera OAuth2 de FastAPI. */
  async ingresar(email: string, contrasena: string) {
    const cuerpo = new URLSearchParams({ username: email, password: contrasena })
    const r = await fetch('/api/auth/token', { method: 'POST', body: cuerpo })
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      throw new ErrorApi(r.status, mensajeDe(d.detail, r.status))
    }
    const datos = (await r.json()) as { access_token: string }
    token.guardar(datos.access_token)
    return datos
  },
}
