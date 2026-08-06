/**
 * El editor de un paso.
 *
 * Todo lo que se elige aquí sale del esquema real de los datos: las columnas
 * vienen del origen, los operadores y las funciones del compilador. El usuario no
 * teclea nombres de columna, y por eso no puede escribir uno que no existe.
 *
 * La excepción es la columna calculada, donde sí se escribe una expresión. Ahí es
 * inevitable —es la parte "fórmula" de la herramienta— y el backend la valida
 * sobre el árbol de SQL antes de aceptarla.
 */

import {
  DE_LISTA,
  FUNCIONES,
  OPERADORES,
  SIN_VALOR,
  type Agregado,
  type Condicion,
  type Origen,
  type Paso,
} from '../api/etl'

interface Props {
  paso: Paso
  columnas: string[]
  origenes: Origen[]
  /** Columnas del origen con el que se va a unir, si el paso es 'unir'. */
  columnasDerecha: string[]
  alCambiar: (cambios: Partial<Paso>) => void
}

export function PasoEditor({
  paso,
  columnas,
  origenes,
  columnasDerecha,
  alCambiar,
}: Props) {
  switch (paso.tipo) {
    case 'filtrar':
      return <Filtrar paso={paso} columnas={columnas} alCambiar={alCambiar} />
    case 'columnas':
      return <Columnas paso={paso} columnas={columnas} alCambiar={alCambiar} />
    case 'renombrar':
      return <Renombrar paso={paso} columnas={columnas} alCambiar={alCambiar} />
    case 'derivar':
      return <Derivar paso={paso} columnas={columnas} alCambiar={alCambiar} />
    case 'agrupar':
      return <Agrupar paso={paso} columnas={columnas} alCambiar={alCambiar} />
    case 'unir':
      return (
        <Unir
          paso={paso}
          columnas={columnas}
          origenes={origenes}
          columnasDerecha={columnasDerecha}
          alCambiar={alCambiar}
        />
      )
    case 'apilar':
      return <Apilar paso={paso} origenes={origenes} alCambiar={alCambiar} />
    case 'ordenar':
      return <Ordenar paso={paso} columnas={columnas} alCambiar={alCambiar} />
    case 'limitar':
      return (
        <div className="campo">
          <label>Quedarse con las primeras</label>
          <input
            type="number"
            min={1}
            value={paso.n ?? 1000}
            onChange={(e) => alCambiar({ n: Number(e.target.value) || 1000 })}
          />
        </div>
      )
    case 'distintos':
      return (
        <p className="chico suave" style={{ margin: 0 }}>
          Deja una sola fila por combinación de valores idéntica.
        </p>
      )
    default:
      return null
  }
}

// --------------------------------------------------------------------------- //

