/**
 * El panel lateral: se ensancha arrastrando y sus secciones se pliegan.
 *
 * Nace de un nombre: `MGSALINAC1__Orcamento_Produtos`. Con cuarenta sucursales,
 * el nombre de un dataset es el de la conexión más el de la tabla, y en 232
 * píxeles no cabe ni la mitad — se lee «MGSALINAC1__Orcament…», que no distingue
 * `Orcamento` de `Orcamento_Produtos`. Ensanchar es la única forma de trabajar.
 *
 * El ancho se recuerda por panel y por pantalla: quien ensancha la lista de
 * cargas en Flujos no quiere encontrársela estrecha al volver mañana. Vive en el
 * navegador y no en el servidor a propósito — es una preferencia de esta
 * pantalla y este monitor, no del usuario.
 *
 * Y las secciones se pliegan desde su cabecera: cuando estás armando un flujo no
 * necesitas ver las transformaciones, y plegarlas le da su alto a la lista que sí
 * estás usando.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

const MINIMO = 180
const MAXIMO = 640

function recordado(clave: string, porOmision: number): number {
  const v = Number(localStorage.getItem(`astrolabio.ancho.${clave}`))
  return Number.isFinite(v) && v >= MINIMO && v <= MAXIMO ? v : porOmision
}

/**
 * Un panel lateral de ancho ajustable.
 *
 * `clave` distingue un panel de otro para recordar su ancho; `lado` dice de qué
 * borde se arrastra.
 */
export function PanelLateral({
  clave,
  lado = 'izquierda',
  porOmision = 232,
  children,
}: {
  clave: string
  lado?: 'izquierda' | 'derecha'
  porOmision?: number
  children: React.ReactNode
}) {
  const [ancho, setAncho] = useState(() => recordado(clave, porOmision))
  const [arrastrando, setArrastrando] = useState(false)
  const inicio = useRef({ x: 0, ancho: 0 })

  const alMover = useCallback((e: PointerEvent) => {
    const delta = e.clientX - inicio.current.x
    // Arrastrar el borde derecho de un panel izquierdo lo ensancha; en el de la
    // derecha es al revés.
    const bruto = inicio.current.ancho + (lado === 'izquierda' ? delta : -delta)
    setAncho(Math.min(MAXIMO, Math.max(MINIMO, Math.round(bruto))))
  }, [lado])

  const alSoltar = useCallback(() => setArrastrando(false), [])

  useEffect(() => {
    if (!arrastrando) return
    window.addEventListener('pointermove', alMover)
    window.addEventListener('pointerup', alSoltar)
    // Sin esto, arrastrar selecciona el texto de las listas y queda todo azul.
    const antes = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    return () => {
      window.removeEventListener('pointermove', alMover)
      window.removeEventListener('pointerup', alSoltar)
      document.body.style.userSelect = antes
      document.body.style.cursor = ''
    }
  }, [arrastrando, alMover, alSoltar])

  // Se guarda al soltar y no en cada píxel: escribir en localStorage sesenta
  // veces por segundo mientras se arrastra no hace falta.
  useEffect(() => {
    if (arrastrando) return
    localStorage.setItem(`astrolabio.ancho.${clave}`, String(ancho))
  }, [arrastrando, ancho, clave])

  const tirador = (
    <div
      className={`tirador${arrastrando ? ' activo' : ''}`}
      role="separator"
      aria-orientation="vertical"
      aria-label="Cambiar el ancho del panel"
      title="Arrastra para cambiar el ancho. Doble clic para volver al normal."
      onPointerDown={(e) => {
        e.preventDefault()
        inicio.current = { x: e.clientX, ancho }
        setArrastrando(true)
      }}
      onDoubleClick={() => setAncho(porOmision)}
    />
  )

  // El tirador es un hermano del cuerpo, no un absoluto encima: dentro de un
  // contenedor que se desplaza, un absoluto se va con el contenido y el borde
  // acaba a media pantalla.
  return (
    <aside className={lado === 'izquierda' ? 'izq' : 'der'}
           style={{ width: ancho, flex: `0 0 ${ancho}px` }}>
      {lado === 'derecha' && tirador}
      <div className="panel-cuerpo">{children}</div>
      {lado === 'izquierda' && tirador}
    </aside>
  )
}

/**
 * Una sección del panel, que se pliega desde su cabecera.
 *
 * Lo que se pulsa es toda la cabecera y no solo el triángulo: acertarle a diez
 * píxeles cuarenta veces al día es trabajo de verdad. `principal` marca la
 * sección larga, la que se lleva el alto que sobre.
 */
export function Seccion({
  titulo,
  extra,
  principal = false,
  fijo,
  children,
  clave,
}: {
  titulo: string
  /** Lo que va a la derecha del título: un contador, normalmente. */
  extra?: React.ReactNode
  principal?: boolean
  /** Lo que se queda quieto entre la cabecera y la parte que se desplaza. */
  fijo?: React.ReactNode
  children: React.ReactNode
  /** Para recordar si estaba plegada. Sin ella, se abre siempre. */
  clave?: string
}) {
  const [plegada, setPlegada] = useState(
    () => !!clave && localStorage.getItem(`astrolabio.plegada.${clave}`) === '1',
  )

  function alternar() {
    const v = !plegada
    setPlegada(v)
    if (clave) localStorage.setItem(`astrolabio.plegada.${clave}`, v ? '1' : '0')
  }

  return (
    <section className={`seccion${principal && !plegada ? ' principal' : ''}`}>
      <header className="plegable" onClick={alternar}
              title={plegada ? 'Abrir' : 'Plegar'}>
        <span className="plegar" aria-hidden="true">{plegada ? '▸' : '▾'}</span>
        {titulo}
        {extra !== undefined && <span className="cuenta">{extra}</span>}
      </header>
      {!plegada && (
        <>
          {fijo}
          <div className="contenido">{children}</div>
        </>
      )}
    </section>
  )
}
