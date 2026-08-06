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
 */

import Editor from '@monaco-editor/react'

import { useYaml } from '../api/hooks'

export function VistaYaml({
  modeloId,
  version,
  hayCambiosSinGuardar,
}: {
  modeloId: number
  version?: number
  hayCambiosSinGuardar: boolean
}) {
  const yaml = useYaml(modeloId, version)
  const oscuro = window.matchMedia('(prefers-color-scheme: dark)').matches

  return (
    <div className="yaml">
      {hayCambiosSinGuardar && (
        <div className="aviso-caja">
          Esto es la versión {yaml.data?.version} tal como está guardada. Los
          cambios que tienes en el lienzo todavía no están aquí.
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
