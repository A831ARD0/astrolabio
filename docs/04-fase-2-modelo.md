# Fase 2 — La interfaz del modelo semántico

Estado: **completa**. 99 pruebas pasando, verificada en el navegador contra el
modelo `demo_comercial` real (11 entidades, 15 relaciones, 6 métricas).

Es la primera pantalla de verdad de Astrolabio, y no por casualidad: el modelo
define qué significa cada cifra. Todo lo demás —dashboards, exploración,
fórmulas— se apoya en él.

---

## 1. Nada se guarda al escribir

Se trabaja sobre un **borrador** en el navegador y guardar es un acto explícito
que crea una **versión nueva e inmutable**. Los dashboards publicados están
anclados a una versión concreta, así que editar el modelo no puede cambiarles la
cifra por debajo a nadie.

Consecuencias visibles en la interfaz:

- Un indicador de *cambios sin guardar* y un botón de deshacer con 50 pasos.
- Aviso del navegador antes de cerrar la pestaña con trabajo pendiente.
- El historial de versiones a la vista, en la barra lateral.
- Cuando hay cambios sin guardar, el diagnóstico se marca como "de la versión
  guardada" en vez de presentarlo como si correspondiera al borrador.

"Hay cambios" no se rastrea con banderas: se compara el borrador contra lo que se
cargó. Una bandera se puede quedar encendida o apagada por error; una comparación
no.

---

## 2. Guardar sin perder lo que el motor no mira

Aquí estaba el riesgo real de esta fase.

El motor (`semantic/engine.py`) lee del YAML **solo lo que necesita para compilar
SQL**. Ignora las jerarquías, las perspectivas, las descripciones. Si la interfaz
guardara serializando los objetos del motor, cada vez que alguien tocara una
relación **se perdería en silencio** todo lo que el motor no interpreta. La
jerarquía `Tiempo` de `dim_calendario` desaparecería y nadie se enteraría hasta
echarla en falta meses después.

Por eso hay una capa aparte, [`semantic/definicion.py`](../backend/semantic/definicion.py):
se edita el **mapa crudo** del YAML y el motor solo se usa para **validar** que
lo editado compila. Los campos que la interfaz no conoce se conservan tal cual
(`extra="allow"` en Pydantic).

Tres pruebas lo fijan: la jerarquía sobrevive, las políticas de seguridad por fila
sobreviven, y el modelo completo sobrevive la ida y vuelta byte a byte
(`model_dump()` idéntico).

**Limitación consciente:** los comentarios del YAML sí se pierden al guardar desde
la interfaz (`safe_load` no los conserva). Quien quiera comentarios los pone
editando el texto.

El orden de las claves al volcar es fijo (`modelo`, `version`, `entidades`,
`relaciones`, `metricas`, `politicas`, `disposicion`). No es estética: el archivo
se versiona y se revisa en diff, y un orden alfabético o al azar produciría un
diff ilegible en cada guardado.

---

## 3. Dos validaciones, y las dos hacen falta

| Validación | Qué aporta |
|---|---|
| Referencias cruzadas (`revisar_referencias`) | dice **qué** está mal: "la relación 3 usa el campo `fact_venta.columna_fantasma`, que no existe" |
| El motor semántico | dice si el modelo **compila** de verdad |

Sin la primera, un error de referencia sale como un `KeyError` a media consulta,
lejos del sitio donde se cometió. Casos cubiertos: relación a una entidad
inexistente, relación a un campo inexistente, clave primaria que no es campo de su
entidad, grano que menciona un campo que no existe, métrica sobre una entidad que
no está, métricas repetidas, y un nombre que es a la vez métrica y entidad.

---

## 4. El lienzo

Entidades como nodos, relaciones como aristas, con React Flow.

- **Cada campo lleva su propio conector a los dos lados.** Una relación se crea
  arrastrando de columna a columna, no uniendo dos cajas y luego eligiendo campos
  en un formulario. La relación *es* entre columnas y la interfaz debería decir
  eso.
- **Hechos y dimensiones se ven distintos** (naranja y azul). No es decoración: de
  esa diferencia dependen las reglas de agregación del motor —un hecho es
  terminal, nunca puente—, así que hay que distinguirlos de un vistazo.
