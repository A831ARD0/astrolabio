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
  Borrador,
  CampoCatalogo,
  DashboardResumen,
  Definicion,
  DefinicionDashboard,
  EnvioEntrada,
  EnvioInforme,
  Filtro,
  FuncionFormula,
  MetricaCatalogo,
  ModeloResumen,
  Problema,
  RespuestaDefinicion,
  ResultadoDatos,
  ResultadoPrueba,
  RevisionFormula,
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
      api.get<{
        version: number
        yaml: string
        /** Si lo devuelto es el borrador sin publicar y no una versión. */
        es_borrador: boolean
        version_vigente: number
      }>(`/modelos/${id}/yaml${version ? `?version=${version}` : ''}`),
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
 * Publicar crea una versión nueva; nunca sobreescribe. Por eso al terminar se
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
// Borrador: guardar sin publicar
//
// Guardar el borrador NO invalida `claves.modelos` —la versión vigente no ha
// cambiado— pero sí escribe el resultado en la caché de la definición, para que
// el aviso de «sin publicar» y la marca de tiempo se actualicen sin ir de nuevo
// al servidor por algo que se acaba de mandar.
// --------------------------------------------------------------------------- //

export function useGuardarBorrador(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { definicion: Definicion }) =>
      api.put<{ problemas: Problema[]; borrador: Borrador; yaml: string }>(
        `/modelos/${id}/borrador`,
        v,
      ),
    onSuccess: (r, v) => {
      qc.setQueryData<RespuestaDefinicion>(claves.definicion(id), (antes) =>
        antes
          ? { ...antes, definicion: v.definicion, problemas: r.problemas,
              borrador: r.borrador }
          : antes,
      )
      qc.invalidateQueries({ queryKey: claves.yaml(id) })
    },
  })
}

/**
 * Reemplaza el borrador con un YAML pegado desde fuera.
 *
 * Mismo destino que guardar el borrador, así que pasa por las mismas
 * validaciones. Va aparte porque no se puede escribir el resultado en la caché
 * como hace `useGuardarBorrador`: lo que se manda es texto, y la definición que
 * salga de ahí la construye el servidor. Se invalida y se vuelve a leer.
 */
export function useImportarYaml(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { yaml: string }) =>
      api.put<{
        problemas: Problema[]
        borrador: Borrador
        yaml: string
        /** Qué se hizo con el texto: reemplazar el borrador o mezclar métricas. */
        importado?: {
          modo: 'reemplazo' | 'mezcla'
          nuevas?: number
          reemplazadas?: number
          intactas?: number
          tablas_medidas?: number
        }
      }>(`/modelos/${id}/borrador`, v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: claves.definicion(id) })
      qc.invalidateQueries({ queryKey: claves.yaml(id) })
    },
  })
}

export function useDescartarBorrador(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.del<{ version: number }>(`/modelos/${id}/borrador`),
    // Sin `setQueryData`: hay que releer lo publicado, que es justo lo que no
    // está en el navegador.
    onSuccess: () => qc.invalidateQueries({ queryKey: ['modelo', id] }),
  })
}

export function usePublicar(id: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { notas?: string }) =>
      api.post<{ version: number; problemas: Problema[] }>(
        `/modelos/${id}/publicar`,
        v,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['modelo', id] })
      qc.invalidateQueries({ queryKey: claves.modelos })
    },
  })
}

