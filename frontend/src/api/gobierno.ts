/**
 * Gobierno: usuarios, políticas de seguridad por fila, simulador y auditoría.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './cliente'

// --------------------------------------------------------------------------- //
// Usuarios
// --------------------------------------------------------------------------- //

export type RolUsuario = 'administrador' | 'editor' | 'lector'

export interface UsuarioCompleto {
  id: number
  email: string
  nombre: string
  rol: RolUsuario
  activo: boolean
  atributos: Record<string, string>
  ultimo_ingreso: string | null
  creado_en: string | null
}

const clave = {
  usuarios: ['usuarios'] as const,
  politicas: (modeloId: number) => ['politicas', modeloId] as const,
  auditoria: (f: FiltroAuditoria) => ['auditoria', f] as const,
  resumen: ['auditoria', 'resumen'] as const,
}

export function useUsuarios() {
  return useQuery({
    queryKey: clave.usuarios,
    queryFn: () => api.get<UsuarioCompleto[]>('/auth/usuarios'),
  })
}

export function useCrearUsuario() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: {
      email: string
      nombre: string
      contrasena: string
      rol: RolUsuario
      atributos: Record<string, string>
    }) => api.post<UsuarioCompleto>('/auth/usuarios', v),
    onSuccess: () => qc.invalidateQueries({ queryKey: clave.usuarios }),
  })
}

export function useEditarUsuario() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...cambios
    }: {
      id: number
      nombre?: string
      rol?: RolUsuario
      activo?: boolean
      atributos?: Record<string, string>
    }) => api.patch<UsuarioCompleto>(`/auth/usuarios/${id}`, cambios),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clave.usuarios })
      // Cambiar un atributo cambia qué ve esa persona: la cobertura de las
      // políticas y el simulador dejan de ser válidos.
      qc.invalidateQueries({ queryKey: ['politicas'] })
    },
  })
}

export function useRestablecerContrasena() {
  return useMutation({
    mutationFn: ({ id, nueva }: { id: number; nueva: string }) =>
      api.post<void>(`/auth/usuarios/${id}/contrasena`, { nueva }),
  })
}

export function useCambiarMiContrasena() {
  return useMutation({
    mutationFn: (v: { actual: string; nueva: string }) =>
      api.post<void>('/auth/cambiar-contrasena', v),
  })
}

// --------------------------------------------------------------------------- //
// Políticas
// --------------------------------------------------------------------------- //

export interface Politica {
  nombre: string
  entidad: string
  predicado: string
  aplica_a_roles: string[]
  descripcion?: string | null
}

export interface Cobertura {
  politica: string
  atributos: string[]
  usuarios_alcanzados: string[]
  sin_atributo: { email: string; faltan: string[] }[]
}

export interface RespuestaPoliticas {
  version: number
  politicas: Politica[]
  errores: string[]
  avisos: string[]
  cobertura: Cobertura[]
  entidades: { nombre: string; tipo: string; campos: string[] }[]
  roles: string[]
}

export function usePoliticas(modeloId: number) {
  return useQuery({
    queryKey: clave.politicas(modeloId),
    queryFn: () => api.get<RespuestaPoliticas>(`/modelos/${modeloId}/politicas`),
    enabled: modeloId > 0,
  })
}

export function useGuardarPoliticas(modeloId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { politicas: Politica[]; notas?: string }) =>
      api.put<{ version: number; avisos: string[]; cobertura: Cobertura[] }>(
        `/modelos/${modeloId}/politicas`,
        v,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clave.politicas(modeloId) })
      // Guardar crea una versión nueva del modelo: el resto de la app la ve.
      qc.invalidateQueries({ queryKey: ['modelo', modeloId] })
      qc.invalidateQueries({ queryKey: ['modelos'] })
    },
  })
}

// --------------------------------------------------------------------------- //
// Simulador
// --------------------------------------------------------------------------- //

export interface EntidadSimulada {
  politica: string
  entidad: string
  predicado: string
  valores: string[]
  filas_totales: number
  filas_visibles: number
  campo_muestra: string | null
  muestra: (string | number | null)[]
  hay_mas: boolean
}

export interface Simulacion {
  version: number
  rol: string
  email: string
  atributos: Record<string, string>
  es_administrador: boolean
  aplicadas: { politica: string; entidad: string; predicado: string; valores: string[] }[]
  omitidas: { nombre: string; motivo: string }[]
  error: string | null
  entidades: EntidadSimulada[]
  consulta: {
    columnas: string[]
    filas: Record<string, unknown>[]
    filas_sin_politicas: Record<string, unknown>[]
    cuenta: number
    cuenta_sin_politicas: number
    ms: number
    sql: string
  } | null
}

export function useSimular() {
  return useMutation({
    mutationFn: (v: {
      modelo_id: number
      usuario_id?: number
      rol?: string
      atributos?: Record<string, string>
      consulta?: { dimensiones: string[]; metricas: string[] }
    }) => api.post<Simulacion>('/gobierno/simular', v),
  })
}

// --------------------------------------------------------------------------- //
// Auditoría
// --------------------------------------------------------------------------- //

export interface FiltroAuditoria {
  accion?: string
  email?: string
  objeto_tipo?: string
  dias?: number
  pagina: number
}

export interface Evento {
  id: number
  cuando: string
  email: string | null
  usuario_id: number | null
  accion: string
  objeto_tipo: string | null
  objeto_id: string | null
  detalle: Record<string, unknown>
}

export function useAuditoria(f: FiltroAuditoria) {
  const q = new URLSearchParams({ pagina: String(f.pagina), por_pagina: '50' })
  if (f.accion) q.set('accion', f.accion)
  if (f.email) q.set('email', f.email)
  if (f.objeto_tipo) q.set('objeto_tipo', f.objeto_tipo)
  if (f.dias) q.set('dias', String(f.dias))
  return useQuery({
    queryKey: clave.auditoria(f),
    queryFn: () =>
      api.get<{
        total: number
        pagina: number
        por_pagina: number
        eventos: Evento[]
      }>(`/gobierno/auditoria?${q}`),
  })
}

export function useResumenAuditoria() {
  return useQuery({
    queryKey: clave.resumen,
    queryFn: () =>
      api.get<{
        dias: number
        acciones: { accion: string; veces: number }[]
        personas: { email: string; veces: number }[]
        objetos: string[]
        ingresos_fallidos: number
      }>('/gobierno/auditoria/resumen'),
  })
}
