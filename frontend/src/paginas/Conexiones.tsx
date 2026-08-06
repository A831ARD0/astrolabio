/**
 * Conexiones y datasets: la puerta de entrada de los datos.
 *
 * **Los datasets van dentro de su conexión, no en una lista aparte.** Antes eran
 * dos listas: arriba las conexiones, abajo una tabla plana con todos los datasets
 * del sistema. Con tres conexiones se leía bien; con cuarenta sucursales trayendo
 * varias tablas cada una son cientos de renglones donde el nombre de la tabla se
 * repite —`cat_conexiones` existe en las cuarenta, en bases distintas— y la única
 * forma de saber de cuál era cada uno es leerse el nombre entero.
 *
 * Aquí cada conexión es una tarjeta que se abre, con lo suyo dentro y un resumen
 * en la cabecera: cuántos datasets tiene y cuántos están sin cargar o fallando.
 * Eso último es lo que se busca al entrar por la mañana.
 *
 * El buscador mira **conexión y tabla a la vez**, y abre solas las tarjetas que
 * tengan algo que coincida: buscar `cat_conexiones` con cuarenta sucursales debe
 * enseñar las cuarenta filas sin tener que abrirlas una por una.
 */

import { useMemo, useState } from 'react'

import {
  type Conexion,
  type Dataset,
  useBorrarConexion,
  useConexiones,
  useDatasets,
  useProbarConexion,
} from '../api/conexiones'
import { useYo } from '../api/hooks'
import { DialogoConexion } from '../conexiones/DialogoConexion'
import { Explorador } from '../conexiones/Explorador'
import { PanelDataset } from '../conexiones/PanelDataset'

/** Los estados por los que de verdad se filtra al entrar por la mañana. */
type Estado = 'todos' | 'error' | 'sin_datos' | 'cargado'

const ESTADOS: { clave: Estado; nombre: string }[] = [
  { clave: 'todos', nombre: 'Todos' },
  { clave: 'error', nombre: 'Con error' },
  { clave: 'sin_datos', nombre: 'Sin datos' },
  { clave: 'cargado', nombre: 'Cargados' },
]

function estadoDe(ds: Dataset): Exclude<Estado, 'todos'> {
  if (ds.ultimo_estado === 'error') return 'error'
  if (!ds.ultima_carga) return 'sin_datos'
  return 'cargado'
}

function Etiqueta({ ds }: { ds: Dataset }) {
  const e = estadoDe(ds)
  if (e === 'error') return <span className="etiqueta critico">falló</span>
  if (e === 'sin_datos') return <span className="etiqueta aviso">sin datos</span>
  return <span className="etiqueta ok">cargado</span>
}

