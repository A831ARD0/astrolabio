/**
 * El lienzo del modelo.
 *
 * Traduce la definición a nodos y aristas y devuelve las acciones. No guarda
 * estado propio del modelo: la única fuente es el borrador. Si el lienzo tuviera
 * su propia copia, arrastrar un nodo y guardar podrían discrepar.
 */

import {
  Background,
  ControlButton,
  Controls,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  MiniMap,
  ReactFlow,
  useNodesState,
  useReactFlow,
} from '@xyflow/react'
import { useEffect, useMemo, useState } from 'react'

import type { Definicion, Problema } from '../api/tipos'
import { type DatosNodo, NodoEntidad } from './NodoEntidad'
import { ETIQUETA_CARDINALIDAD, type Accion, cardinalidadProbable } from './estado'
import { disponer } from './disponer'

const TIPOS_NODO = { entidad: NodoEntidad }

/**
 * Hueco mínimo entre dos tablas para que la curva salga limpia.
 *
 * Por debajo de esto la curva no tiene sitio para separarse de los bordes y se pega
 * a las tablas o se enrosca; se usa ruta ortogonal en su lugar.
 */
const HUECO_MINIMO = 24

/**
 * El botón de reorganizar, dentro del lienzo para poder ajustar la vista.
 *
 * Ajustarla no es un adorno: recolocar todo y dejar la cámara donde estaba hace que
 * el modelo aparezca diminuto en una esquina, y lo que se lee entonces es «no ha
 * pasado nada». Y va DOS fotogramas después porque las posiciones nuevas hacen dos
 * viajes antes de existir para el lienzo: del reductor a las propiedades, y de ahí al
 * estado que React Flow usa para medir. Ajustar en el primero encuadra las de antes.
 */
function BotonReorganizar({ alPulsar }: { alPulsar: () => void }) {
  const rf = useReactFlow()
  return (
    <ControlButton
      onClick={() => {
        alPulsar()
        requestAnimationFrame(() =>
          requestAnimationFrame(() => rf.fitView({ padding: 0.12, duration: 300 })),
        )
      }}
      title="Reorganizar: hechos a la izquierda y dimensiones a la derecha, sin que se toquen y sin líneas por encima de las tablas. Se puede deshacer."
    >
      ⊞
    </ControlButton>
  )
}

export interface Seleccion {
  tipo: 'entidad' | 'relacion'
  id: string | number
}

interface Props {
  definicion: Definicion
  problemas: Problema[]
  seleccion: Seleccion | null
  alSeleccionar: (s: Seleccion | null) => void
  despachar: (a: Accion) => void
  /** Entidades a resaltar: las de la ruta que el usuario está inspeccionando. */
  resaltadas?: Set<string>
}

