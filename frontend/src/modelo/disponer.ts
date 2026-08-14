/**
 * Colocar las tablas del lienzo de forma que se pueda leer.
 *
 * Lo que había era `(i % 4) * 300, floor(i / 4) * 340`: una cuadrícula ciega. Con
 * nodos de hasta 260 de ancho separados 300 y filas de 340 cuando una tabla de
 * veintidós columnas mide más de 500 de alto, las tablas **se solapan** y las líneas
 * cruzan por encima de otras. Con seis tablas se aguanta; con trece y veinticuatro
 * relaciones el lienzo deja de decir nada.
 *
 * Aquí se coloca por **capas**, que es la forma del modelo y no un accidente:
 *
 *   1. Los **hechos** son terminales para el motor —nunca puente— así que van en la
 *      primera columna. De ahí nacen las métricas y de ahí sale toda consulta.
 *   2. Las **dimensiones que tocan un hecho** van en la siguiente; las que solo
 *      tocan a otra dimensión (copo de nieve) en la de después, y así.
 *   3. Lo que no se relaciona con nada va al final, junto: son las huérfanas, y
 *      verlas apartadas es información, no un descuido.
 *
 * Con esa forma **todas las relaciones van de izquierda a derecha**, que es
 * exactamente lo que el lienzo dibuja bien (ver `Lienzo`).
 *
 * Dentro de cada columna el orden se decide por **baricentro**: cada tabla se pone a
 * la altura media de aquellas con las que se relaciona, y se repite unas pasadas
 * alternando de ida y de vuelta. Es lo que quita la mayoría de los cruces sin tener
 * que resolver un problema que es NP-completo.
 *
 * Y se usa el alto **medido** de cada tabla, no uno supuesto: es la única forma de
 * garantizar que no se toquen.
 */

import type { Definicion, Entidad } from '../api/tipos'

export interface Medida {
  ancho: number
  alto: number
}

export interface Punto {
  x: number
  y: number
}

/** Hueco entre columnas. Da sitio a la curva y a la etiqueta de la cardinalidad. */
const HUECO_X = 140
/** Hueco entre tablas de la misma columna. */
const HUECO_Y = 40
/** Por si una tabla todavía no se ha medido. */
const ANCHO_SUPUESTO = 260
const ALTO_SUPUESTO = 220
/** Pasadas de baricentro. Más de esto ya no mueve nada en modelos de este tamaño. */
const PASADAS = 6

/**
 * El tamaño que tendrá una tabla antes de dibujarla.
 *
 * Se usa al abrir un modelo que no traía disposición —uno escrito a mano en YAML—,
 * cuando todavía no hay nada medido. Los números salen de medir el nodo en el
 * navegador —cabecera con su borde y el relleno de la lista, una fila por columna, y
 * el pie del grano cuando lo hay—, y **se redondean hacia arriba** a propósito: pasarse
 * deja un hueco de más entre dos tablas, quedarse corto las solapa, que es el defecto
 * que esto existe para evitar.
 */
export function medidaSupuesta(e: Entidad): Medida {
  const ALTO_CABECERA = 44
  const ALTO_FILA = 23
  const ALTO_PIE = 27
  return {
    ancho: ANCHO_SUPUESTO,
    alto:
      ALTO_CABECERA +
      e.campos.length * ALTO_FILA +
      (e.tipo === 'hecho' && (e.grano?.length ?? 0) > 0 ? ALTO_PIE : 0),
  }
}

