/**
 * Conexiones, exploración del origen y datasets.
 *
 * El backend de esta parte existe desde la Fase 1 y estaba completo; lo que no
 * existía era la interfaz, así que las conexiones se creaban llamando a la API a
 * mano. Este archivo es el puente que faltaba.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './cliente'

export interface Conexion {
  id: number
  nombre: string
  tipo: string
  /** Config pública: nunca trae la contraseña. */
  config: Record<string, unknown>
  tiene_credenciales: boolean
  /**
   * Constantes de esta conexión: `{ id_sucursal: 3 }`. Salen como columna al
   * leer cualquiera de sus datasets. No son secretas: son de negocio.
   */
  etiquetas: Record<string, string | number | boolean | null>
}

export interface TablaOrigen {
  esquema: string | null
  nombre: string
  filas_estimadas: number | null
  es_vista: boolean
}

export interface ColumnaOrigen {
  nombre: string
  tipo: string
  nulable: boolean
  es_clave: boolean
}

export interface Dataset {
  id: number
  nombre: string
  tabla_origen: string
  conexion_id: number
  esquema_origen: string | null
  filas: number
  mb: number
  incremental: string | null
  particionado: string | null
  /** null = todas las columnas del origen. */
  columnas: string[] | null
  ventana: string | null
  /** Qué recargaría la ventana hoy, con fechas. */
  ventana_dicha: string | null
  marca_maxima: string | null
  ultima_carga: string | null
  ultimo_estado: string | null
  cron: string | null
  zona_horaria: string
  programacion_activa: boolean
  proxima_corrida: string | null
}

export interface Prueba {
  ok: boolean
  mensaje: string
  detalle?: Record<string, unknown>
}

export const clavesCon = {
  lista: ['conexiones'] as const,
  tipos: ['conexiones', 'tipos'] as const,
  esquemas: (id: number) => ['conexiones', id, 'esquemas'] as const,
  tablas: (id: number, esquema: string | null) =>
    ['conexiones', id, 'tablas', esquema ?? ''] as const,
  tabla: (id: number, esquema: string | null, tabla: string) =>
    ['conexiones', id, 'tabla', esquema ?? '', tabla] as const,
  muestra: (id: number, esquema: string | null, tabla: string) =>
    ['conexiones', id, 'muestra', esquema ?? '', tabla] as const,
  ventanas: ['conexiones', 'ventanas'] as const,
  odbc: ['conexiones', 'odbc'] as const,
  odbcPerfiles: ['conexiones', 'odbc', 'perfiles'] as const,
  datasets: ['datasets'] as const,
  historial: (id: number) => ['datasets', id, 'historial'] as const,
}

// --------------------------------------------------------------------------- //
// Conexiones
// --------------------------------------------------------------------------- //

/** Guarda las etiquetas de varias conexiones de una vez. */
export function useGuardarEtiquetas() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (cambios: { conexion_id: number; etiquetas: Record<string, string | number | boolean | null> }[]) =>
      api.put<{ cambiadas: number }>('/conexiones/etiquetas', { cambios }),
    onSuccess: () => qc.invalidateQueries({ queryKey: clavesCon.lista }),
  })
}

export function useConexiones() {
  return useQuery({
    queryKey: clavesCon.lista,
    queryFn: () => api.get<Conexion[]>('/conexiones'),
  })
}

export function useTiposConexion() {
  return useQuery({
    queryKey: clavesCon.tipos,
    queryFn: () =>
      api.get<{
        tipos: { tipo: string; requeridos: string[]; opcionales: string[] }[]
      }>('/conexiones/tipos'),
    // Los tipos disponibles no cambian mientras la app está abierta.
    staleTime: Infinity,
  })
}

export interface CuerpoConexion {
  nombre: string
  tipo: string
  config: Record<string, unknown>
}

