/**
 * Medir una hoja para convertirla en una sola página.
 *
 * En su propio archivo y sin componentes: lo usan el botón de PDF y el renderizador
 * del servidor —el Chromium sin ventana que hace el informe que llega por correo—.
 * Dos formas de medir la misma hoja se desvían la primera semana que alguien toque
 * una, y entonces el PDF del correo deja de parecerse al del botón.
 */

/**
 * El ancho del informe de una sola hoja, en píxeles CSS.
 *
 * Fijo y no el de la ventana: si se heredara, el mismo tablero daría un PDF distinto
 * en un portátil y en un monitor, y quien lo manda no sabría cuál de los dos vio el
 * que lo recibe. 1600 es ancho de presentación —cabe una tabla de doce columnas sin
 * apretarla— y da una hoja de proporciones razonables.
 */
const ANCHO = 1600

/**
 * Y si no cabe, se ensancha. 1600 es el ANCHO DE SALIDA, no un tope: una tabla de
 * veinte columnas no entra ahí, y en pantalla eso se resuelve desplazándola dentro
 * del widget. En una sola hoja no hay dónde desplazar, así que lo que sobra se
 * quedaba cortado por el borde de la página — un PDF que enseña doce columnas de
 * veinte y no dice que faltan ocho.
 *
 * Se mide lo que se sale por la derecha y se ensancha la hoja hasta que quepa. En
 * bucle, porque al ensanchar la hoja el widget también se ensancha y la tabla
 * necesita menos de lo que pidió: dos o tres pasadas llegan al ancho justo, y
 * cualquiera de ellas es ya un ancho que no corta.
 */
const PASADAS_DE_ANCHO = 3

/**
 * Tope de alto. Chrome no genera páginas de más de 200 pulgadas (unos 19 200 px) y
 * lo que hace al pasarse es recortar sin avisar, así que por encima de esto se dice
 * y se ofrece la otra forma en vez de entregar un PDF cortado.
 */
const ALTO_MAXIMO = 19_000

/** El mismo tope, para el ancho: el límite de Chrome es de página, no de alto. */
const ANCHO_MAXIMO = 19_000

/**
 * Holgura, en píxeles, entre lo medido y lo que se escribe en `@page`.
 *
 * No es por si acaso: la maquetación de impresión no redondea igual que la de
 * pantalla, y con la medida exacta sobraba una fracción de píxel que se llevaba una
 * segunda página en blanco. Ocho píxeles no se ven; una página vacía en una
 * presentación, sí.
 */
const HOLGURA = 8

/** Dos cuadros de pintura, para que el navegador aplique el diseño del informe. */
/**
 * Cuánto habría que ensanchar la HOJA para que no se corte nada por la derecha.
 *
 * No es lo mismo que cuánto se sale: un widget de tres columnas de doce crece un
 * cuarto de lo que crece la hoja, así que ensanchar la hoja lo que sobresale la tabla
 * se queda corto tres veces. Lo que se devuelve ya está escalado por la fracción de
 * la rejilla que ocupa el widget, y así una sola pasada acierta.
 *
 * Y no vale `scrollWidth` del contenedor: en el informe el desbordamiento está
 * liberado a propósito —una tabla no puede quedarse dentro de una caja que se
 * desplaza— así que la tabla sobresale de su widget sin que nadie lo cuente.
 */
function faltaDeAncho(centro: HTMLElement): number {
  const relleno = parseFloat(getComputedStyle(centro).paddingRight) || 0
  const limite = centro.getBoundingClientRect().right - relleno
  const cols = Number(getComputedStyle(centro).getPropertyValue('--cols')) || 12
  let falta = Math.max(0, centro.scrollWidth - centro.clientWidth)

  for (const el of centro.querySelectorAll('.rejilla .widget')) {
    const caja = el.getBoundingClientRect()
    const gw = Number(getComputedStyle(el).getPropertyValue('--gw')) || cols
    // Lo que se sale del propio widget hay que dárselo al widget, y para eso la
    // hoja tiene que crecer `cols / gw` veces más.
    let dentro = 0
    for (const hijo of el.querySelectorAll('table, .grafico, .lista-valores')) {
      dentro = Math.max(dentro, hijo.getBoundingClientRect().right - caja.right)
    }
    falta = Math.max(falta, (dentro * cols) / Math.max(gw, 1))
    // Y lo que el widget mismo se sale de la hoja va tal cual: es la hoja.
    falta = Math.max(falta, caja.right - limite)
  }
  return falta
}

