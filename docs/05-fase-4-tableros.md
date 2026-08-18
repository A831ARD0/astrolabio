# Fase 4 — Tableros

Estado: **completa**. 124 pruebas pasando, verificada en el navegador con un
tablero de 8 widgets sobre `demo_comercial`.

---

## 1. Un tablero está anclado a una versión del modelo

No al modelo "actual": a una versión concreta. Si alguien cambia la definición de
una métrica, **lo publicado sigue diciendo lo que decía**. El cambio se adopta
moviendo el ancla a propósito, con un botón que avisa de que las cifras pueden
cambiar.

Sin esto, una cifra certificada puede cambiar sola de un día para otro y nadie
sabe por qué. Es el problema que hace que a un tablero se le pierda la confianza.

Dos detalles que hacen que el anclaje no sea decorativo:

- Las consultas llevan `?version=`. Sin ese parámetro el tablero diría
  "versión 2" y preguntaría por la vigente.
- La lista de tableros marca **"modelo más nuevo"** cuando hay una versión
  posterior, así que el desfase se ve sin entrar.

---

## 2. Los datos salen por un solo camino

Cada widget consulta `POST /api/modelos/{id}/consultar`, que es el único camino y
el que aplica la seguridad por fila. **El endpoint de tableros no devuelve datos**,
solo la definición.

Si un tablero pudiera traer datos por su cuenta, sería un agujero en las políticas:
bastaría con guardar el widget adecuado para leer lo que no te toca. Verificado en
las pruebas: un lector regional ve **una** sucursal en el panel de filtros, no las
40 con 39 tachadas — la existencia de una sucursal ya es información.

---

## 3. El bug que habría hecho mentir a los tableros

Encontrado al construir esta fase, en el compilador de consultas:

```python
for f in filtros:
    ent, campo = f["campo"].split(".")
    if ent not in alias:
        continue          # ← el filtro se ignoraba en silencio
```

Un filtro sobre una entidad que la consulta no había unido **se descartaba sin
avisar**. En un tablero eso significa: filtras por marca, el total no cambia, y
nadie lo nota porque el número sigue pareciendo un número.

Medido sobre los datos de prueba con desglose por sucursal y filtro por la marca
del vehículo (las cifras son de la generación de datos de demostración de entonces;
el generador se ha vuelto a sembrar desde y ahora dan otras):

```
sin filtro  : 439,970 unidades
marca Aurex :  58,544 unidades
```

Antes del arreglo, la segunda consulta devolvía 439,970.

El arreglo tiene dos partes, y las dos importan:

1. La entidad de cada filtro se agrega a los objetivos del join, igual que ya se
   hacía con las entidades protegidas por seguridad por fila.
2. Si aun así no hay ruta, la consulta **falla**. `tbl_encuesta_clima` está aislada:
   filtrar por ella no puede devolver un número, tiene que avisar.

---

## 4. Filtros asociativos — los cuatro estados

|  |  |
|---|---|
| **seleccionado** | lo eligió el usuario |
| **posible** | sobrevive a las selecciones de otros campos |
| **alternativo** | *sería* posible; hay otra selección en su propio campo |
| **excluido** | no sobrevive a las selecciones |

La distinción entre **alternativo** y **excluido** es la que separa un motor
asociativo de verdad de una imitación con listas desplegables. Al elegir Aurex, las
demás marcas siguen siendo elegibles (alternativas) y no deben tacharse; las
sucursales que no venden Aurex sí están excluidas.

Verificado en el navegador con Aurex seleccionada:

| | sin filtro | Aurex |
|---|---|---|
| Venta | $184.99 MM | **$25.66 MM** |
| Utilidad | $29.38 MM | **$4.08 MM** |
| Unidades | 440 k | **61 k** |
| Sucursales en el gráfico | 15 | **5** |
| Estados en la tabla | 4 | **2** |

Cada estado se distingue por color **y** por forma (marca punteada, texto tachado):
quien no distinga los grises tiene que poder leerlo igual.

