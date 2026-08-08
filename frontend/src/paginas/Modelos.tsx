import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useCrearModelo, useModelos, useYo } from '../api/hooks'
import type { Entidad } from '../api/tipos'
import { CuerpoEntidad } from '../modelo/DialogoEntidad'
import { Velo } from '../comunes/Velo'

export function Modelos() {
  const modelos = useModelos()
  const yo = useYo()
  const crear = useCrearModelo()
  const navegar = useNavigate()

  const [nuevo, setNuevo] = useState(false)
  const [nombre, setNombre] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [entidad, setEntidad] = useState<Entidad | null>(null)

  const puedeEditar = yo.data?.rol === 'administrador' || yo.data?.rol === 'editor'

  function cerrar() {
    setNuevo(false)
    setNombre('')
    setDescripcion('')
    setEntidad(null)
    crear.reset()
  }

  return (
    <div className="pagina">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <div>
          <h1>Modelos semánticos</h1>
          <p className="suave chico">
            El modelo define qué significa cada cifra. Todo lo demás —dashboards,
            exploración, fórmulas— se apoya en él.
          </p>
        </div>
        {puedeEditar && (
          <button
            className="btn primario"
            style={{ marginLeft: 'auto' }}
            onClick={() => setNuevo(true)}
          >
            + Nuevo modelo
          </button>
        )}
      </div>

      {modelos.isLoading && <div className="vacio">Cargando…</div>}
      {modelos.isError && (
        <div className="error-caja">{(modelos.error as Error).message}</div>
      )}

      {modelos.data?.length === 0 && (
        <div className="vacio">Todavía no hay ningún modelo.</div>
      )}

      <div className="tarjetas">
        {modelos.data?.map((m) => (
          <Link key={m.id} to={`/modelos/${m.id}`} className="tarjeta">
            <h3>{m.nombre}</h3>
            <p className="chico suave" style={{ margin: '0 0 8px' }}>
              {m.descripcion ?? 'Sin descripción'}
            </p>
            <span className="etiqueta">versión {m.version_actual}</span>
          </Link>
        ))}
      </div>

      {/*
        La primera entidad se elige aquí y no después: un modelo sin ninguna no se
        puede guardar, así que un "crear" que dejara el modelo vacío estaría
        prometiendo algo que el servidor va a rechazar. Lo demás —relaciones,
        métricas, más tablas— se arma en el lienzo, que es donde se ve.
      */}
      {nuevo && (
        <Velo alCerrar={cerrar}>
          <div className="modal ancho">
            <header>Nuevo modelo</header>
            <div className="cont">
              <div className="fila">
                <div className="campo">
                  <label>Nombre</label>
                  <input
                    type="text"
                    value={nombre}
                    onChange={(e) => setNombre(e.target.value)}
                    placeholder="Comercial"
                  />
                </div>
                <div className="campo">
                  <label>Descripción</label>
                  <input
                    type="text"
                    value={descripcion}
                    onChange={(e) => setDescripcion(e.target.value)}
                    placeholder="Qué contesta este modelo"
                  />
                </div>
              </div>

              <h4 style={{ margin: '4px 0 0' }}>Primera tabla</h4>
              <CuerpoEntidad yaUsadas={new Set()} alCambiar={setEntidad} />

              {crear.isError && (
                <div className="error-caja">{(crear.error as Error).message}</div>
              )}
            </div>
            <footer>
              <button className="btn" onClick={cerrar}>
                Cancelar
              </button>
              <button
                className="btn primario"
                disabled={!nombre.trim() || !entidad || crear.isPending}
                onClick={() =>
                  entidad &&
                  crear.mutate(
                    {
                      nombre: nombre.trim(),
                      descripcion: descripcion.trim() || null,
                      definicion: {
                        modelo: nombre.trim(),
                        version: 1,
                        entidades: [entidad],
                      },
                    },
                    { onSuccess: (m) => navegar(`/modelos/${m.id}`) },
                  )
                }
              >
                Crear
              </button>
            </footer>
          </div>
        </Velo>
      )}
    </div>
  )
}
