import { useEffect, type ReactNode } from 'react'

/**
 * El fondo oscuro de un modal.
 *
 * **Un clic fuera NO cierra**, y es a propósito. Estos diálogos son formularios:
 * el de una conexión pide servidor, base, usuario y contraseña, y el de un
 * dataset una selección de columnas. Cerrarse por un clic mal puesto tira todo
 * eso sin preguntar y sin manera de recuperarlo. El coste de equivocarse no es
 * simétrico: quien quiere cerrar tiene el botón y la tecla Escape a mano; quien
 * no quería, pierde el trabajo.
 *
 * Escape sí cierra, que es lo que espera cualquiera que use el teclado, y es un
 * gesto deliberado — nadie lo pulsa por accidente al mover el ratón.
 */
export function Velo({ alCerrar, children }: {
  alCerrar: () => void
  children: ReactNode
}) {
  useEffect(() => {
    function alPulsar(e: KeyboardEvent) {
      if (e.key === 'Escape') alCerrar()
    }
    // En `document` y no en el propio nodo: el foco puede estar en cualquier
    // campo del formulario, y desde ahí el evento no llegaría al contenedor.
    document.addEventListener('keydown', alPulsar)
    return () => document.removeEventListener('keydown', alPulsar)
  }, [alCerrar])

  return (
    <div className="velo" role="dialog" aria-modal="true">
      {children}
    </div>
  )
}