function SelectorColumna({
  valor,
  columnas,
  alCambiar,
  vacio = '(columna)',
}: {
  valor: string | undefined
  columnas: string[]
  alCambiar: (v: string) => void
  vacio?: string
}) {
  return (
    <select value={valor ?? ''} onChange={(e) => alCambiar(e.target.value)}>
      <option value="">{vacio}</option>
      {columnas.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  )
}

function Filtrar({
  paso,
  columnas,
  alCambiar,
}: {
  paso: Paso
  columnas: string[]
  alCambiar: (c: Partial<Paso>) => void
}) {
  const condiciones = paso.condiciones ?? []
  const set = (i: number, cambios: Partial<Condicion>) =>
    alCambiar({
      condiciones: condiciones.map((c, j) => (i === j ? { ...c, ...cambios } : c)),
    })

  return (
    <div className="paso-cuerpo">
      {condiciones.length > 1 && (
        <div className="campo">
          <label>Se cumplen</label>
          <select
            value={paso.modo ?? 'y'}
            onChange={(e) => alCambiar({ modo: e.target.value as 'y' | 'o' })}
          >
            <option value="y">todas las condiciones</option>
            <option value="o">al menos una</option>
          </select>
        </div>
      )}

      {condiciones.map((c, i) => (
        <div className="fila-condicion" key={i}>
          <SelectorColumna
            valor={c.campo}
            columnas={columnas}
            alCambiar={(v) => set(i, { campo: v })}
          />
          <select value={c.op} onChange={(e) => set(i, { op: e.target.value })}>
            {OPERADORES.map((o) => (
              <option key={o} value={o}>
                {o.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          {!SIN_VALOR.has(c.op) && (
            <input
              type="text"
              value={
                Array.isArray(c.valor) ? (c.valor as unknown[]).join(', ') : String(c.valor ?? '')
              }
              placeholder={DE_LISTA.has(c.op) ? 'A, B, C' : 'valor'}
              onChange={(e) =>
                set(i, {
                  valor: DE_LISTA.has(c.op)
                    ? e.target.value.split(',').map((s) => s.trim()).filter(Boolean)
                    : convertir(e.target.value),
                })
              }
            />
          )}
          <button
            className="btn chico"
            onClick={() =>
              alCambiar({ condiciones: condiciones.filter((_, j) => j !== i) })
            }
          >
            ✕
          </button>
        </div>
      ))}

      <button
        className="btn chico"
        onClick={() =>
          alCambiar({
            condiciones: [...condiciones, { campo: columnas[0] ?? '', op: '=', valor: '' }],
          })
        }
      >
        + condición
      </button>
    </div>
  )
}

/**
 * `"0"` es un número y `"true"` un booleano. Mandar todo como texto haría que un
 * filtro sobre una columna numérica no encontrara nada, sin error visible.
 */
function convertir(texto: string): unknown {
  const t = texto.trim()
  if (t === '') return ''
  if (t === 'true') return true
  if (t === 'false') return false
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t)
  return texto
}

function Columnas({
  paso,
  columnas,
  alCambiar,
}: {
  paso: Paso
  columnas: string[]
  alCambiar: (c: Partial<Paso>) => void
}) {
  const mantener = paso.mantener ?? []
  return (
    <div className="paso-cuerpo">
      <p className="chico suave" style={{ margin: 0 }}>
        Marca las que se quedan. Sin ninguna marcada se quedan todas.
      </p>
      <div className="casillas">
        {columnas.map((c) => (
          <label key={c} className="casilla">
            <input
              type="checkbox"
              checked={mantener.includes(c)}
              onChange={(e) =>
                alCambiar({
                  mantener: e.target.checked
                    ? [...mantener, c]
                    : mantener.filter((x) => x !== c),
                })
              }
            />
            <span className="mono">{c}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

function Renombrar({
  paso,
  columnas,
  alCambiar,
}: {
  paso: Paso
  columnas: string[]
  alCambiar: (c: Partial<Paso>) => void
}) {
  const cambios = paso.cambios ?? {}
  return (
    <div className="paso-cuerpo">
      {Object.entries(cambios).map(([de, a], i) => (
        <div className="fila-condicion" key={`${de}-${i}`}>
          <SelectorColumna
            valor={de}
            columnas={columnas}
            alCambiar={(v) => {
              const otros = { ...cambios }
              delete otros[de]
              alCambiar({ cambios: { ...otros, [v]: a } })
            }}
          />
          <span className="tenue">→</span>
          <input
            type="text"
            value={a}
            onChange={(e) => alCambiar({ cambios: { ...cambios, [de]: e.target.value } })}
          />
          <button
            className="btn chico"
            onClick={() => {
              const otros = { ...cambios }
              delete otros[de]
              alCambiar({ cambios: otros })
            }}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        className="btn chico"
        onClick={() => {
          const libre = columnas.find((c) => !(c in cambios))
          if (libre) alCambiar({ cambios: { ...cambios, [libre]: libre } })
        }}
      >
        + renombre
      </button>
    </div>
  )
}

function Derivar({
  paso,
  columnas,
  alCambiar,
}: {
  paso: Paso
  columnas: string[]
  alCambiar: (c: Partial<Paso>) => void
}) {
  return (
    <div className="paso-cuerpo">
      <div className="campo">
        <label>Nombre de la columna nueva</label>
        <input
          type="text"
          className="mono"
          value={paso.nombre ?? ''}
          placeholder="neto"
          onChange={(e) => alCambiar({ nombre: e.target.value })}
        />
      </div>
      <div className="campo">
        <label>Cálculo</label>
        <textarea
          rows={2}
          value={paso.expresion ?? ''}
          placeholder="monto_base - monto_impuesto"
          onChange={(e) => alCambiar({ expresion: e.target.value })}
        />
      </div>
      <div className="chico">
        <span className="suave">Columnas: </span>
        {columnas.slice(0, 30).map((c) => (
          <button
            key={c}
            className="btn chico mono"
            style={{ margin: '2px 3px 0 0' }}
            onClick={() => alCambiar({ expresion: (paso.expresion ?? '') + c })}
          >
            {c}
          </button>
        ))}
      </div>
    </div>
  )
}

function Agrupar({
  paso,
  columnas,
  alCambiar,
}: {
  paso: Paso
  columnas: string[]
  alCambiar: (c: Partial<Paso>) => void
}) {
  const por = paso.por ?? []
  const agregados = paso.agregados ?? []
  const set = (i: number, cambios: Partial<Agregado>) =>
    alCambiar({
      agregados: agregados.map((a, j) => (i === j ? { ...a, ...cambios } : a)),
    })

  return (
    <div className="paso-cuerpo">
      <div>
        <div className="chico suave">Agrupar por</div>
        <div className="casillas">
          {columnas.map((c) => (
            <label key={c} className="casilla">
              <input
                type="checkbox"
                checked={por.includes(c)}
                onChange={(e) =>
                  alCambiar({
                    por: e.target.checked ? [...por, c] : por.filter((x) => x !== c),
                  })
                }
              />
              <span className="mono">{c}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="chico suave">Resumir</div>
      {agregados.map((a, i) => (
        <div className="fila-condicion" key={i}>
          <select value={a.funcion} onChange={(e) => set(i, { funcion: e.target.value })}>
            {FUNCIONES.map((f) => (
              <option key={f} value={f}>
                {f.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <SelectorColumna
            valor={a.campo ?? ''}
            columnas={columnas}
            alCambiar={(v) => set(i, { campo: v || null })}
            vacio={a.funcion === 'cuenta' ? '(todas las filas)' : '(columna)'}
          />
          <span className="tenue">→</span>
          <input
            type="text"
            className="mono"
            value={a.nombre}
            placeholder="nombre"
            onChange={(e) => set(i, { nombre: e.target.value })}
          />
          <button
            className="btn chico"
            onClick={() => alCambiar({ agregados: agregados.filter((_, j) => j !== i) })}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        className="btn chico"
        onClick={() =>
          alCambiar({
            agregados: [...agregados, { nombre: 'total', funcion: 'suma', campo: null }],
          })
        }
      >
        + resumen
      </button>
    </div>
  )
}

function Unir({
  paso,
  columnas,
  origenes,
  columnasDerecha,
  alCambiar,
}: {
  paso: Paso
  columnas: string[]
  origenes: Origen[]
  columnasDerecha: string[]
  alCambiar: (c: Partial<Paso>) => void
}) {
  const en = paso.en ?? []
  const traer = paso.traer ?? []

  return (
    <div className="paso-cuerpo">
      <div className="fila-condicion">
        <div className="campo">
          <label>Con</label>
          <select
            value={typeof paso.con === 'string' ? paso.con : ''}
            onChange={(e) => alCambiar({ con: e.target.value })}
          >
            <option value="">(origen)</option>
            {origenes.map((o) => (
              <option key={o.nombre} value={o.nombre}>
                {o.nombre}
              </option>
            ))}
          </select>
        </div>
        <div className="campo">
          <label>Tipo</label>
          <select
            value={paso.como ?? 'izquierda'}
            onChange={(e) => alCambiar({ como: e.target.value as Paso['como'] })}
          >
            <option value="izquierda">izquierda — conserva todas las de la izquierda</option>
            <option value="interna">interna — solo las que hacen pareja</option>
            <option value="derecha">derecha</option>
            <option value="completa">completa</option>
          </select>
        </div>
      </div>

      <div className="chico suave">Emparejar por</div>
      {en.map(([izq, der], i) => (
        <div className="fila-condicion" key={i}>
          <SelectorColumna
            valor={izq}
            columnas={columnas}
            alCambiar={(v) =>
              alCambiar({ en: en.map((p, j) => (i === j ? [v, p[1]] : p)) })
            }
          />
          <span className="tenue">=</span>
          <SelectorColumna
            valor={der}
            columnas={columnasDerecha}
            alCambiar={(v) =>
              alCambiar({ en: en.map((p, j) => (i === j ? [p[0], v] : p)) })
            }
          />
          <button
            className="btn chico"
            onClick={() => alCambiar({ en: en.filter((_, j) => j !== i) })}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        className="btn chico"
        onClick={() =>
          alCambiar({ en: [...en, [columnas[0] ?? '', columnasDerecha[0] ?? '']] })
        }
      >
        + pareja
      </button>

      {columnasDerecha.length > 0 && (
        <div>
          <div className="chico suave">
            Traer del otro origen (sin marcar: todas menos las de emparejar)
          </div>
          <div className="casillas">
            {columnasDerecha.map((c) => (
              <label key={c} className="casilla">
                <input
                  type="checkbox"
                  checked={traer.includes(c)}
                  onChange={(e) =>
                    alCambiar({
                      traer: e.target.checked
                        ? [...traer, c]
                        : traer.filter((x) => x !== c),
                    })
                  }
                />
                <span className="mono">{c}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Apilar({
  paso,
  origenes,
  alCambiar,
}: {
  paso: Paso
  origenes: Origen[]
  alCambiar: (c: Partial<Paso>) => void
}) {
  const con = Array.isArray(paso.con) ? paso.con : []
  return (
    <div className="paso-cuerpo">
      <p className="chico suave" style={{ margin: 0 }}>
        Pega las filas de otros orígenes debajo. Se emparejan <b>por nombre de
        columna</b>, no por posición.
      </p>
      <div className="casillas">
        {origenes.map((o) => (
          <label key={o.nombre} className="casilla">
            <input
              type="checkbox"
              checked={con.includes(o.nombre)}
              onChange={(e) =>
                alCambiar({
                  con: e.target.checked
                    ? [...con, o.nombre]
                    : con.filter((x) => x !== o.nombre),
                })
              }
            />
            <span className="mono">{o.nombre}</span>
          </label>
        ))}
      </div>
      <label className="casilla">
        <input
          type="checkbox"
          checked={!!paso.quitar_repetidas}
          onChange={(e) => alCambiar({ quitar_repetidas: e.target.checked })}
        />
        <span>Quitar filas repetidas</span>
      </label>
    </div>
  )
}

function Ordenar({
  paso,
  columnas,
  alCambiar,
}: {
  paso: Paso
  columnas: string[]
  alCambiar: (c: Partial<Paso>) => void
}) {
  const por = paso.por ?? []
  return (
    <div className="paso-cuerpo">
      <div className="casillas">
        {columnas.map((c) => (
          <label key={c} className="casilla">
            <input
              type="checkbox"
              checked={por.includes(c)}
              onChange={(e) =>
                alCambiar({
                  por: e.target.checked ? [...por, c] : por.filter((x) => x !== c),
                })
              }
            />
            <span className="mono">{c}</span>
          </label>
        ))}
      </div>
      <label className="casilla">
        <input
          type="checkbox"
          checked={!!paso.descendente}
          onChange={(e) => alCambiar({ descendente: e.target.checked })}
        />
        <span>De mayor a menor</span>
      </label>
    </div>
  )
}
