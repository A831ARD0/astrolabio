/**
 * Flujos: cargas y transformaciones en cadena, con un solo horario.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './cliente'

export interface PasoFlujo {
  tipo: 'carga' | 'transformacion'
  id: number
  nombre?: string | null
}

export interface Flujo {
  id: number
  nombre: string
  descripcion: string | null
  pasos: PasoFlujo[]
  al_fallar: 'detener' | 'continuar'
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
  /** Problemas de orden deducidos del linaje. Se recalculan al leer. */
  avisos: string[]
}

export interface ResultadoPaso {
  paso: number
  tipo: string
  nombre: string
  estado: 'exito' | 'error' | 'omitido' | 'corriendo'
  filas?: number
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

export function useSacarDeLaCola() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (trabajoId: number) => api.del<void>(`/flujos/cola/${trabajoId}`),
    onSettled: () => qc.invalidateQueries({ queryKey: clave.cola }),
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