export function disponer(
  definicion: Definicion,
  medidas: Record<string, Medida> = {},
): Record<string, Punto> {
  const nombres = definicion.entidades.map((e) => e.nombre)
  if (nombres.length === 0) return {}

  const vecinos = new Map<string, Set<string>>(nombres.map((n) => [n, new Set()]))
  for (const r of definicion.relaciones) {
    const [a, b] = [r.desde[0], r.hasta[0]]
    if (a === b) continue
    vecinos.get(a)?.add(b)
    vecinos.get(b)?.add(a)
  }

  // --- Capas ---------------------------------------------------------------
  const capaDe = new Map<string, number>()
  const hechos = definicion.entidades
    .filter((e) => e.tipo === 'hecho')
    .map((e) => e.nombre)

  // Sin ningún hecho —un modelo a medio armar— se arranca por la tabla con más
  // relaciones: es la que mejor reparte a las demás.
  const semillas = hechos.length
    ? hechos
    : [[...nombres].sort((a, b) => (vecinos.get(b)?.size ?? 0) - (vecinos.get(a)?.size ?? 0))[0]!]

  let frente = semillas.filter((n) => vecinos.has(n))
  for (const n of frente) capaDe.set(n, 0)
  let capa = 0
  while (frente.length) {
    capa += 1
    const siguiente: string[] = []
    for (const n of frente) {
      for (const v of vecinos.get(n) ?? []) {
        if (!capaDe.has(v)) {
          capaDe.set(v, capa)
          siguiente.push(v)
        }
      }
    }
    frente = siguiente
  }

  // Lo que no alcanzó ninguna semilla: otro componente del grafo, o una huérfana.
  // Va al final, en su propia columna.
  const sueltas = nombres.filter((n) => !capaDe.has(n))
  if (sueltas.length) {
    const ultima = Math.max(0, ...capaDe.values()) + 1
    for (const n of sueltas) capaDe.set(n, ultima)
  }

  const columnas: string[][] = []
  for (const n of nombres) {
    const c = capaDe.get(n)!
    ;(columnas[c] ??= []).push(n)
  }
  // Una capa vacía dejaría una columna en blanco en medio.
  const usadas = columnas.filter((c) => c && c.length)

  // --- Orden dentro de cada columna: baricentro ----------------------------
  const posicionEn = (col: string[]) =>
    new Map(col.map((n, i) => [n, i] as const))

  const ordenar = (col: string[], referencia: Map<string, number>) => {
    const clave = new Map<string, number>()
    for (const n of col) {
      const alturas = [...(vecinos.get(n) ?? [])]
        .map((v) => referencia.get(v))
        .filter((x): x is number => x !== undefined)
      // Sin vecinos en la columna de referencia se queda donde está: moverla al
      // principio la separaría de la única tabla con la que sí se relaciona.
      clave.set(n, alturas.length
        ? alturas.reduce((a, b) => a + b, 0) / alturas.length
        : (referencia.get(n) ?? col.indexOf(n)))
    }
    return [...col].sort((a, b) => clave.get(a)! - clave.get(b)!)
  }

  for (let pasada = 0; pasada < PASADAS; pasada++) {
    // De ida y de vuelta: una sola dirección deja la última columna sin ordenar
    // respecto a la anterior.
    const orden = pasada % 2 === 0
      ? [...usadas.keys()].slice(1)
      : [...usadas.keys()].slice(0, -1).reverse()
    for (const i of orden) {
      const vecina = pasada % 2 === 0 ? usadas[i - 1]! : usadas[i + 1]!
      usadas[i] = ordenar(usadas[i]!, posicionEn(vecina))
    }
  }

  // --- Coordenadas ---------------------------------------------------------
  const medida = (n: string): Medida =>
    medidas[n] ?? { ancho: ANCHO_SUPUESTO, alto: ALTO_SUPUESTO }

  const altoDeColumna = (col: string[]) =>
    col.reduce((t, n) => t + medida(n).alto, 0) + HUECO_Y * (col.length - 1)

  const altoMayor = Math.max(...usadas.map(altoDeColumna))

  const salida: Record<string, Punto> = {}
  let x = 0
  for (const col of usadas) {
    const ancho = Math.max(...col.map((n) => medida(n).ancho))
    // Cada columna centrada respecto a la más alta: así el modelo queda con forma
    // de espina y no escalonado hacia abajo.
    let y = (altoMayor - altoDeColumna(col)) / 2
    for (const n of col) {
      // Centrada dentro del ancho de su columna: una tabla estrecha al lado de una
      // ancha se ve alineada, no pegada a la izquierda.
      salida[n] = { x: Math.round(x + (ancho - medida(n).ancho) / 2), y: Math.round(y) }
      y += medida(n).alto + HUECO_Y
    }
    x += ancho + HUECO_X
  }
  return salida
}
