/**
 * Nueva conexión —y editar una existente—: **probar y luego guardar**, en ese
 * orden y sin atajo.
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
 *
 * **Al editar se manda solo lo que se tocó.** No es una optimización: la API nunca
 * devuelve las contraseñas y enmascara la cadena de ODBC (`PWD=***`), así que los
 * campos que guardan un secreto se enseñan en blanco. Mandar el formulario entero
 * guardaría la máscara y borraría la contraseña de quien entró a cambiar un puerto.
 */

import { useState } from 'react'

import {
  type CambioConexion,
  type CampoPerfil,
  type Conexion,
  type CuerpoConexion,
  useCrearConexion,
  useEditarConexion,
  useOdbcInstalado,
  useOdbcPerfiles,
  useProbarCambio,
  useProbarConfig,
  useTiposConexion,
} from '../api/conexiones'
import { Velo } from '../comunes/Velo'

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

/**
 * Los campos que la API no puede devolver con su valor real: los secretos (nunca
 * viajan) y la cadena de ODBC (viaja enmascarada). Al editar se enseñan en blanco
 * y en blanco significa "no lo toqué".
 */
function noSeMuestra(c: Campo): boolean {
  return !!c.secreto || c.clave === 'cadena'
}

export function DialogoConexion({
  alCerrar,
  conexion,
}: {
  alCerrar: () => void
  /** Presente = editar esa conexión. Ausente = crear una nueva. */
  conexion?: Conexion
}) {
  const editando = !!conexion
  const tipos = useTiposConexion()
  const probarNueva = useProbarConfig()
  const probarCambio = useProbarCambio(conexion?.id ?? 0)
  const probar = editando ? probarCambio : probarNueva
  const crear = useCrearConexion()
  const editar = useEditarConexion(conexion?.id ?? 0)
  const guardar = editando ? editar : crear

  /**
   * De dónde parte el formulario al editar. Se guarda para poder comparar: lo que
   * se manda es la diferencia contra esto, no el formulario entero.
   */
  const [iniciales] = useState<Record<string, unknown>>(() => {
    if (!conexion) return {}
    const c = { ...conexion.config }
    delete c.cadena           // llega como PWD=***; guardarla así sería guardar la máscara
    return c
  })

  const [nombre, setNombre] = useState(conexion?.nombre ?? '')
  // El tipo no se puede cambiar: convertir un MySQL en archivos no es editar, es
  // otra conexión, y los datasets que cuelgan de ella dejarían de tener sentido.
  const [tipo, setTipo] = useState(conexion?.tipo ?? '')
  const [valores, setValores] = useState<Record<string, unknown>>(iniciales)
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

  // Al editar, un secreto en blanco no es un campo sin llenar: es el que ya está
  // guardado. Exigirlo obligaría a reescribir la contraseña para cambiar un puerto.
  const faltan = campos.filter(
    (c) =>
      c.requerido &&
      !String(valores[c.clave] ?? '').trim() &&
      !(editando && noSeMuestra(c)),
  )
  // Sin origen elegido no hay nada que probar: los campos ni se sabe cuáles son.
  const faltaPerfil = tipo === 'odbc' && !perfil

  /** Solo lo que se tocó. Ver la nota de arriba: mandar el resto guarda máscaras. */
  const cambios: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(valores)) {
    if (String(v ?? '') !== String(iniciales[k] ?? '')) cambios[k] = v
  }
  const cambioNombre = editando && nombre.trim() !== conexion!.nombre
  const cambioConfig = Object.keys(cambios).length > 0
  const sinCambios = editando && !cambioConfig && !cambioNombre
  /**
   * Cambiar solo el nombre no necesita prueba: el nombre es una etiqueta nuestra,
   * el servidor de datos no lo ve. Obligar a probar por una errata enseña que el
   * botón es un trámite.
   */
  const soloNombre = editando && cambioNombre && !cambioConfig

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

  const cuerpoCambio = (): CambioConexion => ({
    ...(cambioNombre ? { nombre: nombre.trim() } : {}),
    ...(cambioConfig ? { config: cambios } : {}),
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
        : sinCambios
          ? 'No has cambiado nada.'
          : soloNombre
            ? 'Solo cambia el nombre: no hace falta probar.'
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
    if (editando) probarCambio.mutate(cuerpoCambio())
    else probarNueva.mutate(cuerpo())
  }

  const guardarAhora = () => {
    if (editando) editar.mutate(cuerpoCambio(), { onSuccess: alCerrar })
    else crear.mutate(cuerpo(), { onSuccess: alCerrar })
  }

  return (
    <Velo alCerrar={alCerrar}>
      <div className="modal">
        <header>{editando ? `Editar «${conexion!.nombre}»` : 'Nueva conexión'}</header>
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
            {editando ? (
              <>
                <input type="text" value={TIPOS_NOMBRE[tipo] ?? tipo} disabled />
                <span className="chico tenue">
                  El tipo no se cambia. Sería otra conexión, y los datasets que
                  cuelgan de esta dejarían de tener sentido.
                </span>
              </>
            ) : (
              <>
                <select value={tipo} onChange={(e) => elegirTipo(e.target.value)}>
                  <option value="">(elige uno)</option>
                  {tipos.data?.tipos.map((t) => (
                    <option key={t.tipo} value={t.tipo}>
                      {TIPOS_NOMBRE[t.tipo] ?? t.tipo}
                    </option>
                  ))}
                </select>
                {tipos.isLoading && (
                  <span className="chico tenue">Cargando tipos…</span>
                )}
              </>
            )}
          </div>

          {NOTAS[tipo] && <div className="aviso-caja chico">{NOTAS[tipo]}</div>}

          {tipo === 'odbc' && (
            <div className="campo">
              <label>Origen</label>
              <select
                value={String(valores.perfil ?? '')}
                // Al editar queda fijo, por lo mismo que el tipo: cambiarlo cambia
                // el juego de campos entero, y eso no es editar esta conexión.
                disabled={editando}
                onChange={(e) => elegirPerfil(e.target.value)}
              >
                <option value="">(elige el sistema del que vas a traer datos)</option>
                {perfiles.data?.perfiles.map((p) => (
                  <option key={p.clave} value={p.clave}>
                    {p.nombre}
                    {p.plantilla && !p.instalado ? ' — sin driver en este servidor' : ''}
                  </option>
                ))}
              </select>
              <span className="chico tenue">
                {editando
                  ? 'El origen no se cambia: de él dependen los campos.'
                  : 'De esto dependen los campos: cada driver llama distinto a lo mismo.'}
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

          {/* El puente de 32 bits. Solo se ofrece si el servicio está arriba:
              enseñar una casilla que no puede funcionar es peor que no tenerla,
              porque el error aparece después de llenar el formulario entero.

              Con el origen «ya tengo un DSN» no se enseña: ahí los bits los
              decide el DSN elegido, y dos controles que dicen lo mismo se acaban
              contradiciendo. */}
          {tipo === 'odbc' && perfil && perfil.clave !== 'dsn' && odbc.data?.puente?.activo && (
            <div className="campo">
              <label className="casilla">
                <input
                  type="checkbox"
                  checked={!!valores.puente}
                  onChange={(e) =>
                    setValores((p) => ({ ...p, puente: e.target.checked }))
                  }
                />
                Cargar el driver en el puente de 32 bits
              </label>
              <span className="chico tenue">
                Para los orígenes cuyo driver solo existe de 32 bits, como Pervasive
                con TotalDealer. Un proceso de 64 bits no puede cargar una librería
                de 32, así que la carga la hace otro proceso.
              </span>
            </div>
          )}

          {campos.map((c) => {
            const numero = c.numero || c.clave === 'port'
            const opciones = c.clave === 'driver' ? (perfil?.drivers_detectados ?? []) : []

            // El DSN se elige de lo que hay registrado en la máquina, no se
            // escribe. Escribirlo obliga a acertar un nombre exacto que está en
            // otra ventana, y sobre todo deja elegir uno de 32 bits sin marcar el
            // puente: el formulario se llena entero para acabar en un IM014. Al
            // salir de la lista, los bits los sabe Astrolabio y activa el puente
            // solo. Ver `puente32` en el backend.
            if (c.clave === 'dsn') {
              return (
                <SelectorDsn
                  key={c.clave}
                  campo={c}
                  valor={String(valores.dsn ?? '')}
                  porPuente={!!valores.puente}
                  de64={odbc.data?.dsn ?? []}
                  de32={odbc.data?.puente?.activo ? (odbc.data.puente.dsn ?? []) : []}
                  puenteActivo={!!odbc.data?.puente?.activo}
                  alElegir={(dsn, puente) =>
                    setValores((p) => ({ ...p, dsn, puente }))
                  }
                />
              )
            }

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
                    // Al editar, en blanco es "no lo toqué": lo que hay guardado se
                    // queda. Decirlo aquí evita la duda de si se va a borrar.
                    placeholder={
                      editando && noSeMuestra(c) ? 'Guardado — déjalo en blanco para no cambiarlo' : ''
                    }
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
          {guardar.isError && (
            <div className="error-caja">{(guardar.error as Error).message}</div>
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
            disabled={(!probadoOk && !soloNombre) || guardar.isPending}
            onClick={guardarAhora}
          >
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </footer>
      </div>
    </Velo>
  )
}

const A_MANO = ' a-mano'

/**
 * Elegir el DSN de los que hay registrados, en vez de escribirlo.
 *
 * En Windows los DSN de 32 y los de 64 bits viven en **dos registros distintos**
 * y no se ven entre sí. Un proceso de 64 bits no puede cargar un driver de 32,
 * así que un DSN de 32 solo sirve a través del puente. Escrito a mano eso es
 * imposible de acertar: el nombre está en otra ventana y nada dice de qué
 * registro salió.
 *
 * Por eso los dos grupos van juntos y **la elección decide el puente**. No queda
 * forma de pedir un DSN de 32 bits sin él, que era la única manera de acabar en
 * «la arquitectura del DSN no coincide» con el formulario ya lleno.
 */
function SelectorDsn({ campo, valor, porPuente, de64, de32, puenteActivo, alElegir }: {
  campo: Campo
  valor: string
  porPuente: boolean
  de64: string[]
  de32: string[]
  puenteActivo: boolean
  alElegir: (dsn: string, puente: boolean) => void
}) {
  const enLista =
    (porPuente ? de32 : de64).some((n) => n === valor) && !!valor
  // Un DSN escrito a mano sigue valiendo: puede haberse creado después de abrir
  // la pantalla, o ser un DSN de archivo, que no sale en estas listas.
  const [aMano, setAMano] = useState(!!valor && !enLista)

  return (
    <div className="campo">
      <label>
        {campo.etiqueta}
        {campo.requerido && <span className="tenue"> *</span>}
      </label>

      {de64.length === 0 && de32.length === 0 && !aMano ? (
        <span className="chico tenue">
          Este servidor no tiene ningún DSN registrado.{' '}
          <button className="btn chico" onClick={() => setAMano(true)}>
            Escribir uno a mano
          </button>
        </span>
      ) : (
        <select
          value={aMano ? A_MANO : enLista ? `${porPuente ? 32 : 64}:${valor}` : ''}
          onChange={(e) => {
            if (e.target.value === A_MANO) {
              setAMano(true)
              alElegir('', false)
              return
            }
            setAMano(false)
            if (!e.target.value) {
              alElegir('', false)
              return
            }
            // Se parte solo por el PRIMER ':': un DSN puede llevar dos puntos.
            const corte = e.target.value.indexOf(':')
            alElegir(e.target.value.slice(corte + 1),
                     e.target.value.slice(0, corte) === '32')
          }}
        >
          <option value="">(elige el origen registrado en el servidor)</option>
          {de64.length > 0 && (
            <optgroup label="64 bits — Astrolabio los carga directo">
              {de64.map((n) => (
                <option key={`64:${n}`} value={`64:${n}`}>{n}</option>
              ))}
            </optgroup>
          )}
          {de32.length > 0 && (
            <optgroup label="32 bits — se cargan por el puente">
              {de32.map((n) => (
                <option key={`32:${n}`} value={`32:${n}`}>{n}</option>
              ))}
            </optgroup>
          )}
          <option value={A_MANO}>Otro: escribirlo a mano…</option>
        </select>
      )}

      {aMano && (
        <input
          type="text"
          value={valor}
          placeholder="Nombre exacto del DSN"
          onChange={(e) => alElegir(e.target.value, porPuente)}
        />
      )}

      {aMano ? (
        <label className="casilla chico">
          <input
            type="checkbox"
            checked={porPuente}
            disabled={!puenteActivo}
            onChange={(e) => alElegir(valor, e.target.checked)}
          />
          Es de 32 bits: cargarlo por el puente
        </label>
      ) : (
        <span className="chico tenue">
          {porPuente
            ? 'De 32 bits: la carga la hará el puente, en su propio proceso.'
            : 'Tiene que estar registrado en la máquina donde corre Astrolabio.'}
        </span>
      )}

      {!puenteActivo && (
        <span className="chico tenue">
          El puente de 32 bits no está corriendo, así que aquí solo salen los DSN de
          64. Si el que buscas es de 32, se instala con{' '}
          <span className="mono">instalar-windows.ps1 -Puente32 -Servicios</span>.
        </span>
      )}
    </div>
  )
}
