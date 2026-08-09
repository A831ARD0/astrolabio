/**
 * El lenguaje de fórmulas dentro de Monaco: colores, autocompletado y ayuda.
 *
 * Todo lo que se ofrece aquí sale del catálogo que devuelve el servidor
 * (`GET /api/modelos/funciones`) y de la entidad que se está editando. No hay
 * una segunda lista de funciones escrita a mano en el navegador: si la hubiera,
 * la pantalla acabaría ofreciendo funciones que el compilador no conoce, que es
 * la peor forma de documentar un lenguaje.
 *
 * Monaco registra los proveedores POR LENGUAJE y globalmente, no por editor. Si
 * cada vez que se abre una métrica se registrara uno nuevo, a la quinta el
 * autocompletado enseñaría cinco veces cada campo. Así que se registra una sola
 * vez y lo que cambia —los campos de ESTA entidad, las otras métricas— vive en
 * `contexto`, que el proveedor lee en el momento de sugerir.
 */

import type { Monaco } from '@monaco-editor/react'
// Solo para los tipos de los proveedores. `Monaco` da el objeto global, pero los
// parametros de `provideCompletionItems`/`provideHover` no se infieren solos.
import type { Position, editor } from 'monaco-editor'

import type { FuncionFormula } from '../api/tipos'

export const LENGUAJE = 'formula-astrolabio'
export const TEMA_CLARO = 'astrolabio-formula-claro'
export const TEMA_OSCURO = 'astrolabio-formula-oscuro'

/** Palabras del lenguaje que no son funciones. */
const PALABRAS = [
  'VAR', 'RETURN', 'AND', 'OR', 'NOT', 'IN', 'BETWEEN', 'LIKE', 'ILIKE', 'IS',
  'NULL', 'TRUE', 'FALSE', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'DISTINCT',
  'CAST', 'AS', 'FILTER', 'WHERE', 'INTERVAL',
]

/** Lo que el proveedor necesita saber de la métrica que se está editando. */
export interface ContextoFormula {
  campos: { nombre: string; tipo: string; rol: string }[]
  metricas: { nombre: string; etiqueta: string; expresion: string }[]
  funciones: FuncionFormula[]
}

const contexto: ContextoFormula = { campos: [], metricas: [], funciones: [] }

/** Lo llama el editor en cada render: barato, y siempre al día. */
export function fijarContexto(nuevo: ContextoFormula) {
  contexto.campos = nuevo.campos
  contexto.metricas = nuevo.metricas
  contexto.funciones = nuevo.funciones
}

let registrado = false