- **La cardinalidad de una relación nueva se supone, no se inventa.** Si el campo
  destino es la clave primaria de su entidad, es muchos-a-uno. Si no lo es, se
  marca muchos-a-muchos y el diagnóstico avisa. Suponer muchos-a-uno cuando no
  consta sería inventar una garantía que nadie verificó, y de ahí salen las cifras
  infladas.
- Las relaciones muchos-a-muchos se dibujan **punteadas en ámbar**.
- Los campos que participan en alguna relación llevan un `⇄`.
- **La disposición viaja dentro del modelo**, no en el navegador: abrirlo en otra
  máquina se ve igual, y la posición forma parte de la versión. Al modelo solo
  llega la posición final del arrastre, para no llenar el historial de deshacer con
  un paso por píxel.

### El inspector explica, no solo edita

Al seleccionar una relación, el panel dice por qué importa lo que se está
cambiando: si la cardinalidad es muchos-a-uno pero el campo destino no es clave
primaria, avisa de que **duplicará filas al agregar**. Eso es documentación en el
punto donde se toma la decisión, no en un manual que nadie abre.

---

## 5. Diagnóstico que señala dónde

Los problemas del modelo con las **rutas en conflicto escritas**, y al pasar el
ratón se resaltan en el lienzo las entidades implicadas. Un aviso que no dice
*dónde* obliga a buscarlo a mano.

Sobre `demo_comercial` detecta lo que tiene que detectar:

```
fact_venta → cat_marca        2 caminos de igual longitud
                              fact_venta → cat_sucursal → cat_marca
                              fact_venta → dim_vehiculo → cat_marca
fact_servicio → cat_marca     lo mismo
tbl_encuesta_clima            sin ninguna relación: queda aislada
fact_presupuesto ↔ dim_calendario   muchos-a-muchos
```

(Las dos primeras son legítimas y a la vez peligrosas: la marca de la agencia y la
marca del vehículo no son lo mismo. Es exactamente la clase de ambigüedad que el
Qlik actual resuelve en silencio.)

Decisión de diseño: el marco rojo se reserva para lo que el usuario está
inspeccionando. Las entidades que aparecen en algún problema llevan solo un punto
rojo discreto. Si se pintaran de rojo todas, media pantalla sería roja y el color
dejaría de señalar nada.

---

## 6. Probar una métrica antes de guardarla

El editor de métricas tiene un botón de **Probar** que ejecuta la expresión de
verdad, contra los datos, con el mismo compilador que usará la métrica definitiva.
Probar por otro camino no probaría nada.

Verificado en el navegador con la fórmula de utilidad del Qlik actual:

```
SUM(monto_base - monto_impuesto - monto_costo + monto_bonus + monto_bonus_cancel)
agrupado por cat_sucursal.sucursal_nombre  →  25.7 ms
```

Una expresión se puede escribir bien y significar otra cosa. Ver el número antes
de guardar es lo que evita publicar una cifra plausible y equivocada. Probar no
guarda nada: la métrica se inyecta en una copia del modelo que se descarta al
responder.

---

## 7. Entidades desde tablas reales

El catálogo ([`app/rutas/catalogo.py`](../backend/app/rutas/catalogo.py)) expone
las tablas del motor analítico con sus columnas, sus tipos ya traducidos a los del
modelo, y un **rol sugerido** para cada columna.

Las columnas no se teclean. Un modelo que apunta a una columna inexistente no
falla al guardarse: falla en la primera consulta, lejos de donde se cometió el
error. Si la tabla manda, eso no pasa.

El rol llega sugerido y editable, porque acertar `sucursal_id` es fácil pero si
`monto_objetivo` es medida o dimensión lo sabe la persona, no una heurística.

---

## 8. El YAML a la vista

El modelo como texto, en Monaco, de solo lectura. No es un detalle interno que se
esconde: es el formato en el que el modelo se versiona, se revisa en diff y se
exporta. Poder verlo es lo que evita que la definición quede encerrada en una base
de datos que solo esta aplicación entiende.

Es de solo lectura a propósito: se edita en el lienzo, que valida referencias
mientras se trabaja.

---

