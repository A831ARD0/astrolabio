# La marca

## El nombre

Un **astrolabio** medía la posición mirando el cielo: un anillo graduado, una
regla que apunta, y una lectura. Es lo que hace esta herramienta con un negocio —
apuntar a los datos y devolver una posición—, y trae consigo la idea que ordena
todo el proyecto: **el instrumento se puede revisar**. Un astrolabio se calibra, se
lee y se comprueba; no es una caja que entrega un número y pide que se le crea.

Se descartó el nombre anterior, *Meridian*, por dos motivos concretos: hay varios
productos de software llamados así —algunos en datos— y eso lo hace imposible de
registrar y difícil de encontrar en un buscador.

Se pronuncia y se escribe igual en español y en inglés, sin acentos ni caracteres
raros, así que funciona como nombre de dominio, de paquete y de repositorio.

## El símbolo

El astrolabio reducido a tres elementos: el limbo (anillo graduado), la alidada (la
línea inclinada que apunta) y el punto medido en el centro.

| Archivo | Para qué |
|---|---|
| [`astrolabio-marca.svg`](astrolabio-marca.svg) | El símbolo solo. Hereda `currentColor` |
| [`astrolabio-logotipo.svg`](astrolabio-logotipo.svg) | Símbolo + nombre, para cabeceras y el README |
| [`../../frontend/public/favicon.svg`](../../frontend/public/favicon.svg) | Pestaña del navegador, con color fijo |

Está dibujado **con líneas y sin relleno** por una razón práctica: a 16 px un
símbolo macizo se convierte en una mancha. Las graduaciones son solo cuatro por lo
mismo — las que sobreviven al tamaño pequeño.

Reglas de uso, pocas y firmes:

- No lo estires: el símbolo es cuadrado.
- Deja alrededor al menos el radio del círculo interior.
- Una sola tinta. Si hace falta sobre un fondo con color, va en blanco o en negro
  completo, nunca con sombra ni degradado.
- Por debajo de 16 px, usa solo el círculo exterior y el punto.

## Colores

Los mismos que usa la aplicación (`frontend/src/estilos.css`), no una paleta
aparte: una marca que no coincide con el producto envejece en la primera pantalla
que alguien rediseña.

| | Oscuro | Claro | Uso |
|---|---|---|---|
| Acento | `#4c8dff` | `#2563eb` | El símbolo, enlaces, el botón principal |
| Fondo | `#0e1117` | `#f7f8fa` | El lienzo |
| Panel | `#151a23` | `#ffffff` | Tarjetas y paneles |
| Texto | `#e6e9ef` | `#1a1f28` | Lectura normal |
| Texto suave | `#98a2b3` | `#475467` | Secundario |
| Correcto | `#3fb950` | `#1a7f37` | Cargas que salieron bien |
| Crítico | `#f2545b` | `#cf222e` | Fallos |

El tema claro y el oscuro no son dos diseños: son el mismo con las variables
cambiadas, y la interfaz sigue al sistema operativo.

## Tipografía

La del sistema (`ui-sans-serif`, San Francisco en Mac, Segoe UI en Windows, Roboto
en Android). Cero fuentes descargadas: una plataforma interna que espera a que
baje una tipografía de un CDN es una plataforma que se ve rota en la primera
pantalla y que además le cuenta a ese CDN quién la está usando.

Para cifras y nombres de columna, la monoespaciada del sistema. Es lo que hace que
una columna de números se pueda comparar de un vistazo.

## El tono

Cómo habla el producto, que también es marca:

- **En español**, incluidos los nombres del código.
- **Se dice lo que pasó y qué hacer**, no "ocurrió un error". Un mensaje que no
  ayuda a decidir el siguiente paso está a medio escribir.
- **Ningún botón gris sin motivo**: si algo no se puede hacer, la pantalla dice por
  qué al lado.
- **No se promete lo que no se comprobó.** Si algo no está probado, se dice.
