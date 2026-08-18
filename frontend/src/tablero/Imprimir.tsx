/**
 * La hoja como informe: una sola hoja para presentar, o páginas para imprimir.
 *
 * Se exporta la hoja que se está viendo, con los filtros puestos y tal como se ve:
 * los mismos widgets, los mismos semáforos, los mismos avisos. No se vuelve a
 * consultar nada. Eso es deliberado —un informe tiene que ser una foto de lo que
 * alguien miró, no una consulta nueva que podría dar otra cifra— y también es la
 * razón de que la **portada** no sea decorativa: sin ella, un PDF que circula por
 * correo es una tabla de números sin decir de qué mes es ni quién la sacó, y eso se
 * discute en una junta sin poder comprobarlo. Es el mismo motivo por el que cada
 * Excel lleva su hoja de procedencia.
 *
 * El PDF lo hace el navegador (en su diálogo, «Guardar como PDF»). No lo arma el
 * servidor porque para eso haría falta un navegador headless instalado allí, y aquí
 * el navegador ya tiene la hoja dibujada, con sus gráficos y sus colores, y sale
 * texto de verdad y no una imagen.
 *
 * Dos formas, porque son dos trabajos distintos:
 *
 * - **Una sola hoja.** Para proyectar o mandar por correo. Una única página del alto
 *   que haga falta, sin cortes ni saltos: nada queda partido entre dos páginas
 *   porque no hay dos páginas. El alto se mide de verdad, con el informe ya
 *   dispuesto, y se le escribe a `@page`.
 * - **Páginas A4.** Para papel. Se pagina, las tablas repiten sus encabezados y los
 *   totales salen una sola vez al final.
 *
 * Cuidado con una cosa en las dos: va lo que el widget cargó. Si una tabla venía
 * recortada, la banda ámbar de «faltan filas» se exporta con ella —queda dicho en el
 * documento— pero para el detalle entero lo que hay es el Excel del widget.
 */

import { useEffect, useRef, useState } from 'react'

import { MenuFlotante } from '../comunes/MenuFlotante'
import { dentroDelMenu, useMenuFlotante } from '../comunes/sitioDeMenu'
import type { Filtro } from '../api/tipos'

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
 * Tope de alto. Chrome no genera páginas de más de 200 pulgadas (unos 19 200 px) y
 * lo que hace al pasarse es recortar sin avisar, así que por encima de esto se dice
 * y se ofrece la otra forma en vez de entregar un PDF cortado.
 */
const ALTO_MAXIMO = 19_000

/** Cómo se lee un filtro en la portada. `cat_sucursal.nombre` no le dice nada a nadie. */
function comoSeLee(f: Filtro): { campo: string; valores: string } {
  const campo = f.campo.includes('.') ? f.campo.split('.').slice(1).join('.') : f.campo
  const vs = Array.isArray(f.valor) ? f.valor : [f.valor]
  // Con más de seis valores la lista deja de leerse y solo importa cuántos son;
  // el detalle exacto sigue en el Excel, que lleva los filtros enteros.
  const valores =
    vs.length > 6
      ? `${vs.length} valores`
      : vs.map((v) => (v === null ? '(vacío)' : String(v))).join(', ')
  return { campo, valores }
}

/**
 * La cabecera que solo existe en el informe.
 *
 * Vive siempre en el DOM y oculta; se enseña con la clase `informe`. Se hizo así y
 * no montándola al pulsar el botón porque `window.print()` es síncrono: lo que no
 * estuviera pintado ya, no saldría.
 */
export function PortadaInforme({
  tablero,
  hoja,
  modelo,
  version,
  certificado,
  publicado,
  filtros,
  usuario,
}: {
  tablero: string
  hoja: string
  modelo: string
  version: number
  certificado: boolean
  publicado: boolean
  filtros: Filtro[]
  usuario: string | undefined
}) {
  // La fecha se sella al exportar, no al dibujar la pantalla: un tablero abierto
  // desde la mañana pondría la hora de la mañana en un informe de la tarde.
  const [cuando, setCuando] = useState(() => new Date())
  useEffect(() => {
    const sellar = () => setCuando(new Date())
    window.addEventListener('beforeprint', sellar)
    return () => window.removeEventListener('beforeprint', sellar)
  }, [])

  const leidos = filtros.map(comoSeLee)

  return (
    <div className="portada-informe" aria-hidden="true">
      <div className="titulo">
        <h1>{tablero}</h1>
        <span className="hoja">{hoja}</span>
      </div>

      <dl className="procedencia">
        <dt>Filtros</dt>
        <dd>
          {leidos.length === 0 ? (
            <em>sin filtros: todos los datos del modelo</em>
          ) : (
            leidos.map((f) => (
              <span key={f.campo} className="uno">
                <b>{f.campo}</b> {f.valores}
              </span>
            ))
          )}
        </dd>

        <dt>Modelo</dt>
        <dd>
          {modelo} v{version}
          {certificado && ' · certificado'}
          {!publicado && ' · borrador'}
        </dd>

        <dt>Emitido</dt>
        <dd>
          {cuando.toLocaleString('es-MX', { dateStyle: 'long', timeStyle: 'short' })}
          {usuario ? ` · ${usuario}` : ''}
        </dd>
      </dl>
    </div>
  )
}

