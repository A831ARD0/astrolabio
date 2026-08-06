# Fase 3 — El ETL

Estado: **completa**, con flujos programados (§11). 179 pruebas pasando, verificada en
el navegador con una
transformación real sobre 500,000 filas.

---

## 1. La base analítica nunca se abre para escribir

Es la decisión que ordena toda la fase. Una transformación adjunta la base en
**solo lectura** y escribe su resultado como Parquet en el directorio de datasets.
Tres consecuencias, y las tres se querían:

- El camino de consultas mantiene su garantía: nada de lo que pase por el ETL puede
  modificar una tabla que un tablero está leyendo.
- El resultado es un archivo: se respalda copiándolo, se lee con cualquier
  herramienta, no queda encerrado.
- Ejecutar una transformación mientras alguien consulta no bloquea nada.

Hay una prueba que lo verifica de frente: después de ejecutar, comprueba que la
tabla **no** existe en la base analítica.

Se escribe primero a un directorio temporal y **después** se reemplaza el
definitivo. Si el proceso muere a media escritura, lo que había sigue completo:
media transformación es peor que ninguna, porque parece un resultado.

---

## 2. El SQL se lee como la lista de pasos

Cada paso se compila a un CTE con su nombre:

```sql
WITH p0_origen   AS (SELECT * FROM origen."fact_venta"),
     p1_unir     AS (SELECT izq.*, der."sucursal_nombre" FROM p0_origen AS izq
                     LEFT JOIN origen."cat_sucursal" AS der ON ...),
     p2_filtrar  AS (SELECT * FROM p1_unir WHERE "es_cancelacion" = ?),
     p3_derivar  AS (SELECT *, "monto_base" - "monto_impuesto" AS "neto" FROM p2_filtrar),
     p4_agrupar  AS (SELECT ... FROM p3_derivar GROUP BY ...)
SELECT * FROM p4_agrupar
```

No es estética. Cuando una cifra no cuadra, poder leer el SQL paso por paso —y
contar filas en cada uno— es la diferencia entre depurarlo en diez minutos y
adivinar. El SQL está a la vista en la interfaz, no escondido.

---

## 3. El conteo de filas por paso

Es la característica que más va a usarse. La vista previa muestra cuántas filas
entran y salen de cada paso, medido sobre la transformación real:

```
origen: fact_venta                 500,000
unir con sucursales (izquierda)    500,000
filtrar: 1 condición(es)           469,985    -30,015
derivar: neto                      469,985
agrupar: por 1, 3 agregado(s)           36   -469,949
ordenar por venta_neta                  36
```

De un vistazo se ve que **la unión no duplicó filas** (500,000 → 500,000, o sea que
es de verdad muchos-a-uno), que el filtro quitó 30,015 cancelaciones, y que el
agrupado dejó 36 sucursales.

Un join que duplica filas es la causa número uno de un total inflado, y aquí se
detecta antes de publicar nada. Sin este panel, una transformación de seis pasos es
una caja negra.

---

## 4. Los pasos

| Paso | Qué hace |
|---|---|
| **filtrar** | condiciones con `y`/`o`; contiene, empieza con, en lista, es nulo… |
| **columnas** | quedarse con unas o quitar otras (`EXCLUDE`, así no hay que listar el resto) |
| **renombrar** | cambiar nombres |
| **derivar** | columna calculada con una expresión |
| **agrupar** | suma, promedio, mínimo, máximo, cuenta, cuenta distintos |
| **unir** | join con otro origen, con el tipo y las parejas explícitas |
| **apilar** | pegar filas de otros orígenes |
| **ordenar** / **limitar** / **distintos** | lo que dicen |

Dos decisiones que evitan errores silenciosos:

- **`unir` pide explícitas las columnas que trae del otro lado.** No hay prefijo
  automático: dos columnas con el mismo nombre tras un join es de donde salen los
  "columna ambigua" a mitad de un tablero, y un prefijo automático ensucia todos
  los nombres para evitar un choque que casi nunca ocurre. Las claves del join no
  se traen dos veces.
- **`apilar` empareja por nombre de columna** (`UNION ALL BY NAME`), no por
  posición. Apilar por posición es la forma clásica de mezclar la columna de
  importe con la de fecha cuando dos tablas no traen el mismo orden.

Nada de esto se teclea: las columnas salen del esquema real del origen, así que no
se puede elegir una que no existe.

---

## 5. Las expresiones se validan sobre el árbol, no sobre el texto

Una columna calculada es SQL de verdad, como en cualquier herramienta de BI. Se
pasa por el analizador de SQLGlot y se rechaza todo lo que no sea una **expresión
escalar**: subconsultas, DDL, DML, varias sentencias.

