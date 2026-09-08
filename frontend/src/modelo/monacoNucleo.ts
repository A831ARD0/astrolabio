/**
 * Monaco por piezas: el editor completo, sin un solo servicio de lenguaje.
 *
 * POR QUÉ EXISTE ESTE ARCHIVO. Importar `monaco-editor` a secas trae el paquete
 * entero, y ahí dentro van —cargados de golpe, no en diferido— los servicios de
 * TypeScript, JSON, CSS y HTML. Ninguno se usa aquí: en Astrolabio se escriben
 * exactamente dos lenguajes, YAML en la vista del modelo y el de fórmulas, que
 * `formula.ts` registra a mano. Con el paquete completo la carga inicial pesaba
 * 5.2 MB de JavaScript, y más de la mitad era el compilador de TypeScript
 * esperando a que alguien abriera un `.ts` que no existe.
 *
 * Los ~80 lenguajes de fábrica no eran el problema: cada uno se declara con un
 * `loader: () => import(...)`, así que son trozos aparte que el navegador no pide
 * nunca. Ocupaban sitio en la imagen, no en la red.
 *
 * QUÉ ES ESTA LISTA. Las 74 contribuciones que `monaco-editor/esm/vs/index.js`
 * carga aparte de los lenguajes: buscar, sugerencias, ayuda al pasar el ratón,
 * plegado, multicursor, menú contextual. Están TODAS y en el mismo orden, a
 * propósito: el editor se comporta igual que con el paquete completo, y la única
 * diferencia es que no hay lenguajes. Quitar contribuciones de aquí para ahorrar
 * unos kilobytes es como se pierde una función del editor sin que nada avise.
 *
 * AL ACTUALIZAR MONACO hay que regenerarla, porque estas rutas son internas y se
 * mueven entre versiones —la 0.56 ya eliminó el `editor.all.js` que hacía esto:
 *
 *   cd frontend && python3 - <<'EOF'
 *   import io, re
 *   s = io.open('node_modules/monaco-editor/esm/vs/index.js', encoding='utf-8').read()
 *   for i in re.findall(r"^import '(\./[^']+)';$", s, re.M):
 *       if i.startswith('./languages/definitions/'): continue   # los lenguajes, no
 *       if i.endswith('.css'): continue                          # ver más abajo
 *       print(f"import 'monaco-editor/{i[2:].removesuffix('.js')}'")
 *   EOF
 *
 * Si una ruta desaparece, el build falla al no resolver el módulo. Eso es lo que
 * se quiere: el fallo ruidoso, y no un editor al que le falta el buscador.
 *
 * LOS DOS .CSS DE LA LISTA NO VAN, y el filtro de arriba los salta a propósito.
 * `index.js` importa `codicon.css` y `codicon-modifiers.css`, pero el `exports`
 * del paquete solo sabe resolver a `.js` —le pega la extensión al comodín—, así
 * que pedirlos desde fuera rompe el build. No hace falta: los contribs que los
 * necesitan los importan con rutas relativas de dentro del paquete, y la fuente
 * `codicon.ttf` acaba en el build igual. Comprobado: el CSS construido lleva su
 * `@font-face`.
 *
 * Las rutas van sin el prefijo `esm/vs` y sin extensión porque desde la 0.56 el
 * paquete declara `exports` con `"./*": "./esm/vs/*.js"`. Escribir `esm/vs` hace
 * que Vite no resuelva el módulo y arranque sin avisar en la pantalla, solo con
 * una línea en su propio log.
 */

