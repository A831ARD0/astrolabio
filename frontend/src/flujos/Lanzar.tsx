/**
 * Lanzar un flujo a mano, preguntando cuando ya hay algo corriendo.
 *
 * La corrida va a segundo plano: la petición contesta enseguida y el resultado
 * se sigue por el historial. Eso quita el 502 de las extracciones largas y hace
 * que salirse de la pantalla ya no sea un problema.
 *
 * Lo que sí hay que preguntar es qué hacer si ya hay otra corriendo. Encolar es
 * lo sensato —el cuello de botella es el origen, y cuarenta sucursales sobre el
 * mismo servidor no van más rápido por pedírselo todo de golpe— pero hay casos
 * legítimos para lanzarlas a la par, y esa decisión es de quien opera. Lo que no
 * se hace es decidirlo en silencio.
 *
 * Lanzar DOS VECES lo mismo no se pregunta: se rechaza en el servidor. Eso no es
 * una preferencia, son dos procesos escribiendo los mismos archivos.
 */

import { useState } from 'react'

import { useCola, useEjecutarFlujo } from '../api/flujos'
import { Velo } from '../comunes/Velo'

export function useLanzador() {
  const cola = useCola()
  const ejecutar = useEjecutarFlujo()
  const [pregunta, setPregunta] = useState<
    { id: number; nombre: string; ocupa: string } | null
  >(null)

  function lanzar(id: number, nombre: string) {
    const ocupado = cola.data?.corriendo[0]
    // Si lo que corre es este mismo, no se pregunta nada: el servidor lo
    // rechaza y el mensaje se ve donde toca.
    if (ocupado && !(ocupado.tipo === 'flujo' && ocupado.objeto_id === id)) {
      setPregunta({ id, nombre, ocupa: ocupado.nombre })
      return
    }
    ejecutar.mutate({ id })
  }

  function decidir(aLaPar: boolean) {
    if (!pregunta) return
    ejecutar.mutate({ id: pregunta.id, aLaPar })
    setPregunta(null)
  }

  const dialogo = pregunta ? (
    <Velo alCerrar={() => setPregunta(null)}>
      <div className="modal">
        <header>Ya hay algo corriendo</header>
        <div className="cont">
          <p>
            <strong>{pregunta.ocupa}</strong> está corriendo ahora mismo. ¿Qué hago
            con <strong>{pregunta.nombre}</strong>?
          </p>
          <p className="chico suave">
            Esperar turno es lo normal: si los dos leen del mismo servidor de
            origen, lanzarlos a la vez no acaba antes — y a veces acaba peor.
          </p>
        </div>
        <footer>
          <button className="btn" onClick={() => setPregunta(null)}>Cancelar</button>
          <button className="btn" onClick={() => decidir(true)}>
            Correr ya, a la par
          </button>
          <button className="btn primario" onClick={() => decidir(false)}>
            Esperar turno
          </button>
        </footer>
      </div>
    </Velo>
  ) : null

  return { lanzar, dialogo, ejecutar, cola }
}
