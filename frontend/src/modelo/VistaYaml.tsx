/**
 * El modelo como texto.
 *
 * El YAML no es un detalle interno que se esconde: es el formato en el que el
 * modelo se versiona, se revisa en diff y se exporta. Poder verlo —y compararlo
 * entre versiones— es lo que evita que la definición quede encerrada en una base
 * de datos que solo esta aplicación entiende.
 *
 * Es de solo lectura a propósito. Se edita en el lienzo, que valida referencias
 * mientras se trabaja; un YAML tecleado a mano puede apuntar a columnas que no
 * existen y no se sabría hasta la primera consulta.
 *
 * **Hay dos textos, no uno**, y confundirlos cuesta caro: el borrador —lo que
 * estás armando— y la última versión publicada, que es lo que ven los tableros.
 * Antes esta pestaña enseñaba sólo la publicada, y sin avisar salvo que hubiera
 * cambios sin guardar. Con trece tablas en el lienzo y una publicada, aquí salía
 * UNA, y la conclusión razonable era que el YAML estaba roto — cuando lo que
 * pasaba es que era otro texto.
 */

import Editor from '@monaco-editor/react'
import { useState } from 'react'

import { useYaml } from '../api/hooks'

export function VistaYaml({
  modeloId,
  version,
  hayCambiosSinGuardar,
}: {
  modeloId: number
  /** Una versión concreta del historial. Si viene, no hay nada que elegir. */
  version?: number
  hayCambiosSinGuardar: boolean
}) {
  const [verPublicada, setVerPublicada] = useState(false)

  // Sin `version` la ruta devuelve el borrador si lo hay. Para ver la publicada
  // se le pide su número explícitamente, que es la misma vía del historial.
  const suelto = useYaml(modeloId, version)
  const publicada = useYaml(
    modeloId,
    version ?? (verPublicada ? suelto.data?.version_vigente : undefined),
  )
  const yaml = version === undefined && verPublicada ? publicada : suelto

  const hayBorrador = suelto.data?.es_borrador === true
  const oscuro = window.matchMedia('(prefers-color-scheme: dark)').matches

  return (
    <div className="yaml">
      {version === undefined && hayBorrador && (
        <div className="pestanas">
          <button
            className={verPublicada ? '' : 'activo'}
            onClick={() => setVerPublicada(false)}
          >
            Borrador
          </button>
          <button
            className={verPublicada ? 'activo' : ''}
            title="Lo que ven los tableros ahora mismo"
            onClick={() => setVerPublicada(true)}
          >
            Publicada v{suelto.data?.version_vigente}
          </button>
        </div>
      )}

      {/*
        El borrador guardado tampoco es lo que está en pantalla si hay cambios sin
        guardar. Son tres estados y el aviso tiene que decir en cuál estás.
      */}
      {hayCambiosSinGuardar && !verPublicada && (
        <div className="aviso-caja">
          {hayBorrador
            ? 'Esto es el borrador tal como lo guardaste. Los cambios que tienes en el lienzo todavía no están aquí: guarda el borrador para verlos.'
            : `Esto es la versión ${suelto.data?.version} tal como está publicada. Los cambios que tienes en el lienzo todavía no están aquí.`}
        </div>
      )}

      {version === undefined && !hayBorrador && !hayCambiosSinGuardar && (
        <div className="chico tenue" style={{ padding: '2px 8px' }}>
          Versión {suelto.data?.version}, publicada. No hay borrador sin publicar.
        </div>
      )}

      {yaml.isLoading && <div className="vacio">Cargando…</div>}
      {yaml.isError && <div className="error-caja">{(yaml.error as Error).message}</div>}

      {yaml.data && (
        <Editor
          height="100%"
          language="yaml"
          value={yaml.data.yaml}
          theme={oscuro ? 'vs-dark' : 'light'}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 12.5,
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            renderWhitespace: 'none',
            wordWrap: 'on',
          }}
        />
      )}
    </div>
  )
}
