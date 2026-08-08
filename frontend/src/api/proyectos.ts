/**
 * Proyectos con secciones: el equivalente al script con secciones del editor de
 * carga de Qlik.
 *
 * Un proyecto es un flujo restringido a transformaciones, y de ahí sale la única
 * rareza de este archivo: **se crea y se ordena por `/proyectos`, pero se ejecuta y
 * se programa por `/flujos`**. No es un descuido. Un proyecto comparte tabla y
 * ejecutor con los flujos porque comparte lo que de verdad importa —reintentos,
 * detenerse entre pasos, reanudar, historial— y duplicar eso «pero para proyectos»
 * acabaría con una de las dos copias atrasada. Lo que cambia es el vocabulario de la
 * pantalla, no la corrida: por eso un proyecto también sale en Tareas y se detiene
 * con el mismo botón que todo lo demás.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './cliente'

export interface SeccionProyecto {
  id: number
  nombre: string
  descripcion: string | null
  orden: number
  intermedia: boolean
  filas: number
  ultima_ejecucion: string | null
  ultimo_estado: string | null
  tiene_datos: boolean
}

export interface Proyecto {
  id: number
  nombre: string
  descripcion: string | null
  secciones: SeccionProyecto[]
  cron: string | null
  zona_horaria: string
  programacion_activa: boolean
  ultima_ejecucion: string | null
  ultimo_estado: string | null
  ultimo_mensaje: string | null
  /**
   * Si la última corrida fue un tramo, desde qué sección.
   *
   * Va a la vista: dos secciones en verde de dieciocho se leen como «el proyecto
   * está al día» si nadie dice que las demás no se pidieron.
   */
  ultimo_tramo_desde: number | null
  /** Secciones que el proyecto lista y que ya no existen. Se dicen, no se esconden. */
  huerfanas: number[]
}

const clave = {
  lista: ['proyectos'] as const,
  sueltas: ['proyectos', 'sueltas'] as const,
}

export function useProyectos() {
  return useQuery({
    queryKey: clave.lista,
    queryFn: () => api.get<Proyecto[]>('/proyectos'),
  })
}

/** Las transformaciones que no son sección de ningún proyecto. */
export function useSueltas() {
  return useQuery({
    queryKey: clave.sueltas,
    queryFn: () =>
      api.get<{
        transformaciones: { id: number; nombre: string; filas: number
                            intermedia: boolean }[]
      }>('/proyectos/sueltas'),
  })
}

/** Todo lo que cambia la pertenencia o el orden invalida las mismas tres listas. */
function useCambio<T, R>(fn: (v: T) => Promise<R>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clave.lista })
      qc.invalidateQueries({ queryKey: clave.sueltas })
      qc.invalidateQueries({ queryKey: ['transformaciones'] })
    },
  })
}

export function useCrearProyecto() {
  return useCambio((cuerpo: { nombre: string; descripcion?: string | null }) =>
    api.post<Proyecto>('/proyectos', cuerpo))
}

export function useEditarProyecto() {
  return useCambio(
    ({ id, ...cuerpo }: { id: number; nombre: string
                          descripcion?: string | null; secciones?: number[] }) =>
      api.put<Proyecto>(`/proyectos/${id}`, cuerpo))
}

export function useAgregarSeccion() {
  return useCambio(({ proyecto, transformacion }: { proyecto: number
                                                    transformacion: number }) =>
    api.post<Proyecto>(`/proyectos/${proyecto}/secciones/${transformacion}`))
}

export function useQuitarSeccion() {
  return useCambio(({ proyecto, transformacion }: { proyecto: number
                                                    transformacion: number }) =>
    api.del<Proyecto>(`/proyectos/${proyecto}/secciones/${transformacion}`))
}

export function useBorrarProyecto() {
  return useCambio((id: number) => api.del<void>(`/proyectos/${id}`))
}

/**
 * Lanza el proyecto. `desde` corre solo de esa sección al final.
 *
 * Va por `/flujos` porque un proyecto ES un flujo: así la corrida sale en la cola,
 * se puede detener entre secciones y deja el mismo historial que cualquier otra.
 */
export function useEjecutarProyecto() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, desde }: { id: number; desde?: number }) =>
      api.post<{ trabajo_id: number; estado: string; pasos: number
                 esperando_a: string | null }>(
        `/flujos/${id}/ejecutar${desde && desde > 1 ? `?desde_paso=${desde}` : ''}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clave.lista })
      qc.invalidateQueries({ queryKey: ['flujos'] })
    },
  })
}
