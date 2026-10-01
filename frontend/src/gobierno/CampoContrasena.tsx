/**
 * Campo de contraseña para el administrador: escribirla, generarla, verla y
 * copiarla.
 *
 * Verla es necesario porque la contraseña es para OTRA persona: el administrador
 * tiene que poder leerla o copiarla para dársela. Lo que no se puede es
 * consultarla después de guardar —solo se guarda su hash—, así que el momento de
 * copiarla es éste, y el campo lo dice.
 *
 * Al generar se muestra sola: una contraseña generada que nace oculta obliga a un
 * clic más para lo único que se quiere hacer con ella.
 */

import { useRef, useState } from 'react'

import { generarContrasena } from './generarContrasena'

export function CampoContrasena({
  valor,
  alCambiar,
  placeholder = 'mínimo 10 caracteres',
}: {
  valor: string
  alCambiar: (v: string) => void
  placeholder?: string
}) {
  const [visible, setVisible] = useState(false)
  const [copiada, setCopiada] = useState(false)
  const campo = useRef<HTMLInputElement>(null)

  const cambiar = (v: string) => {
    setCopiada(false)
    alCambiar(v)
  }

  const copiar = async () => {
    // El portapapeles moderno solo existe en contexto seguro (https o localhost).
    // Servido por http en la red interna no está, y entonces se cae al método
    // viejo: seleccionar el texto y pedir la copia. Si tampoco funciona, queda
    // seleccionado y basta con Ctrl+C.
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(valor)
      } else {
        setVisible(true)
        campo.current?.focus()
        campo.current?.select()
        document.execCommand('copy')
      }
      setCopiada(true)
    } catch {
      campo.current?.select()
    }
  }

  return (
    <div className="fila-condicion">
      <input
        ref={campo}
        type={visible ? 'text' : 'password'}
        className={visible ? 'mono' : undefined}
        value={valor}
        placeholder={placeholder}
        autoComplete="new-password"
        spellCheck={false}
        onChange={(e) => cambiar(e.target.value)}
      />
      <button
        type="button"
        className="btn chico"
        onClick={() => {
          cambiar(generarContrasena())
          setVisible(true)
        }}
      >
        Generar
      </button>
      <button
        type="button"
        className="btn chico"
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
      >
        {visible ? 'Ocultar' : 'Ver'}
      </button>
      <button type="button" className="btn chico" disabled={!valor} onClick={copiar}>
        {copiada ? 'Copiada ✓' : 'Copiar'}
      </button>
    </div>
  )
}