import 'monaco-editor/editor/contrib/anchorSelect/browser/anchorSelect'
import 'monaco-editor/editor/contrib/bracketMatching/browser/bracketMatching'
import 'monaco-editor/editor/contrib/caretOperations/browser/transpose'
import 'monaco-editor/editor/contrib/clipboard/browser/clipboard'
import 'monaco-editor/editor/contrib/codeAction/browser/codeActionContributions'
import 'monaco-editor/editor/browser/widget/codeEditor/codeEditorWidget'
import 'monaco-editor/editor/contrib/codelens/browser/codelensController'
import 'monaco-editor/editor/contrib/colorPicker/browser/colorPickerContribution'
import 'monaco-editor/editor/contrib/comment/browser/comment'
import 'monaco-editor/editor/contrib/contextmenu/browser/contextmenu'
import 'monaco-editor/editor/contrib/cursorUndo/browser/cursorUndo'
import 'monaco-editor/editor/browser/widget/diffEditor/diffEditor.contribution'
import 'monaco-editor/editor/contrib/diffEditorBreadcrumbs/browser/contribution'
import 'monaco-editor/editor/contrib/dnd/browser/dnd'
import 'monaco-editor/editor/contrib/documentSymbols/browser/documentSymbols'
import 'monaco-editor/editor/contrib/dropOrPasteInto/browser/dropIntoEditorContribution'
import 'monaco-editor/features/find/register'
import 'monaco-editor/editor/contrib/floatingMenu/browser/floatingMenu.contribution'
import 'monaco-editor/editor/contrib/folding/browser/folding'
import 'monaco-editor/editor/contrib/fontZoom/browser/fontZoom'
import 'monaco-editor/editor/contrib/format/browser/formatActions'
import 'monaco-editor/editor/contrib/gotoError/browser/gotoError'
import 'monaco-editor/editor/standalone/browser/quickAccess/standaloneGotoLineQuickAccess'
import 'monaco-editor/editor/contrib/gotoSymbol/browser/link/goToDefinitionAtPosition'
import 'monaco-editor/editor/contrib/gpu/browser/gpuActions'
import 'monaco-editor/editor/contrib/hover/browser/hoverContribution'
import 'monaco-editor/editor/contrib/indentation/browser/indentation'
import 'monaco-editor/editor/contrib/inlayHints/browser/inlayHintsContribution'
import 'monaco-editor/editor/contrib/inlineCompletions/browser/inlineCompletions.contribution'
import 'monaco-editor/editor/contrib/inlineProgress/browser/inlineProgress'
import 'monaco-editor/editor/contrib/inPlaceReplace/browser/inPlaceReplace'
import 'monaco-editor/editor/contrib/insertFinalNewLine/browser/insertFinalNewLine'
import 'monaco-editor/editor/standalone/browser/inspectTokens/inspectTokens'
import 'monaco-editor/editor/standalone/browser/iPadShowKeyboard/iPadShowKeyboard'
import 'monaco-editor/editor/contrib/lineSelection/browser/lineSelection'
import 'monaco-editor/editor/contrib/linesOperations/browser/linesOperations'
import 'monaco-editor/editor/contrib/linkedEditing/browser/linkedEditing'
import 'monaco-editor/editor/contrib/links/browser/links'
import 'monaco-editor/editor/contrib/longLinesHelper/browser/longLinesHelper'
import 'monaco-editor/editor/contrib/middleScroll/browser/middleScroll.contribution'
import 'monaco-editor/editor/contrib/multicursor/browser/multicursor'
import 'monaco-editor/editor/contrib/parameterHints/browser/parameterHints'
import 'monaco-editor/editor/contrib/placeholderText/browser/placeholderText.contribution'
import 'monaco-editor/editor/standalone/browser/quickAccess/standaloneCommandsQuickAccess'
import 'monaco-editor/editor/standalone/browser/quickAccess/standaloneHelpQuickAccess'
import 'monaco-editor/editor/standalone/browser/quickAccess/standaloneGotoSymbolQuickAccess'
import 'monaco-editor/editor/contrib/readOnlyMessage/browser/contribution'
import 'monaco-editor/editor/standalone/browser/referenceSearch/standaloneReferenceSearch'
import 'monaco-editor/editor/contrib/rename/browser/rename'
import 'monaco-editor/editor/contrib/sectionHeaders/browser/sectionHeaders'
import 'monaco-editor/editor/contrib/semanticTokens/browser/viewportSemanticTokens'
import 'monaco-editor/editor/contrib/smartSelect/browser/smartSelect'
import 'monaco-editor/editor/contrib/snippet/browser/snippetController2'
import 'monaco-editor/editor/contrib/stickyScroll/browser/stickyScrollContribution'
import 'monaco-editor/editor/contrib/suggest/browser/suggestInlineCompletions'
import 'monaco-editor/editor/standalone/browser/toggleHighContrast/toggleHighContrast'
import 'monaco-editor/editor/contrib/toggleTabFocusMode/browser/toggleTabFocusMode'
import 'monaco-editor/editor/contrib/tokenization/browser/tokenization'
import 'monaco-editor/editor/contrib/unicodeHighlighter/browser/unicodeHighlighter'
import 'monaco-editor/editor/contrib/unusualLineTerminators/browser/unusualLineTerminators'
import 'monaco-editor/editor/contrib/wordHighlighter/browser/wordHighlighter'
import 'monaco-editor/editor/contrib/wordOperations/browser/wordOperations'
import 'monaco-editor/editor/contrib/wordPartOperations/browser/wordPartOperations'
import 'monaco-editor/editor/browser/coreCommands'
import 'monaco-editor/editor/contrib/caretOperations/browser/caretOperations'
import 'monaco-editor/editor/contrib/dropOrPasteInto/browser/copyPasteContribution'
import 'monaco-editor/editor/contrib/find/browser/findController'
import 'monaco-editor/editor/contrib/gotoSymbol/browser/goToCommands'
import 'monaco-editor/editor/contrib/gotoError/browser/markerSelectionStatus'
import 'monaco-editor/editor/contrib/semanticTokens/browser/documentSemanticTokens'
import 'monaco-editor/editor/contrib/suggest/browser/suggestController'
import 'monaco-editor/editor/common/standaloneStrings'

// YAML, el único lenguaje de fábrica que se usa: la vista del modelo. Registra el
// lenguaje y deja su gramática en un trozo aparte, que se pide al abrir la vista.
import 'monaco-editor/languages/definitions/yaml/register'

// La API. Va al final porque las contribuciones de arriba se registran al
// importarse y tienen que estar puestas antes de que nadie cree un editor.
export * from 'monaco-editor/editor/editor.api'