## 9. Dos hallazgos durante la fase

### El esquema de metadatos ya no se puede crear con `create_all`

Al arrancar el servidor con las columnas nuevas de la Fase 1:

```
sqlite3.OperationalError: no such column: dataset.cron
```

`create_all` crea tablas, pero **no las altera**. Las pruebas nunca lo vieron
porque parten de una base vacía; la base de desarrollo, que sí tiene datos, quedó
rota. Era justo el momento que estaba anotado como deuda: *"al primer cambio de
esquema se pasa a Alembic"*.

Hecho: Alembic adoptado sobre la base existente sin perder datos, con dos
revisiones y una prueba que compara el esquema de las migraciones contra los
modelos. Ver [ADR 0002](adr/0002-alembic-para-el-esquema.md).

### Dos servidores zombis de una sesión anterior

Un `uvicorn` y un `vite` de días atrás seguían ocupando sus puertos, aceptando
conexiones y sin responder nunca (bloqueados escribiendo a una terminal que ya no
existía). Se reemplazaron por procesos gestionados. Vale saberlo: en el servidor
esto lo evita `systemd` o Docker, no un `npm run dev` en una terminal.

---

## 10. Cómo se ve

```
┌─ entidades ──┬─ lienzo ─────────────────────┬─ inspector ──────┐
│ ● cat_sucursal│  ┌──────────┐  ┌──────────┐ │ Selección │ Diag.│
│ ● cat_marca   │  │dimensión │  │dimensión │ │                  │
│ ■ fact_venta  │  └────┬─────┘  └────┬─────┘ │  tipo, clave,    │
│               │   muchos → uno      │       │  grano, campos   │
│ métricas      │  ┌────┴─────────────┴─────┐ │  con su rol      │
│ Venta         │  │  hecho  (grano: ...)   │ │                  │
│ Utilidad      │  └────────────────────────┘ │                  │
│               │                             │                  │
│ versiones     │  [minimapa]                 │                  │
│ v2 · nota     │                             │                  │
└───────────────┴─────────────────────────────┴──────────────────┘
```

---

## 11. Herramientas del frontend

| | Por qué |
|---|---|
| React 19 + TypeScript + Vite | los tipos de la definición son el contrato con el backend; un rol mal escrito se ve al compilar |
| TanStack Query | una sola definición de cada consulta y de cuándo invalidarla, en `api/hooks.ts` |
| React Flow (`@xyflow/react`) | el lienzo, con conectores por campo |
| Monaco | la vista del YAML |
| CSS propio con tokens | sin librería de componentes; una herramienta de BI se mira durante horas, así que el color se reserva para el dato y para el aviso |

Detalle que costó un rato: **el orden de los imports de CSS importa.** Con los
estilos de React Flow importados después de los nuestros, el minimapa salía en
blanco. Y pasar objetos de nodo nuevos en cada render borra las medidas que React
Flow guarda (`measured`), con lo que el minimapa se queda vacío: el estado de los
nodos lo lleva React Flow y aquí solo se sincroniza lo que cambió.

---

## 12. Lo que falta

| Pendiente | Nota |
|---|---|
| **Editar jerarquías desde la interfaz** | hoy se conservan pero solo se editan en el YAML |
| ~~Editar políticas de seguridad por fila~~ | resuelto en la Fase 6: Gobierno → Seguridad por fila, con simulador ([07](07-fase-6-gobierno.md)) |
| **Restaurar una versión anterior** | se puede *ver* cualquier versión; volver a ella todavía no |
| **Comparar dos versiones** | el YAML es diffable; falta mostrarlo |
| **Resolver una ambigüedad desde el lienzo** | el diagnóstico la explica; elegir el camino se hará al consultar |
| **Diagnóstico del borrador** | hoy es de la versión guardada, y se avisa de ello |

---

## 13. Cómo levantarlo

```bash
cd /backend && ./venv/bin/python3 -m uvicorn app.main:app --port 8000
```

```bash
cd /frontend && npm run dev
```

El frontend pide siempre a `/api` y Vite hace de proxy: el mismo código sirve en
desarrollo y detrás de Caddy en el servidor.

```bash
cd /frontend && npm run typecheck && npx oxlint src
```