Se revisa el árbol y no el texto a propósito: buscar la palabra `DROP` en una cadena
se salta con comentarios, mayúsculas raras o un identificador entre comillas. El
árbol no se deja engañar.

Los valores de los filtros **nunca** se interpolan: van como parámetros. Hay una
prueba que mete `'; DROP TABLE x; --` como valor y comprueba que la palabra no
aparece en el SQL generado.

---

## 6. Pegar SQL, y volver de SQL a pasos

Lo pediste explícitamente al revisar las maquetas: *"me gustaría que también se
pudiera colocar la consulta directamente si es que ya lo tienen, sin tener que
armarlo nuevamente"*.

**Modo SQL:** la consulta se ejecuta tal cual, con los orígenes disponibles por su
alias. Así una consulta pegada puede referirse a `ventas` sin saber si detrás hay
una tabla o un Parquet particionado. Solo se admite lectura: DDL y DML se rechazan.

**De SQL a pasos:** se lee el árbol de la consulta y se reconstruyen los pasos, para
poder seguir editándola visualmente. Verificado en el navegador: esta consulta

```sql
SELECT s.sucursal_nombre, SUM(v.monto_base) AS venta, COUNT(*) AS operaciones
FROM fact_venta AS v
LEFT JOIN cat_sucursal AS s ON v.sucursal_id = s.sucursal_id
WHERE v.es_cancelacion = false
GROUP BY s.sucursal_nombre ORDER BY venta DESC LIMIT 15
```

se convirtió en cinco pasos editables: unir → filtrar → agrupar → ordenar → limitar.

### La regla: no adivinar

Cuando algo no se puede representar como paso, **se dice cuál y por qué**, y no se
convierte:

- funciones de ventana (`OVER`)
- `HAVING`
- subconsultas
- CTEs
- `ORDER BY` que mezcla ascendente y descendente
- agregaciones sobre expresiones en vez de columnas

Una conversión aproximada es peor que ninguna: el usuario creería que ya está,
seguiría editando unos pasos que dicen otra cosa, y la cifra cambiaría sin que
nadie tocara nada.

### El orden de los pasos no es cosmético

El primer intento ponía `filtrar` antes de `unir`. Está mal: en SQL el `WHERE` se
aplica **después** de los joins, y con un `LEFT JOIN` adelantar el filtro cambia el
resultado —las filas sin pareja se comportan distinto—. Además el filtro podría
referirse a una columna que en ese punto todavía no existe.

Hay una prueba que ejecuta la misma consulta por los dos caminos (modo SQL y pasos
reconstruidos) y **compara los números sucursal por sucursal**. Si difieren, la
conversión es una trampa.

---

## 7. Guardas

| Guarda | Por qué |
|---|---|
| Una transformación no puede leer de sí misma, ni en cadena | `a` → `b` → `a` se detectaría en ejecución, después de haber borrado el resultado anterior de una de las dos |
| El nombre no puede chocar con un dataset | los dos escribirían en el mismo directorio y uno pisaría al otro |
| El nombre no se puede cambiar | dejaría huérfano el resultado ya materializado y cualquier modelo que apunte a él |
| Borrar **no** borra los datos salvo que se pida | el resultado puede estar alimentando un modelo |
| Se compila al guardar, sin ejecutar | el error sale al guardar y no de madrugada |
| El historial guarda los fallos | igual que en las cargas: sin historial de fallos no se depura nada |
| El ETL es de editor en adelante | un lector no transforma datos |

---

## 8. Un bug de dependencia que habría pasado por bueno

La conversión desde SQL falló con *"la consulta no tiene FROM"* sobre una consulta
que claramente lo tenía: **SQLGlot 30 renombró la clave del árbol de `from` a
`from_`**. Leer solo una de las dos formas hace que la conversión falle de un modo
que parece un problema de la consulta del usuario.

Ahora se leen las dos, con una función que lo dice en un comentario para que la
próxima actualización no vuelva a esconder el problema.

---

## 9. Lo que falta

| Pendiente | Nota |
|---|---|
| ~~Programar transformaciones~~ | **Resuelto**: ver §11, flujos |
| **`HAVING` como paso** | filtrar después de agrupar; hoy hay que encadenar dos transformaciones |
| **Carga incremental de una transformación** | hoy se recalcula completa; para tablas grandes hará falta un modo incremental |
| **Grafo de linaje visual** | el linaje se guarda (`lee_de`); falta dibujarlo |
| **Perfilado de columnas** | nulos, distintos, mínimos y máximos por columna al elegir un origen |
| **Deshacer** en el editor de pasos | hoy se quita el paso y se vuelve a poner |

---

## 10. Cómo usarlo

```bash
cd /backend && ./venv/bin/python3 -m pytest tests/ -q
```

