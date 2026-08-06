/**
 * Nueva conexión: **probar y luego guardar**, en ese orden y sin atajo.
 *
 * No se puede guardar una conexión que no se ha probado, y cualquier cambio en la
 * configuración invalida la prueba anterior. La comprobación no es "¿se pulsó el
 * botón?" sino "¿la configuración probada es exactamente esta?": se guarda una
 * huella de lo que se probó y se compara. Así no hay forma de probar con un
 * servidor, cambiarlo, y guardar apoyado en un visto bueno que ya no vale.
 *
 * El backend prueba otra vez al crear y se niega a guardar lo que no conecta —esa
 * es la garantía de verdad, porque un cliente se puede saltar—, pero descubrirlo
 * al final, con la contraseña ya escrita y un 400 en la cara, es peor.
 *
 * Ningún botón se desactiva en silencio: si no se puede pulsar, la línea de arriba
 * dice qué falta. Un botón gris sin motivo parece una aplicación rota.
 *
 * Los campos obligatorios los dice el servidor (`/conexiones/tipos`), no una lista
 * escrita aquí: cuando se agregue el conector ODBC, este formulario ya lo sabrá.
 */

import { useState } from 'react'

import {
  type CampoPerfil,
  type CuerpoConexion,
  useCrearConexion,
  useOdbcInstalado,
  useOdbcPerfiles,
  useProbarConfig,
  useTiposConexion,
} from '../api/conexiones'

/** Etiquetas y ayudas de los campos que conocemos. Lo demás se muestra tal cual. */
const CAMPOS: Record<
  string,
  { etiqueta: string; ayuda?: string; secreto?: boolean; numero?: boolean }
> = {
  host: { etiqueta: 'Servidor', ayuda: '127.0.0.1 o el nombre de la máquina' },
  port: { etiqueta: 'Puerto', numero: true },
  user: { etiqueta: 'Usuario' },
  password: {
    etiqueta: 'Contraseña',
    secreto: true,
    ayuda: 'Se guarda cifrada y no se vuelve a mostrar nunca.',
  },
  database: { etiqueta: 'Base de datos' },
  ruta_base: {
    etiqueta: 'Carpeta',
    ayuda: 'Ruta en el servidor. Solo se leen archivos de dentro de esta carpeta.',
  },
  dsn: {
    etiqueta: 'DSN',
    ayuda: 'Si sistemas ya configuró el origen en el servidor, con esto basta.',
  },
  driver: {
    etiqueta: 'Driver',
    ayuda: 'El nombre registrado, o la ruta del archivo del driver (.dylib/.so/.dll).',
  },
  cadena: {
    etiqueta: 'Cadena completa',
    ayuda: 'DRIVER={…};SERVER=…  Si la pones, manda ella y lo demás se ignora.',
  },
  extra: { etiqueta: 'Opciones extra', ayuda: 'Se pegan tal cual: OPCION=valor;OTRA=…' },
}

const PREDETERMINADOS: Record<string, Record<string, unknown>> = {
  mysql: { host: '127.0.0.1', port: 3306 },
}

/** Nombres de los tipos que conocemos. El id crudo ('mysql') no es una etiqueta. */
const TIPOS_NOMBRE: Record<string, string> = {
  mysql: 'MySQL / MariaDB',
  archivo: 'Archivos — CSV, Excel, Parquet',
  odbc: 'ODBC — Pervasive/Actian, SQL Server, Informix y demás',
}

const NOTAS: Record<string, string> = {
  odbc:
    'Elige el origen y el formulario pide solo lo que ese driver necesita: cada uno ' +
    'llama distinto a lo mismo (el servidor es SERVER en SQL Server, SERVERNAME en ' +
    'Pervasive y HOST en Informix), y la cadena la arma el servidor. ODBC es más ' +
    'lento que un conector propio: es para lo que no tiene conector.',
}

/**
 * Un campo del formulario. `pista` la manda el servidor (perfiles ODBC) y `ayuda`
 * la sabe esta pantalla (conectores nativos); se pintan igual.
 */
type Campo = CampoPerfil & { ayuda?: string; numero?: boolean }