export function registrarLenguaje(monaco: Monaco) {
  if (registrado) return
  registrado = true

  monaco.languages.register({ id: LENGUAJE })

  monaco.languages.setLanguageConfiguration(LENGUAJE, {
    comments: { lineComment: '--', blockComment: ['/*', '*/'] },
    brackets: [['(', ')'], ['[', ']']],
    autoClosingPairs: [
      { open: '(', close: ')' },
      { open: '[', close: ']' },
      { open: "'", close: "'" },
    ],
    surroundingPairs: [
      { open: '(', close: ')' },
      { open: '[', close: ']' },
      { open: "'", close: "'" },
    ],
  })

  monaco.languages.setMonarchTokensProvider(LENGUAJE, {
    ignoreCase: true,
    palabras: PALABRAS,
    defaultToken: '',
    tokenizer: {
      root: [
        [/--.*$/, 'comment'],
        [/\/\*/, 'comment', '@bloque'],
        // Referencia a otra métrica. Se colorea distinto porque no es un campo:
        // es una fórmula entera que se pega aquí dentro.
        [/\[[^\]]*\]/, 'type.identifier'],
        [/'([^']|'')*'/, 'string'],
        [/"([^"]|"")*"/, 'string'],
        [/\d+(\.\d+)?/, 'number'],
        [
          /[A-Za-z_ÁÉÍÓÚÜÑáéíóúüñ][\wÁÉÍÓÚÜÑáéíóúüñ]*(?=\s*\()/,
          'keyword.function',
        ],
        [
          /[A-Za-z_ÁÉÍÓÚÜÑáéíóúüñ][\wÁÉÍÓÚÜÑáéíóúüñ]*/,
          { cases: { '@palabras': 'keyword', '@default': 'identifier' } },
        ],
        [/[<>=!+\-*/%|]+/, 'operator'],
        [/[()[\]]/, '@brackets'],
      ],
      bloque: [
        [/[^*/]+/, 'comment'],
        [/\*\//, 'comment', '@pop'],
        [/./, 'comment'],
      ],
    },
  } as never)

  // Los temas se definen aparte de los de Monaco porque hacen falta dos colores
  // que el editor no distingue solo: el de una función del lenguaje y el de una
  // referencia a otra métrica.
  for (const [nombre, base, reglas] of [
    [TEMA_CLARO, 'vs', {
      comment: '6a8759', string: '0a7c3f', number: '1750bd',
      keyword: '9b26b6', fn: '0b5ed7', ref: 'b7791f', ident: '24292f',
    }],
    [TEMA_OSCURO, 'vs-dark', {
      comment: '7f9a6b', string: '8fd694', number: '9cc9ff',
      keyword: 'd48fe0', fn: '6cb6ff', ref: 'e2b33c', ident: 'd6dae0',
    }],
  ] as [string, 'vs' | 'vs-dark', Record<string, string>][]) {
    monaco.editor.defineTheme(nombre, {
      base,
      inherit: true,
      rules: [
        { token: 'comment', foreground: reglas.comment, fontStyle: 'italic' },
        { token: 'string', foreground: reglas.string },
        { token: 'number', foreground: reglas.number },
        { token: 'keyword', foreground: reglas.keyword, fontStyle: 'bold' },
        { token: 'keyword.function', foreground: reglas.fn },
        { token: 'type.identifier', foreground: reglas.ref },
        { token: 'identifier', foreground: reglas.ident },
      ],
      colors: {},
    })
  }

  monaco.languages.registerCompletionItemProvider(LENGUAJE, {
    triggerCharacters: ['[', '(', ',', ' '],
    provideCompletionItems(modelo: editor.ITextModel, posicion: Position) {
      const palabra = modelo.getWordUntilPosition(posicion)
      const rango = {
        startLineNumber: posicion.lineNumber,
        endLineNumber: posicion.lineNumber,
        startColumn: palabra.startColumn,
        endColumn: palabra.endColumn,
      }
      const K = monaco.languages.CompletionItemKind
      const sugerencias: unknown[] = []

      // Las variables que la propia fórmula declaró ARRIBA de donde se escribe.
      // Ofrecer las de abajo sería ofrecer algo que el compilador rechaza.
      const antes = modelo.getValueInRange({
        startLineNumber: 1,
        startColumn: 1,
        endLineNumber: posicion.lineNumber,
        endColumn: posicion.column,
      })
      for (const m of antes.matchAll(/\bVAR\s+([A-Za-z_][\w]*)\s*=/gi)) {
        sugerencias.push({
          label: m[1],
          kind: K.Variable,
          insertText: m[1],
          detail: 'variable de esta fórmula',
          sortText: '0' + m[1],
          range: rango,
        })
      }

      for (const c of contexto.campos) {
        sugerencias.push({
          label: c.nombre,
          kind: c.rol === 'medida_base' ? K.Field : K.Property,
          insertText: c.nombre,
          detail: `${c.rol === 'medida_base' ? 'medida' : c.rol} · ${c.tipo}`,
          sortText: (c.rol === 'medida_base' ? '1' : '2') + c.nombre,
          range: rango,
        })
      }

      for (const m of contexto.metricas) {
        sugerencias.push({
          label: `[${m.nombre}]`,
          kind: K.Reference,
          insertText: `[${m.nombre}]`,
          detail: `métrica · ${m.etiqueta}`,
          documentation: { value: '```\n' + m.expresion + '\n```' },
          sortText: '3' + m.nombre,
          range: rango,
        })
      }

      for (const f of contexto.funciones) {
        sugerencias.push({
          label: f.nombre,
          kind: K.Function,
          // `${1:…}` deja el cursor dentro del paréntesis: escribir la función y
          // tener que mover el cursor a mano es el tipo de fricción que hace que
          // la gente deje de usar el autocompletado.
          insertText: f.maximo === 0 ? `${f.nombre}()` : `${f.nombre}($0)`,
          insertTextRules: monaco.languages.CompletionItemInsertTextRule
            .InsertAsSnippet,
          detail: f.firma,
          documentation: { value: documentar(f) },
          sortText: '4' + f.nombre,
          range: rango,
        })
      }

      for (const p of ['VAR', 'RETURN']) {
        sugerencias.push({
          label: p,
          kind: K.Keyword,
          insertText: p === 'VAR' ? 'VAR ${1:nombre} = $0' : 'RETURN $0',
          insertTextRules: monaco.languages.CompletionItemInsertTextRule
            .InsertAsSnippet,
          detail: p === 'VAR' ? 'declara un paso intermedio' : 'lo que devuelve',
          sortText: '5' + p,
          range: rango,
        })
      }

      return { suggestions: sugerencias as never }
    },
  })

  monaco.languages.registerHoverProvider(LENGUAJE, {
    provideHover(modelo: editor.ITextModel, posicion: Position) {
      const palabra = modelo.getWordAtPosition(posicion)
      if (!palabra) return null
      const rango = {
        startLineNumber: posicion.lineNumber,
        endLineNumber: posicion.lineNumber,
        startColumn: palabra.startColumn,
        endColumn: palabra.endColumn,
      }

      const funcion = contexto.funciones.find(
        (f) => f.nombre === palabra.word.toUpperCase(),
      )
      if (funcion) {
        return { range: rango, contents: [{ value: documentar(funcion) }] }
      }

      const campo = contexto.campos.find((c) => c.nombre === palabra.word)
      if (campo) {
        return {
          range: rango,
          contents: [{
            value: `**${campo.nombre}** — ${campo.rol === 'medida_base'
              ? 'medida' : campo.rol} · \`${campo.tipo}\``,
          }],
        }
      }

      const metrica = contexto.metricas.find((m) => m.nombre === palabra.word)
      if (metrica) {
        return {
          range: rango,
          contents: [
            { value: `**[${metrica.nombre}]** — ${metrica.etiqueta}` },
            { value: '```\n' + metrica.expresion + '\n```' },
          ],
        }
      }
      return null
    },
  })
}

function documentar(f: FuncionFormula): string {
  return [
    `**${f.firma}**`,
    f.resumen,
    f.agrega ? '_Agrega: devuelve un valor por grupo._' : '',
    '```\n' + f.ejemplo + '\n```',
  ]
    .filter(Boolean)
    .join('\n\n')
}