function fecha(iso: string | null) {
  if (!iso) return 'nunca'
  return new Date(iso).toLocaleString('es-MX', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

function TablaDatasets({ datasets, alAbrir }: {
  datasets: Dataset[]
  alAbrir: (ds: Dataset) => void
}) {
  return (
    <div className="tabla-envoltura">
      <table className="datos">
        <thead>
          <tr>
            <th>Tabla del origen</th>
            <th>Dataset</th>
            <th>Filas</th>
            <th>MB</th>
            <th>Incremental</th>
            <th>Partido por</th>
            <th>Última carga</th>
            <th>Horario</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {datasets.map((ds) => (
            <tr key={ds.id}>
              {/* La tabla del origen va PRIMERO: dentro de una conexión es lo que
                  identifica al dataset. El nombre en Astrolabio es un detalle de
                  almacenamiento, y con cuarenta sucursales acaba siendo la tabla
                  con la sucursal pegada delante. */}
              <td className="mono">
                {ds.esquema_origen && (
                  <span className="tenue">{ds.esquema_origen}.</span>
                )}
                {ds.tabla_origen} <Etiqueta ds={ds} />
              </td>
              <td className="chico suave">{ds.nombre}</td>
              <td className="num">{ds.filas.toLocaleString('es-MX')}</td>
              <td className="num">{ds.mb}</td>
              <td className="mono chico">
                {ds.incremental ?? <span className="tenue">—</span>}
              </td>
              <td className="mono chico">
                {ds.particionado ?? <span className="tenue">—</span>}
              </td>
              <td className="chico suave">{fecha(ds.ultima_carga)}</td>
              <td className="chico">
                {ds.programacion_activa ? (
                  <span className="mono" title={ds.zona_horaria}>{ds.cron}</span>
                ) : (
                  <span className="tenue">a mano</span>
                )}
              </td>
              <td>
                <button className="btn chico" onClick={() => alAbrir(ds)}>
                  Abrir
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TarjetaConexion({
  con, datasets, esAdmin, abierta, alPlegar, alExplorar, alEditar, alAbrirDataset,
}: {
  con: Conexion
  datasets: Dataset[]
  esAdmin: boolean
  abierta: boolean
  alPlegar: () => void
  alExplorar: () => void
  alEditar: () => void
  alAbrirDataset: (ds: Dataset) => void
}) {
  const probar = useProbarConexion(con.id)
  const borrar = useBorrarConexion()
  const [confirmar, setConfirmar] = useState(false)

  const fallando = datasets.filter((d) => estadoDe(d) === 'error').length
  const sinDatos = datasets.filter((d) => estadoDe(d) === 'sin_datos').length

  return (
    <div className="tarjeta-con">
      <div className="cabeza">
        {/* Toda la cabecera pliega: con cuarenta tarjetas, acertarle a un
            triangulito de diez píxeles cuarenta veces es trabajo. */}
        <button className="plegar" onClick={alPlegar}
                aria-expanded={abierta}
                title={abierta ? 'Plegar' : 'Ver sus datasets'}>
          {abierta ? '▾' : '▸'}
        </button>
        <strong onClick={alPlegar} style={{ cursor: 'pointer' }}>{con.nombre}</strong>
        <span className="etiqueta">{con.tipo}</span>
        {con.config.puente === true && (
          <span className="etiqueta dim" title="El driver lo carga el proceso de 32 bits">
            puente 32
          </span>
        )}
        {con.tiene_credenciales && (
          <span className="etiqueta dim" title="Guardadas cifradas">
            con credenciales
          </span>
        )}

        {/* El resumen en la cabecera es lo que evita abrir las cuarenta. */}
        <span className="chico suave">
          {datasets.length === 0
            ? 'sin datasets'
            : `${datasets.length} dataset${datasets.length === 1 ? '' : 's'}`}
          {fallando > 0 && <span className="critico-texto"> · {fallando} con error</span>}
          {sinDatos > 0 && <span className="aviso-texto"> · {sinDatos} sin datos</span>}
        </span>

        <div className="acciones">
          <button className="btn chico" onClick={alExplorar}>Explorar</button>
          <button className="btn chico" disabled={probar.isPending}
                  onClick={() => probar.mutate()}>
            {probar.isPending ? 'Probando…' : 'Probar'}
          </button>
          {esAdmin && (
            <>
              <button className="btn chico" onClick={alEditar}>Editar</button>
              <button className="btn chico peligro" onClick={() => setConfirmar(true)}>
                Borrar
              </button>
            </>
          )}
        </div>
      </div>

      <div className="chico mono suave detalle-con">{resumenConfig(con)}</div>

      {probar.data && (
        <div className={probar.data.ok ? 'ok-caja chico' : 'error-caja chico'}>
          {probar.data.mensaje}
        </div>
      )}

      {confirmar && (
        <div className="error-caja chico">
          Borrar «{con.nombre}» se lleva por delante sus {datasets.length} dataset
          {datasets.length === 1 ? '' : 's'} y lo que ya se trajo.
          <div className="acciones" style={{ marginTop: 6 }}>
            <button className="btn chico" onClick={() => setConfirmar(false)}>
              Cancelar
            </button>
            <button className="btn chico peligro" disabled={borrar.isPending}
                    onClick={() => borrar.mutate(con.id)}>
              Borrar
            </button>
          </div>
          {borrar.isError && (
            <div className="chico error-texto">{(borrar.error as Error).message}</div>
          )}
        </div>
      )}

      {abierta && (
        datasets.length === 0 ? (
          <div className="vacio chico">
            Nada traído todavía. «Explorar» abre el origen y desde ahí se eligen las
            tablas.
          </div>
        ) : (
          <TablaDatasets datasets={datasets} alAbrir={alAbrirDataset} />
        )
      )}
    </div>
  )
}

/** La línea de configuración, sin secretos: los filtra el servidor. */
function resumenConfig(con: Conexion): string {
  return Object.entries(con.config)
    .filter(([, v]) => v !== null && v !== '' && v !== undefined)
    .map(([k, v]) => `${k}=${v}`)
    .join(' ')
}

export function Conexiones() {
  const yo = useYo()
  const conexiones = useConexiones()
  const datasets = useDatasets()

  const [nueva, setNueva] = useState(false)
  const [editando, setEditando] = useState<Conexion | null>(null)
  const [explorando, setExplorando] = useState<number | null>(null)
  const [abierto, setAbierto] = useState<Dataset | null>(null)
  const [busca, setBusca] = useState('')
  const [estado, setEstado] = useState<Estado>('todos')
  const [plegadas, setPlegadas] = useState<Set<number>>(new Set())

  const esAdmin = yo.data?.rol === 'administrador'
  // `?? []` dentro de useMemo, no fuera: un arreglo nuevo en cada render hace que
  // la dependencia cambie siempre y el memo no memorice nada. Lo estable es el
  // dato de la consulta.
  const cons = useMemo(() => conexiones.data ?? [], [conexiones.data])
  const todos = useMemo(() => datasets.data?.datasets ?? [], [datasets.data])

  const q = busca.trim().toLowerCase()
  const filtrando = q !== '' || estado !== 'todos'

  /**
   * Qué se enseña de cada conexión. Una conexión sale si ella misma coincide —y
   * entonces se ven todos sus datasets— o si alguno de sus datasets coincide, y
   * entonces se ven solo esos. Sin lo segundo, buscar una tabla obligaría a saber
   * de antemano en qué sucursal está, que es justo lo que uno no sabe.
   */
  const grupos = useMemo(() => {
    return cons
      .map((c) => {
        const suyos = todos.filter((d) => d.conexion_id === c.id)
        const porEstado = estado === 'todos'
          ? suyos
          : suyos.filter((d) => estadoDe(d) === estado)
        const conCoincide = q !== '' && c.nombre.toLowerCase().includes(q)
        const visibles = q === '' || conCoincide
          ? porEstado
          : porEstado.filter((d) =>
              d.tabla_origen.toLowerCase().includes(q) ||
              d.nombre.toLowerCase().includes(q) ||
              (d.esquema_origen ?? '').toLowerCase().includes(q))
        return { con: c, todos: suyos, visibles, conCoincide }
      })
      .filter((g) => !filtrando || g.conCoincide || g.visibles.length > 0)
  }, [cons, todos, q, estado, filtrando])

  const total = todos.length
  const mostrados = grupos.reduce((n, g) => n + g.visibles.length, 0)

  return (
    <div className="pagina">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <div>
          <h1>Conexiones</h1>
          <p className="suave chico">
            De dónde vienen los datos y qué se ha traído de cada uno. Las credenciales
            se guardan cifradas y no vuelven a salir.
          </p>
        </div>
        {esAdmin && (
          <button className="btn primario" style={{ marginLeft: 'auto' }}
                  onClick={() => setNueva(true)}>
            + Nueva conexión
          </button>
        )}
      </div>

      {conexiones.isError && (
        <div className="error-caja">{(conexiones.error as Error).message}</div>
      )}

      {cons.length === 0 ? (
        <div className="vacio">
          Todavía no hay ninguna conexión.
          {esAdmin
            ? ' Empieza por una: un MySQL, o una carpeta con archivos.'
            : ' Pídele a un administrador que cree la primera.'}
        </div>
      ) : (
        <>
          <div className="barra-filtros">
            <input
              type="search"
              placeholder="Buscar conexión o tabla…"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              style={{ flex: '1 1 260px' }}
            />
            <div className="acciones">
              {ESTADOS.map((e) => (
                <button
                  key={e.clave}
                  className={`btn chico${estado === e.clave ? ' primario' : ''}`}
                  onClick={() => setEstado(e.clave)}
                >
                  {e.nombre}
                </button>
              ))}
            </div>
            <span className="chico suave">
              {filtrando
                ? `${mostrados} de ${total} datasets en ${grupos.length} conexion${grupos.length === 1 ? '' : 'es'}`
                : `${total} dataset${total === 1 ? '' : 's'} en ${cons.length} conexion${cons.length === 1 ? '' : 'es'}`}
            </span>
            <div className="acciones">
              <button className="btn chico" onClick={() => setPlegadas(new Set())}>
                Abrir todas
              </button>
              <button className="btn chico"
                      onClick={() => setPlegadas(new Set(cons.map((c) => c.id)))}>
                Plegar todas
              </button>
            </div>
          </div>

          {grupos.length === 0 && (
            <div className="vacio">
              Nada coincide con «{busca}»
              {estado !== 'todos' && ' con ese estado'}.
            </div>
          )}

          <div className="conexiones-lista">
            {grupos.map((g) => (
              <TarjetaConexion
                key={g.con.id}
                con={g.con}
                datasets={g.visibles}
                esAdmin={esAdmin}
                // Filtrando se abren solas: si algo coincidió, es lo que se
                // estaba buscando y esconderlo detrás de un clic no ayuda.
                abierta={filtrando || !plegadas.has(g.con.id)}
                alPlegar={() =>
                  setPlegadas((p) => {
                    const s = new Set(p)
                    if (s.has(g.con.id)) s.delete(g.con.id)
                    else s.add(g.con.id)
                    return s
                  })
                }
                alExplorar={() => setExplorando(g.con.id)}
                alEditar={() => setEditando(g.con)}
                alAbrirDataset={setAbierto}
              />
            ))}
          </div>
        </>
      )}

      {nueva && <DialogoConexion alCerrar={() => setNueva(false)} />}
      {/* `key`: el diálogo toma su estado inicial de la conexión, así que abrir
          otra tiene que montarlo de nuevo, no reutilizar el formulario anterior. */}
      {editando && (
        <DialogoConexion key={editando.id} conexion={editando}
                         alCerrar={() => setEditando(null)} />
      )}
      {explorando !== null && (
        <Explorador key={explorando} conexionId={explorando}
                    alCerrar={() => setExplorando(null)} />
      )}
      {abierto && (
        <PanelDataset
          key={abierto.id}
          ds={todos.find((d) => d.id === abierto.id) ?? abierto}
          alCerrar={() => setAbierto(null)}
        />
      )}
    </div>
  )
}