export function DialogoConexion({ alCerrar }: { alCerrar: () => void }) {
  const tipos = useTiposConexion()
  const probar = useProbarConfig()
  const crear = useCrearConexion()

  const [nombre, setNombre] = useState('')
  const [tipo, setTipo] = useState('')
  const [valores, setValores] = useState<Record<string, unknown>>({})
  /** Huella de la configuración de la última prueba, saliera bien o mal. */
  const [intento, setIntento] = useState<string | null>(null)
  const odbc = useOdbcInstalado(tipo === 'odbc')
  const perfiles = useOdbcPerfiles(tipo === 'odbc')

  const def = tipos.data?.tipos.find((t) => t.tipo === tipo)
  const perfil = perfiles.data?.perfiles.find((p) => p.clave === valores.perfil)

  // Con un perfil ODBC elegido, los campos son los de ese origen y nada más: el
  // formulario genérico mostraba las once claves posibles de ODBC a la vez, y con
  // once casillas ninguna parece la que hay que llenar.
  const campos: Campo[] = perfil
    ? [
        // El driver va primero porque es lo que puede faltar en la máquina, y
        // enterarse al final es lo que hace perder la tarde.
        ...(perfil.plantilla
          ? [
              {
                clave: 'driver',
                etiqueta: 'Driver',
                requerido: true,
                pista: perfil.instalado
                  ? 'Detectado en este servidor.'
                  : `No está instalado aquí. ${perfil.driver?.de_donde ?? ''}`,
              },
            ]
          : []),
        ...perfil.campos,
      ]
    : tipo === 'odbc'
      ? // Sin origen elegido no hay campos que pedir. La lista genérica de ODBC
        // son once casillas, y con once ninguna parece la que hay que llenar.
        []
      : def
      ? // Los campos, obligatorios y opcionales, los dice el servidor. Cuando entre
        // un conector nuevo este formulario ya lo sabrá.
        [
          ...def.requeridos.map((c) => ({ clave: c, requerido: true, ...CAMPOS[c], etiqueta: CAMPOS[c]?.etiqueta ?? c })),
          ...def.opcionales.map((c) => ({ clave: c, ...CAMPOS[c], etiqueta: CAMPOS[c]?.etiqueta ?? c })),
        ]
      : []

  const faltan = campos.filter(
    (c) => c.requerido && !String(valores[c.clave] ?? '').trim(),
  )
  // Sin origen elegido no hay nada que probar: los campos ni se sabe cuáles son.
  const faltaPerfil = tipo === 'odbc' && !perfil
  const listo = !!nombre.trim() && !!tipo && !faltaPerfil && faltan.length === 0

  // El nombre no entra en la huella: es una etiqueta nuestra, no algo que el
  // servidor de datos vea. Corregir una errata en el nombre no cambia si la
  // conexión conecta, y obligar a probar otra vez por eso enseña que el botón es
  // arbitrario.
  const huella = JSON.stringify([tipo, valores])
  /** El resultado a la vista solo vale si es de ESTA configuración. */
  const vigente = intento === huella
  const probadoOk = vigente && probar.data?.ok === true

  const cuerpo = (): CuerpoConexion => ({
    nombre: nombre.trim(),
    tipo,
    config: valores,
  })

  /** Qué impide seguir, en palabras. Nunca un botón gris sin explicación. */
  // Lista, no frase: "Falta el nombre y Carpeta" obliga a concordar artículos con
  // etiquetas que vienen del servidor, y sale mal en cuanto hay dos campos.
  const sinLlenar = [
    ...(nombre.trim() ? [] : ['Nombre']),
    ...faltan.map((c) => c.etiqueta),
  ]
  const pendiente = !tipo
    ? 'Elige el tipo de conexión.'
    : faltaPerfil
      ? 'Elige el origen: de eso dependen los campos.'
      : sinLlenar.length > 0
        ? `Falta: ${sinLlenar.join(', ')}.`
        : probadoOk
          ? null
          : intento && !vigente
            ? 'La configuración cambió. Vuelve a probar.'
            : 'Prueba la conexión antes de guardar.'

  const elegirTipo = (t: string) => {
    setTipo(t)
    // Se reinicia al cambiar de tipo: arrastrar un `host` a una conexión de
    // archivos solo produce configuraciones sin sentido.
    setValores(PREDETERMINADOS[t] ?? {})
    probar.reset()
    setIntento(null)
  }

  /**
   * Al elegir el origen se rellena lo que ya se sabe: el driver detectado y los
   * valores por omisión del perfil (el puerto de cada motor, por ejemplo).
   */
  const elegirPerfil = (clave: string) => {
    const p = perfiles.data?.perfiles.find((x) => x.clave === clave)
    const iniciales: Record<string, unknown> = { perfil: clave }
    if (p?.driver_detectado) iniciales.driver = p.driver_detectado
    for (const c of p?.campos ?? []) if (c.defecto) iniciales[c.clave] = c.defecto
    setValores(iniciales)
    probar.reset()
    setIntento(null)
  }

  const probarAhora = () => {
    setIntento(huella)          // se apunta ANTES: si falla, el fallo también es de esta
    probar.mutate(cuerpo())
  }

  return (
    <div className="velo" onClick={alCerrar}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>Nueva conexión</header>
        <div className="cont">
          <div className="campo">
            <label>Nombre</label>
            <input
              type="text"
              value={nombre}
              placeholder="ventas_produccion"
              onChange={(e) => setNombre(e.target.value)}
            />
            <span className="chico tenue">
              Con el que lo vas a reconocer después. No se puede repetir.
            </span>
          </div>

          <div className="campo">
            <label>Tipo</label>
            <select value={tipo} onChange={(e) => elegirTipo(e.target.value)}>
              <option value="">(elige uno)</option>
              {tipos.data?.tipos.map((t) => (
                <option key={t.tipo} value={t.tipo}>
                  {TIPOS_NOMBRE[t.tipo] ?? t.tipo}
                </option>
              ))}
            </select>
            {tipos.isLoading && <span className="chico tenue">Cargando tipos…</span>}
          </div>

          {NOTAS[tipo] && <div className="aviso-caja chico">{NOTAS[tipo]}</div>}

          {tipo === 'odbc' && (
            <div className="campo">
              <label>Origen</label>
              <select value={String(valores.perfil ?? '')} onChange={(e) => elegirPerfil(e.target.value)}>
                <option value="">(elige el sistema del que vas a traer datos)</option>
                {perfiles.data?.perfiles.map((p) => (
                  <option key={p.clave} value={p.clave}>
                    {p.nombre}
                    {p.plantilla && !p.instalado ? ' — sin driver en este servidor' : ''}
                  </option>
                ))}
              </select>
              <span className="chico tenue">
                De esto dependen los campos: cada driver llama distinto a lo mismo.
              </span>
            </div>
          )}

          {/* El driver que falta no se puede descargar solo, así que lo que se
              puede dar es lo siguiente mejor: de dónde sale y quién lo instala. */}
          {perfil?.plantilla && !perfil.instalado && (
            <div className="error-caja chico">
              El driver de <b>{perfil.nombre}</b> no está instalado donde corre
              Astrolabio, así que esta conexión no va a poder probarse todavía.
              <div style={{ marginTop: 4 }}>{perfil.driver?.de_donde}</div>
              {perfil.driver?.quien === 'sistemas' && (
                <div style={{ marginTop: 4 }}>
                  Lo tiene que instalar sistemas: no hay descarga pública. Mientras
                  tanto se puede escribir la ruta del archivo del driver, si ya está
                  en la máquina.
                </div>
              )}
            </div>
          )}
          {perfil?.notas.map((n) => (
            <div className="aviso-caja chico" key={n}>
              {n}
            </div>
          ))}

          {tipo === 'odbc' && odbc.data?.aviso && (
            <div className="aviso-caja chico">{odbc.data.aviso}</div>
          )}
          {tipo === 'odbc' && (odbc.data?.dsn.length ?? 0) > 0 && (
            <span className="chico tenue">
              DSN configurados en el servidor:{' '}
              <span className="mono">{odbc.data!.dsn.join(', ')}</span>
            </span>
          )}

          {campos.map((c) => {
            const numero = c.numero || c.clave === 'port'
            const opciones = c.clave === 'driver' ? (perfil?.drivers_detectados ?? []) : []
            return (
              <div className="campo" key={c.clave}>
                <label>
                  {c.etiqueta}
                  {c.requerido && <span className="tenue"> *</span>}
                </label>
                {/* Cuando el driver está instalado se elige de una lista: su nombre
                    tiene que coincidir EXACTAMENTE con el registrado, y escribirlo
                    a mano es donde se pierde la tarde. */}
                {opciones.length > 0 ? (
                  <select
                    value={String(valores.driver ?? '')}
                    onChange={(e) => setValores((p) => ({ ...p, driver: e.target.value }))}
                  >
                    {opciones.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={c.secreto ? 'password' : numero ? 'number' : 'text'}
                    value={String(valores[c.clave] ?? '')}
                    onChange={(e) => {
                      const v = numero
                        ? e.target.value === ''
                          ? ''
                          : Number(e.target.value)
                        : e.target.value
                      // No se borra el resultado de la prueba: la huella deja de
                      // cuadrar y se oculta solo. Si se deshace el cambio, el visto
                      // bueno vuelve a valer, porque vuelve a ser el mismo servidor.
                      setValores((p) => ({ ...p, [c.clave]: v }))
                    }}
                  />
                )}
                {(c.pista ?? c.ayuda) && (
                  <span className="chico tenue">{c.pista ?? c.ayuda}</span>
                )}
              </div>
            )
          })}

          {probar.data && vigente && (
            <div className={probar.data.ok ? 'aviso-caja ok-caja' : 'error-caja'}>
              {probar.data.ok ? '✓ ' : ''}
              {probar.data.mensaje}
              {probar.data.detalle && (
                <div className="chico mono" style={{ marginTop: 4 }}>
                  {Object.entries(probar.data.detalle)
                    .map(([k, v]) => `${k}: ${String(v)}`)
                    .join('  ·  ')}
                </div>
              )}
            </div>
          )}
          {probar.isError && vigente && (
            <div className="error-caja">{(probar.error as Error).message}</div>
          )}
          {crear.isError && (
            <div className="error-caja">{(crear.error as Error).message}</div>
          )}
        </div>
        <footer>
          {pendiente && (
            <span className="chico tenue pista">{pendiente}</span>
          )}
          <button className="btn" onClick={alCerrar}>
            Cancelar
          </button>
          <button
            className="btn"
            disabled={!listo || probar.isPending}
            onClick={probarAhora}
          >
            {probar.isPending ? 'Probando…' : probadoOk ? 'Probar otra vez' : 'Probar'}
          </button>
          <button
            className="btn primario"
            // Sin `title`: el motivo va en la pista, que se lee siempre. Un título
            // que suplanta el nombre del botón se lo quita a quien usa lector.
            disabled={!probadoOk || crear.isPending}
            onClick={() => crear.mutate(cuerpo(), { onSuccess: alCerrar })}
          >
            {crear.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </footer>
      </div>
    </div>
  )
}
