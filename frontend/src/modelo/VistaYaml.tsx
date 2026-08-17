/**
 * El modelo como texto.
 *
 * El YAML no es un detalle interno que se esconde: es el formato en el que el
 * modelo se versiona, se revisa en diff y se exporta. Poder verlo —y compararlo
 * entre versiones— es lo que evita que la definición quede encerrada en una base
 * de datos que solo esta aplicación entiende.
 *
 * Se ve de sólo lectura, y además **se puede importar**. Son dos cosas distintas
 * a propósito: teclear encima de lo que estás mirando invita a editar la versión
 * publicada por error, mientras que importar es un acto con su botón, que dice
 * claramente que va a reemplazar el borrador entero. Y hacía falta: sin él, un
 * modelo escrito fuera —una migración de otra herramienta, noventa y seis
 * métricas traducidas— no tenía por dónde entrar más que a mano, una por una.
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

import { useImportarYaml, useYaml } from '../api/hooks'

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
  const [importando, setImportando] = useState(false)
  const [texto, setTexto] = useState('')
  const [hecho, setHecho] = useState<string | null>(null)

  // Sin `version` la ruta devuelve el borrador si lo hay. Para ver la publicada
  // se le pide su número explícitamente, que es la misma vía del historial.
  const suelto = useYaml(modeloId, version)
  const publicada = useYaml(
    modeloId,
    version ?? (verPublicada ? suelto.data?.version_vigente : undefined),
  )
  const yaml = version === undefined && verPublicada ? publicada : suelto
  const importar = useImportarYaml(modeloId)

  const hayBorrador = suelto.data?.es_borrador === true
  const oscuro = window.matchMedia('(prefers-color-scheme: dark)').matches

  function aplicar() {
    setHecho(null)
    importar.mutate(
      { yaml: texto },
      {
        onSuccess: (r) => {
          const criticos = r.problemas.filter((p) => p.gravedad === 'critico')
          const i = r.importado
          // Qué se hizo, y sólo después si algo quedó mal. Con una mezcla, lo
          // primero que hay que poder comprobar es que no desapareció nada.
          const que =
            i?.modo === 'mezcla'
              ? `${i.nuevas} métrica(s) nueva(s), ${i.reemplazadas} reemplazada(s)`
                + ` y ${i.intactas} sin tocar.`
              : 'Borrador reemplazado.'
          setHecho(
            que
            + (criticos.length
              ? ` El diagnóstico ve ${criticos.length} problema(s) crítico(s).`
              : ' El diagnóstico no ve nada crítico.'),
          )
          setImportando(false)
          setTexto('')
        },
      },
    )
  }

  return (
    <div className="yaml">
      <div className="pestanas">
        {version === undefined && hayBorrador && (
          <>
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
          </>
        )}
        {version === undefined && (
          <button
            style={{ marginLeft: 'auto' }}
            title="Reemplaza el borrador entero con un YAML pegado. No toca ninguna versión publicada."
            onClick={() => {
              setHecho(null)
              setImportando((x) => !x)
            }}
          >
            {importando ? 'Cancelar' : 'Importar YAML…'}
          </button>
        )}
      </div>

      {importando && (
        <div style={{ padding: '8px 8px 0' }}>
          <p className="chico tenue" style={{ margin: '0 0 6px' }}>
            Dos cosas valen aquí. El <strong>modelo completo</strong> —empieza por{' '}
            <code>modelo:</code> y lleva <code>entidades:</code>— reemplaza el
            borrador. Un <strong>trozo con sólo <code>metricas:</code></strong> se
            mezcla con lo que ya tienes: las de igual nombre se sustituyen, las
            demás se quedan.
          </p>
          <p className="chico tenue" style={{ margin: '0 0 6px' }}>
            En los dos casos se toca el <strong>borrador</strong> —lo que ven los
            tableros no cambia hasta que publiques— y se revisa igual que si lo
            hubieras armado en el lienzo: si una métrica nombra una columna que no
            existe, no entra.
          </p>
          <textarea
            className="mono"
            value={texto}
            spellCheck={false}
            placeholder={'modelo: Mi modelo\nversion: 1\nentidades:\n  - …'}
            onChange={(e) => setTexto(e.target.value)}
            style={{ width: '100%', minHeight: 160, fontSize: 12 }}
          />
          <div className="fila" style={{ gap: 8, marginTop: 6 }}>
            <button
              className="btn"
              disabled={!texto.trim() || importar.isPending}
              onClick={aplicar}
            >
              {importar.isPending ? 'Importando…' : 'Reemplazar el borrador'}
            </button>
            <span className="chico tenue">
              {texto.split('\n').length} líneas pegadas
            </span>
          </div>
          {importar.isError && (
            <div className="error-caja chico" style={{ marginTop: 6 }}>
              {(importar.error as Error).message}
            </div>
          )}
        </div>
      )}

      {hecho && <div className="aviso-caja chico">{hecho}</div>}

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