export function Lienzo({
  definicion,
  problemas,
  seleccion,
  alSeleccionar,
  despachar,
  resaltadas,
}: Props) {
  /** Entidades mencionadas por un problema crítico, para pintarlas. */
  const conProblema = useMemo(() => {
    const s = new Set<string>()
    for (const p of problemas) {
      if (p.gravedad !== 'critico') continue
      for (const parte of p.entidad.split('→')) s.add(parte.trim())
      for (const ruta of p.rutas ?? []) {
        for (const parte of ruta.split('→')) s.add(parte.trim())
      }
    }
    return s
  }, [problemas])

  const huerfanas = useMemo(
    () =>
      new Set(
        problemas.filter((p) => p.tipo === 'tabla_huerfana').map((p) => p.entidad),
      ),
    [problemas],
  )

  /** Campos que participan en alguna relación, para marcarlos en el nodo. */
  const camposRelacionados = useMemo(() => {
    const m = new Map<string, Set<string>>()
    for (const r of definicion.relaciones) {
      for (const [ent, campo] of [r.desde, r.hasta]) {
        if (!m.has(ent)) m.set(ent, new Set())
        m.get(ent)!.add(campo)
      }
    }
    return m
  }, [definicion.relaciones])

  const calculados: Node<DatosNodo>[] = useMemo(
    () =>
      definicion.entidades.map((e) => ({
        id: e.nombre,
        type: 'entidad',
        position: definicion.disposicion[e.nombre] ?? { x: 0, y: 0 },
        data: {
          entidad: e,
          seleccionada: seleccion?.tipo === 'entidad' && seleccion.id === e.nombre,
          resaltada: !!resaltadas?.has(e.nombre),
          conProblema: conProblema.has(e.nombre),
          huerfana: huerfanas.has(e.nombre),
          camposEnRelacion: camposRelacionados.get(e.nombre) ?? new Set(),
        },
      })),
    [
      definicion.entidades,
      definicion.disposicion,
      seleccion,
      resaltadas,
      conProblema,
      huerfanas,
      camposRelacionados,
    ],
  )

  /*
   * React Flow guarda las medidas de cada nodo (`measured`) al montarlo, y las
   * necesita para el minimapa y para trazar las aristas. Si en cada render se le
   * pasaran objetos nuevos, esas medidas se perderían: el minimapa sale vacío y
   * los nodos se vuelven a medir sin parar.
   *
   * Así que el estado de los nodos lo lleva React Flow y aquí solo se sincroniza
   * lo que cambió, conservando la medida del nodo que ya existía. La fuente de
   * verdad del modelo sigue siendo el borrador; esto es solo la copia que dibuja.
   */
  const [nodos, setNodos, alCambiarNodosRF] = useNodesState<Node<DatosNodo>>([])

  /** Se está arrastrando una unión: los conectores se hacen visibles. */
  const [conectando, setConectando] = useState(false)

  /**
   * La tabla que tiene el ratón encima. Sus relaciones se quedan y las demás se
   * apagan.
   *
   * Con veinticuatro relaciones, saber cuáles son las de UNA tabla mirando el
   * dibujo es imposible: hay que seguir una línea con el dedo entre otras veinte
   * que la cruzan. Apagar el resto un instante contesta esa pregunta sin cambiar
   * nada del modelo, y se deshace solo al quitar el ratón.
   */
  const [sobre, setSobre] = useState<string | null>(null)

  useEffect(() => {
    setNodos((previos) => {
      const antes = new Map(previos.map((n) => [n.id, n]))
      return calculados.map((n) => {
        const p = antes.get(n.id)
        return p ? { ...p, ...n, measured: p.measured } : n
      })
    })
  }, [calculados, setNodos])

  /**
   * Dónde empieza y acaba cada tabla, para decidir por qué cara sale cada línea.
   *
   * Sale de `nodos` y no de `definicion.disposicion` porque las tablas no miden todas
   * lo mismo —el ancho lo fija el nombre de columna más largo— y hace falta el ancho
   * medido, que es el que tiene React Flow. Mientras se arrastra se recalcula, así
   * que la línea cambia de lado en el momento en que la tabla pasa al otro.
   */
  const cajas = useMemo(() => {
    const m = new Map<string, { izq: number; der: number; centro: number }>()
    for (const n of nodos) {
      const ancho = n.measured?.width ?? 0
      m.set(n.id, {
        izq: n.position.x,
        der: n.position.x + ancho,
        centro: n.position.x + ancho / 2,
      })
    }
    return m
  }, [nodos])

  const aristas: Edge[] = useMemo(
    () =>
      definicion.relaciones.map((r, i) => {
        // Empatados o sin medir todavía: por la derecha, que es como estaba.
        const origenALaIzquierda =
          (cajas.get(r.desde[0])?.centro ?? 0) <= (cajas.get(r.hasta[0])?.centro ?? 0)
        // La línea se dibuja de la columna de la izquierda a la de la derecha,
        // aunque la relación vaya al contrario. Los conectores son uno por lado
        // —origen a la derecha, destino a la izquierda—, así que dibujarla siempre
        // en el sentido de la relación obligaba a las que van hacia la izquierda a
        // salir por la derecha, cruzar el lienzo entero y volver a entrar por la
        // izquierda, pasando por dentro de las dos tablas: eran los lazos.
        //
        // Invertir el dibujo no cambia la relación —lo que se guarda sigue siendo
        // `desde` → `hasta`, y de ahí salen la cardinalidad y el SQL—, solo por qué
        // cara sale la línea. Estas líneas no llevan punta de flecha; si algún día
        // la llevan, hay que apuntarla según la relación y no según el dibujo.
        const [izq, der] = origenALaIzquierda ? [r.desde, r.hasta] : [r.hasta, r.desde]
        // Cuando las dos tablas se solapan horizontalmente no hay orientación que
        // evite que la línea retroceda, y una curva que retrocede se enrosca sobre
        // sí misma —el rizo que se veía entre tablas puestas una encima de otra—.
        // Ahí se cambia a ruta ortogonal, que rodea en ángulo recto y se lee. Es un
        // trazo distinto para un caso distinto, no una inconsistencia.
        const hueco = (cajas.get(der[0])?.izq ?? 0) - (cajas.get(izq[0])?.der ?? 0)
        return {
          id: `r${i}`,
          type: hueco < HUECO_MINIMO ? 'smoothstep' : undefined,
          source: izq[0],
          sourceHandle: izq[1],
          target: der[0],
          targetHandle: der[1],
          label: r.activa === false
            ? `${ETIQUETA_CARDINALIDAD[r.cardinalidad]} · inactiva`
            : ETIQUETA_CARDINALIDAD[r.cardinalidad],
          labelShowBg: true,
          selected: seleccion?.tipo === 'relacion' && seleccion.id === i,
          className: [
            r.cardinalidad === 'muchos_a_muchos' && 'm2m',
            // Punteada y apagada: existe, se puede activar, y ninguna consulta
            // pasa por ella. Verla igual que las demás haría creer que sí.
            r.activa === false && 'inactiva',
            // Solo se pinta en rojo la relación que forma parte de la ruta que se
            // está inspeccionando: pintar todas las sospechosas no dice cuál.
            resaltadas?.has(r.desde[0]) && resaltadas?.has(r.hasta[0]) && 'ambigua',
            sobre !== null && r.desde[0] !== sobre && r.hasta[0] !== sobre && 'apagada',
          ]
            .filter(Boolean)
            .join(' '),
        }
      }),
    [definicion.relaciones, seleccion, resaltadas, cajas, sobre],
  )

  /**
   * Recolocar todas las tablas. Es un botón y no algo automático a propósito: la
   * disposición viaja con la versión del modelo, y mover de sitio el trabajo de
   * alguien sin que lo haya pedido es peor que dejarlo desordenado.
   */
  function reorganizar() {
    const medidas = Object.fromEntries(
      nodos.map((n) => [
        n.id,
        { ancho: n.measured?.width ?? 0, alto: n.measured?.height ?? 0 },
      ]),
    )
    despachar({ t: 'reorganizar', disposicion: disponer(definicion, medidas) })
  }

  function alConectar(c: Connection) {
    if (!c.source || !c.target || !c.sourceHandle || !c.targetHandle) return
    if (c.source === c.target) return // una entidad no se relaciona consigo misma
    despachar({
      t: 'agregar_relacion',
      desde: [c.source, c.sourceHandle],
      hasta: [c.target, c.targetHandle],
      cardinalidad: cardinalidadProbable(
        definicion.entidades,
        c.target,
        c.targetHandle,
      ),
    })
    alSeleccionar({ tipo: 'relacion', id: definicion.relaciones.length })
  }

  function alCambiarNodos(cambios: NodeChange<Node<DatosNodo>>[]) {
    alCambiarNodosRF(cambios)      // arrastre y medidas los lleva React Flow
    for (const c of cambios) {
      // Al modelo solo llega la posición final: guardar cada píxel llenaría el
      // historial de deshacer con pasos que nadie quiere deshacer.
      if (c.type === 'position' && c.position && c.dragging === false) {
        despachar({ t: 'mover', entidad: c.id, x: c.position.x, y: c.position.y })
      }
    }
  }

  return (
    <div className="lienzo">
      <ReactFlow
        nodes={nodos}
        edges={aristas}
        nodeTypes={TIPOS_NODO}
        onNodesChange={alCambiarNodos}
        onConnect={alConectar}
        onNodeClick={(_, n) => alSeleccionar({ tipo: 'entidad', id: n.id })}
        onNodeMouseEnter={(_, n) => setSobre(n.id)}
        onNodeMouseLeave={() => setSobre(null)}
        onEdgeClick={(_, e) =>
          alSeleccionar({ tipo: 'relacion', id: Number(e.id.slice(1)) })
        }
        onPaneClick={() => alSeleccionar(null)}
        onConnectStart={() => setConectando(true)}
        onConnectEnd={() => setConectando(false)}
        // Suelta en el conector más cercano dentro de este radio. Sin esto hay
        // que soltar DENTRO del punto, y a un zoom del 60% eso son cinco píxeles
        // reales: la queja de que cuesta trabajo hacer las uniones era esto.
        connectionRadius={38}
        className={conectando ? 'conectando' : undefined}
        fitView
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={18} size={1} color="var(--borde)" />
        <Controls showInteractive={false}>
          <BotonReorganizar alPulsar={reorganizar} />
        </Controls>
        {/* Tamaño y máscara van en el CSS. Aquí solo el color por tipo, que
            depende del dato y tiene que ser un color literal: un var() dentro de
            un atributo de SVG no se resuelve. */}
        <MiniMap
          pannable
          zoomable
          bgColor="transparent"
          nodeStrokeWidth={0}
          nodeColor={(n) =>
            (n.data as DatosNodo).entidad.tipo === 'hecho' ? '#f0a35e' : '#4c8dff'
          }
        />
      </ReactFlow>
    </div>
  )
}
