import { useQueryClient } from '@tanstack/react-query'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { token } from './api/cliente'
import { useYo } from './api/hooks'
import { Avisos } from './paginas/Avisos'
import { Conexiones } from './paginas/Conexiones'
import { Etl } from './paginas/Etl'
import { Flujos } from './paginas/Flujos'
import { Gobierno } from './paginas/Gobierno'
import { Ingreso } from './paginas/Ingreso'
import { Modelo } from './paginas/Modelo'
import { Modelos } from './paginas/Modelos'
import { Tablero } from './paginas/Tablero'
import { Tableros } from './paginas/Tableros'

export function App() {
  const yo = useYo()
  const qc = useQueryClient()

  if (!token.leer() || yo.isError) {
    return <Ingreso alEntrar={() => qc.invalidateQueries()} />
  }
  if (yo.isLoading) return <div className="vacio">Cargando…</div>

  const salir = () => {
    token.borrar()
    qc.clear()
  }

  return (
    <div className="app">
      <header className="barra">
        {/* El símbolo va en línea y no como <img>: hereda el color del tema y no
            añade una petición más al cargar. */}
        <div className="marca">
          <svg viewBox="0 0 64 64" className="simbolo" aria-hidden="true">
            <g fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round">
              <circle cx="32" cy="32" r="20" />
              <circle cx="32" cy="32" r="12" opacity="0.45" />
              <path d="M32 10v5M32 49v5M10 32h5M49 32h5" opacity="0.7" />
              <path d="M18 46 46 18" opacity="0.9" />
            </g>
            <circle cx="32" cy="32" r="4" fill="currentColor" />
          </svg>
          Astrolabio
        </div>
        <nav className="nav">
          <NavLink to="/tableros" className={({ isActive }) => (isActive ? 'activo' : '')}>
            Tableros
          </NavLink>
          {/* Un lector no edita el modelo; enseñarle la pestaña solo lleva a un 403. */}
          {yo.data?.rol !== 'lector' && (
            <>
              <NavLink to="/conexiones" className={({ isActive }) => (isActive ? 'activo' : '')}>
                Conexiones
              </NavLink>
              <NavLink to="/etl" className={({ isActive }) => (isActive ? 'activo' : '')}>
                Transformar
              </NavLink>
              <NavLink to="/flujos" className={({ isActive }) => (isActive ? 'activo' : '')}>
                Flujos
              </NavLink>
              {/* Junto a Flujos porque es de lo mismo: quién se entera cuando uno
                  de ellos se rompe de madrugada. */}
              <NavLink to="/avisos" className={({ isActive }) => (isActive ? 'activo' : '')}>
                Avisos
              </NavLink>
              <NavLink to="/modelos" className={({ isActive }) => (isActive ? 'activo' : '')}>
                Modelo
              </NavLink>
            </>
          )}
          {/* Gobierno es solo de administrador: usuarios, políticas y auditoría. */}
          {yo.data?.rol === 'administrador' && (
            <NavLink to="/gobierno" className={({ isActive }) => (isActive ? 'activo' : '')}>
              Gobierno
            </NavLink>
          )}
        </nav>
        <div className="derecha">
          <span className="chico suave">
            {yo.data?.nombre} · <span className="etiqueta">{yo.data?.rol}</span>
          </span>
          <button className="btn chico" onClick={salir}>
            Salir
          </button>
        </div>
      </header>

      <div className="cuerpo">
        <Routes>
          <Route path="/tableros" element={<Tableros />} />
          <Route path="/tableros/:id" element={<Tablero />} />
          <Route path="/conexiones" element={<Conexiones />} />
          <Route path="/etl" element={<Etl />} />
          <Route path="/flujos" element={<Flujos />} />
          <Route path="/avisos" element={<Avisos />} />
          <Route path="/gobierno" element={<Gobierno />} />
          <Route path="/modelos" element={<Modelos />} />
          <Route path="/modelos/:id" element={<Modelo />} />
          <Route path="*" element={<Navigate to="/tableros" replace />} />
        </Routes>
      </div>
    </div>
  )
}
