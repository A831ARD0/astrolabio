/**
 * Los tipos de la definición del modelo, espejo de `semantic/definicion.py`.
 *
 * `[clave: string]: unknown` en las entidades no es pereza: el backend conserva
 * a propósito las claves que no conoce (jerarquías, perspectivas, lo que añada
 * una versión futura). Si aquí se tipara cerrado, la interfaz las borraría al
 * guardar — que es exactamente el problema que esa capa evita.
 */

export type TipoCampo = 'entero' | 'decimal' | 'texto' | 'fecha' | 'booleano'
export type RolCampo = 'clave' | 'clave_externa' | 'dimension' | 'medida_base'
export type Cardinalidad = 'muchos_a_uno' | 'uno_a_uno' | 'muchos_a_muchos'
export type DireccionFiltro = 'ambas' | 'una'
export type TipoEntidad = 'dimension' | 'hecho'

export interface Campo {
  nombre: string
  tipo: TipoCampo
  rol: RolCampo
  etiqueta?: string | null
  visible?: boolean
  pii?: boolean
}

export interface Entidad {
  nombre: string
  tipo: TipoEntidad
  origen: { tabla: string; [clave: string]: unknown }
  campos: Campo[]
  clave_primaria?: string | null
  grano?: string[]
  [clave: string]: unknown
}

export interface Relacion {
  desde: [string, string]
  hasta: [string, string]
  cardinalidad: Cardinalidad
  direccion_filtro: DireccionFiltro
  [clave: string]: unknown
}

export interface Metrica {
  nombre: string
  etiqueta: string
  entidad: string
  expresion: string
  formato?: string
  [clave: string]: unknown
}

export interface Definicion {
  modelo: string
  version: number
  entidades: Entidad[]
  relaciones: Relacion[]
  metricas: Metrica[]
  politicas: Record<string, unknown>[]
  disposicion: Record<string, { x: number; y: number }>
  [clave: string]: unknown
}

export interface Problema {
  tipo: 'ruta_ambigua' | 'tabla_huerfana' | 'muchos_a_muchos'
  gravedad: 'critico' | 'advertencia'
  entidad: string
  mensaje: string
  rutas?: string[]
}

export interface RespuestaDefinicion {
  version: number
  es_vigente: boolean
  definicion: Definicion
  problemas: Problema[]
}

export interface ModeloResumen {
  id: number
  nombre: string
  descripcion: string | null
  version_actual: number
}

export interface VersionResumen {
  version: number
  notas: string | null
  creado_en: string
  entidades: number
  relaciones: number
  metricas: number
}

export interface ColumnaCatalogo {
  nombre: string
  tipo_origen: string
  tipo: TipoCampo
  nulable: boolean
  rol_sugerido: RolCampo
}

export interface TablaCatalogo {
  nombre: string
  clave_primaria: string | null
  columnas: ColumnaCatalogo[]
}

export interface Usuario {
  id: number
  email: string
  nombre: string
  rol: 'administrador' | 'editor' | 'lector'
}

export interface Rutas {
  desde: string
  hasta: string
  agregacion: string[][]
  asociativa: string[][]
  ambigua: boolean
}

// --------------------------------------------------------------------------- //
// Dashboards
// --------------------------------------------------------------------------- //

export type TipoWidget =
  | 'kpi'
  | 'barras'
  | 'barras_horizontales'
  | 'lineas'
  | 'area'
  | 'pastel'
  | 'tabla'
  | 'filtro'
  | 'texto'

export interface Posicion {
  x: number
  y: number
  ancho: number
  alto: number
}

export interface Filtro {
  campo: string
  op: '=' | '!=' | '>' | '>=' | '<' | '<=' | 'LIKE' | 'ILIKE' | 'IN'
  valor: unknown
}

export interface Widget {
  id: string
  tipo: TipoWidget
  titulo: string
  posicion: Posicion
  dimensiones: string[]
  metricas: string[]
  filtros: Filtro[]
  rutas_elegidas: Record<string, string>
  limite: number
  /** Opciones propias del tipo: formato, texto, orden. El backend las conserva. */
  [clave: string]: unknown
}

export interface DefinicionDashboard {
  widgets: Widget[]
  selecciones: Record<string, unknown[]>
  [clave: string]: unknown
}

export interface DashboardResumen {
  id: number
  nombre: string
  modelo_id: number
  modelo_nombre: string
  version_modelo: number
  version_vigente_del_modelo: number
  definicion: DefinicionDashboard
  publicado: boolean
  certificado: boolean
  actualizado_en: string
}

/** Los cuatro estados de Qlik. `alternativo` es el que separa lo real de la imitación. */
export interface Estados {
  seleccionado: unknown[]
  posible: unknown[]
  alternativo: unknown[]
  excluido: unknown[]
}

export interface ResultadoConsulta {
  columnas: string[]
  filas: Record<string, unknown>[]
  ms: number
  politicas_aplicadas: string[]
  sql: string | null
}

export interface CampoCatalogo {
  clave: string
  etiqueta: string
  entidad: string
  tipo?: string
}

export interface MetricaCatalogo {
  clave: string
  etiqueta: string
  entidad: string
  formato: string
}

export interface ResultadoPrueba {
  columnas: string[]
  filas: Record<string, unknown>[]
  ms: number
  sql: string
}