Hacer clic en una barra también selecciona: el gráfico es un filtro, como en Qlik.

---

## 4.1 Varios campos por panel, y el colapso a desplegable

Un panel de filtro lleva **los campos que le pongas**, no uno. No hizo falta cambiar
el esquema del widget: `dimensiones` ya era una lista y un filtro de un campo es el
caso de una sola, así que los tableros que ya existían se leen igual.

Y cuando no hay alto para listas, cada campo se colapsa en un **desplegable** que
dice lo elegido y abre la lista completa al tocarlo — el comportamiento del panel de
filtros de Qlik.

### La decisión la toma el espacio, no una casilla

Se mide el alto disponible con un `ResizeObserver` y se divide entre el número de
campos. Por debajo de 150 px por campo, desplegables. Es lo que hace que «hago el
widget chico y se vuelve desplegable» funcione sin configurar nada, y además
sobrevive a cambiar el tamaño de la ventana.

Ese 150 se midió mirando el resultado, no se calculó: con 125 px por campo la lista
técnicamente cabe pero enseña **un** valor, y ahí el desplegable es mejor. Verificado
en los dos sentidos sobre el mismo widget: con un campo abre lista, con dos colapsa.

### El resumen no consulta al servidor

«Marca: Aurex» o «Año: 2 de 5» sale de las selecciones, que ya están en memoria.
Los cuatro estados se piden **solo al abrir** el desplegable. Un panel con seis
campos colapsados hace cero consultas hasta que tocas uno; si el resumen necesitara
los estados serían seis, y otras seis con cada clic en cualquier otro filtro del
tablero.

### La lista se dibuja en un portal

El widget recorta lo que desborda —tiene que hacerlo, es una celda de la rejilla—,
así que una lista dentro del widget saldría cortada justo en los widgets pequeños,
que son los únicos que la usan. Va a `document.body` con posición calculada del
botón, y se abre hacia arriba si no cabe abajo.

La lista de valores vive en un solo componente (`ListaValores`) que usan las dos
formas. Si cada una tuviera la suya, tarde o temprano una dejaría de distinguir
*alternativo* de *excluido* — que es justo la distinción que no se puede perder.

---

## 5. Una ambigüedad no es un error: es una decisión

Al filtrar por marca pasó lo que tenía que pasar: **los ocho widgets se negaron a
calcular**. `cat_marca` se alcanza desde `fact_venta` por dos caminos —la marca de
la agencia y la marca del vehículo— y no son lo mismo.

Eso es correcto y es el corazón del diseño: el motor no elige por su cuenta. Pero
como experiencia era inaceptable: seleccionas una marca y el tablero se llena de
mensajes técnicos.

La solución no fue elegir un camino por defecto —eso es exactamente lo que produce
cifras equivocadas— sino **ofrecer la decisión donde ocurre**:

```
Hay 2 caminos de igual longitud para cruzar estos datos, y dan cifras
distintas. Elige cuál usar en todo el tablero:

  [ fact_venta → cat_sucursal → cat_marca ]
  [ fact_venta → dim_vehiculo → cat_marca ]
```

Se elige una vez, aplica a todo el tablero y **se guarda con él**, así que la
cifra es reproducible: quien abra el tablero mañana verá el mismo número por el
mismo camino. Un widget puede sobreescribir la elección si de verdad quiere medir
por el otro camino.

---

## 6. Publicar y certificar

| | |
|---|---|
| **Borrador** | solo lo ven editores y administradores. Un borrador a medias no es una cifra con la que nadie deba decidir |
| **Publicado** | visible para lectores |
| **Certificado** | "estas cifras se revisaron". Solo un administrador, requiere estar publicado, y **se pierde al editar** o al mover de versión |

Que la certificación se caiga al editar no es una molestia: lo que se revisó ya no
es esto.

---

## 7. Decisiones sobre los gráficos

No son de gusto:

- **El eje de valores empieza en cero** en barras y áreas. Un eje truncado exagera
  diferencias: dos sucursales que difieren un 3% parecen el doble una de otra. En
  líneas se permite no empezar en cero, porque ahí se lee la forma de la serie.
