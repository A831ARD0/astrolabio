/**
 * Diagnóstico del modelo.
 *
 * No es una lista de advertencias decorativa: una ruta ambigua significa que dos
 * caminos igual de válidos pueden dar cifras distintas, y el motor se niega a
 * elegir por su cuenta. Al pulsar un problema se resaltan en el lienzo las
 * entidades implicadas, porque un aviso que no dice *dónde* obliga a buscarlo a
 * mano.
 */

import type { Problema } from '../api/tipos'

export function PanelDiagnostico({
  problemas,
  alResaltar,
}: {
  problemas: Problema[]
  alResaltar: (entidades: Set<string> | null) => void
}) {
  const criticos = problemas.filter((p) => p.gravedad === 'critico')

  if (problemas.length === 0) {
    return (
      <div className="vacio">
        Sin problemas detectados: ninguna ruta ambigua, ninguna tabla aislada.
      </div>
    )
  }

  return (
    <div className="inspector">
      <h3>
        Diagnóstico{' '}
        {criticos.length > 0 && (
          <span className="etiqueta critico">{criticos.length} crítico(s)</span>
        )}
      </h3>

      <div className="problemas">
        {problemas.map((p, i) => (
          <button
            key={i}
            className={`problema ${p.gravedad}`}
            onMouseEnter={() => alResaltar(entidadesDe(p))}
            onMouseLeave={() => alResaltar(null)}
            onClick={() => alResaltar(entidadesDe(p))}
          >
            <div className="quien">{p.entidad}</div>
            <div className="msg">{p.mensaje}</div>
            {p.rutas && (
              <div className="rutas">
                {p.rutas.map((r) => (
                  <code key={r}>{r}</code>
                ))}
              </div>
            )}
          </button>
        ))}
      </div>

      {criticos.length > 0 && (
        <div className="chico suave">
          Un modelo con rutas ambiguas se puede guardar —a veces la ambigüedad es
          legítima y se resuelve al consultar, eligiendo el camino—, pero mientras
          exista, cualquier consulta que la cruce fallará pidiendo que elijas.
        </div>
      )}
    </div>
  )
}

function entidadesDe(p: Problema): Set<string> {
  const s = new Set<string>()
  for (const parte of p.entidad.split(/→|↔/)) s.add(parte.trim())
  for (const ruta of p.rutas ?? []) {
    for (const parte of ruta.split('→')) s.add(parte.trim())
  }
  return s
}
