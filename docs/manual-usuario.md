# Manual de usuario

Para quien va a usar Astrolabio: traer datos, transformarlos, modelarlos y
publicar tableros. No hace falta saber programar; sí ayuda saber qué significan
tus datos.

Si lo que buscas es instalarlo o mantenerlo, ese es el
[manual técnico](manual-tecnico.md).

**Índice**

1. [Entrar, y qué puede hacer cada quién](#1-entrar-y-qué-puede-hacer-cada-quién)
2. [Conectar a un origen](#2-conectar-a-un-origen)
3. [Traer una tabla: el dataset](#3-traer-una-tabla-el-dataset)
4. [Mantener los datos al día](#4-mantener-los-datos-al-día)
5. [Transformar](#5-transformar)
6. [El modelo: cómo se cruzan las tablas](#6-el-modelo-cómo-se-cruzan-las-tablas)
7. [Tableros](#7-tableros)
8. [Quién ve qué](#8-quién-ve-qué)
9. [Avisos cuando algo falla](#9-avisos-cuando-algo-falla)
10. [Preguntas frecuentes](#10-preguntas-frecuentes)

---

## 1. Entrar, y qué puede hacer cada quién

Hay tres roles. No se eligen por pantalla: los asigna un administrador.

| Rol | Puede |
|---|---|
| **Lector** | Ver los tableros publicados, filtrar y exportar. Solo las filas que le corresponden |
| **Editor** | Todo lo anterior, más conexiones, datos, transformaciones, modelo y tableros |
| **Administrador** | Todo, más usuarios, políticas y auditoría. **Las políticas no le aplican**: siempre ve todo |

Ese último punto importa: un administrador no puede comprobar una política mirando
sus propias pantallas. Para eso está el simulador (§8).

La primera vez, el administrador que se crea al arrancar sale en el registro del
servidor con una contraseña temporal. **Cámbiala al entrar**: no se vuelve a mostrar.

---

## 2. Conectar a un origen

![Pantalla de conexiones](img/conexiones.png)

**Conexiones → + Nueva conexión.** Hay tres tipos:

- **MySQL / MariaDB** — el conector nativo, el más rápido.
- **Archivos** — una carpeta del servidor con CSV, Excel o Parquet. Solo se lee de
  dentro de esa carpeta.
- **ODBC** — el comodín: Pervasive/Actian, SQL Server, Informix, PostgreSQL… Elige
  primero el **origen** y el formulario pide solo lo que ese driver necesita, porque
  cada uno llama distinto a lo mismo.

### Probar y luego guardar, en ese orden

El botón **Guardar** no se enciende hasta que la prueba sale bien, y **cualquier
cambio en la configuración invalida la prueba anterior**. No es una molestia: evita
probar contra un servidor, cambiar el servidor y guardar apoyado en un visto bueno
que ya no vale.

Si un botón está apagado, la línea de al lado dice por qué. Siempre.

### Las contraseñas

Se guardan cifradas y **no vuelven a salir nunca**, ni enmascaradas de forma
reversible.

Para cambiar una —rotar una contraseña, mover el servidor de máquina— está el botón
**Editar** de la conexión. Dos cosas que conviene saber:

- **El campo de contraseña sale en blanco, y en blanco significa "no la toques".**
  No se puede mostrar la guardada, así que se enseña vacía. Solo se cambia si
  escribes una nueva. Cambiar el puerto no te obliga a volver a teclear la
  contraseña.
- **El tipo y, en ODBC, el origen no se cambian.** Serían otra conexión, y los
  datasets que cuelgan de esta dejarían de tener sentido. Para eso, crea una nueva.

Editar prueba antes de guardar, igual que crear: si el cambio no conecta, no se
guarda y la conexión anterior sigue funcionando. Cambiar solo el nombre no necesita
prueba —el nombre es una etiqueta tuya, el servidor de datos no lo ve.

> Antes esto no existía y había que borrar la conexión y volver a crearla, **lo que
> se llevaba por delante todos sus datasets**: su historial, sus horarios y sus
> columnas elegidas.

> **Pide siempre un usuario de solo lectura** para cada origen. Astrolabio nunca
> escribe en tus sistemas, y un usuario con permisos de escritura solo puede
> hacer daño si algo sale mal.

---

## 3. Traer una tabla: el dataset

**Conexiones → Explorar → elige una tabla → Traer una tabla.**

Un *dataset* es una tabla de tu origen ya copiada a Parquet local. Se configura una
vez y a partir de ahí recargarla es un botón.

Lo que se decide al crearlo:

| Campo | Para qué | Consejo |
|---|---|---|
| **Nombre** | Con el que lo verás después | Sin espacios; es también el nombre del directorio |
| **Columnas** | Cuáles traer | Por defecto **todas**, y eso es lo que conviene dejar salvo que la tabla sea muy ancha |
| **Partir por** | Una columna de fecha | Permite recargar un mes sin tocar los demás |
| **Columna incremental** | Un id o fecha que solo crece | Hace que la segunda carga traiga solo lo nuevo |

### Sobre elegir columnas

La vista de muestra **se vuelve a pedir al origen** con las columnas elegidas, así
que ves exactamente lo que vas a traer. Si dejas todas, se guarda «todas» y no la
lista: así, cuando el origen agregue una columna el mes que viene, llegará sola.

Dos cosas que la pantalla no te deja hacer, porque fallarían de madrugada: dejar
fuera la columna de partición o la incremental, y dejarlo todo fuera.

**Si cambias las columnas de un dataset que ya cargó, la siguiente carga será
completa** y reescribirá todo. El archivo en disco tiene las columnas viejas, y
mezclar dos juegos haría que leerlo fallara o —peor— devolviera nulos.

### ¿La primera carga trae todo?

Sí. El modo no se elige: sale del estado del dataset.

- Sin carga previa → **completa**.
- Con marca previa e incremental → **incremental** (solo lo nuevo).
- Con ventana móvil → **recarga de particiones** (ver abajo).

---

## 4. Mantener los datos al día

Hay cuatro formas, y sirven para cosas distintas:

| | Cómo | Cuándo |
|---|---|---|
| **A mano** | El botón «Cargar» | Probando, o corrigiendo algo puntual |
| **Horario del dataset** | Un cron por dataset | Una tabla que no depende de nada |
| **Horario del flujo** | Un cron para la cadena completa | **Lo normal.** Es el equivalente de una tarea de Qlik Sense |
| **Ventana móvil** | No es un disparador: es *qué* se recarga | Tablas donde las filas viejas cambian |

### Ventanas móviles

Una carga incremental trae lo **nuevo** y nunca vuelve a mirar lo que **cambió**. Si
una venta de hace tres semanas se corrige o se cancela, su id no cambia y el dato
se queda viejo para siempre.

Una ventana dice «recarga siempre este rango»: `el mes en curso`, `el mes en curso y
el anterior`, `los últimos 2 años`, `solo el día anterior`, `los últimos N días`…

El rango **se calcula cada vez que corre**, con la zona horaria del dataset. La
pantalla te dice qué haría hoy: *«El mes en curso y el anterior: del 2026-07-01 al
2026-08-05. Se recalcula en cada corrida.»*

«Cargar» respeta la ventana; **«Recargar completo» se la salta**.

### Flujos

![Pantalla de flujos](img/flujos.png)

Un flujo es «cada día a las 6, carga estas tablas y **luego** recalcula estas
transformaciones». Los pasos van en orden y **si uno falla, los siguientes no
corren**: seguir recalculando sobre datos que no se cargaron produce un número que
parece fresco y no lo es.

El botón **Ordenar solo** propone el orden correcto leyendo de qué lee cada
transformación. Es una propuesta, no un cambio automático.

⚠️ Un dataset con horario propio que además es paso de un flujo **se carga dos
veces**. A veces es lo que se quiere; conviene saberlo.

### Tareas

**Tareas** es la pantalla de la mañana: todo lo que corre solo, en una sola tabla.
Los flujos y las cargas con horario propio aparecen juntos, porque a las 8 de la
mañana lo que importa es qué corrió anoche y cómo salió, no de qué tipo era.

Cada fila dice el horario, cuándo corrió por última vez, cómo salió y cuándo vuelve
a correr. El triángulo de la izquierda **despliega los pasos en su orden**, así que
no hay que abrir el flujo para saber qué hace.

Lo que falló sale arriba. Los filtros de la barra —*Fallaron*, *Corriendo*, *Bien*,
*Sin correr*, *Sin horario*— y el buscador, que también busca por tabla y por
conexión, sirven para responder «¿quién carga esta tabla?».

Aquí no se edita nada: **Abrir** lleva a Flujos o a Conexiones, que es donde se
cambia. **Ejecutar** lanza un flujo a mano.

#### Ejecutar a mano: corre en segundo plano

**Ejecutar** no se queda esperando. Un flujo de veintiocho tablas por el puente
tarda minutos; tener la pantalla esperando todo ese rato terminaba en un *Error
502* del proxy aunque el servidor siguiera trabajando. Ahora la corrida se lanza
y se sigue por el historial: **puedes cerrar la pantalla, o el navegador**.

Si ya hay algo corriendo, Astrolabio pregunta:

- **Esperar turno** (lo normal). Se pone en cola y arranca cuando acabe lo de
  antes. Si los dos leen del mismo servidor de origen, lanzarlos a la vez no
  acaba antes — y a veces acaba peor.
- **Correr ya, a la par**. Arranca de inmediato. Tiene sentido cuando son
  sucursales en servidores distintos.

Arriba de la tabla aparece una barra con lo que corre y lo que espera turno; de
la cola se puede sacar algo que **todavía no empezó**. Lo que ya arrancó no se
corta: a mitad de una ingesta, cortar deja el destino a medias.

**El mismo flujo dos veces a la vez se rechaza**, y eso no se pregunta: serían
dos procesos escribiendo los mismos archivos.

---

## 5. Transformar

![Pantalla del ETL](img/etl.png)

**Transformar** es donde se limpia y se resume: filtrar, unir, agrupar, derivar
columnas, apilar, ordenar. Dos formas de trabajar, y se puede saltar de una a otra:

- **Por pasos**, eligiendo de listas que salen del esquema real (no se puede elegir
  una columna que no existe).
- **Pegando SQL**, si ya lo tienes escrito. Y se puede convertir de vuelta a pasos.

### Lo que más vas a usar: el conteo por paso

```
origen: fact_venta                 500,000
unir con sucursales (izquierda)    500,000
filtrar: 1 condición(es)           469,985    -30,015
derivar: neto                      469,985
agrupar: por 1, 3 agregado(s)           36   -469,949
```

De un vistazo se ve que **la unión no duplicó filas** (500,000 → 500,000, o sea que
de verdad es muchos-a-uno), que el filtro quitó 30,015 cancelaciones y que quedaron
36 sucursales. Un join que duplica filas es la causa número uno de un total
inflado, y aquí se ve antes de publicar nada.

### Al convertir SQL a pasos: no se adivina

Si algo no se puede representar (funciones de ventana, `HAVING`, subconsultas,
CTEs…), **se dice cuál y por qué**, y no se convierte. Una conversión aproximada es
peor que ninguna: seguirías editando unos pasos que dicen otra cosa.

---

## 6. El modelo: cómo se cruzan las tablas

![El lienzo del modelo](img/modelo.png)

El modelo dice qué es cada tabla (dimensión o hecho), cómo se relacionan y qué
métricas existen. Se dibuja arrastrando de un campo a otro.

**Las métricas se definen una vez.** «Utilidad» es una fórmula que vive en el
modelo, no algo que cada quien reescribe en su tablero. Es lo que hace que dos
personas no tengan dos utilidades distintas.

### El panel de diagnóstico

Marca los problemas que producen cifras mal sin avisar:

| Problema | Qué significa |
|---|---|
| **Ruta ambigua** | Hay dos caminos para cruzar dos tablas y dan resultados distintos. Al usarlo, el tablero te pide elegir cuál, y guarda tu respuesta |
| **Fan trap** | Unir dos hechos de distinto grano infla los totales al sumar |
| **Tabla huérfana** | No se relaciona con nada; sus cifras no se pueden cruzar |
| **Falta el grano** | Sin saber qué es una fila, no se puede detectar lo anterior |

Que aparezcan no significa que esté mal: significa que hay una decisión que tomar,
y que la herramienta no la va a tomar por ti en silencio.

### Versiones

Guardar el modelo **crea una versión nueva**; las anteriores no se tocan. Cada
tablero está anclado a una versión concreta, así que cambiar el modelo no rompe en
silencio lo ya publicado.

---

## 7. Tableros

![Un tablero](img/tablero.png)

**Tableros → + Nuevo tablero.** Se arrastran widgets y se colocan a gusto: KPI,
barras, líneas, pastel, tabla.

Cada widget lleva dimensiones (por qué se desglosa) y métricas (qué se mide), y
salen de listas del modelo.

### Filtros asociativos

Al hacer clic en un valor, **todo el tablero se filtra**, y los demás filtros
muestran qué valores siguen siendo posibles con esa selección y cuáles ya no. Es el
comportamiento al que uno se acostumbra en Qlik.

### Exportar

Cada widget tiene su flecha: **Excel** o **CSV**. El archivo lleva una hoja con el
contexto —qué filtros estaban puestos, qué versión del modelo, quién lo exportó y
cuándo— para que una tabla que alguien manda por correo siga diciendo de dónde salió.

---

## 8. Quién ve qué

![Gobierno](img/gobierno.png)

**Gobierno** (solo administradores) tiene tres pestañas.

**Usuarios.** Alta, rol y *atributos*. Un atributo es un dato de la persona —por
ejemplo `region_id = 3`— que las políticas usan para filtrar.

**Seguridad por fila.** Una política es una condición que se añade a **todas** las
consultas de quien le aplica:

```
entidad:   cat_sucursal
predicado: region_id = {{ usuario.region_id }}
aplica a:  lector
```

Tres cosas que conviene saber:

- El filtro **no se puede quitar** desde el tablero: se inyecta en el SQL.
- **También filtra el total.** Aunque no desglose por sucursal, la cifra viene
  filtrada. Si no fuera así, el gran total delataría lo que la persona no ve.
- **Falla cerrado**: si a alguien le falta el atributo que la política necesita, no
  ve nada en vez de verlo todo.

**Simulador.** «Ver como» otro usuario, sin su contraseña. Muestra qué políticas le
aplican, con qué valores, y qué cifras le salen. Es la única forma de que un
administrador compruebe una política, porque a él no le aplican.

**Auditoría.** Quién hizo qué y cuándo: ingresos, ingresos fallidos, consultas,
cargas, cambios de política. **No se puede borrar** — un registro que se puede
limpiar no sirve para lo único que existe.

---

## 9. Avisos cuando algo falla

![Avisos](img/avisos.png)

Un flujo que se rompe de madrugada no se lo cuenta a nadie: los tableros siguen
abriendo, con las cifras del día anterior y sin ninguna señal de que están viejas.

Una **regla de aviso** dice a quién contárselo, por **correo** o por **webhook**
(Teams, Slack). Por defecto cubre todo lo que falle, que es lo que conviene: una
regla por dataset deja sin cubrir justo el que se cree mañana.

- **Prueba la regla** con el botón que está a su lado. Un canal que nadie probó no
  es cobertura, es creer que la hay.
- **Repetición**: una carga rota cada 15 minutos mandaría 96 correos al día y
  conseguiría que se archiven todos. Por eso se manda uno y se callan los
  siguientes durante el tiempo que elijas.
- **También avisa al recuperarse**, que es la otra mitad: si no, nadie sabe si
  sigue roto.

Si el correo no está configurado en el servidor, la propia regla lo dice en rojo.

---

## 10. Preguntas frecuentes

**¿Los datos salen de mi servidor?**
No. No hay telemetría, ni fuentes de un CDN, ni ninguna llamada a internet.

**¿Puedo seguir usando Excel?**
Sí: cualquier widget exporta a Excel o CSV con su contexto.

**Una cifra no cuadra con mi sistema origen. ¿Por dónde empiezo?**
1. **Historial del dataset**: ¿cuándo fue la última carga buena?
2. **Conteo por paso** en la transformación: ¿dónde cambia el número?
3. **SQL a la vista** en el tablero (editores y administradores lo ven).
4. **Auditoría**: ¿alguien cambió el modelo o una política?

**¿Por qué el tablero me pide elegir un camino?**
Porque hay dos formas legítimas de cruzar esas tablas y dan cifras distintas. Elige
la que corresponde a tu pregunta; queda guardada en el tablero y ya no vuelve a
preguntar.

**Cambié el modelo y el tablero sigue igual.**
Es a propósito: el tablero está anclado a una versión. Ábrelo y actualízalo a la
versión nueva cuando quieras.

**¿Cuántos datos aguanta?**
Las pruebas corren sobre 11.5 millones de filas en una laptop, con respuestas por
debajo del segundo. El límite práctico es la memoria del servidor.

**¿Se puede en inglés?**
Hoy no; toda la interfaz está en español. Las traducciones son bienvenidas
([CONTRIBUTING.md](../CONTRIBUTING.md)).