const dosCuadros = () =>
  new Promise<void>((listo) =>
    requestAnimationFrame(() => requestAnimationFrame(() => listo())),
  )

/**
 * Poner la clase y esperar a que la página se quede quieta.
 *
 * Los gráficos se redibujan solos —su `ResizeObserver`— pero no en el mismo cuadro:
 * sin esta espera, lo que se mide es la hoja de antes de que se recolocaran.
 */
async function asentarse() {
  await dosCuadros()
  await new Promise((listo) => setTimeout(listo, 350))
  await dosCuadros()
}

/** Lo que mide la hoja: el tamaño de la página que hay que pedirle al navegador. */
export type Medida = { ancho: number; alto: number }

/**
 * Deja la hoja puesta como informe de una sola página y devuelve su tamaño.
 *
 * **No limpia lo que puso**: eso lo decide quien llama. El botón lo quita al acabar
 * de imprimir; el renderizador del servidor no lo quita nunca, porque se lleva el PDF
 * y cierra la pestaña.
 *
 * Está fuera del componente a propósito. El PDF que llega por correo sale de este
 * mismo código —el servidor abre esta misma pantalla y llama aquí—, y no de una
 * segunda implementación que mediría distinto y se desviaría a la primera semana.
 */
export async function prepararUnaHoja(): Promise<Medida> {
  const raiz = document.documentElement
  // Se enciende el informe ANTES de medir: el alto de una hoja de una sola página es
  // el que ocupa ya dispuesta como informe, con los altos sueltos y las tablas
  // enteras. Medir la pantalla daría el alto de la ventana.
  raiz.style.setProperty('--ancho-informe', `${ANCHO}px`)
  raiz.classList.add('informe', 'una-hoja')
  await asentarse()

  const centro = document.querySelector('.centro') as HTMLElement | null
  if (!centro) throw new Error('No se pudo medir la hoja.')

  // Primero el ancho: el alto depende de él —una tabla que cabe no parte renglones—
  // así que medirlo antes sería medir otra hoja.
  let ancho = ANCHO
  for (let i = 0; i < PASADAS_DE_ANCHO; i++) {
    const falta = Math.ceil(faltaDeAncho(centro))
    if (falta <= 1 || ancho >= ANCHO_MAXIMO) break
    ancho = Math.min(ancho + falta, ANCHO_MAXIMO)
    raiz.style.setProperty('--ancho-informe', `${ancho}px`)
    await asentarse()
  }
  // Lo que quede después de las pasadas se le da a la PÁGINA, no a la hoja: la hoja
  // ya no se recompone —cada vez que se ensancha, la tabla pide un poco más y el
  // resto no baja de unos pocos píxeles— y una página un poco más ancha que su
  // contenido solo deja aire a la derecha. Negarse a hacer el PDF por tres píxeles
  // era peor que el problema que evitaba.
  const resto = Math.ceil(faltaDeAncho(centro))
  const anchoPagina = ancho + (resto > 0 ? resto + HOLGURA : 0)
  if (anchoPagina > ANCHO_MAXIMO) {
    throw new Error(
      `La hoja necesita ${anchoPagina} px de ancho y el navegador no hace páginas de ` +
        `más de ${ANCHO_MAXIMO}. Cortaría las últimas columnas sin avisar, así que ` +
        `mejor «Páginas A4», o quita columnas de la tabla.`,
    )
  }

  const medido = Math.max(centro.scrollHeight, document.body.scrollHeight)
  if (medido <= 0) throw new Error('No se pudo medir la hoja.')
  const alto = Math.ceil(medido) + HOLGURA
  if (alto > ALTO_MAXIMO) {
    throw new Error(
      `La hoja mide ${alto} px de alto y el navegador no hace páginas de más de ` +
        `${ALTO_MAXIMO}. Lo cortaría sin avisar, así que mejor «Páginas A4», o parte ` +
        `la hoja en dos.`,
    )
  }
  return { ancho: anchoPagina, alto }
}

/** Deshace lo que puso `prepararUnaHoja`. */
export function quitarInforme() {
  const raiz = document.documentElement
  raiz.classList.remove('informe', 'una-hoja')
  raiz.style.removeProperty('--ancho-informe')
}