/** Dos cuadros de pintura, para que el navegador aplique el diseño del informe. */
const dosCuadros = () =>
  new Promise<void>((listo) =>
    requestAnimationFrame(() => requestAnimationFrame(() => listo())),
  )

/**
 * El botón. Abre el diálogo del navegador, donde se elige «Guardar como PDF».
 *
 * Además pone la clase `informe` en cualquier impresión, también en un Ctrl+P que no
 * pase por aquí: quien pulsa Ctrl+P en un tablero espera el tablero, no la
 * aplicación con sus paneles y sus botones.
 */
export function Imprimir({ hoja }: { hoja: string }) {
  const [abierto, setAbierto] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const caja = useRef<HTMLDivElement | null>(null)
  // Fuera de la barra: la barra recorta lo que desborda. Ver `MenuFlotante`.
  const { boton, sitio } = useMenuFlotante(abierto)

  useEffect(() => {
    const raiz = document.documentElement
    const antes = () => raiz.classList.add('informe')
    const despues = () => raiz.classList.remove('informe', 'una-hoja')
    window.addEventListener('beforeprint', antes)
    window.addEventListener('afterprint', despues)
    return () => {
      window.removeEventListener('beforeprint', antes)
      window.removeEventListener('afterprint', despues)
      despues()
    }
  }, [])

  useEffect(() => {
    if (!abierto) return
    const fuera = (e: MouseEvent) => {
      const t = e.target as Node
      // El menú ya no está dentro de `caja`: hay que preguntarle también a él, o el
      // primer clic en «Una sola hoja» lo cerraría antes de llegar al botón.
      if (!caja.current?.contains(t) && !dentroDelMenu(t)) setAbierto(false)
    }
    const escape = (e: KeyboardEvent) => e.key === 'Escape' && setAbierto(false)
    document.addEventListener('mousedown', fuera)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', fuera)
      document.removeEventListener('keydown', escape)
    }
  }, [abierto])

  function paginas() {
    setAbierto(false)
    // La clase la pone `beforeprint`; el `@page` de A4 ya está en la hoja de estilos.
    window.print()
  }

  async function unaHoja() {
    setError(null)
    setOcupado(true)
    const raiz = document.documentElement
    const estilo = document.createElement('style')
    try {
      // Se enciende el informe ANTES de medir: el alto de una hoja de una sola página
      // es el alto que ocupa ya dispuesta como informe, con los altos sueltos y las
      // tablas enteras. Medir la pantalla daría el alto de la ventana.
      raiz.style.setProperty('--ancho-informe', `${ANCHO}px`)
      raiz.classList.add('informe', 'una-hoja')
      await dosCuadros()
      // Los gráficos se redibujan solos (su `ResizeObserver`), pero no en el mismo
      // cuadro: sin esta espera el alto medido es el de antes de que se recolocaran.
      await new Promise((listo) => setTimeout(listo, 350))
      await dosCuadros()

      const centro = document.querySelector('.centro') as HTMLElement | null
      const medido = Math.max(centro?.scrollHeight ?? 0, document.body.scrollHeight)
      // La holgura no es por si acaso: la maquetación de impresión no redondea igual
      // que la de pantalla, y con la medida exacta sobraba una fracción de píxel que
      // se llevaba una segunda página en blanco al PDF. Ocho píxeles no se ven; una
      // página vacía en una presentación, sí.
      const alto = Math.ceil(medido) + 8
      if (medido <= 0) throw new Error('No se pudo medir la hoja.')
      if (alto > ALTO_MAXIMO) {
        throw new Error(
          `La hoja mide ${alto} px de alto y el navegador no hace páginas de más de ` +
            `${ALTO_MAXIMO}. Lo cortaría sin avisar, así que mejor «Páginas A4», o ` +
            `parte la hoja en dos.`,
        )
      }

      // Va después de la hoja de estilos, así que gana al `@page` de A4.
      estilo.id = 'tamano-una-hoja'
      estilo.textContent = `@page { size: ${ANCHO}px ${alto}px; margin: 0; }`
      document.head.appendChild(estilo)
      setAbierto(false)
      window.print()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo preparar el PDF')
    } finally {
      // `afterprint` quita las clases, pero también hay que quitarlas si esto falló
      // antes de llegar a imprimir: si no, el tablero se queda con cara de informe.
      raiz.classList.remove('informe', 'una-hoja')
      raiz.style.removeProperty('--ancho-informe')
      estilo.remove()
      setOcupado(false)
    }
  }

  return (
    <div className="exportar no-imprimir" ref={caja}>
      <button
        ref={boton}
        className="btn chico"
        title={`Guardar en PDF la hoja «${hoja}» con los filtros puestos`}
        onClick={() => setAbierto(!abierto)}
        disabled={ocupado}
      >
        {ocupado ? '…' : 'PDF'}
      </button>
      {abierto && (
        <MenuFlotante sitio={sitio} clase="no-imprimir">
          <button onClick={unaHoja}>Una sola hoja</button>
          <button onClick={paginas}>Páginas A4</button>
          <div className="chico tenue" style={{ padding: '4px 8px 2px' }}>
            En el diálogo, elige «Guardar como PDF». Una sola hoja no corta nada y es
            la de presentar; A4 es la de papel.
          </div>
        </MenuFlotante>
      )}
      {error && (
        <MenuFlotante sitio={sitio} clase="error-caja chico no-imprimir">
          {error}
        </MenuFlotante>
      )}
    </div>
  )
}
