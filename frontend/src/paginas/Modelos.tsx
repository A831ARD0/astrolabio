import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import type { ErrorApi } from '../api/cliente'
import { useBorrarModelo, useCrearModelo, useModelos, useYo } from '../api/hooks'
import type { Entidad, ModeloResumen } from '../api/tipos'
import { CuerpoEntidad } from '../modelo/DialogoEntidad'
import { Velo } from '../comunes/Velo'

export function Modelos() {
  const modelos = useModelos()
  const yo = useYo()
  const crear = useCrearModelo()
  const borrar = useBorrarModelo()
  const navegar = useNavigate()

  const [nuevo, setNuevo] = useState(false)
  const [nombre, setNombre] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [entidad, setEntidad] = useState<Entidad | null>(null)
  const [aBorrar, setABorrar] = useState<ModeloResumen | null>(null)
  const [confirmacion, setConfirmacion] = useState('')

  const puedeEditar = yo.data?.rol === 'administrador' || yo.data?.rol === 'editor'
  const puedeBorrar = yo.data?.rol === 'administrador'

  /**
   * Los tableros que impiden borrar. Vienen dentro del 409 y no de otra
   * llamada: preguntar antes «¿tiene tableros?» y borrar después deja una
   * ventana en la que alguien publica uno justo en medio.
   */
  const detalle = (borrar.error as ErrorApi | null)?.detalle as
    | { tableros?: { id: number; nombre: string; publicado: boolean }[] }
    | undefined
  const tablerosQueEstorban = detalle?.tableros ?? []

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
            {puedeBorrar && (
              // Dentro del Link, así que hay que cortarle la navegación: sin
              // esto, pulsar «Borrar» abriría el modelo y el diálogo saldría
              // encima de otra pantalla.
              <button
                className="btn chico peligro borrar-tarjeta"
                title="Borrar el modelo"
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  borrar.reset()
                  setConfirmacion('')
                  setABorrar(m)
                }}
              >
                Borrar
              </button>
            )}
          </Link>
        ))}
      </div>

      {/*
        Se pide teclear el nombre. No es ceremonia: borrar un modelo se lleva su
        historial entero de versiones, y esa es la clase de cosa que no se debe
        poder hacer con el mismo gesto con el que se cierra un aviso.
      */}
      {aBorrar && (
        <Velo alCerrar={() => setABorrar(null)}>
          <div className="modal">
            <header>Borrar «{aBorrar.nombre}»</header>
            <div className="cont">
              <p>
                Se borran el modelo y sus {aBorrar.version_actual} versiones, con
                su historial. No se puede deshacer.
              </p>

              {tablerosQueEstorban.length > 0 ? (
                <div className="error-caja">
                  <div>{(borrar.error as Error).message}</div>
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                    {tablerosQueEstorban.map((t) => (
                      <li key={t.id}>
                        {t.nombre}
                        {t.publicado ? ' (publicado)' : ''}
                      </li>
                    ))}
                  </ul>
                  <div className="chico" style={{ marginTop: 6 }}>
                    Bórralos o muévelos a otro modelo primero.
                  </div>
                </div>
              ) : (
                borrar.isError && (
                  <div className="error-caja">{(borrar.error as Error).message}</div>
                )
              )}

              <div className="campo">
                <label>
                  Escribe <span className="mono">{aBorrar.nombre}</span> para
                  confirmar
                </label>
                <input
                  type="text"
                  className="mono"
                  autoFocus
                  value={confirmacion}
                  onChange={(e) => setConfirmacion(e.target.value)}
                />
              </div>
            </div>
            <footer>
              <button className="btn" onClick={() => setABorrar(null)}>
                Cancelar
              </button>
              <button
                className="btn peligro"
                disabled={confirmacion !== aBorrar.nombre || borrar.isPending}
                onClick={() =>
                  borrar.mutate(aBorrar.id, { onSuccess: () => setABorrar(null) })
                }
              >
                {borrar.isPending ? 'Borrando…' : 'Borrar'}
              </button>
            </footer>
          </div>
        </Velo>
      )}

      {/*
        La primera entidad se elige aquí y no después: un modelo sin ninguna no se
        puede guardar, así que un "crear" que dejara el modelo vacío estaría
        prometiendo algo que el servidor va a rechazar. Lo demás —relaciones,
        métricas, más tablas— se arma en el lienzo, que es donde se ve.
      */}
      {nuevo && (
        <Velo alCerrar={cerrar}>
          {/* La misma caja que «Agregar entidad»: dentro va el mismo trabajo
              —elegir tabla y repasar sus columnas— y verlo en dos tamaños
              distintos hace pensar que son dos cosas distintas. */}
          <div className="modal entidad">
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
