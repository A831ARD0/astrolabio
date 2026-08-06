# Astrolabio — frontend

React 19 + TypeScript + Vite. La documentación de lo que hace cada pantalla está
en [`docs/04-fase-2-modelo.md`](../docs/04-fase-2-modelo.md).

```bash
npm install
npm run dev          # http://localhost:5173
npm run typecheck    # tsc --noEmit
npx oxlint src
```

El frontend **nunca** sabe dónde vive la API: pide a `/api` y Vite hace de proxy
(`ASTROLABIO_API` para apuntar a otro sitio, por defecto `http://127.0.0.1:8000`).
El mismo código sirve en desarrollo y detrás de Caddy en el servidor.

## Cómo está organizado

```
src/
  api/
    cliente.ts     un solo sitio que habla con el backend: el token viaja
                   siempre y los mensajes de error del servidor llegan enteros
    tipos.ts       espejo de semantic/definicion.py
    hooks.ts       todas las claves de caché y las invalidaciones, juntas
  modelo/
    estado.ts      el borrador y las acciones que lo cambian (nada muta)
    Lienzo.tsx     entidades y relaciones con React Flow
    NodoEntidad.tsx
    Panel*.tsx     inspectores de entidad, relación, métrica y diagnóstico
    DialogoEntidad.tsx   agregar una entidad desde una tabla real
    VistaYaml.tsx
  paginas/
  estilos.css      tokens de diseño; sin librería de componentes
```

## Dos cosas que no son evidentes

**El orden de los imports de CSS en `main.tsx` importa.** Los estilos de React Flow
van primero y los nuestros después. Al contrario, el minimapa sale en blanco.

**El estado de los nodos del lienzo lo lleva React Flow, no nosotros.** React Flow
guarda las medidas de cada nodo y las necesita para el minimapa y las aristas; si
en cada render se le pasaran objetos nuevos, esas medidas se perderían. La fuente
de verdad del modelo sigue siendo el borrador — lo de React Flow es la copia que
dibuja.

## `prototipo-inicial/`

El prototipo desechable de la primera semana (JSX, otra API). Se guarda porque el
repositorio no está en git todavía; no forma parte de la aplicación y se puede
borrar en cuanto lo esté.
