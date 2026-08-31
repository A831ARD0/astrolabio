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
 *
 * **Filtrar y ordenar los hace el servidor**, no esta pantalla, y eso no es un
 * detalle de implementación: el límite corta DESPUÉS. Una tabla de cien mil filas
 * llega recortada a doscientas, y ordenar esas doscientas por fecha no da la
 * última factura —da la última de las doscientas primeras que el motor encontró—.
 * Mientras el recorte no se dice, la tabla se lee como si fuera todo. Por eso el
 * orden y los filtros viajan a la consulta, y por eso el servidor pide una fila
 * más de las que va a devolver: para poder avisar de que hay más.
 */

import { useEffect, useState } from 'react'

import { useMuestra, useVistaPrevia } from '../api/hooks'
import type { Definicion, Filtro, ResultadoDatos } from '../api/tipos'
import { Combo } from '../comunes/Combo'
import type { Direccion, EstadoOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'
import { filtroDeTexto } from './filtroColumna'

type Vista = 'resultado' | 'muestra'

/**
 * Las funciones que comparan contra otro mes.
 *
 * Son las de la categoría «tiempo» del catálogo, y hay una prueba en el servidor
 * —`test_las_funciones_de_tiempo_de_la_pantalla_son_las_del_catalogo`— que falla si
 * se agrega una función de tiempo y esta lista se queda atrás. Duplicarla aquí es
 * lo de menos; que se desincronice en silencio sería lo malo.
 */
const DE_TIEMPO =
  /\b(ACUMANIO|MESANTERIOR|MISMOMESANIOANTERIOR|PROMEDIOMESES)\s*\(/i

/**
 * Las métricas que comparan contra otro mes, **contando las que lo hacen a través
 * de otra**.
 *
 * Tiene que ser transitivo: `% Crec MoM` es
 * `DIVIDIR([Unidades] - [Ventas Mes Anterior], [Ventas Mes Anterior], 0)` y no
 * nombra ninguna función de tiempo — la de tiempo es la que referencia. Mirar sólo
 * su propio texto la dejaba pasar, y el error volvía con otro nombre.
 */
function comparanContraOtroMes(
  metricas: { nombre: string; expresion: string }[],
): Set<string> {
  const porNombre = new Map(metricas.map((m) => [m.nombre, m.expresion]))
  const sabido = new Map<string, boolean>()

  function mira(nombre: string, enCurso: Set<string>): boolean {
    const ya = sabido.get(nombre)
    if (ya !== undefined) return ya
    // Un ciclo entre métricas es un error del modelo y lo dice el servidor; aquí
    // sólo hay que no quedarse dando vueltas.
    if (enCurso.has(nombre)) return false
    const expresion = porNombre.get(nombre)
    if (expresion === undefined) return false

    enCurso.add(nombre)
    let si = DE_TIEMPO.test(expresion)
    if (!si) {
      for (const ref of expresion.matchAll(/\[([^\]]+)\]/g)) {
        if (mira((ref[1] ?? '').trim(), enCurso)) {
          si = true
          break
        }
      }
    }
    enCurso.delete(nombre)
    sabido.set(nombre, si)
    return si
  }

  return new Set(
    metricas.filter((m) => mira(m.nombre, new Set())).map((m) => m.nombre),
  )
}

/** Por qué columna se ordena y en qué sentido. `null` = como venga del motor. */
type Orden = { clave: string; dir: Direccion } | null

/**
 * Los tres estados del encabezado —ascendente, descendente y **sin orden**—
 * llevados a un `EstadoOrden` que se resuelve en el servidor.
 *
 * El tercero importa: el orden de llegada suele significar algo, y sin poder
 * volver a él habría que recargar la página.
 */
function ordenServidor(
  actual: Orden,
  cambiar: (o: Orden) => void,
): EstadoOrden {
  return {
    clave: actual?.clave ?? null,
    dir: actual?.dir ?? 'asc',
    alternar(nueva: string) {
      if (nueva !== actual?.clave) cambiar({ clave: nueva, dir: 'asc' })
      else if (actual.dir === 'asc') cambiar({ clave: nueva, dir: 'desc' })
      else cambiar(null)
    },
  }
}

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
  /**
   * Las que se marcan solas al entrar.
   *
   * Seis, y **ninguna que compare contra otro mes**. Ésas necesitan una columna de
   * meses en el desglose, y al entrar no hay desglose: con un modelo de noventa y
   * seis métricas, entre las seis primeras caía una de tiempo y la pestaña se
   * abría con un error sobre una métrica que nadie había elegido. El error era
   * correcto y la conclusión razonable era que lo roto era la métrica que sí
   * habías marcado.
   *
   * Se reconocen por las funciones de tiempo del catálogo, que es la misma lista
   * que el servidor usa para exigir la columna.
   */
  const [metricas, setMetricas] = useState<string[]>(() => {
    const deTiempo = comparanContraOtroMes(definicion.metricas)
    return definicion.metricas
      .filter((m) => !deTiempo.has(m.nombre))
      .slice(0, 6)
      .map((m) => m.nombre)
  })
  const [desglose, setDesglose] = useState<string[]>([])
  const [entidad, setEntidad] = useState(
    () => hechos[0]?.nombre ?? definicion.entidades[0]?.nombre ?? '',
  )
  const [filas, setFilas] = useState(50)

  /**
   * Lo escrito en la casilla de cada columna, y por qué columna se ordena.
   *
   * Separados por vista: las columnas de una son «entidad.campo» y nombres de
   * métrica, las de la otra son los campos pelados de UNA tabla. Un filtro
   * arrastrado de una a otra hablaría de una columna que ahí no existe.
   */
  const [texRes, setTexRes] = useState<Record<string, string>>({})
  const [texMue, setTexMue] = useState<Record<string, string>>({})
  const [ordRes, setOrdRes] = useState<Orden>(null)
  const [ordMue, setOrdMue] = useState<Orden>(null)

  function ejecutar(t = texRes, o = ordRes) {
    previa.mutate({
      definicion, metricas, dimensiones: desglose, limite: 200,
      filtros: filtrosRes(t), orden: o?.clave ?? null, descendente: o?.dir === 'desc',
    })
  }

  /**
   * Tira el error al cambiar la selección.
   *
   * Un error habla de UNA consulta. Si se queda ahí después de quitar la métrica
   * que lo causaba, está describiendo algo que ya no se está pidiendo, y lo
   * razonable es concluir que lo roto es lo que acabas de marcar. Sólo el error:
   * la tabla de resultados lleva sus métricas en las cabeceras, así que se explica
   * sola mientras el botón «Calcular» sigue ahí.
   */
  function olvidarError() {
    if (previa.isError) previa.reset()
  }

  function verFilas(t = texMue, o = ordMue, n = filas) {
    muestra.mutate({
      definicion, entidad, limite: n,
      filtros: filtrosMue(t), orden: o?.clave ?? null, descendente: o?.dir === 'desc',
    })
  }

  /**
   * De qué tipo es cada campo del modelo, por «entidad.campo».
   *
   * Hace falta para saber si una casilla busca «contiene» o «igual», y se saca del
   * MODELO y no de las filas que llegaron: en cuanto un filtro deja la tabla
   * vacía ya no hay filas de donde deducir el tipo, y la siguiente cosa que se
   * escriba en la casilla se interpretaría al revés.
   */
  const tipoDe = new Map<string, string>()
  for (const e of definicion.entidades) {
    for (const c of e.campos) tipoDe.set(`${e.nombre}.${c.nombre}`, c.tipo)
  }
  const NUMERICOS = new Set(['entero', 'decimal'])
  const nombresMetrica = new Set(definicion.metricas.map((m) => m.nombre))

  function numericaRes(col: string): boolean {
    return nombresMetrica.has(col) || NUMERICOS.has(tipoDe.get(col) ?? '')
  }
  function numericaMue(col: string): boolean {
    return NUMERICOS.has(tipoDe.get(`${entidad}.${col}`) ?? '')
  }

  /**
   * Qué columnas del resultado se pueden filtrar: las del desglose.
   *
   * Las métricas no. Un filtro sobre una métrica es un `HAVING` —se aplica a la
   * cifra ya sumada— y el motor aplica estos filtros antes de sumar: la casilla
   * daría un número distinto del que se ve, que es peor que no tenerla. Se pueden
   * ORDENAR, y ordenar de mayor a menor contesta casi siempre la misma pregunta.
   */
  function filtrosRes(t: Record<string, string>): Filtro[] {
    return desglose
      .map((col) => filtroDeTexto(col, t[col] ?? '', numericaRes(col)))
      .filter((f): f is Filtro => f !== null)
  }

  function filtrosMue(t: Record<string, string>): Filtro[] {
    return Object.keys(t)
      .map((col) => filtroDeTexto(`${entidad}.${col}`, t[col] ?? '', numericaMue(col)))
      .filter((f): f is Filtro => f !== null)
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
                      onClick={() => {
                        olvidarError()
                        setMetricas((v) =>
                          v.includes(m.nombre)
                            ? v.filter((n) => n !== m.nombre)
                            : [...v, m.nombre],
                        )
                      }}
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
                        onClick={() => {
                          olvidarError()
                          setDesglose((v) => v.filter((x) => x !== d))
                          setTexRes(({ [d]: _fuera, ...resto }) => resto)
                          setOrdRes((o) => (o?.clave === d ? null : o))
                        }}
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
                      alElegir={(clave) => {
                        olvidarError()
                        setDesglose((v) => [...v, clave])
                      }}
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
                onClick={() => ejecutar()}
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
              onChange={(e) => {
                // Los filtros y el orden de la tabla anterior nombran columnas
                // que en la nueva no existen: se van con ella.
                setEntidad(e.target.value)
                setTexMue({})
                setOrdMue(null)
              }}
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
          <button className="btn primario" disabled={muestra.isPending} onClick={() => verFilas()}>
            {muestra.isPending ? 'Leyendo…' : 'Ver filas'}
          </button>
        </div>
      )}

      {activa.isError && (
        <div className="error-caja" style={{ margin: '0 12px' }}>
          {(activa.error as Error).message}
        </div>
      )}

      {activa.data &&
        (vista === 'muestra' ? (
          <Tabla
            resultado={activa.data}
            etiquetas={etiquetas}
            crudas={identificadores}
            limite={filas}
            orden={ordenServidor(ordMue, (o) => {
              setOrdMue(o)
              verFilas(texMue, o)
            })}
            filtros={{
              texto: texMue,
              // En la muestra todas: son las columnas de UNA tabla, tal cual.
              filtrable: () => true,
              alCambiar(col, valor) {
                const t = { ...texMue, [col]: valor }
                setTexMue(t)
                verFilas(t)
              },
              alLimpiar() {
                setTexMue({})
                verFilas({})
              },
            }}
          />
        ) : (
          <Tabla
            resultado={activa.data}
            etiquetas={etiquetas}
            crudas={periodos}
            limite={200}
            orden={ordenServidor(ordRes, (o) => {
              setOrdRes(o)
              ejecutar(texRes, o)
            })}
            filtros={{
              texto: texRes,
              filtrable: (col) => desglose.includes(col),
              alCambiar(col, valor) {
                const t = { ...texRes, [col]: valor }
                setTexRes(t)
                ejecutar(t)
              },
              alLimpiar() {
                setTexRes({})
                ejecutar({})
              },
            }}
          />
        ))}
    </div>
  )
}

