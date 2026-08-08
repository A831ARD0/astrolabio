/**
 * Consultas al backend con TanStack Query.
 *
 * Todas las claves de caché viven aquí, en un solo sitio, para que invalidar
 * después de guardar no dependa de recordar cómo se escribió la clave en otro
 * archivo.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './cliente'
import type {
  CampoCatalogo,
  DashboardResumen,
  Definicion,
  DefinicionDashboard,
  MetricaCatalogo,
  ModeloResumen,
  RespuestaDefinicion,
  ResultadoPrueba,
  Rutas,
  TablaCatalogo,
  TablaResumen,
  Usuario,
  VersionResumen,
} from './tipos'

export const claves = {
  yo: ['yo'] as const,
  modelos: ['modelos'] as const,
  definicion: (id: number, version?: number) =>
    ['modelo', id, 'definicion', version ?? 'vigente'] as const,
  versiones: (id: number) => ['modelo', id, 'versiones'] as const,
  yaml: (id: number, version?: number) =>
    ['modelo', id, 'yaml', version ?? 'vigente'] as const,
  tablas: ['catalogo', 'tablas'] as const,
  tabla: (nombre: string) => ['catalogo', 'tabla', nombre] as const,
  rutas: (id: number, desde: string, hasta: string) =>
    ['modelo', id, 'rutas', desde, hasta] as const,
}

export const clavesDash = {
  lista: ['dashboards'] as const,
  uno: (id: number) => ['dashboard', id] as const,
}

export function useYo() {
  return useQuery({
    queryKey: claves.yo,
    queryFn: () => api.get<Usuario>('/auth/yo'),
    retry: false,
  })
}

export function useModelos() {
  return useQuery({
    queryKey: claves.modelos,
    queryFn: () => api.get<ModeloResumen[]>('/modelos'),
  })
}

export function useDefinicion(id: number, version?: number) {
  return useQuery({
    queryKey: claves.definicion(id, version),
    queryFn: () =>
      api.get<RespuestaDefinicion>(
        `/modelos/${id}/definicion${version ? `?version=${version}` : ''}`,
      ),
  })
}

export function useVersiones(id: number) {
  return useQuery({
    queryKey: claves.versiones(id),
    queryFn: () =>
      api.get<{ versiones: VersionResumen[] }>(`/modelos/${id}/versiones`),
  })
}

export function useYaml(id: number, version?: number) {
  return useQuery({
    queryKey: claves.yaml(id, version),
    queryFn: () =>
      api.get<{ version: number; yaml: string }>(
        `/modelos/${id}/yaml${version ? `?version=${version}` : ''}`,
      ),
  })
}

export function useTablas() {
  return useQuery({
    queryKey: claves.tablas,
    queryFn: () => api.get<{ tablas: TablaResumen[] }>('/catalogo/tablas'),
  })
}

/**
 * Crear un modelo. Lleva su primera entidad dentro: un modelo sin ninguna no se
 * puede guardar, así que pedir el nombre y la primera tabla en el mismo paso es lo
 * único que no deja a medias.
 */
export function useCrearModelo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: {
      nombre: string
      descripcion?: string | null
      definicion: Partial<Definicion>
    }) => api.post<ModeloResumen>('/modelos', v),
    onSuccess: () => qc.invalidateQueries({ queryKey: claves.modelos }),
  })
}

export function useTabla(nombre: string | null) {
  return useQuery({
    queryKey: claves.tabla(nombre ?? ''),
    queryFn: () => api.get<TablaCatalogo>(`/catalogo/tablas/${nombre}`),
    enabled: !!nombre,
  })
}

export function useRutas(id: number, desde: string | null, hasta: string | null) {
  return useQuery({
    queryKey: claves.rutas(id, desde ?? '', hasta ?? ''),
    queryFn: () =>
      api.get<Rutas>(`/modelos/${id}/rutas?desde=${desde}&hasta=${hasta}`),
    enabled: !!desde && !!hasta,
  })
}

/**
 * Guardar crea una versión nueva; nunca sobreescribe. Por eso al terminar se
 * invalida también el historial: la lista de versiones acaba de cambiar.
 */
export function useGuardarDefinicion(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { definicion: Definicion; notas?: string }) =>
      api.put<{ version: number; problemas: unknown[]; yaml: string }>(
        `/modelos/${id}/definicion`,
        v,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['modelo', id] })
      qc.invalidateQueries({ queryKey: claves.modelos })
    },
  })
}

// --------------------------------------------------------------------------- //
// Dashboards
// --------------------------------------------------------------------------- //

export function useDashboards() {
  return useQuery({
    queryKey: clavesDash.lista,
    queryFn: () => api.get<DashboardResumen[]>('/dashboards'),
  })
}

export function useDashboard(id: number) {
  return useQuery({
    queryKey: clavesDash.uno(id),
    queryFn: () => api.get<DashboardResumen>(`/dashboards/${id}`),
  })
}

export function useCampos(modeloId: number, version?: number) {
  return useQuery({
    queryKey: ['modelo', modeloId, 'campos', version ?? 'vigente'] as const,
    queryFn: () =>
      api.get<{
        version: number
        dimensiones: CampoCatalogo[]
        metricas: MetricaCatalogo[]
      }>(`/modelos/${modeloId}/campos`),
    enabled: modeloId > 0,
  })
}

export function useGuardarDashboard(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { nombre?: string; definicion?: DefinicionDashboard }) =>
      api.put<DashboardResumen>(`/dashboards/${id}`, v),
    onSuccess: (d) => {
      qc.setQueryData(clavesDash.uno(id), d)
      qc.invalidateQueries({ queryKey: clavesDash.lista })
    },
  })
}

export function useCrearDashboard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { nombre: string; modelo_id: number }) =>
      api.post<DashboardResumen>('/dashboards', v),
    onSuccess: () => qc.invalidateQueries({ queryKey: clavesDash.lista }),
  })
}

export function useAccionDashboard(id: number) {
  const qc = useQueryClient()
  const tras = (d: DashboardResumen) => {
    qc.setQueryData(clavesDash.uno(id), d)
    qc.invalidateQueries({ queryKey: clavesDash.lista })
  }
  return {
    publicar: useMutation({
      mutationFn: (publicado: boolean) =>
        api.post<DashboardResumen>(`/dashboards/${id}/publicar?publicado=${publicado}`),
      onSuccess: tras,
    }),
    certificar: useMutation({
      mutationFn: (certificado: boolean) =>
        api.post<DashboardResumen>(
          `/dashboards/${id}/certificar?certificado=${certificado}`,
        ),
      onSuccess: tras,
    }),
    moverAVersion: useMutation({
      mutationFn: (version: number) =>
        api.post<DashboardResumen>(`/dashboards/${id}/mover-a-version?version=${version}`),
      onSuccess: tras,
    }),
    borrar: useMutation({
      mutationFn: () => api.del<void>(`/dashboards/${id}`),
      onSuccess: () => qc.invalidateQueries({ queryKey: clavesDash.lista }),
    }),
  }
}

export function useProbarMetrica(id: number) {
  return useMutation({
    mutationFn: (v: {
      entidad: string
      expresion: string
      dimensiones?: string[]
      limite?: number
    }) => api.post<ResultadoPrueba>(`/modelos/${id}/probar-metrica`, v),
  })
}
