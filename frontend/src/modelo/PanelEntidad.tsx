/**
 * Inspector de una entidad: su tipo, su clave, su grano y el rol de cada campo.
 *
 * El rol no es una etiqueta descriptiva: decide qué puede hacer el campo. Una
 * `medida_base` se puede sumar dentro de una métrica; una `dimension` sirve para
 * agrupar; una `clave_externa` es por donde pasa un join. Cambiarlo cambia lo que
 * el modelo permite, así que se edita aquí, a la vista, y no en un YAML aparte.
 */

import { useState } from 'react'

import type { Campo, Definicion, Entidad, RolCampo, TipoEntidad } from '../api/tipos'
import { useTabla } from '../api/hooks'
import {
  ETIQUETA_ROL,
  type Accion,
  confirmarClave,
  describirUsos,
  resincronizar,
  usosDeCampo,
} from './estado'
import { useOrden } from '../comunes/orden'
import { Th } from '../comunes/Th'

const ROLES: RolCampo[] = ['clave', 'clave_externa', 'dimension', 'medida_base']

export function PanelEntidad({
  entidad,
  definicion,
  despachar,
  enRelaciones,
}: {
  entidad: Entidad
  /** El borrador entero: hace falta para contar a quién afecta cambiar la clave. */
  definicion: Definicion
  despachar: (a: Accion) => void
  /** Cuántas relaciones la usan: borrarla se las lleva. */
  enRelaciones: number
}) {
  const cambiar = (cambios: Partial<Entidad>) =>
    despachar({ t: 'cambiar_entidad', nombre: entidad.nombre, cambios })

  // Las columnas que tiene el origen AHORA MISMO, para poder compararlas con la
  // copia que guarda la entidad. Se pide siempre: es una consulta cacheada por
  // TanStack y saber que hay desfase importa antes de que alguien lo pregunte.
  const origen = useTabla(entidad.origen.tabla)
  const [resultado, setResultado] = useState<string | null>(null)

  const enOrigen = origen.data?.columnas ?? []
  const desfase = enOrigen.length
    ? resincronizar(entidad, enOrigen)
    : null
  const hayDesfase = !!desfase
    && (desfase.retipados.length > 0 || desfase.nuevas.length > 0
      || desfase.desaparecidas.length > 0)

  // Una columna que ya no existe se puede quitar sin más si no la usa nadie. Las que
  // sí, no: quitar una con una relación encima rompería el modelo lejos de este
  // botón, en la primera consulta. Se separan para poder decir cada cosa.
  const desaparecidas = (desfase?.desaparecidas ?? []).map((campo) => ({
    campo,
    usos: describirUsos(usosDeCampo(definicion, entidad.nombre, campo)),
  }))
  const sueltas = desaparecidas.filter((x) => x.usos === null).map((x) => x.campo)
  const ocupadas = desaparecidas.filter(
    (x): x is { campo: string; usos: string } => x.usos !== null,
  )

  /**
   * A qué columna se renombró cada una que desapareció, cuando se puede adivinar.
   *
   * Solo con una desaparecida y una candidata del mismo tipo: con dos y dos ya no hay
   * forma de saber cuál va con cuál, y emparejarlas al azar movería las relaciones de
   * sitio sin que nadie lo pidiera. Se propone, y confirma quien sabe.
   */
  const sugerencias: Record<string, string> = {}
  if (desfase && desfase.desaparecidas.length === 1) {
    const ida = desfase.desaparecidas[0]!
    const tipoIda = entidad.campos.find((c) => c.nombre === ida)?.tipo
    // Candidatas: las que llegaron nuevas, o —si ya se pulsó «actualizar» antes— las
    // del origen que no estaban en la entidad cuando se agregó.
    const candidatas = desfase.nuevas.length
      ? enOrigen.filter((c) => desfase.nuevas.includes(c.nombre))
      : enOrigen.filter((c) => c.tipo === tipoIda)
    if (candidatas.length === 1) sugerencias[ida] = candidatas[0]!.nombre
  }

  const [renombres, setRenombres] = useState<Record<string, string>>({})

  const orden = useOrden(entidad.campos, (c, clave) =>
    clave === 'nombre' ? c.nombre
    : clave === 'tipo' ? c.tipo
    : clave === 'rol' ? c.rol
    : clave === 'ver' ? c.visible !== false
    : clave === 'unico' ? c.nombre === entidad.clave_primaria || c.unico === true
    : c.pii === true)

  const cambiarCampo = (campo: string, cambios: Partial<Campo>) =>
    despachar({ t: 'cambiar_campo', entidad: entidad.nombre, campo, cambios })

  function quitar() {
    const aviso =
      enRelaciones > 0
        ? `Se quitará '${entidad.nombre}' y con ella ${enRelaciones} relación(es) y sus métricas. ¿Continuar?`
        : `¿Quitar '${entidad.nombre}' del modelo?`
    if (confirm(aviso)) despachar({ t: 'quitar_entidad', nombre: entidad.nombre })
  }

  return (
    <div className="inspector">
      <h3>
        <span className={`punto ${entidad.tipo}`} />
        {entidad.nombre}
      </h3>
      <div className="chico tenue mono">tabla: {entidad.origen.tabla}</div>

      <div className="fila">
        <div className="campo">
          <label>Tipo</label>
          <select
            value={entidad.tipo}
            onChange={(e) => cambiar({ tipo: e.target.value as TipoEntidad })}
          >
            <option value="dimension">dimensión</option>
            <option value="hecho">hecho</option>
          </select>
        </div>
        <div className="campo">
          <label>Clave primaria</label>
          <select
            value={entidad.clave_primaria ?? ''}
            // Cambiarla no añade: sustituye. Las relaciones que unían contra la
            // anterior se quedan sin la garantía de que su columna no se repite,
            // y el aviso que alguien venía a quitar reaparece en otras ocho.
            onChange={(e) => {
              const nueva = e.target.value || null
              if (nueva && !confirmarClave(definicion, entidad.nombre, nueva)) return
              cambiar({ clave_primaria: nueva })
            }}
          >
            <option value="">(ninguna)</option>
            {orden.filas.map((c) => (
              <option key={c.nombre} value={c.nombre}>
                {c.nombre}
              </option>
            ))}
          </select>
        </div>
      </div>

      {entidad.tipo === 'hecho' && (
        <div className="campo">
          <label>Grano — qué identifica una fila</label>
          <input
            type="text"
            className="mono"
            value={(entidad.grano ?? []).join(', ')}
            placeholder="venta_id"
            onChange={(e) =>
              cambiar({
                grano: e.target.value
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
          <span className="chico tenue">
            Declararlo es lo que permite detectar que una métrica se está
            duplicando al cruzarla con otra de grano distinto.
          </span>
        </div>
      )}

      {/*
        El desfase con el origen se avisa solo. Es el fallo que no se ve: la
        transformación se cambia, el modelo sigue con la copia vieja y lo único
        que se nota es un tipo raro en una tabla de catorce campos.
      */}
      {hayDesfase && (
        <div className="aviso-caja">
          <b className="mono">{entidad.origen.tabla}</b> ya no es como se leyó al
          agregarla:
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {desfase!.retipados.length > 0 && (
              <li>
                cambió el tipo de {desfase!.retipados.length}:{' '}
                <span className="mono">{desfase!.retipados.join(', ')}</span>
              </li>
            )}
            {desfase!.nuevas.length > 0 && (
              <li>
                {desfase!.nuevas.length} columna(s) nueva(s):{' '}
                <span className="mono">{desfase!.nuevas.join(', ')}</span>
              </li>
            )}
            {sueltas.length > 0 && (
              <li>
                ya no está(n) y no las usa nadie:{' '}
                <span className="mono">{sueltas.join(', ')}</span>
                {' '}— se quitan al actualizar.
              </li>
            )}
            {ocupadas.length > 0 && (
              <li>
                ya no está(n) pero <b>algo las usa</b>, así que hay que decidir:
                <ul style={{ margin: '4px 0 0', paddingLeft: 14 }}>
                  {ocupadas.map(({ campo, usos }) => (
                    <li key={campo} style={{ marginBottom: 2 }}>
                      <span className="mono">{campo}</span> — {usos}
                    </li>
                  ))}
                </ul>
              </li>
            )}
          </ul>

          {/*
            Renombrar es el caso normal y no había forma de decirlo. Se renombra una
            columna en la transformación y el modelo ve dos cosas: una que desapareció
            y otra nueva. Pulsar «actualizar» añadía la nueva y dejaba la vieja, así
            que el aviso no se iba NUNCA por más veces que se pulsara — y el botón
            parecía roto. Aquí se dice que son la misma, y el rol, la clave, el grano
            y las relaciones se van con el nombre nuevo.
          */}
          {desfase!.desaparecidas.length > 0 && enOrigen.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="chico" style={{ marginBottom: 4 }}>
                ¿Alguna es la misma con otro nombre?
              </div>
              {desfase!.desaparecidas.map((campo) => (
                <div
                  key={campo}
                  style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}
                >
                  <span className="mono chico" style={{ flex: '0 1 auto', minWidth: 0 }}>
                    {campo}
                  </span>
                  <span className="chico tenue">→</span>
                  <select
                    className="chico"
                    style={{ flex: 1, minWidth: 0 }}
                    value={renombres[campo] ?? sugerencias[campo] ?? ''}
                    onChange={(e) =>
                      setRenombres((r) => ({ ...r, [campo]: e.target.value }))
                    }
                  >
                    <option value="">(no, es otra cosa)</option>
                    {enOrigen.map((c) => (
                      <option key={c.nombre} value={c.nombre}>
                        {c.nombre} · {c.tipo}
                      </option>
                    ))}
                  </select>
                  <button
                    className="btn chico"
                    disabled={!(renombres[campo] ?? sugerencias[campo])}
                    onClick={() => {
                      const despues = renombres[campo] ?? sugerencias[campo]!
                      despachar({
                        t: 'renombrar_campo',
                        entidad: entidad.nombre,
                        antes: campo,
                        despues,
                      })
                      const usos = usosDeCampo(definicion, entidad.nombre, campo)
                      setResultado(
                        `'${campo}' pasó a ser '${despues}'.`
                        + (usos.relaciones.length
                          ? ` ${usos.relaciones.length} relación(es) apuntan ya al nombre nuevo.`
                          : '')
                        + (usos.metricas.length
                          ? ` Revisa la fórmula de: ${usos.metricas.join(', ')} —`
                            + ' el nombre viejo sigue escrito ahí y eso no se toca solo.'
                          : ''),
                      )
                    }}
                  >
                    Es la misma
                  </button>
                </div>
              ))}
            </div>
          )}

          <div style={{ marginTop: 8 }}>
            <button
              className="btn chico"
              onClick={() => {
                // El rol, la etiqueta, «ver» y «PII» se conservan: son trabajo
                // hecho a mano y volver a adivinarlos sería tirarlo.
                cambiar({ campos: desfase!.campos })
                // Y las que ya no existen y no usa nadie se van. Dejarlas era lo que
                // hacía que el aviso no se fuera nunca: se pulsaba el botón, se
                // añadía la columna nueva, y el mismo aviso seguía ahí.
                if (sueltas.length) {
                  despachar({
                    t: 'quitar_campos',
                    entidad: entidad.nombre,
                    campos: sueltas,
                  })
                }
                setResultado(
                  `${desfase!.retipados.length} tipo(s) al día, `
                  + `${desfase!.nuevas.length} columna(s) agregada(s), `
                  + `${sueltas.length} quitada(s).`
                  + (ocupadas.length
                    ? ` Quedan ${ocupadas.length} que algo usa: dile a qué se`
                      + ' renombraron, o quita antes lo que las usa.'
                    : ''),
                )
              }}
            >
              Actualizar columnas desde el origen
            </button>
          </div>
        </div>
      )}
      {/* Se muestra HAYA O NO desfase todavía. Solo cuando ya no quedaba nada por
          resolver era peor que no mostrarlo: el aviso más importante que sale de aquí
          —«revisa la fórmula de Utilidad, el nombre viejo sigue escrito ahí»— aparece
          justo después de renombrar una columna de tres, o sea con desfase pendiente,
          y así no se veía nunca. */}
      {resultado && (
        <div className="chico tenue">{resultado} Los roles se conservaron.</div>
      )}

      <div>
        <div className="chico suave" style={{ marginBottom: 4 }}>
          Campos ({entidad.campos.length})
        </div>
        {/* El panel es angosto y la tabla no se puede comprimir más sin volverse
            ilegible: se desplaza dentro de su caja, no empuja el panel. */}
        <div style={{ overflowX: 'auto' }}>
        <table className="campos">
          <thead>
            <tr>
              <Th orden={orden} clave="nombre">campo</Th>
              <Th orden={orden} clave="tipo">tipo</Th>
              <Th orden={orden} clave="rol">rol</Th>
              <Th orden={orden} clave="ver" titulo="Visible en la interfaz para quien explora">
                ver
              </Th>
              <Th
                orden={orden}
                clave="unico"
                titulo="No se repite: es lo que una relación muchos-a-uno necesita del lado «uno»"
              >
                única
              </Th>
              <Th orden={orden} clave="pii" titulo="Dato personal">PII</Th>
            </tr>
          </thead>
          <tbody>
            {entidad.campos.map((c) => (
              <tr key={c.nombre}>
                <td title={c.etiqueta ?? undefined}>{c.nombre}</td>
                <td className="tenue chico">{c.tipo}</td>
                <td>
                  <select
                    value={c.rol}
                    onChange={(e) =>
                      cambiarCampo(c.nombre, { rol: e.target.value as RolCampo })
                    }
                  >
                    {ROLES.map((r) => (
                      <option key={r} value={r}>
                        {ETIQUETA_ROL[r]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={c.visible !== false}
                    onChange={(e) =>
                      cambiarCampo(c.nombre, { visible: e.target.checked })
                    }
                  />
                </td>
                <td>
                  {/* La clave primaria es única por definición: la casilla sale
                      marcada y bloqueada, porque desmarcarla no significaría
                      nada y sí confundiría. */}
                  <input
                    type="checkbox"
                    checked={c.nombre === entidad.clave_primaria || !!c.unico}
                    disabled={c.nombre === entidad.clave_primaria}
                    title={c.nombre === entidad.clave_primaria
                      ? 'Es la clave primaria: única por definición'
                      : 'Marcar si esta columna no tiene valores repetidos'}
                    onChange={(e) => cambiarCampo(c.nombre, { unico: e.target.checked })}
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={!!c.pii}
                    onChange={(e) => cambiarCampo(c.nombre, { pii: e.target.checked })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      <button className="btn peligro" onClick={quitar}>
        Quitar del modelo
      </button>
    </div>
  )
}