/** Lo que la tabla necesita para tener una casilla de filtro por columna. */
interface Filtrado {
  texto: Record<string, string>
  /** Si esta columna admite casilla. Ver `filtrosRes`: las métricas no. */
  filtrable: (col: string) => boolean
  alCambiar: (col: string, valor: string) => void
  /** Quitar todos de una vez: hacerlo columna por columna dispara una consulta
   *  por columna, y todas menos la última verían el estado anterior. */
  alLimpiar: () => void
}

function Tabla({
  resultado,
  etiquetas,
  crudas,
  orden,
  filtros,
  limite,
}: {
  resultado: ResultadoDatos
  etiquetas: Record<string, string>
  /** Columnas numéricas que se escriben tal cual, sin separador de miles. */
  crudas: Set<string>
  /** El orden lo resuelve el servidor. Ver la cabecera del módulo. */
  orden: EstadoOrden
  filtros: Filtrado
  /** Cuántas filas se pidieron, para poder decir de qué recorte se habla. */
  limite: number
}) {
  const pii = new Set(resultado.pii ?? [])
  const puestos = resultado.columnas.filter((c) => (filtros.texto[c] ?? '') !== '')

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
        {/* El recorte, dicho. Sin esto la tabla se lee como si fuera todo, y la
            fila de arriba parece la primera de los datos cuando es la primera de
            las que caben. */}
        {resultado.truncado && (
          <span className="etiqueta aviso">
            hay más de {limite}: se enseñan las {limite} primeras del orden
            actual. Ordena o filtra para acercarte a las que buscas.
          </span>
        )}
        {puestos.length > 0 && (
          <button
            type="button"
            className="enlace"
            onClick={filtros.alLimpiar}
          >
            quitar {puestos.length === 1 ? 'el filtro' : `los ${puestos.length} filtros`}
          </button>
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
                    debajo={
                      filtros.filtrable(c) ? (
                        <CasillaFiltro
                          valor={filtros.texto[c] ?? ''}
                          alConfirmar={(v) => filtros.alCambiar(c, v)}
                        />
                      ) : (
                        // El hueco, para que todas las cabeceras midan igual: sin
                        // él las columnas con casilla quedan más altas que las de
                        // las métricas y la cabecera sale escalonada.
                        <span className="sin-filtro" />
                      )
                    }
                  >
                    {etiquetas[c] ?? c}
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {resultado.filas.map((f, i) => (
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

/**
 * La casilla de filtro de una columna.
 *
 * Se confirma con Enter o al salir, no a cada tecla: cada confirmación es una
 * consulta al servidor, y filtrar letra por letra serían seis consultas para
 * escribir «VOLVO», con la penúltima llegando después de la última.
 *
 * El texto se guarda aquí mientras se escribe y se sincroniza con el de fuera
 * cuando éste cambia —al limpiar todos, por ejemplo—, que es lo que evita que la
 * casilla se quede con lo que ya no está aplicado.
 */
function CasillaFiltro({
  valor,
  alConfirmar,
}: {
  valor: string
  alConfirmar: (v: string) => void
}) {
  const [texto, setTexto] = useState(valor)
  useEffect(() => setTexto(valor), [valor])

  return (
    <input
      className="filtro-columna"
      value={texto}
      placeholder="filtrar…"
      title={
        'Filtra en el servidor, no sólo lo que se ve.\n\n' +
        'texto      contiene (en columnas de texto) · igual (en números)\n' +
        '=texto     exactamente igual\n' +
        '>100       también >=, <, <=, <> y !=\n' +
        'a, b, c    cualquiera de la lista\n\n' +
        'Se aplica con Enter, o al salir de la casilla.'
      }
      onChange={(e) => setTexto(e.target.value)}
      onBlur={() => {
        if (texto !== valor) alConfirmar(texto)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') alConfirmar(texto)
        if (e.key === 'Escape') setTexto(valor)
      }}
    />
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
