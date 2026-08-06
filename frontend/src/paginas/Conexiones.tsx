/**
 * Conexiones y datasets: la puerta de entrada de los datos.
 *
 * Las dos listas en la misma pantalla porque son un solo flujo: se conecta a un
 * origen, se explora, se trae una tabla, se carga. Separarlas en dos pantallas
 * obligaría a recordar de dónde vino cada dataset.
 */

import { useState } from 'react'

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

function FilaConexion({
  con,
  esAdmin,
  alExplorar,
  alEditar,
}: {
  con: Conexion
  esAdmin: boolean
  alExplorar: () => void
  alEditar: () => void
}) {
  const probar = useProbarConexion(con.id)
  const borrar = useBorrarConexion()
  const [confirmar, setConfirmar] = useState(false)

  return (
    <div className="tarjeta-con">
      <div className="cabeza">
        <strong>{con.nombre}</strong>
        <span className="etiqueta">{con.tipo}</span>
        {con.tiene_credenciales && (
          <span className="etiqueta dim" title="Guardadas cifradas">
            con credenciales
          </span>
        )}
        <div className="acciones">
          <button className="btn chico" onClick={alExplorar}>
            Explorar
          </button>
          <button
            className="btn chico"
            disabled={probar.isPending}
            onClick={() => probar.mutate()}
          >
            {probar.isPending ? 'Probando…' : 'Probar'}
          </button>
          {/* Editar existe para que rotar una contraseña no obligue a borrar la
              conexión y recrearla, llevándose sus datasets por delante. */}
          {esAdmin && (
            <button className="btn chico" onClick={alEditar}>
              Editar
            </button>
          )}
          {esAdmin && (
            <button className="btn chico peligro" onClick={() => setConfirmar(true)}>
              Borrar
            </button>
          )}
        </div>
      </div>

      <div className="chico mono suave">
        {Object.entries(con.config)
          .map(([k, v]) => `${k}=${String(v)}`)
          .join('  ')}
      </div>

      {probar.data && (
        <div className={`chico ${probar.data.ok ? 'ok-texto' : 'error-texto'}`}>
          {probar.data.ok ? '✓ ' : '✕ '}
          {probar.data.mensaje}
        </div>
      )}
      {probar.isError && (
        <div className="chico error-texto">{(probar.error as Error).message}</div>
      )}

      {confirmar && (
        <div className="aviso-caja chico">
          Borrar la conexión se lleva también sus datasets registrados. Los archivos
          Parquet que ya se trajeron se quedan.
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button className="btn chico" onClick={() => setConfirmar(false)}>
              Cancelar
            </button>
            <button
              className="btn chico peligro"
              disabled={borrar.isPending}
              onClick={() => borrar.mutate(con.id)}
            >
              Borrar
            </button>
          </div>
          {borrar.isError && (
            <div className="chico error-texto">{(borrar.error as Error).message}</div>
          )}
        </div>
      )}
    </div>
  )
}

function estadoDataset(ds: Dataset) {
  if (ds.ultimo_estado === 'error') return <span className="etiqueta critico">falló</span>
  if (!ds.ultima_carga) return <span className="etiqueta aviso">sin datos</span>
  return <span className="etiqueta ok">cargado</span>
}

export function Conexiones() {
  const yo = useYo()
  const conexiones = useConexiones()
  const datasets = useDatasets()

  const [nueva, setNueva] = useState(false)
  const [editando, setEditando] = useState<Conexion | null>(null)
  const [explorando, setExplorando] = useState<number | null>(null)
  const [abierto, setAbierto] = useState<Dataset | null>(null)

  const esAdmin = yo.data?.rol === 'administrador'

  return (
    <div className="pagina">
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <div>
          <h1>Conexiones</h1>
          <p className="suave chico">
            De dónde vienen los datos y qué se ha traído. Las credenciales se guardan
            cifradas y no vuelven a salir.
          </p>
        </div>
        {esAdmin && (
          <button
            className="btn primario"
            style={{ marginLeft: 'auto' }}
            onClick={() => setNueva(true)}
          >
            + Nueva conexión
          </button>
        )}
      </div>

      {conexiones.isError && (
        <div className="error-caja">{(conexiones.error as Error).message}</div>
      )}
      {conexiones.data?.length === 0 && (
        <div className="vacio">
          Todavía no hay ninguna conexión.
          {esAdmin
            ? ' Empieza por una: un MySQL, o una carpeta con archivos.'
            : ' Pídele a un administrador que cree la primera.'}
        </div>
      )}

      <div className="conexiones-lista">
        {conexiones.data?.map((c) => (
          <FilaConexion
            key={c.id}
            con={c}
            esAdmin={esAdmin}
            alExplorar={() => setExplorando(c.id)}
            alEditar={() => setEditando(c)}
          />
        ))}
      </div>

      <h2>Datasets</h2>
      <p className="chico suave" style={{ margin: '0 0 8px' }}>
        Cada uno es una tabla del origen ya traída a Parquet local. Es lo que ven el
        modelo y los tableros.
      </p>

      {datasets.data?.datasets.length === 0 && (
        <div className="vacio">
          Ninguno todavía. Entra a una conexión con «Explorar» y trae una tabla.
        </div>
      )}

      {(datasets.data?.datasets.length ?? 0) > 0 && (
        <div className="tabla-envoltura">
          <table className="datos">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Origen</th>
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
              {datasets.data?.datasets.map((ds) => (
                <tr key={ds.id}>
                  <td>
                    <strong>{ds.nombre}</strong> {estadoDataset(ds)}
                  </td>
                  <td className="mono chico suave">{ds.tabla_origen}</td>
                  <td className="num">{ds.filas.toLocaleString('es-MX')}</td>
                  <td className="num">{ds.mb}</td>
                  <td className="mono chico">
                    {ds.incremental ?? <span className="tenue">—</span>}
                  </td>
                  <td className="mono chico">
                    {ds.particionado ?? <span className="tenue">—</span>}
                  </td>
                  <td className="chico suave">
                    {ds.ultima_carga
                      ? new Date(ds.ultima_carga).toLocaleString('es-MX', {
                          day: 'numeric',
                          month: 'short',
                          hour: '2-digit',
                          minute: '2-digit',
                        })
                      : 'nunca'}
                  </td>
                  <td className="chico">
                    {ds.programacion_activa ? (
                      <span className="mono" title={ds.zona_horaria}>
                        {ds.cron}
                      </span>
                    ) : (
                      <span className="tenue">a mano</span>
                    )}
                  </td>
                  <td>
                    <button className="btn chico" onClick={() => setAbierto(ds)}>
                      Abrir
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {nueva && <DialogoConexion alCerrar={() => setNueva(false)} />}
      {/* `key`: el diálogo toma su estado inicial de la conexión, así que abrir
          otra tiene que montarlo de nuevo, no reutilizar el formulario anterior. */}
      {editando && (
        <DialogoConexion
          key={editando.id}
          conexion={editando}
          alCerrar={() => setEditando(null)}
        />
      )}
      {explorando !== null && (
        <Explorador
          key={explorando}
          conexionId={explorando}
          alCerrar={() => setExplorando(null)}
        />
      )}
      {abierto && (
        <PanelDataset
          key={abierto.id}
          ds={datasets.data?.datasets.find((d) => d.id === abierto.id) ?? abierto}
          alCerrar={() => setAbierto(null)}
        />
      )}
    </div>
  )
}
