/**
 * Avisos: a quién se le cuenta cuando una carga o un flujo falla.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './cliente'

export interface ReglaAviso {
  id: number
  nombre: string
  canal: 'correo' | 'webhook'
  destino: string
  eventos: string[]
  objeto_tipo: 'dataset' | 'flujo' | null
  objeto_id: number | null
  objeto_nombre: string | null
  silencio_minutos: number
  activa: boolean
  /** Si el canal puede entregar ahora mismo. Una regla activa sobre un canal sin
   *  configurar se ve igual que una que funciona si no se dice. */
  canal_listo: boolean
  canal_detalle: string
  ultimo_envio: string | null
  ultimo_estado: string | null
}

export interface CuerpoRegla {
  nombre: string
  canal: 'correo' | 'webhook'
  destino: string
  eventos: string[]
  objeto_tipo: 'dataset' | 'flujo' | null
  objeto_id: number | null
  silencio_minutos: number
  activa: boolean
}

export interface CatalogoAvisos {
  eventos: { clave: string; etiqueta: string; requiere: string | null }[]
  canales: { clave: string; listo: boolean; detalle: string }[]
  datasets: { id: number; nombre: string }[]
  flujos: { id: number; nombre: string }[]
}

export interface EnvioAviso {
  id: number
  regla: string
  evento: string
  objeto_tipo: string | null
  objeto_id: number | null
  asunto: string
  estado: 'enviado' | 'silenciado' | 'error'
  mensaje: string | null
  cuando: string
}

const clave = {
  lista: ['avisos'] as const,
  catalogo: ['avisos', 'catalogo'] as const,
  historial: ['avisos', 'historial'] as const,
}

export function useAvisos() {
  return useQuery({
    queryKey: clave.lista,
    queryFn: () => api.get<ReglaAviso[]>('/avisos'),
  })
}

export function useCatalogoAvisos() {
  return useQuery({
    queryKey: clave.catalogo,
    queryFn: () => api.get<CatalogoAvisos>('/avisos/catalogo'),
  })
}

export function useHistorialAvisos() {
  return useQuery({
    queryKey: clave.historial,
    queryFn: () => api.get<{ envios: EnvioAviso[] }>('/avisos/historial'),
  })
}

export function useGuardarAviso() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, cuerpo }: { id: number | null; cuerpo: CuerpoRegla }) =>
      id === null
        ? api.post<ReglaAviso>('/avisos', cuerpo)
        : api.put<ReglaAviso>(`/avisos/${id}`, cuerpo),
    onSuccess: () => qc.invalidateQueries({ queryKey: clave.lista }),
  })
}

/**
 * Prueba de la regla. No lanza cuando el envío falla: contesta `ok: false` con el
 * error del canal, que es justo lo que se necesita leer para arreglarlo.
 */
export function useProbarAviso() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api.post<{ ok: boolean; detalle: string }>(`/avisos/${id}/probar`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clave.historial })
      qc.invalidateQueries({ queryKey: clave.lista })
    },
  })
}

export function useBorrarAviso() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del(`/avisos/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: clave.lista }),
  })
}