- **Nada de etiquetas rotadas 90°.** Si los nombres no caben, el gráfico se dibuja
  horizontal. Los nombres de las sucursales son largos.
- **Cifras en `es-MX` con separador de miles**, y compactas en los ejes (`$1.2 M`).
  El valor exacto vive en el tooltip y en la tabla. `1234567.891` obliga a contar
  dígitos con el dedo, y ahí es donde alguien lee un millón donde hay diez.
- **Paleta corta y estable.** Si el color cambia de significado entre dos gráficos
  del mismo tablero, el color deja de informar.
- Cuando una consulta falla, el widget **muestra el error**. Un panel en blanco o
  con un cero es peor que un mensaje: parece un dato.

### El aviso del KPI con desglose

Un KPI suma las filas que le llegan. Para métricas aditivas está bien; para un
promedio o un porcentaje da un número equivocado sin fallar. El editor lo dice en
el sitio donde se configura, no en un manual.

---

## 8. Dos problemas de dependencias

**`echarts-for-react` es CommonJS** y su punto de entrada `lib/core` reventaba en
el navegador con `exports is not defined`. Se reemplazó por
[`useEcharts`](../frontend/src/tablero/useEcharts.ts), cuarenta líneas propias que
además resuelven bien las tres cosas que importan: redimensionar con
`ResizeObserver` (un widget en una rejilla cambia de tamaño constantemente),
`dispose()` al desmontar (sin eso cada navegación deja una instancia viva) y
reemplazar en vez de fusionar las opciones (fusionar deja restos del gráfico
anterior al cambiar de tipo).

**`react-grid-layout` 2 cambió la API por completo**: `cols`/`rowHeight`/
`isDraggable` pasaron a `gridConfig`/`dragConfig`/`resizeConfig`, y el tipo
`Layout` que antes era una caja ahora es la lista entera. El paquete
`@types/react-grid-layout` sobra y estorba: describe la versión 1.

---

## 9. Lo que falta

| Pendiente | Nota |
|---|---|
| **Comparar contra un objetivo** en el KPI | la métrica `objetivo_unidades` existe; falta el widget que la enfrente a lo real |
| ~~Exportar a Excel / CSV~~ | resuelto: xlsx con hoja de procedencia, y CSV |
| **Barra de selecciones** | quien viene de Qlik la busca con los ojos: hoy solo hay «Quitar N filtro(s)», sin ver *qué* está elegido sin mirar los paneles |
| **Atrás/adelante en las selecciones** | un clic de más se deshace a mano |
| **Marcadores** | se puede fijar un juego de selecciones como estado inicial del tablero; nombrar varios todavía no |
| **Candado en una selección** | para que «quitar todo» no se la lleve |
| **Seleccionar los excluidos / invertir** | y seleccionar todo el resultado de una búsqueda de golpe |
| **Lazo sobre un gráfico** | hoy se selecciona punto por punto |
| **Perforar (drill-down)** | hacer clic en una barra filtra; bajar un nivel de jerarquía todavía no |
| **Un widget de fecha decente** | hoy el tiempo se filtra como cualquier dimensión, sin selector de rango |
| **Ordenar y limitar desde la interfaz** | hoy el orden lo decide la consulta |
| **Tableros por rol** | quién ve qué tablero, más allá de publicado/borrador |
| **Refrescar solo** | un tablero abierto no se entera de que hubo una carga nueva |

---

## 10. Cómo usarlo

```bash
cd /backend && ./venv/bin/python3 -m pytest tests/ -q
```

Flujo: **Tableros → + Nuevo tablero → Editar → agregar widgets → elegir métricas y
dimensiones del catálogo → Guardar → Publicar**.

Nada se guarda al escribir. Las selecciones son del momento y no se guardan al
mover un filtro: solo con "Guardar con filtros", porque un tablero que se abre
siempre con el filtro de alguien puesto es una trampa.
