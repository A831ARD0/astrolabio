/**
 * Usuarios: quién entra, con qué rol, y con qué atributos.
 *
 * Los atributos se editan aquí y no en una pantalla aparte porque son la mitad de
 * una política: `region_id = {{ usuario.region_id }}` no hace nada si la persona no
 * tiene `region_id`. Verlos junto al rol es lo que hace evidente cuando falta uno.
 */

import { useState } from 'react'

import {
  type RolUsuario,
  type UsuarioCompleto,
  useCrearUsuario,
  useEditarUsuario,
  useRestablecerContrasena,
  useUsuarios,
} from '../api/gobierno'

const ROLES: { valor: RolUsuario; que_puede: string }[] = [
  { valor: 'administrador', que_puede: 'todo, y las políticas no le aplican' },
  { valor: 'editor', que_puede: 'modelo, datos y tableros' },
  { valor: 'lector', que_puede: 'ver tableros, con sus políticas aplicadas' },
]

function fecha(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es-MX', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Editor de pares clave/valor. Las claves son las que usan las políticas. */
function EditorAtributos({
  valor,
  alCambiar,
}: {
  valor: Record<string, string>
  alCambiar: (v: Record<string, string>) => void
}) {
  const [clave, setClave] = useState('')
  const [dato, setDato] = useState('')
  const pares = Object.entries(valor)

  const agregar = () => {
    const k = clave.trim()
    if (!k) return
    alCambiar({ ...valor, [k]: dato.trim() })
    setClave('')
    setDato('')
  }

  return (
    <div className="campo">
      <label>Atributos</label>
      <div className="atributos">
        {pares.length === 0 && (
          <span className="chico tenue">
            Ninguno. Una política que necesite un atributo dejará a esta persona
            sin datos, no con datos de más.
          </span>
        )}
        {pares.map(([k, v]) => (
          <span className="chip" key={k}>
            <span className="mono">
              {k} = {v}
            </span>
            <button
              title="Quitar"
              onClick={() => {
                const copia = { ...valor }
                delete copia[k]
                alCambiar(copia)
              }}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="fila-condicion">
        <input
          type="text"
          placeholder="region_id"
          value={clave}
          onChange={(e) => setClave(e.target.value)}
        />
        <input
          type="text"
          placeholder="3"
          value={dato}
          onChange={(e) => setDato(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && agregar()}
        />
        <button className="btn chico" onClick={agregar} disabled={!clave.trim()}>
          Agregar
        </button>
      </div>
    </div>
  )
}

function PanelUsuario({
  usuario,
  alCerrar,
}: {
  usuario: UsuarioCompleto
  alCerrar: () => void
}) {
  const [nombre, setNombre] = useState(usuario.nombre)
  const [rol, setRol] = useState<RolUsuario>(usuario.rol)
  const [activo, setActivo] = useState(usuario.activo)
  const [atributos, setAtributos] = useState(usuario.atributos)
  const [nueva, setNueva] = useState('')

  const editar = useEditarUsuario()
  const restablecer = useRestablecerContrasena()

  return (
    <div className="velo" onClick={alCerrar}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>{usuario.email}</header>
        <div className="cont">
          <div className="campo">
            <label>Nombre</label>
            <input
              type="text"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </div>

          <div className="campo">
            <label>Rol</label>
            <select value={rol} onChange={(e) => setRol(e.target.value as RolUsuario)}>
              {ROLES.map((r) => (
                <option key={r.valor} value={r.valor}>
                  {r.valor}
                </option>
              ))}
            </select>
            <span className="chico tenue">
              {ROLES.find((r) => r.valor === rol)?.que_puede}
            </span>
          </div>

          <label className="casilla">
            <input
              type="checkbox"
              checked={activo}
              onChange={(e) => setActivo(e.target.checked)}
            />
            Puede entrar
          </label>

          <EditorAtributos valor={atributos} alCambiar={setAtributos} />

          {editar.isError && (
            <div className="error-caja">{(editar.error as Error).message}</div>
          )}

          <hr style={{ border: 0, borderTop: '1px solid var(--borde)' }} />

          <div className="campo">
            <label>Restablecer contraseña</label>
            <div className="fila-condicion">
              <input
                type="password"
                placeholder="mínimo 10 caracteres"
                value={nueva}
                onChange={(e) => setNueva(e.target.value)}
              />
              <button
                className="btn chico"
                disabled={nueva.length < 10 || restablecer.isPending}
                onClick={() =>
                  restablecer.mutate(
                    { id: usuario.id, nueva },
                    { onSuccess: () => setNueva('') },
                  )
                }
              >
                Restablecer
              </button>
            </div>
            <span className="chico tenue">
              {restablecer.isSuccess && !nueva
                ? 'Hecho. Dísela por un canal aparte; aquí no se vuelve a mostrar.'
                : 'La anterior no se puede consultar: solo se guarda su hash.'}
            </span>
            {restablecer.isError && (
              <div className="error-caja">
                {(restablecer.error as Error).message}
              </div>
            )}
          </div>
        </div>
        <footer>
          <button className="btn" onClick={alCerrar}>
            Cerrar
          </button>
          <button
            className="btn primario"
            disabled={editar.isPending}
            onClick={() =>
              editar.mutate(
                { id: usuario.id, nombre, rol, activo, atributos },
                { onSuccess: alCerrar },
              )
            }
          >
            Guardar
          </button>
        </footer>
      </div>
    </div>
  )
}

function DialogoNuevo({ alCerrar }: { alCerrar: () => void }) {
  const [email, setEmail] = useState('')
  const [nombre, setNombre] = useState('')
  const [contrasena, setContrasena] = useState('')
  const [rol, setRol] = useState<RolUsuario>('lector')
  const [atributos, setAtributos] = useState<Record<string, string>>({})
  const crear = useCrearUsuario()

  return (
    <div className="velo" onClick={alCerrar}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>Nueva persona</header>
        <div className="cont">
          <div className="campo">
            <label>Correo</label>
            <input
              type="text"
              value={email}
              placeholder="nombre@example.com"
              onChange={(e) => setEmail(e.target.value)}
            />
            <span className="chico tenue">
              No se puede cambiar después: es la identidad con la que queda escrito
              todo el registro de auditoría.
            </span>
          </div>
          <div className="campo">
            <label>Nombre</label>
            <input
              type="text"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
            />
          </div>
          <div className="campo">
            <label>Contraseña temporal</label>
            <input
              type="password"
              value={contrasena}
              placeholder="mínimo 10 caracteres"
              onChange={(e) => setContrasena(e.target.value)}
            />
          </div>
          <div className="campo">
            <label>Rol</label>
            <select value={rol} onChange={(e) => setRol(e.target.value as RolUsuario)}>
              {ROLES.map((r) => (
                <option key={r.valor} value={r.valor}>
                  {r.valor} — {r.que_puede}
                </option>
              ))}
            </select>
          </div>
          <EditorAtributos valor={atributos} alCambiar={setAtributos} />
          {crear.isError && (
            <div className="error-caja">{(crear.error as Error).message}</div>
          )}
        </div>
        <footer>
          <button className="btn" onClick={alCerrar}>
            Cancelar
          </button>
          <button
            className="btn primario"
            disabled={
              !email.trim() ||
              !nombre.trim() ||
              contrasena.length < 10 ||
              crear.isPending
            }
            onClick={() =>
              crear.mutate(
                {
                  email: email.trim(),
                  nombre: nombre.trim(),
                  contrasena,
                  rol,
                  atributos,
                },
                { onSuccess: alCerrar },
              )
            }
          >
            Crear
          </button>
        </footer>
      </div>
    </div>
  )
}

export function Usuarios() {
  const usuarios = useUsuarios()
  const [editando, setEditando] = useState<UsuarioCompleto | null>(null)
  const [nuevo, setNuevo] = useState(false)

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <p className="suave chico" style={{ margin: 0 }}>
          El rol dice qué puede hacer; los atributos, qué filas puede ver.
        </p>
        <button
          className="btn primario chico"
          style={{ marginLeft: 'auto' }}
          onClick={() => setNuevo(true)}
        >
          + Nueva persona
        </button>
      </div>

      {usuarios.isError && (
        <div className="error-caja">{(usuarios.error as Error).message}</div>
      )}

      <div className="tabla-envoltura" style={{ marginTop: 12 }}>
        <table className="datos">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Correo</th>
              <th>Rol</th>
              <th>Atributos</th>
              <th>Último ingreso</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {usuarios.data?.map((u) => (
              <tr key={u.id} style={{ opacity: u.activo ? 1 : 0.5 }}>
                <td>{u.nombre}</td>
                <td className="mono">{u.email}</td>
                <td>
                  <span
                    className={`etiqueta ${u.rol === 'administrador' ? 'critico' : u.rol === 'editor' ? 'dim' : ''}`}
                  >
                    {u.rol}
                  </span>
                  {!u.activo && <span className="etiqueta"> desactivado</span>}
                </td>
                <td className="mono chico">
                  {Object.entries(u.atributos)
                    .map(([k, v]) => `${k}=${v}`)
                    .join('  ') || (
                    <span className="tenue">
                      {u.rol === 'administrador' ? '(no le aplican)' : 'ninguno'}
                    </span>
                  )}
                </td>
                <td className="chico suave">{fecha(u.ultimo_ingreso)}</td>
                <td>
                  <button className="btn chico" onClick={() => setEditando(u)}>
                    Editar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editando && (
        <PanelUsuario
          key={editando.id}
          usuario={editando}
          alCerrar={() => setEditando(null)}
        />
      )}
      {nuevo && <DialogoNuevo alCerrar={() => setNuevo(false)} />}
    </>
  )
}
