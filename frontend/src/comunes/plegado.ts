/**
 * Si un grupo está plegado, recordado en el navegador.
 *
 * Una sola pieza para toda la aplicación. Vive aparte del componente `Grupo` porque
 * hay sitios que necesitan **el mismo comportamiento con otra cabecera**: los cajones
 * de métricas del panel del modelo llevan su punto de color, su contador y sus
 * acciones al pasar el ratón, y no pueden usar la cabecera gris y pequeña de `Grupo`.
 * Lo que sí tiene que ser idéntico es cómo se pliega y dónde se acuerda —misma clave,
 * mismo sitio— para que plegar signifique lo mismo en las dos pantallas.
 *
 * Vive en el navegador y no en el servidor a propósito, igual que el ancho de los
 * paneles: es una preferencia de esta pantalla, no del usuario.
 *
 * Quien lo use debe darle a su elemento un `key` que dependa del nombre. Al renombrar
 * un cajón cambia la clave, y es el remontaje lo que hace que se lea la nueva —el
 * valor inicial de `useState` solo se calcula al montar.
 */

import { useCallback, useState } from 'react'

export function usePlegado(clave: string): [boolean, () => void] {
  const [plegado, setPlegado] = useState(
    () => localStorage.getItem(`astrolabio.grupo.${clave}`) === '1',
  )
  const alternar = useCallback(() => {
    setPlegado((previo) => {
      localStorage.setItem(`astrolabio.grupo.${clave}`, previo ? '0' : '1')
      return !previo
    })
  }, [clave])
  return [plegado, alternar]
}
