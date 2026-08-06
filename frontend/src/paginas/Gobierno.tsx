/**
 * Gobierno: quién entra, qué puede ver y qué hizo.
 *
 * Las tres cosas juntas y en ese orden porque se usan juntas: una política se
 * escribe mirando los atributos de la gente, y se comprueba mirando lo que quedó
 * registrado.
 */

import { useState } from 'react'

import { Auditoria } from '../gobierno/Auditoria'
import { Politicas } from '../gobierno/Politicas'
import { Usuarios } from '../gobierno/Usuarios'

type Pestana = 'usuarios' | 'seguridad' | 'auditoria'

const PESTANAS: { id: Pestana; titulo: string; pie: string }[] = [
  { id: 'usuarios', titulo: 'Usuarios', pie: 'Quién entra y con qué atributos' },
  { id: 'seguridad', titulo: 'Seguridad por fila', pie: 'Qué filas ve cada quién' },
  { id: 'auditoria', titulo: 'Auditoría', pie: 'Qué se hizo y quién lo hizo' },
]

export function Gobierno() {
  const [pestana, setPestana] = useState<Pestana>('usuarios')
  const actual = PESTANAS.find((p) => p.id === pestana)!

  return (
    <div className="pagina">
      <h1>Gobierno</h1>
      <p className="suave chico">{actual.pie}</p>

      <div className="pestanas" style={{ margin: '14px 0 16px' }}>
        {PESTANAS.map((p) => (
          <button
            key={p.id}
            className={pestana === p.id ? 'activo' : ''}
            onClick={() => setPestana(p.id)}
          >
            {p.titulo}
          </button>
        ))}
      </div>

      {pestana === 'usuarios' && <Usuarios />}
      {pestana === 'seguridad' && <Politicas />}
      {pestana === 'auditoria' && <Auditoria />}
    </div>
  )
}
