import { useState } from 'react'

import { ErrorApi, api } from '../api/cliente'

export function Ingreso({ alEntrar }: { alEntrar: () => void }) {
  const [email, setEmail] = useState('')
  const [contrasena, setContrasena] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      await api.ingresar(email, contrasena)
      alEntrar()
    } catch (err) {
      // El backend responde lo mismo para correo desconocido y contraseña mala:
      // decir cuál de las dos falló revela qué cuentas existen.
      setError(err instanceof ErrorApi ? err.message : 'No se pudo entrar')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="ingreso">
      <form onSubmit={enviar}>
        <h1>Astrolabio</h1>
        <p className="chico suave" style={{ margin: '-8px 0 0' }}>
          Conectar, transformar, modelar y publicar
        </p>

        {error && <div className="error-caja">{error}</div>}

        <div className="campo">
          <label htmlFor="email">Correo</label>
          <input
            id="email"
            type="text"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>

        <div className="campo">
          <label htmlFor="clave">Contraseña</label>
          <input
            id="clave"
            type="password"
            autoComplete="current-password"
            value={contrasena}
            onChange={(e) => setContrasena(e.target.value)}
            required
          />
        </div>

        <button className="btn primario" type="submit" disabled={enviando}>
          {enviando ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
    </div>
  )
}
