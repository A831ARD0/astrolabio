import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useCrearDashboard, useDashboards, useModelos, useYo } from '../api/hooks'
import { Velo } from '../comunes/Velo'

export function Tableros() {
  const tableros = useDashboards()
  const modelos = useModelos()
  const yo = useYo()
  const crear = useCrearDashboard()
  const navegar = useNavigate()

  const [nuevo, setNuevo] = useState(false)
  const [nombre, setNombre] = useState('')
  const [modeloId, setModeloId] = useState<number | ''>('')

  const puedeEditar = yo.data?.rol === 'administrador' || yo.data?.rol === 'editor'

  return (
    <div className="pagina">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <div>
          <h1>Tableros</h1>
          <p className="suave chico">
            Cada tablero está anclado a una versión del modelo, así que sus cifras
            no cambian por su cuenta.
          </p>
        </div>
        {puedeEditar && (
          <button
            className="btn primario"
            style={{ marginLeft: 'auto' }}
            onClick={() => setNuevo(true)}
          >
            + Nuevo tablero
          </button>
        )}
      </div>

      {tableros.isLoading && <div className="vacio">Cargando…</div>}
      {tableros.isError && (
        <div className="error-caja">{(tableros.error as Error).message}</div>
      )}
      {tableros.data?.length === 0 && (
        <div className="vacio">Todavía no hay ningún tablero.</div>
      )}

      <div className="tarjetas">
        {tableros.data?.map((t) => (
          <Link key={t.id} to={`/tableros/${t.id}`} className="tarjeta">
            <h3>{t.nombre}</h3>
            <p className="chico suave" style={{ margin: '0 0 8px' }}>
              {t.definicion.widgets.length} widget(s) ·{' '}
              {t.modelo_nombre} v{t.version_modelo}
            </p>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {t.certificado && <span className="etiqueta ok">certificado</span>}
              {t.publicado ? (
                <span className="etiqueta dim">publicado</span>
              ) : (
                <span className="etiqueta">borrador</span>
              )}
              {t.version_modelo !== t.version_vigente_del_modelo && (
                <span
                  className="etiqueta aviso"
                  title={`El modelo va por la v${t.version_vigente_del_modelo}`}
                >
                  modelo más nuevo
                </span>
              )}
            </div>
          </Link>
        ))}
      </div>

      {nuevo && (
        <Velo alCerrar={() => setNuevo(false)}>
          <div className="modal">
            <header>Nuevo tablero</header>
            <div className="cont">
              <div className="campo">
                <label>Nombre</label>
                <input
                  type="text"
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  placeholder="Comercial — venta mensual"
                />
              </div>
              <div className="campo">
                <label>Modelo</label>
                <select
                  value={modeloId}
                  onChange={(e) => setModeloId(Number(e.target.value))}
                >
                  <option value="">(elige uno)</option>
                  {modelos.data?.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.nombre} — v{m.version_actual}
                    </option>
                  ))}
                </select>
                <span className="chico tenue">
                  Se ancla a la versión vigente. Se puede mover después, a
                  propósito.
                </span>
              </div>
              {crear.isError && (
                <div className="error-caja">{(crear.error as Error).message}</div>
              )}
            </div>
            <footer>
              <button className="btn" onClick={() => setNuevo(false)}>
                Cancelar
              </button>
              <button
                className="btn primario"
                disabled={!nombre.trim() || !modeloId || crear.isPending}
                onClick={() =>
                  crear.mutate(
                    { nombre: nombre.trim(), modelo_id: Number(modeloId) },
                    { onSuccess: (d) => navegar(`/tableros/${d.id}`) },
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
