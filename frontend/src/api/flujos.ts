/**
 * Flujos: cargas y transformaciones en cadena, con un solo horario.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './cliente'

export interface PasoFlujo {
  /** `flujo` es un flujo entero como paso de otro: así se encadena. */
  tipo: 'carga' | 'transformacion' | 'flujo'
  id: number
  nombre?: string | null
}

export interface Flujo {
  id: number
  nombre: string
  descripcion: string | null
  pasos: PasoFlujo[]
  al_fallar: 'detener' | 'continuar'
  /** Cuántas veces se reintenta un paso antes de darlo por fallido. */
  reintentos: number
  espera_reintento_seg: number
  cron: string | null
  zona_horaria: string
  programacion_activa: boolean
  proxima_corrida: string | null
  ultima_ejecucion: string | null
  ultimo_estado: string | null
  /** Cuánto tardó y qué dijo la última corrida, sin abrir el historial. */
  ultima_ms: number | null
  ultimo_mensaje: string | null
  /** «7 de 28» mientras corre; null el resto del tiempo. */
  progreso: string | null
  /** Los flujos que llaman a este. Vacío si nadie lo llama. */
  llamado_por: string[]
  /** Problemas de orden deducidos del linaje. Se recalculan al leer. */
  avisos: string[]
}

export interface ResultadoPaso {
  paso: number
  tipo: string
  nombre: string
  /** `cancelado`: alguien detuvo el flujo antes de llegar a este paso. */
  estado: 'exito' | 'error' | 'omitido' | 'corriendo' | 'cancelado' | 'saltado'
  /** Cuántos intentos hicieron falta. Solo viene si hubo más de uno. */
  intentos?: number
  filas?: number
  /** Cuántos pasos traía dentro, cuando el paso es un flujo. */
  sub_pasos?: number
  modo?: string
  ms?: number
  mensaje?: string
}

export interface EjecucionFlujo {
  id: number
  estado: string
  disparo: string
  ms: number
  mensaje: string | null
  pasos: ResultadoPaso[]
  /** Cuantos pasos tiene el flujo, para poder decir «7 de 28». */
  total: number | null
  /** Si esta corrida la disparó otro flujo, cuál. */
  llamado_por?: string | null
  /** La corrida que esta continúa, y la que continuó a esta. */
  reanuda_a: number | null
  reanudada_por: number | null
  /** Si se puede continuar: se detuvo o falló y nadie la ha continuado. */
  reanudable: boolean
  /** Cuántos pasos se saltarían y cuántos se correrían. Solo si es reanudable. */
  saltaria?: number
  correria?: number
  /** Pasos que estaban en esa corrida y ya no están en el flujo. */
  ausentes?: { tipo: string; nombre: string | null }[]
  cuando: string
}

const clave = {
  lista: ['flujos'] as const,
  disponibles: ['flujos', 'disponibles'] as const,
  cola: ['flujos', 'cola'] as const,
  historial: (id: number) => ['flujos', id, 'historial'] as const,
}

/**
 * La lista de flujos. Se vuelve a pedir sola mientras alguno corra: es de donde
 * sale el «va por el paso 7 de 28», y un numero que no avanza no sirve de nada.
 */
export function useFlujos() {
  return useQuery({
    queryKey: clave.lista,
    queryFn: () => api.get<Flujo[]>('/flujos'),
    refetchInterval: (q) => {
      const d = q.state.data as Flujo[] | undefined
      return d?.some((f) => f.progreso) ? 3000 : false
    },
  })
}

export function useDisponiblesFlujo() {
  return useQuery({
    queryKey: clave.disponibles,
    queryFn: () =>
      api.get<{
        flujos: { id: number; nombre: string; pasos: number; cron_propio: string | null }[]
        cargas: { id: number; nombre: string; tabla: string; cron_propio: string | null }[]
        transformaciones: { id: number; nombre: string; lee_de: Record<string, string[]> }[]
      }>('/flujos/disponibles'),
  })
}

export interface CuerpoFlujo {
  nombre: string
  descripcion?: string | null
  pasos: PasoFlujo[]
  al_fallar: 'detener' | 'continuar'
  reintentos: number
  espera_reintento_seg: number
}

export function useGuardarFlujo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, cuerpo }: { id: number | null; cuerpo: CuerpoFlujo }) =>
      id === null
        ? api.post<Flujo>('/flujos', cuerpo)
        : api.put<Flujo>(`/flujos/${id}`, cuerpo),
    onSuccess: () => qc.invalidateQueries({ queryKey: clave.lista }),
  })
}

export function useSugerirOrden() {
  return useMutation({
    mutationFn: (cuerpo: CuerpoFlujo) =>
      api.post<{ pasos: PasoFlujo[]; avisos: string[] }>('/flujos/sugerir-orden', cuerpo),
  })
}

/** Lo que corre ahora y lo que espera turno. */
export interface Trabajo {
  id: number
  tipo: string
  objeto_id: number
  nombre: string
  estado: 'en_cola' | 'corriendo'
  /** Ya se pidió que pare; termina la tabla en curso y se detiene. */
  parando: boolean
  a_la_par: boolean
  quien: string
  encolado_en: string
  iniciado_en: string | null
}

