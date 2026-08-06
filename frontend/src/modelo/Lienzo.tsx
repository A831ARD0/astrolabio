/**
 * El lienzo del modelo.
 *
 * Traduce la definición a nodos y aristas y devuelve las acciones. No guarda
 * estado propio del modelo: la única fuente es el borrador. Si el lienzo tuviera
 * su propia copia, arrastrar un nodo y guardar podrían discrepar.
 */

import {
  Background,
  Controls,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  MiniMap,
  ReactFlow,
  useNodesState,
} from '@xyflow/react'
import { useEffect, useMemo } from 'react'

import type { Definicion, Problema } from '../api/tipos'
import { type DatosNodo, NodoEntidad } from './NodoEntidad'
import { ETIQUETA_CARDINALIDAD, type Accion, cardinalidadProbable } from './estado'

const TIPOS_NODO = { entidad: NodoEntidad }

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

  useEffect(() => {
    setNodos((previos) => {
      const antes = new Map(previos.map((n) => [n.id, n]))
      return calculados.map((n) => {
        const p = antes.get(n.id)
        return p ? { ...p, ...n, measured: p.measured } : n
      })
    })
  }, [calculados, setNodos])

  const aristas: Edge[] = useMemo(
    () =>
      definicion.relaciones.map((r, i) => ({
        id: `r${i}`,
        source: r.desde[0],
        sourceHandle: r.desde[1],
        target: r.hasta[0],
        targetHandle: r.hasta[1],
        label: ETIQUETA_CARDINALIDAD[r.cardinalidad],
        labelShowBg: true,
        selected: seleccion?.tipo === 'relacion' && seleccion.id === i,
        className: [
          r.cardinalidad === 'muchos_a_muchos' && 'm2m',
          // Solo se pinta en rojo la relación que forma parte de la ruta que se
          // está inspeccionando: pintar todas las sospechosas no dice cuál.
          resaltadas?.has(r.desde[0]) && resaltadas?.has(r.hasta[0]) && 'ambigua',
        ]
          .filter(Boolean)
          .join(' '),
      })),
    [definicion.relaciones, seleccion, resaltadas],
  )

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
        onEdgeClick={(_, e) =>
          alSeleccionar({ tipo: 'relacion', id: Number(e.id.slice(1)) })
        }
        onPaneClick={() => alSeleccionar(null)}
        fitView
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={18} size={1} color="var(--borde)" />
        <Controls showInteractive={false} />
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