En la interfaz: **Datos → + Nueva transformación → ponle nombre → elige orígenes de
la izquierda → agrega pasos**. La vista previa se calcula sola mientras editas.
Después **Crear** y **Ejecutar**; el resultado queda disponible como origen de un
modelo semántico o de otra transformación.

---

## 11. Flujos: cargar y transformar en cadena

Añadido después de la Fase 3. Un **flujo** es una lista ordenada de pasos con un
solo horario: *"cada día a las 6, trae las ventas y luego recalcula el resumen por
sucursal"*.

### Es una lista, no un grafo de dependencias

A propósito. Un grafo es más potente y también más difícil de mirar y de razonar;
una lista se lee de arriba abajo. Pero el orden **no se deja al azar**: se comprueba
contra el linaje que ya guarda cada transformación.

Verificado en el navegador poniendo el orden mal a propósito. El aviso sale **en el
paso mismo**, no en un mensaje aparte:

> Paso 1 (bono_por_sucursal) lee de 'bonificaciones', que se actualiza en el paso 2,
> **DESPUÉS**. Tal como está, trabajará con los datos anteriores.

Y el botón **Ordenar solo** lo arregla: reordena según el linaje y agrega las cargas
que falten. Es una propuesta que se revisa, no un cambio automático — puede haber
razones para el orden que tenía.

Son avisos y no errores porque hay casos legítimos: una transformación puede leer de
un dataset que se carga en otro flujo, o de una tabla del motor que no se carga
nunca. Bloquear eso sería adivinar. Cuando pasa, el aviso lo dice de otra forma:
*"este flujo no actualiza 'X'. Se usará lo que haya de la última vez."*

### Al fallar se detiene

Es el valor por defecto, y es el que importa. **Seguir recalculando cuando la carga
de la que se depende no ocurrió produce un número que parece fresco y no lo es** — y
esa es la clase de error que nadie detecta hasta que alguien decide con él.

Los pasos que no se llegaron a intentar quedan marcados como **omitidos**. Un hueco
en el historial se leería como "corrió y no hizo nada".

Se puede cambiar a "continuar" cuando los pasos son de verdad independientes.

### Un solo camino, otra vez

El ejecutor del flujo llama a los **mismos servicios** que los botones:
`cargas.ejecutar_carga` y `transformar.ejecutar` (extraído de la ruta HTTP en este
mismo cambio, por la misma razón que en la Fase 1). Así:

- cada paso deja su propia entrada en su propio historial, además del resumen del
  flujo;
- un paso corrido por el flujo y el mismo paso a mano son indistinguibles en el
  registro salvo por el campo que dice quién lo disparó — que es justo lo que
  interesa;
- el flujo guarda **resumen y detalle**: el primero para saber si la noche salió
  bien, el segundo para saber cuál paso la arruinó.

### Medido en la interfaz

```
Flujo completo: 2 paso(s) en 23.5 ms
  1  cargar      bonificaciones       5 filas · 4.3 ms
  2  transformar bono_por_sucursal    3 filas · 1.9 ms

Próxima corrida: 5/8/2026, 6:00:00 a.m.
```

El horario se elige de una lista de casos frecuentes ("todos los días a las 6:00",
"de lunes a sábado", "el día 1 de cada mes") y también se puede escribir el cron a
mano. La zona horaria viaja con él: "a las 6" en un servidor en UTC no es a las 6 en
Monterrey, y una carga a la hora equivocada trae el día incompleto.

Igual que con las cargas: si la excepción escapara del trabajo, APScheduler apagaría
el flujo y dejaría de correr en silencio. Hay prueba de eso.

### Las cuatro formas de actualizar, y cuál usar

No hace falta ponerle horario a nada para que los datos se actualicen, y no hace
falta un horario por tabla:

| | Cómo | Cuándo conviene |
|---|---|---|
| **A mano** | «Cargar» en el dataset o «Ejecutar» en el flujo | probando, y para corregir algo puntual |
| **Horario del dataset** | un cron por dataset | una tabla que no depende de nada más |
| **Horario del flujo** | un cron para la cadena entera: carga estas tablas, luego recalcula estas transformaciones | **lo normal**. Es el equivalente de una tarea de Qlik Sense |
| **Ventana móvil** | no es un disparador: es *qué* se recarga cada vez que corre. Ver `docs/03 §10.3` | tablas donde las filas viejas cambian |

Un flujo **es** «ejecutar una tarea después de otra»: los pasos van en orden y si uno
falla, los siguientes no corren. Lo que todavía no existe es que **el fin de un flujo
dispare otro flujo** —el «triggered by task completion» de Qlik Sense—; hoy eso se
resuelve poniendo los pasos de los dos en un solo flujo, que para el caso de un origen real
alcanza, y cuando no alcance es una fila más en la tabla de abajo.

