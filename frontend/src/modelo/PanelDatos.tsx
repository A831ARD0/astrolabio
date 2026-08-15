/**
 * Ver el resultado del modelo, sin publicarlo.
 *
 * Un modelo se termina cuando alguien mira un número y dice «sí, ese es». Hasta
 * aquí ese momento sólo llegaba después de publicar, lo cual invierte el orden
 * natural: publicar debería significar «esto ya está bien», no «a ver qué sale».
 *
 * Dos vistas, porque son dos preguntas distintas y en este orden:
 *
 *   - **Muestra** — «¿qué hay en esta tabla?». Filas crudas, sin agregar. Es la
 *     pregunta previa a escribir la primera métrica: sin ver una fila no se sabe
 *     si la fecha viene como fecha o como texto, ni si el tipo dice «Contado» o
 *     «CONTADO».
 *   - **Resultado** — «¿qué dan mis métricas?». El modelo entero corriendo, con
 *     las métricas que se elijan y el desglose que se elija.
 *
 * Las dos ejecutan **lo que hay en pantalla**: se manda la definición completa,
 * así que valen para métricas escritas hace un minuto y todavía sin guardar.
 */

import { useEffect, useState } from 'react'

import { useMuestra, useVistaPrevia } from '../api/hooks'
import type { Definicion, ResultadoDatos } from '../api/tipos'
import { Combo } from '../comunes/Combo'
import { useOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'

type Vista = 'resultado' | 'muestra'

export function PanelDatos({
  modeloId,
  definicion,
}: {
  modeloId: number
  definicion: Definicion
}) {
  const previa = useVistaPrevia(modeloId)
  const muestra = useMuestra(modeloId)

  const hechos = definicion.entidades.filter((e) => e.tipo === 'hecho')
  const dimensiones = definicion.entidades.flatMap((e) =>
    e.campos
      .filter((c) => c.rol === 'dimension' && c.visible !== false)
      .map((c) => ({ clave: `${e.nombre}.${c.nombre}`, etiqueta: c.etiqueta || c.nombre })),
  )

  // Sin métricas todavía no hay resultado que enseñar, así que se abre en la
  // muestra: es lo único que en ese momento tiene algo que decir.
  const [vista, setVista] = useState<Vista>(
    definicion.metricas.length > 0 ? 'resultado' : 'muestra',
  )
  const [metricas, setMetricas] = useState<string[]>(() =>
    definicion.metricas.slice(0, 6).map((m) => m.nombre),
  )
  const [desglose, setDesglose] = useState<string[]>([])
  const [entidad, setEntidad] = useState(
    () => hechos[0]?.nombre ?? definicion.entidades[0]?.nombre ?? '',
  )
  const [filas, setFilas] = useState(50)

  function ejecutar() {
    previa.mutate({ definicion, metricas, dimensiones: desglose, limite: 200 })
  }

  function verFilas() {
    muestra.mutate({ definicion, entidad, limite: filas })
  }

  // El primer resultado sale solo. Entrar a una pestaña llamada «Datos» y
  // encontrarla vacía hasta pulsar un botón es pedir un clic para nada.
  useEffect(() => {
    if (vista === 'resultado' && metricas.length > 0 && !previa.data && !previa.isPending) {
      ejecutar()
    }
    if (vista === 'muestra' && entidad && !muestra.data && !muestra.isPending) {
      verFilas()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vista])

  const activa = vista === 'resultado' ? previa : muestra

  // Las cabeceras van con la etiqueta de negocio y el nombre técnico detrás:
  // «Venta» dice más que `monto_venta`, pero el técnico es el que se escribe en
  // las fórmulas, así que no puede desaparecer.
  const etiquetas: Record<string, string> = {}
  for (const m of definicion.metricas) etiquetas[m.nombre] = m.etiqueta || m.nombre
  for (const d of dimensiones) etiquetas[d.clave] = d.etiqueta

  /**
   * Columnas que son identificadores y no cantidades.
   *
   * Un `cliente_id` con separador de miles —«109,421»— se lee como una cifra,
   * que es justo lo que no es. Se sacan del modelo en vez de adivinarlas por el
   * nombre: el rol del campo ya lo dice.
   */
  const identificadores = new Set(
    definicion.entidades
      .find((e) => e.nombre === entidad)
      ?.campos.filter((c) => c.rol === 'clave' || c.rol === 'clave_externa')
      .map((c) => c.nombre) ?? [],
  )

  /**
   * Columnas de periodo, por lo mismo: `202601` no es doscientos mil.
   *
   * Aquí las claves llevan el prefijo de la entidad porque así vienen en el
   * resultado de una consulta agregada, que es otra tabla distinta de la muestra.
   */
  const periodos = new Set(
    definicion.entidades.flatMap((e) =>
      e.campos.filter((c) => c.grano_tiempo).map((c) => `${e.nombre}.${c.nombre}`),
    ),
  )

  return (
    <div className="datos-vista">
      <div className="barra-datos">
        <div className="pestanas">
          <button
            className={vista === 'resultado' ? 'activo' : ''}
            onClick={() => setVista('resultado')}
          >
            Resultado
          </button>
          <button
            className={vista === 'muestra' ? 'activo' : ''}
            onClick={() => setVista('muestra')}
          >
            Muestra de filas
          </button>
        </div>
        <span className="chico tenue" style={{ marginLeft: 'auto' }}>
          Se ejecuta el modelo que tienes en pantalla, sin publicar nada.
        </span>
      </div>

      {vista === 'resultado' ? (
        <div className="controles-datos">
          {definicion.metricas.length === 0 ? (
            <div className="vacio">
              Este modelo todavía no tiene métricas. Créala en el panel de la
              izquierda y vuelve aquí a ver el número.
            </div>
          ) : (
            <>
              <div className="grupo-datos">
                <label className="chico suave">Métricas</label>
                <div className="atributos">
                  {definicion.metricas.map((m) => (
                    <button
                      key={m.nombre}
                      className={`chip como-boton${metricas.includes(m.nombre) ? ' puesto' : ''}`}
                      onClick={() =>
                        setMetricas((v) =>
                          v.includes(m.nombre)
                            ? v.filter((n) => n !== m.nombre)
                            : [...v, m.nombre],
                        )
                      }
                    >
                      {m.etiqueta || m.nombre}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grupo-datos">
                <label className="chico suave">Desglosar por</label>
                <div className="atributos">
                  {desglose.map((d) => (
                    <span key={d} className="chip">
                      {d}
                      <button
                        title="Quitar"
                        onClick={() => setDesglose((v) => v.filter((x) => x !== d))}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  {/* Con cuarenta tablas la lista de dimensiones es tan larga
                      como el catálogo entero: se busca, no se recorre. */}
                  <div style={{ minWidth: 240 }}>
                    <Combo
                      opciones={dimensiones
                        .filter((d) => !desglose.includes(d.clave))
                        .map((d) => ({
                          valor: d.clave,
                          etiqueta: d.clave,
                          detalle: d.etiqueta,
                        }))}
                      valor={null}
                      alElegir={(clave) => setDesglose((v) => [...v, clave])}
                      marcador="+ dimensión"
                    />
                  </div>
                  {desglose.length === 0 && (
                    <span className="chico tenue">sin desglose: el total</span>
                  )}
                </div>
              </div>

              <button
                className="btn primario"
                disabled={metricas.length === 0 || previa.isPending}
                onClick={ejecutar}
              >
                {previa.isPending ? 'Calculando…' : 'Calcular'}
              </button>
            </>
          )}
        </div>
      ) : (
        <div className="controles-datos">
          <div className="grupo-datos">
            <label className="chico suave">Entidad</label>
            <select
              value={entidad}
              style={{ width: 'auto' }}
              onChange={(e) => setEntidad(e.target.value)}
            >
              {definicion.entidades.map((e) => (
                <option key={e.nombre} value={e.nombre}>
                  {e.nombre}
                </option>
              ))}
            </select>
          </div>
          <div className="grupo-datos">
            <label className="chico suave">Filas</label>
            <select
              value={filas}
              style={{ width: 'auto' }}
              onChange={(e) => setFilas(Number(e.target.value))}
            >
              {[10, 50, 100, 500].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
          <button className="btn primario" disabled={muestra.isPending} onClick={verFilas}>
            {muestra.isPending ? 'Leyendo…' : 'Ver filas'}
          </button>
        </div>
      )}

      {activa.isError && (
        <div className="error-caja" style={{ margin: '0 12px' }}>
          {(activa.error as Error).message}
        </div>
      )}

      {activa.data && (
        <Tabla
          resultado={activa.data}
          etiquetas={etiquetas}
          crudas={vista === 'muestra' ? identificadores : periodos}
        />
      )}
    </div>
  )
}

function Tabla({
  resultado,
  etiquetas,
  crudas,
}: {
  resultado: ResultadoDatos
  etiquetas: Record<string, string>
  /** Columnas numéricas que se escriben tal cual, sin separador de miles. */
  crudas: Set<string>
}) {
  const orden = useOrden(resultado.filas, (f, c) => f[c])
  const pii = new Set(resultado.pii ?? [])

  return (
    <div className="resultado-datos">
      <div className="chico tenue" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <span>
          {resultado.filas.length} {resultado.filas.length === 1 ? 'fila' : 'filas'} ·{' '}
          {resultado.ms} ms
        </span>
        {/* Las políticas que se aplicaron: quien edita tiene que saber que está
            mirando un subconjunto, o creerá que faltan datos en el origen. */}
        {resultado.politicas_aplicadas.length > 0 && (
          <span className="etiqueta aviso">
            filtrado por: {resultado.politicas_aplicadas.join(', ')}
          </span>
        )}
        {pii.size > 0 && (
          <span className="etiqueta aviso">
            datos personales: {[...pii].join(', ')}
          </span>
        )}
      </div>

      {resultado.filas.length === 0 ? (
        <div className="vacio">La consulta no devolvió ninguna fila.</div>
      ) : (
        <div className="tabla-envoltura">
          <table className="datos">
            <thead>
              <tr>
                {resultado.columnas.map((c) => (
                  <Th
                    key={c}
                    orden={orden}
                    clave={c}
                    className={pii.has(c) ? 'pii' : ''}
                    titulo={c}
                  >
                    {etiquetas[c] ?? c}
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orden.filas.map((f, i) => (
                <tr key={i}>
                  {resultado.columnas.map((c) => (
                    <td key={c} className={typeof f[c] === 'number' ? 'num' : ''}>
                      {formatear(f[c], crudas.has(c))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <details className="chico">
        <summary className="suave">SQL ejecutado</summary>
        <pre className="mono" style={{ overflow: 'auto', maxHeight: 240 }}>
          {resultado.sql}
        </pre>
      </details>
    </div>
  )
}

function formatear(v: unknown, crudo = false): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') {
    if (crudo) return String(v)
    // `v === 0` también captura el -0 que sale de restar dos importes iguales, y
    // que impreso como «-0» parece un número mal calculado.
    if (v === 0) return '0'
    return v.toLocaleString('es-MX', { maximumFractionDigits: 2 })
  }
  if (typeof v === 'boolean') return v ? 'sí' : 'no'
  return String(v)
}
