/**
 * Panel de filtro asociativo — los cuatro estados de Qlik.
 *
 *   seleccionado  el usuario lo eligió                        (verde)
 *   posible       sobrevive a las selecciones de otros campos (normal)
 *   alternativo   sería posible, pero hay una selección en su
 *                 propio campo que no lo incluye              (atenuado)
 *   excluido      no sobrevive a las selecciones              (tachado)
 *
 * La distinción entre **alternativo** y **excluido** es la que separa un motor
 * asociativo de verdad de una imitación con listas desplegables. Si eliges Aurex,
 * las demás marcas siguen siendo elegibles (alternativas): la lista no debe
 * tacharlas como si no existieran. Las sucursales que no venden Aurex, en cambio,
 * sí están excluidas.
 *
 * La lista vive en `ListaValores` y no dentro del panel porque el mismo campo se
 * dibuja de dos formas —lista abierta cuando hay espacio, desplegable cuando no— y
 * las dos tienen que comportarse igual. Si cada forma tuviera su propia lista,
 * tarde o temprano una de las dos dejaría de distinguir alternativo de excluido.
 */

import { useMemo, useState } from 'react'

import type { Estados } from '../api/tipos'

type Estado = keyof Estados

const ORDEN: Estado[] = ['seleccionado', 'posible', 'alternativo', 'excluido']

const AYUDA: Record<Estado, string> = {
  seleccionado: 'elegido',
  posible: 'compatible con lo que ya elegiste',
  alternativo: 'se podría elegir; hay otra selección en este mismo campo',
  excluido: 'no existe en combinación con lo que ya elegiste',
}

export function ListaValores({
  estados,
  cargando,
  error,
  alAlternar,
}: {
  estados: Estados | undefined
  cargando: boolean
  error: Error | null
  alAlternar: (valor: unknown) => void
}) {
  const [busqueda, setBusqueda] = useState('')

  const items = useMemo(() => {
    if (!estados) return []
    const lista: { valor: unknown; estado: Estado }[] = []
    for (const estado of ORDEN) {
      for (const valor of estados[estado]) lista.push({ valor, estado })
    }
    const q = busqueda.trim().toLowerCase()
    return q
      ? lista.filter((i) => String(i.valor).toLowerCase().includes(q))
      : lista
  }, [estados, busqueda])

  return (
    // El envoltorio lleva la clase, y el estilo cuelga de aquí y no del panel.
    // Cuando colgaba de `.filtro`, la misma lista dibujada en el portal del
    // desplegable no heredaba nada: salía con viñetas y sin los cuatro estados.
    <div className="lista-valores">
      {items.length > 8 && (
        <input
          type="search"
          placeholder="Buscar…"
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
          className="buscar"
        />
      )}

      {cargando && <div className="vacio chico">Calculando…</div>}
      {error && <div className="error-caja chico">{error.message}</div>}

      <ul className="valores">
        {items.map(({ valor, estado }) => (
          <li key={String(valor)}>
            <button
              className={`valor ${estado}`}
              title={AYUDA[estado]}
              onClick={() => alAlternar(valor)}
            >
              <span className="marca" />
              <span className="txt">{String(valor)}</span>
            </button>
          </li>
        ))}
        {!cargando && items.length === 0 && (
          <li className="vacio chico">Sin valores</li>
        )}
      </ul>
    </div>
  )
}

export function FiltroCampo({
  campo,
  etiqueta,
  estados,
  cargando,
  error,
  alAlternar,
  alLimpiar,
}: {
  campo: string
  etiqueta: string
  estados: Estados | undefined
  cargando: boolean
  error: Error | null
  alAlternar: (valor: unknown) => void
  alLimpiar: () => void
}) {
  const sel = estados?.seleccionado ?? []
  const elegidos = sel.length

  return (
    <div className="filtro">
      <header>
        <span className="nom" title={campo}>
          {etiqueta}
        </span>
        {elegidos > 0 && (
          <button className="btn chico" onClick={alLimpiar} title="Quitar la selección">
            {elegidos} ✕
          </button>
        )}
      </header>

      {/* En papel un filtro no imprime su lista de cuarenta valores: imprime en
          qué quedó. Un informe que enseña las opciones y no la elección no dice
          nada, y ocupa una página entera para no decirlo. */}
      <div className="solo-papel">
        {elegidos === 0
          ? 'todos'
          : elegidos <= 6
            ? sel.map(String).join(', ')
            : `${elegidos} valores elegidos`}
      </div>

      <ListaValores
        estados={estados}
        cargando={cargando}
        error={error}
        alAlternar={alAlternar}
      />
    </div>
  )
}
