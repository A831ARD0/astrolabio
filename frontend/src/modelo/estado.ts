/**
 * El borrador del modelo y las operaciones que lo cambian.
 *
 * Todo lo que el lienzo hace pasa por aquí, y ninguna operación muta: cada una
 * devuelve una definición nueva. Eso es lo que permite tener un botón de deshacer
 * de verdad y saber con certeza si hay cambios sin guardar — comparar contra la
 * versión cargada, no rastrear banderas a mano.
 *
 * Nada de esto toca el servidor. Guardar es un acto explícito que crea una
 * versión nueva; hasta entonces el modelo publicado sigue intacto.
 */

import type {
  Cardinalidad,
  Campo,
  Definicion,
  DireccionFiltro,
  Entidad,
  Metrica,
  RolCampo,
  TipoEntidad,
} from '../api/tipos'

export type Accion =
  | { t: 'cargar'; definicion: Definicion }
  | { t: 'mover'; entidad: string; x: number; y: number }
  | { t: 'agregar_entidad'; entidad: Entidad }
  | { t: 'quitar_entidad'; nombre: string }
  | { t: 'cambiar_entidad'; nombre: string; cambios: Partial<Entidad> }
  | { t: 'cambiar_campo'; entidad: string; campo: string; cambios: Partial<Campo> }
  | {
      t: 'agregar_relacion'
      desde: [string, string]
      hasta: [string, string]
      cardinalidad: Cardinalidad
    }
  | {
      t: 'cambiar_relacion'
      indice: number
      cambios: {
        cardinalidad?: Cardinalidad
        direccion_filtro?: DireccionFiltro
        // Las columnas unidas también se cambian aquí. Antes había que quitar la
        // relación y volver a arrastrarla sólo por haber acertado la tabla y
        // fallado la columna, que es el error normal cuando no se llaman igual.
        desde?: [string, string]
        hasta?: [string, string]
        activa?: boolean
      }
    }
  | { t: 'quitar_relacion'; indice: number }
  | { t: 'guardar_metrica'; indice: number | null; metrica: Metrica }
  | { t: 'quitar_metrica'; nombre: string }

export interface Estado {
  /** Lo que se cargó del servidor. Es la referencia para saber qué cambió. */
  original: Definicion | null
  borrador: Definicion | null
  historial: Definicion[]
}

export const estadoInicial: Estado = { original: null, borrador: null, historial: [] }

/** Cambios sin guardar, comparando estructura y no banderas. */
export function haCambiado(e: Estado): boolean {
  if (!e.original || !e.borrador) return false
  return JSON.stringify(e.original) !== JSON.stringify(e.borrador)
}

/**
 * Mover un nodo también es un cambio del modelo (la disposición viaja con la
 * versión), pero no debe llenar el historial de deshacer con un paso por píxel.
 */
function esSoloVisual(a: Accion): boolean {
  return a.t === 'mover'
}

export function reducir(estado: Estado, accion: Accion): Estado {
  if (accion.t === 'cargar') {
    return {
      original: accion.definicion,
      borrador: accion.definicion,
      historial: [],
    }
  }
  const d = estado.borrador
  if (!d) return estado

  const siguiente = aplicar(d, accion)
  if (siguiente === d) return estado
  return {
    ...estado,
    borrador: siguiente,
    historial: esSoloVisual(accion)
      ? estado.historial
      : [...estado.historial, d].slice(-50),
  }
}

export function deshacer(estado: Estado): Estado {
  const previo = estado.historial.at(-1)
  if (!previo) return estado
  return { ...estado, borrador: previo, historial: estado.historial.slice(0, -1) }
}

function aplicar(d: Definicion, a: Accion): Definicion {
  switch (a.t) {
    case 'mover':
      return {
        ...d,
        disposicion: { ...d.disposicion, [a.entidad]: { x: a.x, y: a.y } },
      }

    case 'agregar_entidad':
      if (d.entidades.some((e) => e.nombre === a.entidad.nombre)) return d
      return { ...d, entidades: [...d.entidades, a.entidad] }

    case 'quitar_entidad': {
      const { [a.nombre]: _, ...disposicion } = d.disposicion
      return {
        ...d,
        entidades: d.entidades.filter((e) => e.nombre !== a.nombre),
        // Las relaciones y métricas que dependían de ella se van con ella: si
        // se quedaran, el modelo no compilaría y el error aparecería lejos de
        // aquí, en la primera consulta.
        relaciones: d.relaciones.filter(
          (r) => r.desde[0] !== a.nombre && r.hasta[0] !== a.nombre,
        ),
        metricas: d.metricas.filter((m) => m.entidad !== a.nombre),
        disposicion,
      }
    }

    case 'cambiar_entidad':
      return {
        ...d,
        entidades: d.entidades.map((e) =>
          e.nombre === a.nombre ? { ...e, ...a.cambios } : e,
        ),
      }

    case 'cambiar_campo':
      return {
        ...d,
        entidades: d.entidades.map((e) =>
          e.nombre !== a.entidad
            ? e
            : {
                ...e,
                campos: e.campos.map((c) =>
                  c.nombre === a.campo ? { ...c, ...a.cambios } : c,
                ),
              },
        ),
      }

    case 'agregar_relacion': {
      const repetida = d.relaciones.some(
        (r) =>
          (r.desde[0] === a.desde[0] &&
            r.desde[1] === a.desde[1] &&
            r.hasta[0] === a.hasta[0] &&
            r.hasta[1] === a.hasta[1]) ||
          (r.desde[0] === a.hasta[0] &&
            r.desde[1] === a.hasta[1] &&
            r.hasta[0] === a.desde[0] &&
            r.hasta[1] === a.desde[1]),
      )
      if (repetida) return d
      // La segunda relación entre las mismas dos tablas nace INACTIVA. Tres
      // fechas de un hecho contra el calendario son tres relaciones ciertas,
      // pero si las tres estuvieran activas cada consulta tendría tres caminos
      // válidos hacia el calendario y el total dependería de cuál se eligiera.
      // Activarla es un clic; que el modelo se rompa solo, no.
      const yaHayActiva = d.relaciones.some(
        (r) =>
          r.activa !== false &&
          ((r.desde[0] === a.desde[0] && r.hasta[0] === a.hasta[0]) ||
            (r.desde[0] === a.hasta[0] && r.hasta[0] === a.desde[0])),
      )
      return {
        ...d,
        relaciones: [
          ...d.relaciones,
          {
            desde: a.desde,
            hasta: a.hasta,
            cardinalidad: a.cardinalidad,
            direccion_filtro: 'ambas',
            activa: !yaHayActiva,
          },
        ],
      }
    }

    case 'cambiar_relacion':
      return {
        ...d,
        relaciones: d.relaciones.map((r, i) =>
          i === a.indice ? { ...r, ...a.cambios } : r,
        ),
      }

    case 'quitar_relacion':
      return { ...d, relaciones: d.relaciones.filter((_, i) => i !== a.indice) }

    case 'guardar_metrica':
      return {
        ...d,
        metricas:
          a.indice === null
            ? [...d.metricas, a.metrica]
            : d.metricas.map((m, i) => (i === a.indice ? a.metrica : m)),
      }

    case 'quitar_metrica':
      return { ...d, metricas: d.metricas.filter((m) => m.nombre !== a.nombre) }

    default:
      return d
  }
}