Los dos horarios pueden convivir, y ahí sí hay una trampa: un dataset con cron propio
que además es paso de un flujo se carga **dos veces**. No está prohibido —a veces es lo
que se quiere— pero conviene mirarlo.

## 12. Avisos: que un fallo se lo cuente a alguien

Un fallo quedaba en el historial, que sirve si alguien va a mirarlo. El daño de un
flujo que se rompe un martes a las 3 de la mañana no es que falle: es que los
tableros siguen abriendo, con las cifras del día anterior y sin ninguna señal de que
están viejas. Alguien decide con ellas.

Una **regla de aviso** dice a quién contárselo: por correo o por webhook (Teams,
Slack o lo que sea — los dos leen el campo `text`, así que el mismo mensaje sirve),
de qué eventos, y sobre qué. El alcance por omisión es **todo**, y es el que
conviene: una regla por dataset parece más fina y en la práctica deja sin cubrir
justo el dataset que se cree mañana.

Cuatro decisiones, cada una de un modo distinto de fallar:

| Decisión | El fallo que evita |
|---|---|
| **Un aviso que falla no rompe la carga** | tumbar una carga que salió bien porque el servidor de correo no contesta |
| **Se guarda cada intento, también los fallidos** | «no me llegó nada» y «no falló nada» se ven igual. El modo de fallo de un sistema de avisos no es avisar mal: es que uno crea que está avisando |
| **Silencio entre repeticiones** | una carga rota cada 15 min manda 96 correos al día; a los dos días hay una regla en el buzón que los archiva sola, y el que importaba también |
| **También se avisa al recuperarse** | es la otra mitad del silencio: sin ella nadie sabe si sigue roto, y averiguarlo entrando a mirar es lo que el aviso venía a evitar |

El botón **Probar** está junto a cada regla, no escondido en un menú: un canal que
nadie probó no es cobertura, es creer que la hay — y con avisos uno deja de mirar el
historial, así que la creencia equivocada sale más cara que no tener avisos. La
prueba se salta el silencio y los eventos, y cuando falla contesta **200 con el error
del canal**, porque ese error es el resultado útil de la ruta.

Si el canal no puede entregar —correo sin `ASTROLABIO_SMTP_HOST`— se dice en la propia
regla. Una regla activa sobre un canal sin configurar se ve exactamente igual que
una que funciona.

Lo que dice un aviso de carga fallida:

```
[Astrolabio] Falló la carga de ventas_agencias

  Origen  : tbl_ventas
  Disparo : programado
  Cuando  : 2026-08-05 09:00 UTC
  Error   : No se pudo conectar por ODBC: Data source name not found

Ultima carga que si salio bien: 2026-08-04 09:00 UTC.
Hasta que se arregle, lo que se ve en los tableros es de esa fecha.
```

Esa última línea es la que hace falta a las 3 de la mañana: no «falló algo», sino
con qué datos se está viendo el tablero mientras tanto. En el de un flujo, lo
equivalente es la lista de pasos que **no se llegaron a ejecutar**.

Configuración del correo (`.env`): `ASTROLABIO_SMTP_HOST`, `ASTROLABIO_SMTP_PUERTO`,
`ASTROLABIO_SMTP_USUARIO`, `ASTROLABIO_SMTP_CONTRASENA`, `ASTROLABIO_SMTP_TLS`,
`ASTROLABIO_SMTP_REMITENTE`. El webhook no necesita nada de eso: la URL es el destino.

**Un límite conocido:** el envío ocurre dentro de la transacción de la carga, con un
timeout de 10 s. Es simple y verificable, y el precio es que un servidor de correo
lento retrasa el final de la carga hasta 10 segundos. Mandarlo aparte, en una cola,
sería mejor cuando haya muchas reglas.

### Lo que falta de los flujos

| Pendiente | Nota |
|---|---|
| **Un flujo que dispare a otro al terminar** | el «triggered by task completion» de Qlik Sense. Hoy se juntan los pasos en un flujo |
| **Pasos en paralelo** | dos cargas independientes podrían ir a la vez |
| **Reintentar un paso** | hoy se vuelve a correr el flujo entero |
| **Refrescar los tableros al terminar** | un tablero abierto no se entera de que hay datos nuevos |
| **Avisar de un dataset programado dos veces** | por su cron y por un flujo a la vez. El aviso de fallo ya existe; este es otro |
| **Avisar de una carga que trae 0 filas** | no es un error y a veces es peor que uno: la carga «sale bien» y no hay datos |
| **Limpiar el historial de avisos** | crece con cada intento, incluidos los silenciados |