export function useBorrarModelo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del<void>(`/modelos/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: claves.modelos }),
  })
}

// --------------------------------------------------------------------------- //
// Fórmulas
// --------------------------------------------------------------------------- //

/**
 * El catálogo de funciones. Es el mismo para todos los modelos y no cambia
 * mientras el servidor no se reinicie, así que se pide una vez y se guarda: lo
 * consume el autocompletado, que dispara con cada tecla.
 */
export function useFunciones() {
  return useQuery({
    queryKey: ['formula', 'funciones'] as const,
    queryFn: () => api.get<{ funciones: FuncionFormula[] }>('/modelos/funciones'),
    staleTime: Infinity,
  })
}

/**
 * Revisa una fórmula sin ejecutarla. Se le mandan los campos y las métricas que
 * hay EN PANTALLA y no los guardados: se está escribiendo sobre un borrador que
 * puede tener una entidad que el servidor todavía no ha visto, y validar contra
 * lo guardado subrayaría en rojo un campo que sí existe.
 */
export function useRevisarFormula(id: number) {
  return useMutation({
    mutationFn: (v: {
      /** `null` = compuesta: se revisa contra las métricas, no contra campos. */
      entidad: string | null
      expresion: string
      campos?: string[]
      metricas?: Record<string, string>
      /** Columnas de todas las entidades del borrador, para las condiciones que
       *  nombran la columna de otra tabla (`DIM_ORIGEN.categoria_canal`). */
      campos_por_entidad?: Record<string, string[]>
      /** Solo si es compuesta: expresión si también lo es, `null` si no. */
      metricas_del_modelo?: Record<string, string | null>
    }) => api.post<RevisionFormula>(`/modelos/${id}/revisar-formula`, v),
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
    mutationFn: (v: {
      nombre?: string
      carpeta?: string
      definicion?: DefinicionDashboard
    }) =>
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
    mutationFn: (v: { nombre: string; carpeta?: string; modelo_id: number }) =>
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
      /** `null` = compuesta. */
      entidad: string | null
      expresion: string
      dimensiones?: string[]
      limite?: number
    }) => api.post<ResultadoPrueba>(`/modelos/${id}/probar-metrica`, v),
  })
}

/**
 * Ejecuta el modelo que se tiene en pantalla, sin guardarlo ni publicarlo.
 *
 * Se manda la `definicion` completa a proposito: lo que hay que ver es el
 * resultado de lo que se acaba de escribir, no el de lo que quedo publicado.
 */
export function useVistaPrevia(id: number) {
  return useMutation({
    mutationFn: (v: {
      definicion?: Definicion
      dimensiones?: string[]
      metricas: string[]
      limite?: number
      /** Filtros por columna. Los aplica el motor, no la pantalla. */
      filtros?: Filtro[]
      /** Columna del resultado por la que ordenar, y sentido. */
      orden?: string | null
      descendente?: boolean
    }) => api.post<ResultadoDatos>(`/modelos/${id}/vista-previa`, v),
  })
}

/** Filas crudas de una entidad, sin agregar. */
/** Comprueba contra los datos que el grano declarado de una entidad se cumpla. */
export function useComprobarGrano(id: number) {
  return useMutation({
    mutationFn: (v: { definicion?: Definicion; entidad: string }) =>
      api.post<{
        entidad: string
        grano: string[]
        filas: number
        combinaciones: number
        repetidas: number
        cumple: boolean
        sql: string
      }>(`/modelos/${id}/comprobar-grano`, v),
  })
}

export function useMuestra(id: number) {
  return useMutation({
    mutationFn: (v: {
      definicion?: Definicion
      entidad: string
      limite?: number
      filtros?: Filtro[]
      orden?: string | null
      descendente?: boolean
    }) => api.post<ResultadoDatos>(`/modelos/${id}/muestra`, v),
  })
}


// --------------------------------------------------------------------------- //
// Envíos de un informe por correo
// --------------------------------------------------------------------------- //

const clavesEnvios = (dashboardId: number) =>
  ['dashboard', dashboardId, 'envios'] as const

export function useEnvios(dashboardId: number, activo = true) {
  return useQuery({
    queryKey: clavesEnvios(dashboardId),
    queryFn: () => api.get<EnvioInforme[]>(`/dashboards/${dashboardId}/envios`),
    enabled: activo && dashboardId > 0,
  })
}

/**
 * Crear, cambiar, borrar y probar, en un solo gancho.
 *
 * Juntos porque las cuatro invalidan lo mismo y siempre se usan desde la misma
 * pantalla: separarlos obligaría a repetir la invalidación cuatro veces, que es
 * justo donde se olvida una y la lista se queda vieja.
 */
export function useAccionEnvio(dashboardId: number) {
  const qc = useQueryClient()
  const refrescar = () =>
    qc.invalidateQueries({ queryKey: clavesEnvios(dashboardId) })
  const base = `/dashboards/${dashboardId}/envios`
  return {
    crear: useMutation({
      mutationFn: (e: EnvioEntrada) => api.post<EnvioInforme>(base, e),
      onSuccess: refrescar,
    }),
    cambiar: useMutation({
      mutationFn: ({ id, ...e }: EnvioEntrada & { id: number }) =>
        api.put<EnvioInforme>(`${base}/${id}`, e),
      onSuccess: refrescar,
    }),
    quitar: useMutation({
      mutationFn: (id: number) => api.del<void>(`${base}/${id}`),
      onSuccess: refrescar,
    }),
    probar: useMutation({
      mutationFn: (id: number) =>
        api.post<{ ms: number; asunto: string; destinatarios: string[] }>(
          `${base}/${id}/probar`,
          {},
        ),
      onSuccess: refrescar,
    }),
  }
}
