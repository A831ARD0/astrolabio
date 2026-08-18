/**
 * Semáforos: la flecha verde o roja al lado de una cifra.
 *
 * Tres decisiones, y las tres son para que la flecha no mienta:
 *
 * 1. **La dirección se declara.** «Mejor arriba» no es universal: un logro sube y
 *    está bien, y los días que un auto lleva en inventario suben y está mal. Un
 *    semáforo que siempre pintara verde hacia arriba pondría en verde justo la
 *    columna que hay que mirar.
 *
 * 2. **Contra qué se compara es explícito**: un número fijo (el objetivo: 45 días,
 *    100 %, 0) o **otra métrica del mismo widget** (lo facturado contra su objetivo,
 *    el mes contra el anterior). No se adivina.
 *
 * 3. **Color y forma a la vez.** El color dice el estado y la flecha lo repite:
 *    quien no distingue verde de rojo —uno de cada doce hombres— tiene que poder
 *    leerlo igual.
 *
 * Lo que un semáforo NO hace es cambiar la cifra. Es una lectura de la cifra que ya
 * está, calculada en el navegador sobre lo que la consulta devolvió.
 */

import { esNumero } from './formato'

/**
 * `sin_dato` es el estado que evita el peor fallo posible de un semáforo.
 *
 * Una sucursal con objetivo y sin ninguna venta no trae cifra —el hecho no tiene
 * filas—, así que no hay nada que comparar. Dejarla sin pintar la haría parecer
 * neutral justo cuando es el peor caso de la tabla, mientras que quien vendió poco
 * sale en rojo: el que peor va se vería mejor que el que va mal. Y pintarla como
 * cero sería que la pantalla decidiera que «sin filas» significa «cero», que es una
 * decisión de la métrica y no del semáforo.
 */
export type Direccion = 'bueno' | 'malo' | 'igual' | 'sin_dato'

export interface Semaforo {
  /** Contra un número fijo o contra otra métrica de este widget. */
  comparar: 'valor' | 'metrica'
  /** El umbral, en las unidades del dato (un 100 % se guarda como 1). */
  objetivo?: number
  /** La métrica contra la que se compara, si `comparar` es `metrica`. */
  metrica?: string
  bueno: 'mayor' | 'menor'
  /** Flecha al lado, fondo tenue, o las dos cosas. */
  mostrar: 'flecha' | 'fondo' | 'ambos'
}

export const SEMAFORO_NUEVO: Semaforo = {
  comparar: 'valor',
  objetivo: 0,
  bueno: 'mayor',
  mostrar: 'ambos',
}

/**
 * Cómo va esta celda. `null` cuando no hay nada que decir —no hay cifra, o no hay
 * contra qué comparar—, y entonces no se dibuja flecha: una flecha gris «por si
 * acaso» se lee como un dato.
 */
export function evaluar(
  valor: unknown,
  sem: Semaforo | undefined,
  fila: Record<string, unknown> | undefined,
): Direccion | null {
  if (!sem) return null

  const contra =
    sem.comparar === 'metrica'
      ? sem.metrica
        ? fila?.[sem.metrica]
        : undefined
      : sem.objetivo
  // Sin umbral no hay semáforo: no es que falte el dato, es que falta la regla.
  if (!esNumero(contra)) return null
  // Con umbral y sin cifra, sí hay algo que decir. Ver `Direccion`.
  if (!esNumero(valor)) return 'sin_dato'

  if (valor === contra) return 'igual'
  const arriba = valor > contra
  return arriba === (sem.bueno === 'mayor') ? 'bueno' : 'malo'
}

/** La flecha, que dice lo mismo que el color por si el color no llega. */
export function flecha(d: Direccion): string {
  if (d === 'igual') return '='
  if (d === 'sin_dato') return '?'
  return d === 'bueno' ? '▲' : '▼'
}

/** Por qué esta celda está así, para el `title`. */
export function porque(d: Direccion, sem: Semaforo): string {
  if (d === 'sin_dato') {
    return 'Hay objetivo pero no hay cifra: el hecho no trae ninguna fila para esta ' +
      'combinación. No es un cero medido, y por eso no se pinta como si lo fuera.'
  }
  const ref = sem.comparar === 'metrica' ? 'la otra columna' : 'el objetivo'
  if (d === 'igual') return `Igual que ${ref}.`
  const lado = d === 'bueno' ? 'del lado bueno' : 'del lado malo'
  return `Está ${lado} de ${ref} (aquí ${sem.bueno === 'mayor' ? 'más' : 'menos'} es mejor).`
}
