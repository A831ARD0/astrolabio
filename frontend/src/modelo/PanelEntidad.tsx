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
import { useComprobarGrano, useTabla } from '../api/hooks'
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
  modeloId,
  entidad,
  definicion,
  despachar,
  enRelaciones,
}: {
  modeloId: number
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
  const grano = useComprobarGrano(modeloId)
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
    : clave === 'mes' ? c.grano_tiempo === 'mes'
    : c.pii === true)

  /**
   * Cambiar el grano tira el resultado de la última comprobación.
   *
   * Ese cuadro dice «se cumple» sobre unas columnas concretas. Si se quita una y
   * el cuadro se queda, está afirmando de un grano nuevo lo que se comprobó del
   * viejo — y es una afirmación sobre cifras: justo la que no puede quedarse
   * colgada en pantalla.
   */
  const fijarGrano = (cols: string[]) => {
    grano.reset()
    cambiar({ grano: cols })
  }

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
          {/*
            Se elige de una lista, no se escribe. Escribirlo era pedir el nombre
            exacto de una columna de memoria y separarlo por comas: un `Fecha_objetivo`
            con la o minúscula no es un error de tipografía, es un grano que habla de
            una columna que no existe. Y comprobarlo sólo puede decir eso mismo.
          */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            {(entidad.grano ?? []).map((c) => (
              <span className="chip mono" key={c}>
                {c}
                <button
                  type="button"
                  title={`Quitar ${c} del grano`}
                  onClick={() => fijarGrano((entidad.grano ?? []).filter((x) => x !== c))}
                >
                  ×
                </button>
              </span>
            ))}
            <select
              // Vuelve siempre a «(agregar)»: no es un valor elegido, es una acción
              // que añade uno más. Dejarlo marcado haría creer que se puede cambiar
              // desde ahí lo que ya está puesto.
              value=""
              onChange={(e) => {
                if (e.target.value)
                  fijarGrano([...(entidad.grano ?? []), e.target.value])
              }}
            >
              <option value="">
                {(entidad.grano ?? []).length
                  ? '+ y también…'
                  : '+ elige la columna'}
              </option>
              {orden.filas
                .filter((c) => !(entidad.grano ?? []).includes(c.nombre))
                .map((c) => (
                  <option key={c.nombre} value={c.nombre}>
                    {c.nombre}
                  </option>
                ))}
            </select>
          </div>
          {/*
            El grano es una AFIRMACIÓN, y por eso hay un botón para comprobarla:
            «sucursal y mes juntas no se repiten» es fácil de creer y fácil de que
            sea falso, y si es falso todo lo que se sume de esta tabla cuenta algo
            dos veces. Se comprueba con la definición de pantalla, sin guardar,
            porque el momento de la duda es mientras se declara.
          */}
          <div className="fila" style={{ alignItems: 'center', gap: 8 }}>
            <span className="chico tenue" style={{ flex: 1 }}>
              Son las columnas que <strong>juntas</strong> identifican una fila.
              No es la clave primaria: esa es una sola columna y es por donde se
              une.
            </span>
            <button
              className="btn chico"
              style={{ flex: '0 0 auto' }}
              disabled={(entidad.grano ?? []).length === 0 || grano.isPending}
              title={
                (entidad.grano ?? []).length === 0
                  ? 'Declara el grano para poder comprobarlo'
                  : 'Cuenta las filas y las combinaciones distintas del grano'
              }
              onClick={() =>
                grano.mutate({ definicion, entidad: entidad.nombre })
              }
            >
              {grano.isPending ? 'Comprobando…' : 'Comprobar'}
            </button>
          </div>

          {grano.isError && (
            <div className="error-caja chico">
              {(grano.error as Error).message}
            </div>
          )}
          {grano.data && (
            <div className={grano.data.cumple ? 'aviso-caja chico' : 'error-caja chico'}>
              {grano.data.cumple ? (
                <>
                  Se cumple: {grano.data.filas.toLocaleString('es-MX')} filas y
                  otras tantas combinaciones de{' '}
                  <span className="mono">{grano.data.grano.join(' + ')}</span>.
                </>
              ) : (
                <>
                  <strong>No se cumple.</strong>{' '}
                  {grano.data.filas.toLocaleString('es-MX')} filas para{' '}
                  {grano.data.combinaciones.toLocaleString('es-MX')} combinaciones
                  de <span className="mono">{grano.data.grano.join(' + ')}</span>:
                  sobran {grano.data.repetidas.toLocaleString('es-MX')}. Todo lo
                  que se sume de esta tabla está contando algo más de una vez.
                </>
              )}
            </div>
          )}
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
          {/*
            Plegado, y no siempre abierto. Es una fila por columna que desapareció:
            en un catálogo de veintidós columnas son veintidós desplegables, y
            empujaban la tabla de campos tan abajo que parecía no existir — alguien
            que venía a ocultar una columna no encontraba la casilla «ver» y
            concluía, con razón, que la opción no estaba en la pantalla. El aviso de
            arriba se sigue viendo entero; lo que se pliega es la lista larga.
          */}
          {desfase!.desaparecidas.length > 0 && enOrigen.length > 0 && (
            <details style={{ marginTop: 8 }} open={desfase!.desaparecidas.length <= 4}>
              <summary className="chico" style={{ cursor: 'pointer', marginBottom: 4 }}>
                ¿Alguna es la misma con otro nombre?
                {desfase!.desaparecidas.length > 4
                  && ` (${desfase!.desaparecidas.length})`}
              </summary>
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
            </details>
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
              <Th
                orden={orden}
                clave="mes"
                titulo="Esta columna nombra un mes concreto, como 202601. Es lo que permite comparar contra el mes anterior"
              >
                mes
              </Th>
              <th title="Por qué otra columna se ordenan sus valores en un filtro. «Enero, febrero, marzo» no es el orden alfabético">
                orden
              </th>
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
                <td>
                  {/* Sólo tiene sentido en una columna que identifique UN mes
                      —`202601`, o una fecha—. En `mes` de 1 a 12 no: se repite
                      cada año, y correrla un mes atrás no significa nada. Por eso
                      se ofrece únicamente donde el tipo lo permite. */}
                  <input
                    type="checkbox"
                    checked={c.grano_tiempo === 'mes'}
                    disabled={c.tipo !== 'entero' && c.tipo !== 'fecha'}
                    title={
                      c.tipo !== 'entero' && c.tipo !== 'fecha'
                        ? 'Un mes se nombra con un entero (202601) o con una fecha'
                        : 'Marcar si cada valor nombra un mes concreto, como 202601'
                    }
                    onChange={(e) =>
                      cambiarCampo(c.nombre, {
                        grano_tiempo: e.target.checked ? 'mes' : null,
                      })
                    }
                  />
                </td>
                <td>
                  {/* Se ofrecen las demás columnas de esta entidad y nada más: un
                      orden que viniera de otra tabla necesitaría una unión, y
                      entonces el orden de un filtro dependería de por dónde se
                      une — que es exactamente lo que no puede pasar. */}
                  <select
                    value={c.ordenar_por ?? ''}
                    title="Por su propio valor, o por otra columna: el nombre del mes por el número del mes"
                    onChange={(e) =>
                      cambiarCampo(c.nombre, { ordenar_por: e.target.value || null })
                    }
                  >
                    <option value="">por su valor</option>
                    {entidad.campos
                      .filter((o) => o.nombre !== c.nombre)
                      .map((o) => (
                        <option key={o.nombre} value={o.nombre}>
                          {o.nombre}
                        </option>
                      ))}
                  </select>
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