export interface Cola {
  corriendo: Trabajo[]
  en_cola: Trabajo[]
}

export interface Lanzado {
  trabajo_id: number
  estado: 'en_cola' | 'corriendo'
  pasos: number
  /** Nombre de lo que ya estaba corriendo cuando este quedó en cola. */
  esperando_a: string | null
}

/**
 * Lanza el flujo. NO espera a que termine.
 *
 * Antes esta llamada tenía la petición abierta hasta el último paso; con
 * veintiocho tablas por el puente eso son minutos, el proxy corta con un 502 y
 * salirse de la pantalla dejaba sin saber cómo acabó. Ahora contesta enseguida
 * y el resultado se sigue por el historial.
 */
export function useEjecutarFlujo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, aLaPar = false }: { id: number; aLaPar?: boolean }) =>
      api.post<Lanzado>(`/flujos/${id}/ejecutar?a_la_par=${aLaPar}`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: clave.lista })
      qc.invalidateQueries({ queryKey: clave.cola })
      qc.invalidateQueries({ queryKey: ['flujos'] })
      qc.invalidateQueries({ queryKey: ['transformaciones'] })
    },
  })
}

/**
 * Continúa una corrida que se detuvo o falló, saltándose lo que ya salió bien.
 *
 * Las transformaciones se rehacen siempre: reanudar mezcla dos momentos, y una
 * transformación que ya corrió con los datos viejos se quedaría rancia mientras
 * sus orígenes se actualizan.
 */
export function useReanudar(flujoId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ejecucionId: number) =>
      api.post<Lanzado & { continua_de: number; saltados: number }>(
        `/flujos/${flujoId}/reanudar/${ejecucionId}`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['flujos'] })
    },
  })
}

/**
 * La cola, refrescada sola mientras haya algo.
 *
 * Se pregunta seguido a propósito: es la única señal de que la extracción de la
 * noche sigue viva. Cuando no hay nada, baja el ritmo y deja de molestar.
 */
export function useCola() {
  return useQuery({
    queryKey: clave.cola,
    queryFn: () => api.get<Cola>('/flujos/cola'),
    refetchInterval: (q) => {
      const d = q.state.data as Cola | undefined
      return d && (d.corriendo.length || d.en_cola.length) ? 3000 : 15000
    },
  })
}

/**
 * Detiene un trabajo: lo saca de la cola, o le pide parar si ya corre.
 *
 * Un flujo que corre se detiene **entre pasos**, nunca a media tabla: la que se
 * está trayendo se termina y los pasos que faltan quedan como cancelados.
 */
export function useDetener() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (trabajoId: number) =>
      api.del<{ estado: 'sacado' | 'parando'; mensaje: string }>(
        `/flujos/cola/${trabajoId}`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: clave.cola })
      qc.invalidateQueries({ queryKey: clave.lista })
    },
  })
}

/**
 * El historial. Mientras la corrida de arriba siga viva se vuelve a pedir sola:
 * es donde se ve avanzar una extraccion larga, paso a paso.
 */
export function useHistorialFlujo(id: number | null) {
  return useQuery({
    queryKey: clave.historial(id ?? 0),
    queryFn: () =>
      api.get<{ ejecuciones: EjecucionFlujo[] }>(`/flujos/${id}/historial`),
    enabled: !!id,
    refetchInterval: (q) => {
      const d = q.state.data as { ejecuciones: EjecucionFlujo[] } | undefined
      return d?.ejecuciones[0]?.estado === 'corriendo' ? 3000 : false
    },
  })
}

export function useProgramarFlujo(id: number | null) {
  const qc = useQueryClient()
  const tras = () => qc.invalidateQueries({ queryKey: clave.lista })
  return {
    programar: useMutation({
      mutationFn: (v: { cron: string; zona_horaria: string; activa: boolean }) =>
        api.put<Flujo>(`/flujos/${id}/programacion`, v),
      onSuccess: tras,
    }),
    quitar: useMutation({
      mutationFn: () => api.del<void>(`/flujos/${id}/programacion`),
      onSuccess: tras,
    }),
    borrar: useMutation({
      mutationFn: () => api.del<void>(`/flujos/${id}`),
      onSuccess: tras,
    }),
  }
}

/** Horarios frecuentes, para no tener que saber cron de memoria. */
export const HORARIOS: { etiqueta: string; cron: string }[] = [
  { etiqueta: 'Cada hora', cron: '0 * * * *' },
  { etiqueta: 'Todos los días a las 6:00', cron: '0 6 * * *' },
  { etiqueta: 'Todos los días a las 22:00', cron: '0 22 * * *' },
  { etiqueta: 'De lunes a sábado a las 6:00', cron: '0 6 * * 1-6' },
  { etiqueta: 'Los lunes a las 7:00', cron: '0 7 * * 1' },
  { etiqueta: 'El día 1 de cada mes a las 5:00', cron: '0 5 1 * *' },
]
