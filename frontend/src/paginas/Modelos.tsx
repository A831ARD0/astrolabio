import { Link } from 'react-router-dom'

import { useModelos } from '../api/hooks'

export function Modelos() {
  const modelos = useModelos()

  return (
    <div className="pagina">
      <h1>Modelos semánticos</h1>
      <p className="suave chico">
        El modelo define qué significa cada cifra. Todo lo demás —dashboards,
        exploración, fórmulas— se apoya en él.
      </p>

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
    </div>
  )
}
