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
  /**
   * No se repite, aunque no sea la clave primaria.
   *
   * Una entidad tiene UNA clave primaria, pero un catálogo suele traer varios
   * identificadores que tampoco se repiten —el propio, el del sistema de origen,
   * el del CRM— y cada uno es por donde se une un hecho distinto. Lo que una
   * relación muchos-a-uno necesita del lado «uno» no es ser la clave primaria:
   * es no repetirse.
   */
  unico?: boolean
  /**
   * Qué periodo nombra esta columna, si nombra alguno.
   *
   * Es lo que permite escribir «el mes anterior». `Periodo_YYYYMM` nombra un mes
   * concreto; `Mes`, de 1 a 12, se repite cada año y correrla un mes hacia atrás
   * no significa nada — por eso se marca una y no la otra.
   */
  grano_tiempo?: 'dia' | 'mes' | 'trimestre' | 'anio' | null
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
  /**
   * Solo la activa se usa al agregar. Dos tablas pueden relacionarse por varias
   * columnas —tres fechas contra el calendario— y las tres se dejan escritas,
   * pero mandando una sola: con dos, cada consulta tendría dos caminos válidos.
   */
  activa?: boolean
  [clave: string]: unknown
}

/**
 * Un cajón con nombre para guardar métricas, sin datos propios.
 *
 * No es una entidad y no puede serlo: una entidad tiene tabla, columnas y
 * relaciones, y sale en el diagnóstico como huérfana si no se une a nada. Esto es
 * la «tabla de medidas» de Power BI, y como allí **solo organiza**: de dónde salen
 * las cifras lo sigue diciendo el hecho de cada métrica.
 */
export interface TablaMedidas {
  nombre: string
  descripcion?: string | null
  [clave: string]: unknown
}

export interface Metrica {
  nombre: string
  etiqueta: string
  /**
   * El hecho del que se calcula: es lo que decide el FROM del SQL.
   *
   * `null` la marca como **compuesta**: no sale de ninguna tabla, sino de
   * combinar otras métricas —`DIVIDIR([Unidades], [Objetivo])`—, y se calcula
   * después de que cada hecho agregó lo suyo.
   */
  entidad: string | null
  /** En qué tabla de medidas se muestra. Ausente = debajo de su propio hecho. */
  tabla_medidas?: string | null
  expresion: string
  formato?: string
  /**
   * Relaciones que esta métrica usa en vez de la activa, como
   * `"entidad.campo -> entidad.campo"`.
   *
   * Un hecho toca el calendario por más de una fecha más a menudo de lo que
   * parece. Sólo una puede estar activa; las demás se dejan dibujadas e
   * inactivas y la métrica dice cuál es la suya.
   */
  uniones?: string[]
  [clave: string]: unknown
}

export interface Definicion {
  modelo: string
  version: number
  entidades: Entidad[]
  /** Puede no venir: los modelos guardados antes de que esto existiera no la traen. */
  tablas_medidas?: TablaMedidas[]
  relaciones: Relacion[]
  metricas: Metrica[]
  politicas: Record<string, unknown>[]
  disposicion: Record<string, { x: number; y: number }>
  [clave: string]: unknown
}

export interface Problema {
  tipo: 'ruta_ambigua' | 'tabla_huerfana' | 'muchos_a_muchos' | 'formula'
  gravedad: 'critico' | 'advertencia' | 'informativo'
  entidad: string
  mensaje: string
  rutas?: string[]
}

/** Quién tiene trabajo a medias sobre el modelo, y desde cuándo. */
export interface Borrador {
  desde_version: number
  actualizado_en: string
  actualizado_por: string | null
}

export interface RespuestaDefinicion {
  /** La del borrador si lo hay; si no, la vigente o la que se pidió. */
  version: number
  es_vigente: boolean
  definicion: Definicion
  problemas: Problema[]
  /** null = no hay nada sin publicar. */
  borrador: Borrador | null
  version_vigente: number
}

/** Una función del lenguaje de fórmulas, tal como la ofrece el editor. */
export interface FuncionFormula {
  nombre: string
  firma: string
  categoria: 'agregacion' | 'condicion' | 'matematica' | 'texto' | 'fecha'
  resumen: string
  ejemplo: string
  agrega: boolean
  minimo: number
  maximo: number | null
}

/** Un problema de una fórmula, con dónde está para poder subrayarlo. */
export interface FalloFormula {
  mensaje: string
  linea: number
  columna: number
  largo: number
  gravedad: 'error' | 'advertencia'
}

export interface RevisionFormula {
  fallos: FalloFormula[]
  hay_errores: boolean
  sql: string | null
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

/**
 * De dónde sale una tabla: del archivo analítico, de una carga, o de una
 * transformación. Para el modelo son lo mismo —un nombre con columnas—; para quien
 * lo arma, no.
 */
export type OrigenTabla = 'motor' | 'carga' | 'resultado'

export interface TablaResumen {
  nombre: string
  filas: number
  origen: OrigenTabla
}

export interface TablaCatalogo {
  nombre: string
  origen: OrigenTabla
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
  | 'tabla_dinamica'
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
  /** A qué hoja pertenece. `''` = la primera, para lo guardado antes de las hojas. */
  hoja: string
  dimensiones: string[]
  metricas: string[]
  filtros: Filtro[]
  rutas_elegidas: Record<string, string>
  limite: number
  /** Opciones propias del tipo: formato, texto, orden. El backend las conserva. */
  [clave: string]: unknown
}

/** El tamaño del espacio de trabajo de una hoja. */
export interface Lienzo {
  /** `pantalla`: la hoja entera se ve sin desplazar. `libre`: se desplaza. */
  modo: 'pantalla' | 'libre'
  columnas: number
  filas: number
}

export interface Hoja {
  id: string
  nombre: string
  lienzo: Lienzo
}

export interface DefinicionDashboard {
  widgets: Widget[]
  /** Vacío = una sola hoja implícita. Un tablero es un libro de hojas. */
  hojas: Hoja[]
  selecciones: Record<string, unknown[]>
  [clave: string]: unknown
}

export interface DashboardResumen {
  id: number
  nombre: string
  /** Carpeta del estante. Vacía = sin carpeta. **Solo ordena**: no da ni quita acceso. */
  carpeta: string
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

/** Lo que devuelven `vista-previa` y `muestra`: la misma tabla, distinto origen. */
export interface ResultadoDatos extends ResultadoPrueba {
  politicas_aplicadas: string[]
  /** Solo la muestra: columnas marcadas como datos personales. */
  pii?: string[]
}
