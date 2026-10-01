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
  useDesbloquearUsuario,
  useEditarUsuario,
  useRestablecerContrasena,
  useUsuarios,
} from '../api/gobierno'
import { useOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'
import { Velo } from '../comunes/Velo'
import { CampoContrasena } from './CampoContrasena'

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

/**
 * El bloqueo por intentos fallidos, con su botón para quitarlo.
 *
 * Hasta ahora no se veía en ningún sitio: el contador vive en la memoria del
 * servicio, no en la tabla de usuarios, y la única salida era esperar o reiniciar
 * —que suelta a todas las cuentas a la vez, también a la que alguien esté
 * atacando—.
 */
function Bloqueo({ u }: { u: UsuarioCompleto }) {
  const desbloquear = useDesbloquearUsuario()
  if (!u.bloqueado_segundos) return null
  const minutos = Math.max(1, Math.ceil(u.bloqueado_segundos / 60))
  return (
    <>
      {' '}
      <span className="etiqueta aviso"
            title="Demasiadas contraseñas equivocadas seguidas. Se quita solo al pasar el tiempo.">
        bloqueado · {minutos} min
      </span>{' '}
      <button className="btn chico" disabled={desbloquear.isPending}
              onClick={() => desbloquear.mutate(u.id)}>
        {desbloquear.isPending ? 'Desbloqueando…' : 'Desbloquear'}
      </button>
    </>
  )
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
  /** La última que se guardó, para decir «hecha» mientras siga en el campo. */
  const [guardada, setGuardada] = useState('')

  const editar = useEditarUsuario()
  const restablecer = useRestablecerContrasena()

  // Una contraseña escrita o generada que todavía no se ha guardado. Antes el
  // Guardar de abajo la ignoraba —solo mandaba nombre, rol, activo y atributos— y
  // cerraba el panel: la contraseña no cambiaba y la generada se perdía, así que
  // el administrador le daba a la persona una contraseña que no funcionaba.
  const pendiente = nueva !== '' && nueva !== guardada
  const [avisarDescarte, setAvisarDescarte] = useState(false)

  /** Cerrar sin perder en silencio una contraseña que no se guardó. */
  const intentarCerrar = () => {
    if (pendiente && !avisarDescarte) return setAvisarDescarte(true)
    alCerrar()
  }

  const guardar = async () => {
    const conContrasena = pendiente
    if (conContrasena) {
      await restablecer.mutateAsync({ id: usuario.id, nueva })
      setGuardada(nueva)
      setAvisarDescarte(false)
    }
    await editar.mutateAsync({ id: usuario.id, nombre, rol, activo, atributos })
    // Si se acaba de poner una contraseña, el panel se queda abierto: es el único
    // momento en que se puede copiar, y cerrarlo ahora la haría desaparecer.
    if (!conContrasena) alCerrar()
  }

  return (
    <Velo alCerrar={intentarCerrar}>
      <div className="modal">
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
            {/* La nueva se queda en el campo al guardar. Antes se vaciaba en el
                acto, que es justo cuando hace falta copiarla para dársela. */}
            <CampoContrasena valor={nueva} alCambiar={(v) => {
              setNueva(v)
              setGuardada('')
            }} />
            <div className="fila-condicion" style={{ marginTop: 6 }}>
              <button
                className="btn chico primario"
                disabled={nueva.length < 10 || nueva === guardada || restablecer.isPending}
                onClick={() =>
                  restablecer.mutate(
                    { id: usuario.id, nueva },
                    { onSuccess: () => setGuardada(nueva) },
                  )
                }
              >
                {restablecer.isPending ? 'Restableciendo…' : 'Restablecer'}
              </button>
            </div>
            <span className="chico tenue">
              {guardada && guardada === nueva
                ? 'Guardada. Cópiala ahora y dásela por un canal aparte: al ' +
                  'cerrar este panel no se vuelve a poder ver.'
                : 'La anterior no se puede consultar: solo se guarda su hash. ' +
                  'Restablecerla también quita el bloqueo por intentos fallidos.'}
            </span>
            {restablecer.isError && (
              <div className="error-caja">
                {(restablecer.error as Error).message}
              </div>
            )}
          </div>
        </div>
        {avisarDescarte && pendiente && (
          <div className="aviso-caja" style={{ margin: '0 16px 12px' }}>
            La contraseña nueva <strong>no se ha guardado</strong>. Pulsa
            «Guardar» para ponérsela, o «Cerrar» otra vez para descartarla.
          </div>
        )}
        {(editar.isError || restablecer.isError) && (
          <div className="error-caja" style={{ margin: '0 16px 12px' }}>
            {((editar.error ?? restablecer.error) as Error).message}
          </div>
        )}
        <footer>
          <button className="btn" onClick={intentarCerrar}>
            Cerrar
          </button>
          <button
            className="btn primario"
            disabled={
              editar.isPending ||
              restablecer.isPending ||
              (pendiente && nueva.length < 10)
            }
            title={pendiente && nueva.length < 10
              ? 'La contraseña nueva necesita al menos 10 caracteres' : undefined}
            onClick={() => {
              guardar().catch(() => {})
            }}
          >
            {editar.isPending || restablecer.isPending
              ? 'Guardando…'
              : pendiente ? 'Guardar, con la contraseña nueva' : 'Guardar'}
          </button>
        </footer>
      </div>
    </Velo>
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
    <Velo alCerrar={alCerrar}>
      <div className="modal">
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
            <CampoContrasena valor={contrasena} alCambiar={setContrasena} />
            <span className="chico tenue">
              Cópiala antes de crear la cuenta: después solo se guarda su hash y no
              se puede volver a ver.
            </span>
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
    </Velo>
  )
}

export function Usuarios() {
  const usuarios = useUsuarios()
  const [editando, setEditando] = useState<UsuarioCompleto | null>(null)
  const [nuevo, setNuevo] = useState(false)

  const orden = useOrden(
    usuarios.data ?? [],
    (u, clave) =>
      clave === 'nombre' ? u.nombre
      : clave === 'email' ? u.email
      : clave === 'rol' ? u.rol
      : clave === 'atributos'
        ? Object.entries(u.atributos).map(([k, v]) => `${k}=${v}`).join(' ')
        : u.ultimo_ingreso,
  )

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
              <Th orden={orden} clave="nombre">Nombre</Th>
              <Th orden={orden} clave="email">Correo</Th>
              <Th orden={orden} clave="rol">Rol</Th>
              <Th orden={orden} clave="atributos">Atributos</Th>
              <Th orden={orden} clave="ingreso">Último ingreso</Th>
              <th />
            </tr>
          </thead>
          <tbody>
            {orden.filas.map((u) => (
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
                  <Bloqueo u={u} />
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
