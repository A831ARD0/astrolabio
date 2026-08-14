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
} from '../api/tipos'

export type Accion =
  | { t: 'cargar'; definicion: Definicion }
  | { t: 'mover'; entidad: string; x: number; y: number }
  | { t: 'agregar_entidad'; entidad: Entidad }
  | { t: 'quitar_entidad'; nombre: string }
  | { t: 'cambiar_entidad'; nombre: string; cambios: Partial<Entidad> }
  | { t: 'cambiar_campo'; entidad: string; campo: string; cambios: Partial<Campo> }
  | { t: 'renombrar_campo'; entidad: string; antes: string; despues: string }
  | { t: 'quitar_campos'; entidad: string; campos: string[] }
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
  | { t: 'reorganizar'; disposicion: Record<string, { x: number; y: number }> }
  | { t: 'agregar_tabla_medidas'; nombre: string }
  | { t: 'renombrar_tabla_medidas'; antes: string; despues: string }
  | { t: 'quitar_tabla_medidas'; nombre: string }

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

    /*
     * Renombrar una columna en la transformación y que el modelo lo siga.
     *
     * Es el caso que destapó el defecto: se renombra una columna a `id_sucursal` en la
     * transformación, el modelo avisa de que una columna «ya no está» y no había
     * ninguna forma de decirle que es la misma con otro nombre. Pulsar «actualizar»
     * añadía la nueva y dejaba la vieja, así que el aviso no se iba nunca y el botón
     * parecía roto.
     *
     * La referencia a una columna va por su nombre en cuatro sitios estructurados, y
     * los cuatro se arrastran aquí: el campo, la clave primaria, el grano y las
     * relaciones. Lo que NO se toca son las fórmulas de las métricas: ahí el nombre
     * es texto dentro de un lenguaje con variables, y reescribirlo a ciegas podría
     * cambiar una `VAR` que se llame igual. Se avisa —ver `usosDeCampo`— y las
     * arregla quien las escribió, que es el único que sabe qué quiso decir.
     */
    case 'renombrar_campo': {
      if (a.antes === a.despues) return d
      const e = d.entidades.find((x) => x.nombre === a.entidad)
      if (!e) return d
      const viejo = e.campos.find((c) => c.nombre === a.antes)
      if (!viejo) return d
      const nuevo = e.campos.find((c) => c.nombre === a.despues)

      // El tipo sale del origen —es un hecho, no una decisión—; el rol, la
      // etiqueta, «ver», PII y «única» son trabajo hecho a mano y viajan con el
      // nombre. Eso es todo el sentido de renombrar en vez de quitar y añadir.
      const heredado: Campo = {
        ...(nuevo ?? viejo),
        nombre: a.despues,
        rol: viejo.rol,
        etiqueta: viejo.etiqueta,
        visible: viejo.visible,
        pii: viejo.pii,
        unico: viejo.unico,
      }

      const renombraCol = (par: [string, string]): [string, string] =>
        par[0] === a.entidad && par[1] === a.antes ? [par[0], a.despues] : par

      return {
        ...d,
        entidades: d.entidades.map((x) =>
          x.nombre !== a.entidad
            ? x
            : {
                ...x,
                // Si la columna nueva ya estaba —porque se pulsó «actualizar» antes—
                // se queda en su sitio y se le pega lo heredado; si no, el campo
                // viejo se renombra donde está. En los dos casos el viejo desaparece.
                campos: nuevo
                  ? x.campos
                      .filter((c) => c.nombre !== a.antes)
                      .map((c) => (c.nombre === a.despues ? heredado : c))
                  : x.campos.map((c) => (c.nombre === a.antes ? heredado : c)),
                clave_primaria:
                  x.clave_primaria === a.antes ? a.despues : x.clave_primaria,
                grano: x.grano?.map((g) => (g === a.antes ? a.despues : g)),
              },
        ),
        relaciones: d.relaciones.map((r) => ({
          ...r,
          desde: renombraCol(r.desde),
          hasta: renombraCol(r.hasta),
        })),
      }
    }

    // Quitar columnas que el origen ya no tiene. Quien llama comprueba antes que
    // nada las use: aquí no se puede decidir eso sin la definición entera a la
    // vista, y quitar una columna con una relación encima rompe el modelo lejos de
    // este botón — en la primera consulta.
    case 'quitar_campos': {
      const fuera = new Set(a.campos)
      if (fuera.size === 0) return d
      return {
        ...d,
        entidades: d.entidades.map((e) =>
          e.nombre !== a.entidad
            ? e
            : {
                ...e,
                campos: e.campos.filter((c) => !fuera.has(c.nombre)),
                clave_primaria: fuera.has(e.clave_primaria ?? '')
                  ? null
                  : e.clave_primaria,
                grano: e.grano?.filter((g) => !fuera.has(g)),
              },
        ),
      }
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

    // Toda la disposición de una vez, y no un `mover` por tabla: reorganizar es un
    // solo gesto y tiene que deshacerse con un solo «Deshacer». Con trece tablas,
    // trece pasos de historial para volver atrás no es un botón de deshacer.
    case 'reorganizar':
      return { ...d, disposicion: a.disposicion }

    case 'agregar_tabla_medidas':
      return {
        ...d,
        tablas_medidas: [...(d.tablas_medidas ?? []), { nombre: a.nombre }],
      }

    // Renombrar arrastra a sus métricas: la referencia va por nombre, así que
    // cambiar el cajón sin tocarlas dejaría a todas apuntando a uno que no existe
    // y el modelo no se podría guardar.
    case 'renombrar_tabla_medidas':
      return {
        ...d,
        tablas_medidas: (d.tablas_medidas ?? []).map((t) =>
          t.nombre === a.antes ? { ...t, nombre: a.despues } : t,
        ),
        metricas: d.metricas.map((m) =>
          m.tabla_medidas === a.antes ? { ...m, tabla_medidas: a.despues } : m,
        ),
      }

    // Quitar el cajón NO borra sus métricas: vuelven a verse bajo su hecho. Un
    // botón de ordenar que borra el trabajo ordenado no se puede pulsar tranquilo.
    case 'quitar_tabla_medidas':
      return {
        ...d,
        tablas_medidas: (d.tablas_medidas ?? []).filter(
          (t) => t.nombre !== a.nombre,
        ),
        metricas: d.metricas.map((m) =>
          m.tabla_medidas === a.nombre ? { ...m, tabla_medidas: null } : m,
        ),
      }

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
 * Quién usa una columna. Es lo que decide si se puede quitar sin romper nada.
 *
 * El aviso decía «no se quitan solas por si alguna relación o métrica las usa», y
 * «por si» no es una respuesta: obligaba a repasar a mano las veinticuatro
 * relaciones y las treinta métricas para saber si esa columna importaba. Aquí se
 * mira, y lo que se encuentra se puede nombrar.
 *
 * Las métricas se buscan por texto en su fórmula, con límite de palabra. Es una
 * aproximación **por exceso** y a propósito: la fórmula es un lenguaje con
 * variables, así que una `VAR` que se llame igual que la columna sale en la lista
 * sin serlo. Pasarse nombrando a un sospechoso de más es barato; no nombrar a la
 * métrica que se va a romper, no.
 */
export function usosDeCampo(
  d: Definicion,
  entidad: string,
  campo: string,
): { relaciones: string[]; metricas: string[]; esClave: boolean; enGrano: boolean } {
  const e = d.entidades.find((x) => x.nombre === entidad)
  const relaciones = d.relaciones
    .filter(
      (r) =>
        (r.desde[0] === entidad && r.desde[1] === campo) ||
        (r.hasta[0] === entidad && r.hasta[1] === campo),
    )
    .map((r) => `${r.desde[0]}.${r.desde[1]} → ${r.hasta[0]}.${r.hasta[1]}`)

  // Se escapa el nombre: una columna puede llevar puntos o paréntesis, y sin
  // escapar se convertirían en comodines del propio patrón.
  const suelto = new RegExp(
    `(^|[^\\w])${campo.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^\\w])`,
  )
  const metricas = d.metricas
    .filter((m) => m.entidad === entidad && suelto.test(m.expresion))
    .map((m) => m.etiqueta || m.nombre)

  return {
    relaciones,
    metricas,
    esClave: e?.clave_primaria === campo,
    enGrano: (e?.grano ?? []).includes(campo),
  }
}

/** Los usos de una columna en una línea, o `null` si no la usa nadie. */
export function describirUsos(
  usos: ReturnType<typeof usosDeCampo>,
): string | null {
  const partes: string[] = []
  if (usos.esClave) partes.push('es la clave primaria')
  if (usos.enGrano) partes.push('está en el grano')
  if (usos.relaciones.length) {
    partes.push(
      `${usos.relaciones.length} relación(es): ${usos.relaciones.join('; ')}`,
    )
  }
  if (usos.metricas.length) {
    partes.push(`la nombran ${usos.metricas.length} métrica(s): ${usos.metricas.join(', ')}`)
  }
  return partes.length ? partes.join(' · ') : null
}

/**
 * Volver a leer las columnas del origen y ponerlas al día en la entidad.
 *
 * La entidad guarda su propia copia de los campos, tomada el día que se agregó al
 * modelo. Eso es a propósito —el modelo tiene que poder abrirse y compilar sin
 * tocar la base— pero tiene un precio: si la transformación cambia después, la
 * copia se queda vieja y no lo dice. El caso concreto que lo destapó fue una
 * columna a la que se le añadió un `cast(… as date)` en la transformación y que
 * en el modelo seguía saliendo como texto, con todo lo que eso arrastra: el rol
 * sugerido, el aviso de tipos que no casan en la relación con el calendario, y
 * las funciones de fecha que no se ofrecen en las fórmulas.
 *
 * Lo que se conserva y lo que se pisa:
 *
 * - **El tipo se pisa.** Es un hecho del origen, no una decisión de nadie.
 * - **El rol, la etiqueta, `visible` y `pii` se conservan.** Son decisiones
 *   tomadas a mano; volver a adivinarlas borraría el trabajo de clasificar
 *   catorce campos.
 * - **Las columnas nuevas se añaden** con su rol sugerido.
 * - **Las que desaparecieron NO se borran aquí.** Puede haber relaciones o métricas
 *   apuntando a ellas, y borrarlas en silencio dejaría el modelo roto lejos de
 *   aquí. Se devuelven en `desaparecidas`, y quien llama mira con `usosDeCampo`
 *   cuáles no las usa nadie —esas sí se quitan, con `quitar_campos`— y cuáles hay
 *   que resolver a mano. Que se queden TODAS, como pasaba antes, hacía que el aviso
 *   no se fuera nunca por más veces que se pulsara el botón.
 */
export function resincronizar(
  entidad: Entidad,
  columnas: { nombre: string; tipo: string; rol_sugerido: string }[],
): { campos: Campo[]; retipados: string[]; nuevas: string[]; desaparecidas: string[] } {
  const llegan = new Map(columnas.map((c) => [c.nombre, c]))
  const retipados: string[] = []
  const desaparecidas: string[] = []

  const campos: Campo[] = entidad.campos.map((c) => {
    const nueva = llegan.get(c.nombre)
    if (!nueva) {
      desaparecidas.push(c.nombre)
      return c
    }
    if (nueva.tipo !== c.tipo) {
      retipados.push(`${c.nombre}: ${c.tipo} → ${nueva.tipo}`)
      return { ...c, tipo: nueva.tipo as Campo['tipo'] }
    }
    return c
  })

  const ya = new Set(entidad.campos.map((c) => c.nombre))
  const nuevas = columnas.filter((c) => !ya.has(c.nombre))
  for (const c of nuevas) {
    campos.push({
      nombre: c.nombre,
      tipo: c.tipo as Campo['tipo'],
      rol: c.rol_sugerido as RolCampo,
    })
  }

  return { campos, retipados, nuevas: nuevas.map((c) => c.nombre), desaparecidas }
}

/** ¿La entidad no declara todavía ninguna clave primaria? */
export function sinClave(d: Definicion, entidad: string): boolean {
  return !d.entidades.find((e) => e.nombre === entidad)?.clave_primaria
}

/**
 * Dejar constancia de que una columna no se repite.
 *
 * Hay dos maneras y la buena depende de si la entidad ya tiene clave primaria:
 *
 * - **No la tiene**: se declara esta. Es lo que identifica la fila y hacía falta
 *   de todos modos.
 * - **Ya tiene otra**: se marca esta como `unico`. Una entidad tiene UNA clave
 *   primaria, así que sustituirla para callar un aviso encendía el mismo aviso en
 *   todas las relaciones que unían contra la anterior — ocho, en un catálogo de
 *   sucursales con varios identificadores. Marcarla única no le quita el sitio a
 *   nadie y es exactamente lo que la relación necesita saber.
 */
export function marcarUnica(
  d: Definicion,
  entidad: string,
  campo: string,
  despachar: (a: Accion) => void,
): void {
  if (sinClave(d, entidad)) {
    despachar({ t: 'cambiar_entidad', nombre: entidad, cambios: { clave_primaria: campo } })
  } else {
    despachar({ t: 'cambiar_campo', entidad, campo, cambios: { unico: true } })
  }
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
