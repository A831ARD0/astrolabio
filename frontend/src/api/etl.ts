/**
 * Tipos y consultas del ETL. Espejo de `semantic/transformacion.py`.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './cliente'

export type TipoPaso =
  | 'filtrar'
  | 'columnas'
  | 'renombrar'
  | 'derivar'
  | 'agrupar'
  | 'unir'
  | 'apilar'
  | 'ordenar'
  | 'limitar'
  | 'distintos'

export const OPERADORES = [
  '=', '!=', '>', '>=', '<', '<=',
  'contiene', 'empieza_con', 'termina_con', 'en', 'no_en',
  'es_nulo', 'no_es_nulo',
] as const

export const SIN_VALOR = new Set(['es_nulo', 'no_es_nulo'])
export const DE_LISTA = new Set(['en', 'no_en'])

export const FUNCIONES = [
  'suma', 'promedio', 'minimo', 'maximo', 'cuenta', 'cuenta_distintos',
] as const

export interface Condicion {
  campo: string
  op: string
  valor?: unknown
}

export interface Agregado {
  nombre: string
  funcion: string
  campo?: string | null
}

/** Un paso. Los campos que sobran para su tipo simplemente no se usan. */
export interface Paso {
  tipo: TipoPaso
  // filtrar
  condiciones?: Condicion[]
  modo?: 'y' | 'o'
  // columnas
  mantener?: string[]
  quitar?: string[]
  // renombrar
  cambios?: Record<string, string>
  // derivar
  nombre?: string
  expresion?: string
  // agrupar
  por?: string[]
  agregados?: Agregado[]
  // unir / apilar
  con?: string | string[]
  como?: 'interna' | 'izquierda' | 'derecha' | 'completa'
  en?: [string, string][]
  traer?: string[]
  renombres?: Record<string, string>
  quitar_repetidas?: boolean
  // ordenar
  descendente?: boolean
  // limitar
  n?: number
  [clave: string]: unknown
}

export interface Origen {
  nombre: string
  tipo: 'tabla' | 'dataset' | 'tabla_en_conexiones'
  referencia: string
}

export interface DefinicionTransformacion {
  nombre: string
  descripcion?: string | null
  origenes: Origen[]
  pasos: Paso[]
  sql?: string | null
}

export interface TransformacionResumen {
  id: number
  nombre: string
  descripcion: string | null
  definicion: DefinicionTransformacion
  lee_de: { tablas?: string[]; datasets?: string[]; transformaciones?: string[] }
  filas: number
  mb: number
  ultima_ejecucion: string | null
  ultimo_estado: string | null
  tiene_datos: boolean
}

export interface Previa {
  columnas: string[]
  filas: Record<string, string | null>[]
  ms: number
  sql: string
  conteos: { paso: string; filas: number }[]
}

export interface Conversion {
  convertible: boolean
  origenes: Origen[]
  pasos: Paso[]
  no_representable: string[]
}

const clave = {
  lista: ['transformaciones'] as const,
  origenes: ['transformaciones', 'origenes'] as const,
  columnas: (tipo: string, ref: string) =>
    ['transformaciones', 'columnas', tipo, ref] as const,
  historial: (id: number) => ['transformaciones', id, 'historial'] as const,
}

export function useTransformaciones() {
  return useQuery({
    queryKey: clave.lista,
    queryFn: () => api.get<TransformacionResumen[]>('/transformaciones'),
  })
}

export function useOrigenesDisponibles() {
  return useQuery({
    queryKey: clave.origenes,
    queryFn: () =>
      api.get<{
        tablas: { nombre: string; filas: number }[]
        datasets: { nombre: string; filas: number; tiene_datos: boolean
                    usable: boolean }[]
        transformaciones: { nombre: string; filas: number; tiene_datos: boolean
                            usable: boolean }[]
        /** La misma tabla del origen traída por varias conexiones. */
        en_varias_conexiones: { tabla: string; conexiones: number; cargados: number }[]
        /** Lo que no se pudo leer, y por qué. Un bloque roto no tumba los demás. */
        avisos: string[]
      }>('/transformaciones/origenes'),
  })
}

export function useColumnasOrigen(origen: Origen | null) {
  return useQuery({
    queryKey: clave.columnas(origen?.tipo ?? '', origen?.referencia ?? ''),
    queryFn: () =>
      api.get<{ columnas: { nombre: string; tipo: string }[] }>(
        `/transformaciones/columnas?tipo=${origen!.tipo}&referencia=${encodeURIComponent(origen!.referencia)}`,
      ),
    enabled: !!origen,
  })
}

export function usePrevisualizar() {
  return useMutation({
    mutationFn: (definicion: DefinicionTransformacion) =>
      api.post<Previa>('/transformaciones/previsualizar', { definicion }),
  })
}

export function useGuardarTransformacion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, definicion }: { id: number | null; definicion: DefinicionTransformacion }) =>
      id === null
        ? api.post<TransformacionResumen>('/transformaciones', { definicion })
        : api.put<TransformacionResumen>(`/transformaciones/${id}`, { definicion }),
    onSuccess: () => qc.invalidateQueries({ queryKey: clave.lista }),
  })
}

export function useEjecutarTransformacion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api.post<{
        filas: number
        columnas: string[]
        mb: number
        ms: number
      }>(`/transformaciones/${id}/ejecutar`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clave.lista })
      qc.invalidateQueries({ queryKey: clave.origenes })
    },
  })
}

export function useHistorialTransformacion(id: number | null) {
  return useQuery({
    queryKey: clave.historial(id ?? 0),
    queryFn: () =>
      api.get<{
        ejecuciones: {
          id: number
          estado: string
          filas: number
          ms: number
          mensaje: string | null
          cuando: string
        }[]
      }>(`/transformaciones/${id}/historial`),
    enabled: !!id,
  })
}

export function useDesdeSql() {
  return useMutation({
    mutationFn: (sql: string) =>
      api.post<Conversion>('/transformaciones/desde-sql', { sql }),
  })
}

export const ETIQUETA_PASO: Record<TipoPaso, string> = {
  filtrar: 'Filtrar filas',
  columnas: 'Elegir columnas',
  renombrar: 'Renombrar',
  derivar: 'Columna calculada',
  agrupar: 'Agrupar y resumir',
  unir: 'Unir con otro origen',
  apilar: 'Apilar filas',
  ordenar: 'Ordenar',
  limitar: 'Limitar filas',
  distintos: 'Quitar repetidas',
}
