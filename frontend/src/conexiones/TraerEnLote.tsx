/**
 * Traer las mismas tablas desde varias conexiones de una vez.
 *
 * El caso que lo motiva: cuarenta sucursales con el mismo sistema detrás, cada
 * una en su base. Traer cinco tablas de las cuarenta por el diálogo normal son
 * doscientos recorridos, y doscientos nombres que inventar.
 *
 * Aquí se eligen **las tablas de una conexión de referencia** —la que se toma de
 * plantilla porque todas tienen el mismo esquema— y **a qué conexiones
 * aplicarlas**. Los nombres los pone el servidor.
 *
 * Nada se crea sin enseñar antes la cuenta: «se van a crear 200 datasets» es una
 * frase que conviene leer antes y no después.
 */

import { useMemo, useState } from 'react'

import {
  type Conexion,
  type ResultadoLote,
  useConexiones,
  useTablasOrigen,
  useTraerEnLote,
} from '../api/conexiones'
import { Velo } from '../comunes/Velo'
import { useOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'

export function TraerEnLote({ alCerrar }: { alCerrar: () => void }) {
  const conexiones = useConexiones()
  const enLote = useTraerEnLote()

  const cons = useMemo(() => conexiones.data ?? [], [conexiones.data])
  // De referencia se toma la primera: en un grupo de sucursales iguales sirve
  // cualquiera, y elegirla es un paso más que casi siempre sobra.
  const [referencia, setReferencia] = useState<number | null>(null)
  const ref = referencia ?? cons[0]?.id ?? null

  const tablas = useTablasOrigen(ref, null)

  const [elegidas, setElegidas] = useState<Set<string>>(new Set())
  const [destinos, setDestinos] = useState<Set<number>>(new Set())
  const [buscaTabla, setBuscaTabla] = useState('')
  const [buscaCon, setBuscaCon] = useState('')
  const [resultado, setResultado] = useState<ResultadoLote | null>(null)
  const ordenFallidos = useOrden(resultado?.fallidos ?? [], (f, c) =>
    c === 'conexion' ? f.conexion : c === 'tabla' ? f.tabla : f.motivo)
  const ordenCreados = useOrden(resultado?.creados ?? [], (x, c) =>
    c === 'conexion' ? x.conexion : c === 'tabla' ? x.tabla : x.nombre)

  const listaTablas = (tablas.data?.tablas ?? []).filter((t) =>
    t.nombre.toLowerCase().includes(buscaTabla.trim().toLowerCase()))
  const listaCons = cons.filter((c) =>
    c.nombre.toLowerCase().includes(buscaCon.trim().toLowerCase()))

  const total = elegidas.size * destinos.size
  const puede = total > 0 && !enLote.isPending

  /**
   * Devuelve un actualizador, no un conjunto ya calculado.
   *
   * Con `setDestinos(alternar(destinos, id))` el manejador se queda con el
   * `destinos` de SU render, así que dos clics seguidos parten del mismo estado
   * y el segundo pisa al primero. Aquí se marcan decenas de casillas seguidas:
   * marcar cuatro sucursales y que solo entren dos es exactamente el fallo que
   * salió al probarlo.
   */
  function alterna<T>(v: T) {
    return (previo: Set<T>) => {
      const s = new Set(previo)
      if (s.has(v)) s.delete(v)
      else s.add(v)
      return s
    }
  }

  function crear() {
    enLote.mutate(
      {
        conexiones: [...destinos],
        tablas: [...elegidas].map((t) => ({ tabla: t })),
      },
      { onSuccess: setResultado },
    )
  }

  if (resultado) {
    return (
      <Velo alCerrar={alCerrar}>
        <div className="modal ancho">
          <header>Resultado</header>
          <div className="cont">
            <div className={resultado.fallidos.length ? 'aviso-caja' : 'aviso-caja ok-caja'}>
              <strong>{resultado.creados.length}</strong> datasets creados
              {resultado.omitidos.length > 0 &&
                `, ${resultado.omitidos.length} que ya estaban`}
              {resultado.fallidos.length > 0 &&
                `, ${resultado.fallidos.length} que no se pudieron`}.
            </div>

            {/* Lo que fallo va primero y entero: es lo unico que pide accion. */}
            {resultado.fallidos.length > 0 && (
              <>
                <h3 className="chico">No se pudieron</h3>
                <div className="tabla-envoltura">
                  <table className="datos">
                    <thead>
                      <tr>
                        <Th orden={ordenFallidos} clave="conexion">Conexión</Th>
                        <Th orden={ordenFallidos} clave="tabla">Tabla</Th>
                        <Th orden={ordenFallidos} clave="motivo">Motivo</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {ordenFallidos.filas.map((f, i) => (
                        <tr key={i}>
                          <td>{f.conexion}</td>
                          <td className="mono">{f.tabla}</td>
                          <td className="chico">{f.motivo}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {resultado.creados.length > 0 && (
              <>
                <h3 className="chico">Creados</h3>
                <div className="tabla-envoltura" style={{ maxHeight: '32vh' }}>
                  <table className="datos">
                    <thead>
                      <tr>
                        <Th orden={ordenCreados} clave="conexion">Conexión</Th>
                        <Th orden={ordenCreados} clave="tabla">Tabla</Th>
                        <Th orden={ordenCreados} clave="nombre">Dataset</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {ordenCreados.filas.map((c) => (
                        <tr key={c.id}>
                          <td>{c.conexion}</td>
                          <td className="mono">{c.tabla}</td>
                          <td className="chico suave">{c.nombre}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            <p className="chico suave">
              Se crearon vacíos. Para traer los datos, cárgalos desde su conexión o
              métete a Flujos y ponlos en uno con horario.
            </p>
          </div>
          <footer>
            <button className="btn primario" onClick={alCerrar}>Cerrar</button>
          </footer>
        </div>
      </Velo>
    )
  }

  return (
    <Velo alCerrar={alCerrar}>
      <div className="modal ancho">
        <header>Traer tablas desde varias conexiones</header>
        <div className="cont explorador">
          <div className="lado">
            <label className="chico">
              Tablas de{' '}
              <select value={String(ref ?? '')}
                      onChange={(e) => {
                        setReferencia(Number(e.target.value))
                        setElegidas(new Set())
                      }}>
                {cons.map((c: Conexion) => (
                  <option key={c.id} value={c.id}>{c.nombre}</option>
                ))}
              </select>
            </label>
            <span className="chico tenue">
              Se toma de plantilla: se supone que las demás tienen las mismas tablas.
            </span>
            <input type="search" placeholder="Filtrar tablas…" value={buscaTabla}
                   onChange={(e) => setBuscaTabla(e.target.value)} />
            {tablas.isLoading && <span className="chico suave">Leyendo el origen…</span>}
            {tablas.isError && (
              <div className="error-caja chico">{(tablas.error as Error).message}</div>
            )}
            <div className="lista-tablas">
              {listaTablas.map((t) => (
                <label key={t.nombre} className="casilla fila-lista">
                  <input type="checkbox" checked={elegidas.has(t.nombre)}
                         onChange={() => setElegidas(alterna(t.nombre))} />
                  <span className="mono chico">{t.nombre}</span>
                </label>
              ))}
            </div>
            <span className="chico suave">{elegidas.size} tabla(s) elegidas</span>
          </div>

          <div className="lado principal">
            <div className="acciones">
              <strong className="chico">Aplicar a estas conexiones</strong>
              <button className="btn chico" style={{ marginLeft: 'auto' }}
                      onClick={() => setDestinos(new Set(listaCons.map((c) => c.id)))}>
                Todas
              </button>
              <button className="btn chico" onClick={() => setDestinos(new Set())}>
                Ninguna
              </button>
            </div>
            <input type="search" placeholder="Filtrar conexiones…" value={buscaCon}
                   onChange={(e) => setBuscaCon(e.target.value)} />
            <div className="lista-tablas">
              {listaCons.map((c) => (
                <label key={c.id} className="casilla fila-lista">
                  <input type="checkbox" checked={destinos.has(c.id)}
                         onChange={() => setDestinos(alterna(c.id))} />
                  <span>{c.nombre}</span>
                  <span className="etiqueta dim">{c.tipo}</span>
                </label>
              ))}
            </div>

            {total > 0 && (
              <div className="aviso-caja chico">
                Se van a crear <strong>{total}</strong> datasets:{' '}
                {elegidas.size} tabla(s) × {destinos.size} conexion(es). Los que ya
                existan se saltan.
                <div className="mono chico tenue" style={{ marginTop: 4 }}>
                  p. ej. {[...destinos].slice(0, 1).map((id) =>
                    cons.find((c) => c.id === id)?.nombre)}__{[...elegidas][0]}
                </div>
              </div>
            )}
            {enLote.isError && (
              <div className="error-caja chico">{(enLote.error as Error).message}</div>
            )}
          </div>
        </div>
        <footer>
          <span className="pista chico suave">
            {total === 0
              ? 'Elige al menos una tabla y una conexión.'
              : 'Se crean vacíos: después se cargan.'}
          </span>
          <button className="btn" onClick={alCerrar}>Cancelar</button>
          <button className="btn primario" disabled={!puede} onClick={crear}>
            {enLote.isPending ? 'Creando…' : `Crear ${total || ''}`}
          </button>
        </footer>
      </div>
    </Velo>
  )
}