/** Probar antes de guardar: no persiste nada. */
export function useProbarConfig() {
  return useMutation({
    mutationFn: (v: CuerpoConexion) => api.post<Prueba>('/conexiones/probar-config', v),
  })
}

export function useCrearConexion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: CuerpoConexion) => api.post<Conexion>('/conexiones', v),
    onSuccess: () => qc.invalidateQueries({ queryKey: clavesCon.lista }),
  })
}

/**
 * Cambio parcial de una conexión.
 *
 * Un secreto vacío **no** se manda: significa "no lo toqué", y el backend conserva
 * el guardado. Es la única lectura posible cuando la API nunca devuelve la
 * contraseña y el formulario la enseña en blanco.
 */
export interface CambioConexion {
  nombre?: string
  config?: Record<string, unknown>
  /** Para quitar una credencial de verdad hay que nombrarla. */
  borrar_secretos?: string[]
}

/** Probar un cambio con los secretos que ya están guardados. No persiste nada. */
export function useProbarCambio(id: number) {
  return useMutation({
    mutationFn: (v: CambioConexion) =>
      api.post<Prueba>(`/conexiones/${id}/probar-cambio`, v),
  })
}

export function useEditarConexion(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: CambioConexion) => api.patch<Conexion>(`/conexiones/${id}`, v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clavesCon.lista })
      // El nombre de la conexión sale en el panel de datasets.
      qc.invalidateQueries({ queryKey: clavesCon.datasets })
    },
  })
}

export function useProbarConexion(id: number) {
  return useMutation({
    mutationFn: () => api.post<Prueba>(`/conexiones/${id}/probar`),
  })
}

