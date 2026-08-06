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
  /** Problemas de orden deducidos del linaje. Se recalculan al leer. */
  avisos: string[]
}

export interface ResultadoPaso {
  paso: number
  tipo: string
  nombre: string
  estado: 'exito' | 'error' | 'omitido'
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
  cuando: string
}

const clave = {
  lista: ['flujos'] as const,
  disponibles: ['flujos', 'disponibles'] as const,
  historial: (id: number) => ['flujos', id, 'historial'] as const,
}

export function useFlujos() {
  return useQuery({ queryKey: clave.lista, queryFn: () => api.get<Flujo[]>('/flujos') })
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

export function useEjecutarFlujo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api.post<{ estado: string; ms: number; pasos: ResultadoPaso[] }>(
        `/flujos/${id}/ejecutar`,
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: clave.lista })
      qc.invalidateQueries({ queryKey: ['flujos'] })
      qc.invalidateQueries({ queryKey: ['transformaciones'] })
    },
  })
}

export function useHistorialFlujo(id: number | null) {
  return useQuery({
    queryKey: clave.historial(id ?? 0),
    queryFn: () =>
      api.get<{ ejecuciones: EjecucionFlujo[] }>(`/flujos/${id}/historial`),
    enabled: !!id,
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