// --------------------------------------------------------------------------- //
// Ayudas
// --------------------------------------------------------------------------- //

/**
 * Cardinalidad probable de una relación nueva.
 *
 * Si el campo destino es la clave primaria de su entidad, es muchos-a-uno: el
 * caso normal de un hecho apuntando a una dimensión. Si no lo es, se marca
 * muchos-a-muchos, que el diagnóstico avisará. Suponer muchos-a-uno cuando no
 * consta sería inventar una garantía que nadie verificó, y de ahí salen las
 * cifras infladas.
 */
export function cardinalidadProbable(
  entidades: Entidad[],
  hastaEntidad: string,
  hastaCampo: string,
): Cardinalidad {
  const destino = entidades.find((e) => e.nombre === hastaEntidad)
  if (!destino) return 'muchos_a_muchos'
  if (destino.clave_primaria === hastaCampo) return 'muchos_a_uno'
  const campo = destino.campos.find((c) => c.nombre === hastaCampo)
  return campo?.rol === 'clave' ? 'muchos_a_uno' : 'muchos_a_muchos'
}

/**
 * Preguntar antes de cambiarle la clave primaria a una entidad.
 *
 * Una entidad tiene UNA clave primaria. Declarar otra no es añadir: es sustituir,
 * y las relaciones que apuntaban a la anterior se quedan apuntando a una columna
 * que ya no consta única — así que el aviso que se venía a quitar reaparece en
 * ellas. Hacerlo en silencio desde un botón que dice «declararla clave primaria»
 * sería arreglar una fila rompiendo otras tres.
 *
 * Devuelve `true` si se puede seguir: o no había clave, o ya era esa, o el
 * usuario aceptó el cambio.
 */
export function confirmarClave(
  d: Definicion,
  entidad: string,
  campo: string,
): boolean {
  const actual = d.entidades.find((e) => e.nombre === entidad)?.clave_primaria
  if (!actual || actual === campo) return true
  const afectadas = d.relaciones.filter(
    (r) => r.hasta[0] === entidad && r.hasta[1] === actual,
  ).length
  return window.confirm(
    `${entidad} ya tiene clave primaria: ${actual}. Solo puede haber una, así `
    + `que ${campo} la sustituye.`
    + (afectadas > 0
      ? `\n\nHay ${afectadas} relación(es) que unen contra ${actual} y pasarán a `
        + 'avisar de lo mismo que estás quitando aquí.'
      : '')
    + '\n\n¿Cambiarla?',
  )
}

/**
 * Posiciones para un modelo que todavía no tiene disposición guardada:
 * dimensiones arriba, hechos abajo. No es un algoritmo de grafos, es lo
 * suficiente para que al abrirlo se entienda y se pueda acomodar a mano.
 */
export function disponer(entidades: Entidad[]): Record<string, { x: number; y: number }> {
  const ANCHO = 300
  const salida: Record<string, { x: number; y: number }> = {}
  const porTipo: Record<TipoEntidad, Entidad[]> = {
    dimension: entidades.filter((e) => e.tipo === 'dimension'),
    hecho: entidades.filter((e) => e.tipo === 'hecho'),
  }
  porTipo.dimension.forEach((e, i) => {
    salida[e.nombre] = { x: i * ANCHO, y: 0 }
  })
  porTipo.hecho.forEach((e, i) => {
    salida[e.nombre] = { x: i * ANCHO + 120, y: 420 }
  })
  return salida
}

export const ETIQUETA_ROL: Record<RolCampo, string> = {
  clave: 'clave',
  clave_externa: 'clave ext.',
  dimension: 'dimensión',
  medida_base: 'medida',
}

export const ETIQUETA_CARDINALIDAD: Record<Cardinalidad, string> = {
  muchos_a_uno: 'muchos → uno',
  uno_a_uno: 'uno → uno',
  muchos_a_muchos: 'muchos ↔ muchos',
}