export function useBorrarConexion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del<void>(`/conexiones/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: clavesCon.lista })
      // Los datasets de esa conexión se van con ella (ON DELETE CASCADE).
      qc.invalidateQueries({ queryKey: clavesCon.datasets })
    },
  })
}

// --------------------------------------------------------------------------- //
// Explorar el origen
// --------------------------------------------------------------------------- //

export function useEsquemas(id: number | null) {
  return useQuery({
    queryKey: clavesCon.esquemas(id ?? 0),
    queryFn: () => api.get<{ esquemas: string[] }>(`/conexiones/${id}/esquemas`),
    enabled: !!id,
  })
}

export function useTablasOrigen(id: number | null, esquema: string | null) {
  return useQuery({
    queryKey: clavesCon.tablas(id ?? 0, esquema),
    queryFn: () =>
      api.get<{ tablas: TablaOrigen[] }>(
        `/conexiones/${id}/tablas${esquema ? `?esquema=${encodeURIComponent(esquema)}` : ''}`,
      ),
    enabled: !!id,
  })
}

function sufijoEsquema(esquema: string | null): string {
  return esquema ? `?esquema=${encodeURIComponent(esquema)}` : ''
}

export function useDescribirTabla(
  id: number | null,
  esquema: string | null,
  tabla: string | null,
) {
  return useQuery({
    queryKey: clavesCon.tabla(id ?? 0, esquema, tabla ?? ''),
    queryFn: () =>
      api.get<{
        esquema: string | null
        nombre: string
        filas: number | null
        es_vista: boolean
        columnas: ColumnaOrigen[]
      }>(
        `/conexiones/${id}/tablas/${encodeURIComponent(tabla!)}${sufijoEsquema(esquema)}`,
      ),
    enabled: !!id && !!tabla,
  })
}

/**
 * Muestra de filas. `columnas = null` es todas.
 *
 * Las columnas van en la clave y en la petición: la vista previa tiene que ser una
 * muestra de lo que se va a traer, no de la tabla entera. Si mostrara columnas que
 * se descartaron, la columna de partición se elegiría mirando datos que no van a
 * estar.
 */
export function useMuestra(
  id: number | null,
  esquema: string | null,
  tabla: string | null,
  columnas: string[] | null = null,
) {
  return useQuery({
    queryKey: [...clavesCon.muestra(id ?? 0, esquema, tabla ?? ''), columnas] as const,
    queryFn: () => {
      const q = new URLSearchParams({ limite: '25' })
      if (esquema) q.set('esquema', esquema)
      if (columnas?.length) q.set('columnas', columnas.join(','))
      return api.get<{ columnas: string[]; filas: Record<string, string | null>[] }>(
        `/conexiones/${id}/tablas/${encodeURIComponent(tabla!)}/muestra?${q}`,
      )
    },
    enabled: !!id && !!tabla,
  })
}

export function useVentanas() {
  return useQuery({
    queryKey: clavesCon.ventanas,
    queryFn: () =>
      api.get<{ ventanas: { clave: string; etiqueta: string }[] }>(
        '/conexiones/ventanas',
      ),
    staleTime: Infinity,
  })
}

// --------------------------------------------------------------------------- //
// Datasets
// --------------------------------------------------------------------------- //

export function useDatasets() {
  return useQuery({
    queryKey: clavesCon.datasets,
    queryFn: () => api.get<{ datasets: Dataset[] }>('/conexiones/datasets/lista'),
  })
}

/** Lo que contesta «traer estas tablas desde estas conexiones». */
export interface ResultadoLote {
  creados: { conexion_id: number; conexion: string; tabla: string; id: number; nombre: string }[]
  omitidos: { conexion_id: number; conexion: string; tabla: string; nombre: string; motivo: string }[]
  fallidos: { conexion_id: number; conexion: string; tabla: string; motivo: string }[]
}

/**
 * Crea un dataset por cada (conexión, tabla) y NO se detiene en el primero que
 * falla: con cuarenta sucursales siempre hay alguna apagada. Lo que salió mal
 * viene en `fallidos`, con su motivo.
 */
export function useTraerEnLote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: {
      conexiones: number[]
      tablas: { esquema?: string | null; tabla: string }[]
    }) => api.post<ResultadoLote>('/conexiones/datasets/en-lote', v),
    onSuccess: () => qc.invalidateQueries({ queryKey: clavesCon.datasets }),
  })
}

export function useCrearDataset(conexionId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: {
      nombre: string
      esquema?: string | null
      tabla: string
      columna_incremental?: string | null
      particionar_por?: string | null
      /** null = todas. Ver la nota en `Dataset.columnas` del backend. */
      columnas?: string[] | null
      ventana?: string | null
    }) => api.post<{ id: number; nombre: string; ventana: string | null }>(
      `/conexiones/${conexionId}/datasets`, v),
    onSuccess: () => qc.invalidateQueries({ queryKey: clavesCon.datasets }),
  })
}

export interface CambioDataset {
  /** `[]` vuelve a todas las columnas; `undefined` no toca nada. */
  columnas?: string[]
  /** `''` quita la ventana. */
  ventana?: string
  columna_incremental?: string
  particionar_por?: string
}

export function useEditarDataset(datasetId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: CambioDataset) =>
      api.patch<{
        id: number
        columnas: string[] | null
        ventana: string | null
        ventana_dicha: string | null
        avisos: string[]
      }>(`/conexiones/datasets/${datasetId}`, v),
    onSuccess: () => qc.invalidateQueries({ queryKey: clavesCon.datasets }),
  })
}

export function useOdbcInstalado(activo: boolean) {
  return useQuery({
    queryKey: clavesCon.odbc,
    queryFn: () =>
      api.get<{
        disponible: boolean
        drivers: string[]
        dsn: string[]
        // El puente de 32 bits ve OTROS drivers y OTROS DSN: en Windows, 32 y 64
        // bits son dos registros separados. Por eso vienen aparte y no mezclados.
        puente: {
          activo: boolean
          url?: string
          bits?: number
          motivo?: string
          drivers: string[]
          dsn: string[]
        }
        aviso: string | null
      }>('/conexiones/odbc/instalado'),
    enabled: activo,
    staleTime: Infinity,
  })
}

/** Un campo que pide un perfil ODBC. Las etiquetas las manda el servidor. */
export interface CampoPerfil {
  clave: string
  etiqueta: string
  requerido?: boolean
  pista?: string
  secreto?: boolean
  defecto?: string
}

export interface PerfilOdbc {
  clave: string
  nombre: string
  /** Sin plantilla = DSN o cadena a mano: no hay que armar nada. */
  plantilla?: string
  campos: CampoPerfil[]
  notas: string[]
  /** De dónde sale el driver cuando no está instalado. */
  driver?: { de_donde: string; quien: string }
  drivers_detectados: string[]
  driver_detectado: string | null
  instalado: boolean
}

/**
 * El catálogo de orígenes ODBC con los drivers de este servidor ya cruzados.
 *
 * Es lo más cercano a la descarga automática de drivers de DBeaver que se puede
 * hacer con ODBC: DBeaver baja .jar de JDBC, y un driver ODBC es una librería
 * nativa del sistema. Lo que sí se puede es armar la cadena por origen y decir
 * qué falta y de dónde sale.
 */
export function useOdbcPerfiles(activo: boolean) {
  return useQuery({
    queryKey: clavesCon.odbcPerfiles,
    queryFn: () =>
      api.get<{ disponible: boolean; drivers: string[]; perfiles: PerfilOdbc[] }>(
        '/conexiones/odbc/perfiles',
      ),
    enabled: activo,
    staleTime: Infinity,
  })
}

export interface ResultadoCarga {
  estado: string
  modo: string
  disparo: string
  filas: number
  mb: number
  ms: number
  archivos: number
  marca_maxima: string | null
  filas_totales: number
  filas_sin_particion: number
  particiones: string[]
}

export function useAccionesDataset(id: number | null) {
  const qc = useQueryClient()
  const tras = () => {
    qc.invalidateQueries({ queryKey: clavesCon.datasets })
    qc.invalidateQueries({ queryKey: clavesCon.historial(id ?? 0) })
    // Una carga cambia lo que hay en el motor analítico.
    qc.invalidateQueries({ queryKey: ['catalogo'] })
  }
  return {
    cargar: useMutation({
      mutationFn: (v: { incremental: boolean; limite?: number }) =>
        api.post<ResultadoCarga>(
          `/conexiones/datasets/${id}/cargar?incremental=${v.incremental}` +
            (v.limite ? `&limite=${v.limite}` : ''),
        ),
      onSettled: tras,
    }),
    recargarRango: useMutation({
      mutationFn: (v: { desde: string; hasta: string }) =>
        api.post<ResultadoCarga>(`/conexiones/datasets/${id}/recargar-rango`, v),
      onSettled: tras,
    }),
    programar: useMutation({
      mutationFn: (v: { cron: string; zona_horaria: string; activa: boolean }) =>
        api.put<{ cron: string; proxima: string | null }>(
          `/conexiones/datasets/${id}/programacion`,
          v,
        ),
      onSuccess: tras,
    }),
    quitarHorario: useMutation({
      mutationFn: () => api.del<void>(`/conexiones/datasets/${id}/programacion`),
      onSuccess: tras,
    }),
    borrar: useMutation({
      mutationFn: () =>
        api.del<{ nombre: string; parquet_conservado: string; aviso: string }>(
          `/conexiones/datasets/${id}`,
        ),
      onSuccess: tras,
    }),
  }
}

export interface EjecucionCarga {
  id: number
  estado: string
  modo: string
  disparo: string
  filas: number
  ms: number
  mensaje: string | null
  detalle: Record<string, unknown>
  cuando: string
}

export function useHistorialDataset(id: number | null) {
  return useQuery({
    queryKey: clavesCon.historial(id ?? 0),
    queryFn: () =>
      api.get<{ ejecuciones: EjecucionCarga[] }>(
        `/conexiones/datasets/${id}/historial`,
      ),
    enabled: !!id,
  })
}
