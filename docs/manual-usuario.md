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

### Cargar no bloquea la pantalla

**Cargar** y **Recargar completo** lanzan la carga y contestan enseguida: puedes
cerrar la ventana, o el navegador. El resultado aparece en el historial de ese
mismo panel, que se actualiza solo mientras corre.

Como los flujos, las cargas **hacen cola**: dos a la vez sobre el mismo origen no
acaban antes. Y **el mismo dataset dos veces a la vez se rechaza** — serían dos
procesos escribiendo los mismos archivos.

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

### Pegar una consulta SQL

**Transformar → Pegar SQL.** Se puede escribir SQL normal contra lo que ya tienes:

```sql
SELECT * FROM SUC_CENTRAL__ventas WHERE anio = 2026
```

El nombre que pongas en el `FROM` se busca entre **lo que existe aquí**: las tablas
del motor, los datasets ya cargados, los resultados de otras transformaciones y las
tablas que llegaron de varias conexiones. No hace falta saber si detrás hay una
tabla o un Parquet particionado.

⚠️ **Tiene que existir aquí, no en la base de la que salieron los datos.** Una tabla
de tu MySQL o de tu Pervasive no se puede nombrar en una consulta hasta que la hayas
traído como dataset. Si el nombre no existe, la pantalla lo dice y sugiere el más
parecido, en vez de dejarte con un error del motor.

Dos botones: **Convertir a pasos** la traduce a la vista visual —y si algo no se
puede representar, dice exactamente qué—, y **Usar como SQL** la deja tal cual.

### Flujos

![Pantalla de flujos](img/flujos.png)

Un flujo es «cada día a las 6, carga estas tablas y **luego** recalcula estas
transformaciones». Los pasos van en orden y **si uno falla, los siguientes no
corren**: seguir recalculando sobre datos que no se cargaron produce un número que
parece fresco y no lo es.

En la lista de la izquierda, **lo que ya está en el flujo lleva una palomita** y
el título dice cuántas van («12 / 35»). Con cuarenta sucursales por veintiocho
tablas esa lista es de mil renglones: hay un filtro por nombre y una casilla
*Solo las que faltan* para no ir contando a ojo.

El botón **Ordenar solo** propone el orden correcto leyendo de qué lee cada
transformación. Es una propuesta, no un cambio automático.

⚠️ Un dataset con horario propio que además es paso de un flujo **se carga dos
veces**. A veces es lo que se quiere; conviene saberlo.

#### Encadenar flujos: que uno empiece cuando el otro acabe

Un flujo también puede ser **un paso de otro**. En la lista de flujos, el **+**
que aparece al pasar por encima lo pone como paso del que estás editando.

Es la respuesta a «primero la sucursal A, y cuando termine, la B». Con horarios no
se puede decir: no sabes cuánto va a tardar cada una, y cuarenta crones a las 6:00
no las ponen en fila — las ponen a pelearse por el mismo Pervasive. Un flujo
maestro que llame a los cuarenta sí lo dice exacto, y lleva **un solo horario**.

Cada eslabón corre entero, con **sus** reintentos y **su** regla al fallar, y deja
su propia entrada en su propio historial: en el maestro ves «hijo_a · 28 pasos ·
1,204,331 filas», y para saber cuál de esos 28 falló abres el hijo. Si un hijo
falla, el maestro se detiene igual que con cualquier otro paso.

Dos cosas que no se pueden hacer, y se avisan al guardar: que un flujo **se llame
a sí mismo**, y que dos flujos se llamen **en círculo**. Eso no daría un error
visible — daría un servidor dando vueltas de madrugada sin nadie mirando.

*Ordenar solo* no toca los pasos de tipo flujo: desde fuera no se puede saber qué
trae dentro cada uno.

**Se ve de dónde viene cada cosa.** En Tareas, un flujo al que llama un maestro ya
no dice «a mano» —era falso—: dice *dentro de «EXTRACTOR_ALL»*, y debajo del nombre
*lo llama «EXTRACTOR_ALL»*. Si además tiene horario propio, la columna dice las dos
cosas, porque entonces corre dos veces. En su historial, esas corridas aparecen como
*desde «EXTRACTOR_ALL»* en vez de *manual*, así que se puede reconstruir quién
disparó qué. Y el filtro *Sin horario* ya no los acusa: sí corren solos.

#### El horario se elige por partes, no en cron

Se elige **cada cuánto** (cada hora, todos los días, de lunes a viernes o a sábado,
un día de la semana, un día del mes), **a qué hora** en a. m./p. m., y **en qué
zona**. El cron se escribe solo y queda a la vista; si escribes ahí algo que no
encaja en esas formas —`*/15 * * * *`, por ejemplo— el selector se pone en
*Avanzado* en vez de mentir sobre lo que hay guardado.

La **zona** antes estaba fija en `America/Mexico_City`: era el valor por omisión de
la base de datos, no una elección. Ahora se elige de una lista con las once de
México por su nombre de a pie —Cancún, Hermosillo, Tijuana…— y el resto del mundo
debajo; un horario nuevo arranca en la zona de **tu navegador**, y si la guardada es
otra, la pantalla te dice cuál es la tuya. Importa: «las 6:00» en Cancún y en
Tijuana son tres horas de diferencia.

⚠️ El día del mes llega hasta **28** a propósito. Un `30` o un `31` se salta
febrero, y una carga que no corre un mes al año es de las que nadie nota.

#### Detener una cadena que ya arrancó

El botón **Detener** —en Flujos, junto al nombre, y también en el aviso de Tareas—
para un flujo que ya va corriendo.

**No corta la tabla en curso.** La que se está trayendo se termina, y los pasos que
faltan quedan como *detenidos*. Eso no es prudencia de más: el destino de una carga
**se borra antes de escribir**, así que una recarga completa cortada en el momento
justo dejaría el dataset **vacío**. Esperar la tabla en curso son minutos;
recuperar un dataset vacío, no.

En un maestro, detenerlo detiene también al hijo que esté corriendo —termina su tabla
y para—, y los hijos que faltaban no se lanzan.

La corrida queda como **detenido**, no como *falló*: en gris, no en rojo, y **sin
mandar el aviso de fallo**. Un correo de alarma por algo que acabas de hacer tú es la
forma de que esos correos se dejen de leer. En Tareas hay un filtro *Detenidos*.

#### Continuar donde se quedó

En el historial del flujo, una corrida **detenida o fallida** trae un botón
**Continuar**, con lo que va a hacer escrito al lado: *salta 19 · corre 19 · lo hecho
tiene 12 minutos*.

Continuar **se salta los pasos que ya salieron bien** y corre los demás. Los pasos
saltados aparecen como *ya estaba*, que no es lo mismo que *éxito* — el historial
tiene que poder decir cuál de las dos cosas fue.

Sirve igual para lo que **falló**, y ese es el caso frecuente: la sucursal 20 estaba
apagada a las 6, los pasos 1–19 salieron bien y del 21 al 38 quedaron omitidos.
Continuar arranca en el 20 en vez de volver a traer las 38.

Tres cosas que conviene entender:

- **Las transformaciones se rehacen siempre**, aunque hubieran salido bien. Continuar
  mezcla dos momentos —lo traído a la 1 y lo traído a las 6—; para cuarenta sucursales
  independientes eso da igual, pero una transformación que ya corrió con los datos de
  la 1 se quedaría vieja mientras sus orígenes se actualizan. Eso es justo el número
  que parece fresco y no lo es. Rehacerla cuesta poco: lee Parquet local.
- **La antigüedad se dice, no se prohíbe.** Si lo completado tiene tres días, la
  pantalla lo dice y tú decides. No hay un límite en horas porque cualquier número
  ahí sería inventado.
- **Los pasos se reconocen por lo que son, no por su número.** Si editas el flujo
  mientras está pausado, continuar sigue saltándose las tablas correctas, corre las
  nuevas, y te avisa de las que estaban en esa corrida y ya no están en el flujo.

Una corrida solo se puede continuar **una vez**: la que la continuó queda anotada
(*continúa #41*), y un segundo intento se rechaza diciendo cuál ya la retomó. Si de
verdad hay que repetirlo todo, se ejecuta el flujo completo.

⚠️ **Una carga suelta no se puede detener.** No tiene pasos donde pararse: o termina,
o se corta a la mitad. La pantalla lo dice en vez de ofrecer un botón que no
funcionaría.

#### Reintentos

Con cuarenta sucursales, que una esté apagada a las 6 de la mañana pasa seguido —
y a los dos minutos ya no lo está. Cada flujo dice **cuántas veces se reintenta
un paso** antes de darlo por fallido, y cuánto espera entre intentos.

Por omisión son **cero**, a propósito: reintentar sin que nadie lo pida esconde
un origen que va mal, y la primera vez que algo falla hay que verlo. Súbelo
cuando sepas que ese origen se cae a ratos.

Un éxito al tercer intento **no es lo mismo** que un éxito: el historial dice
cuántos intentos hicieron falta. Si un paso empieza a necesitar tres cada noche,
el problema no es el reintento.

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

Aquí no se edita nada: **Abrir** lleva a Flujos o a Conexiones **con esa tarea ya abierta** — no hay que volver a buscarla entre las demás. **Ejecutar** lanza un flujo a mano.

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

Mientras corre **se ve por dónde va**: el paso en curso queda marcado como
*trayendo…*, los que ya acabaron enseñan sus filas y su tiempo, y arriba dice
«va por el paso 7 de 28». Se actualiza solo, sin recargar.

Arriba de la tabla aparece una barra con lo que corre y lo que espera turno; de
la cola se puede sacar algo que **todavía no empezó**. Lo que ya arrancó no se
corta: a mitad de una ingesta, cortar deja el destino a medias.

**El mismo flujo dos veces a la vez se rechaza**, y eso no se pregunta: serían
dos procesos escribiendo los mismos archivos.

### Etiquetas: de qué sucursal viene cada fila

**Conexiones → Etiquetas.**

Cuarenta agencias con el mismo sistema dan cuarenta veces la misma tabla. Una vez
juntas, nada dice de cuál venía cada fila — y ese dato no está en el origen,
porque allá cada base es «la base».

Una etiqueta es una **constante de la conexión** que sale como **columna** al leer
cualquiera de sus datasets: `id_sucursal = 3` en una, `= 5` en otra. Es el
equivalente exacto de la variable por sucursal de un script de Qlik.

Se editan **todas juntas**, en una tabla de conexiones × etiquetas: ir una por una
cuarenta veces es justo el trabajo que esto quita. La flecha ↓ copia el primer
valor a las vacías, para las etiquetas que casi siempre son la misma (la marca,
el país). Si dos conexiones acaban con el mismo valor, la celda se marca en
ámbar: casi siempre es un dedazo.

**No se escriben en los archivos.** Se agregan al leer, así que corregir un
número no obliga a volver a extraer nada.

> Si una etiqueta se llama igual que una columna de la tabla, la transformación
> se detiene y lo dice. Cámbiale el nombre a la etiqueta.

### La misma tabla de todas las conexiones

En **Transformar**, la lista de orígenes tiene un apartado *La misma tabla en
varias conexiones*: eliges `Funcionarios` una vez y se apilan las cuarenta, cada
una con las etiquetas de su conexión. No hay que enumerar cuarenta datasets ni
acordarse de agregar el cuarenta y uno cuando abra una agencia nueva.

- Se apila **por nombre de columna**: una sucursal con una columna de más —o de
  menos— no tumba a las otras treinta y nueve. Lo que falte llega en nulo.
- Si a alguna le faltan datos, **se detiene y la nombra**. Devolver un total al
  que le faltan sucursales sin que nadie lo note hace más daño que un fallo.

El contador `38/40` de al lado dice cuántas están cargadas.

Con eso, el `If(...)` de tu script de Qlik es una **columna calculada** y la
variable de sucursal es la etiqueta:

```sql
CASE
  WHEN LEFT("Nm Funcionario", 3) = 'HU-'  THEN 3
  WHEN LEFT("Nm Funcionario", 4) = 'PTO-' THEN 5
  WHEN LEFT("Nm Funcionario", 3) = 'VW-'  THEN 1
  ELSE id_sucursal
END
```

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

### Cambiar el nombre

El nombre no es solo una etiqueta: es la **carpeta en disco** donde vive el resultado
y el nombre con el que **otras transformaciones lo leen**. Aun así se puede cambiar.

Escribe el nombre nuevo en el cuadro de arriba y aparece un botón **Renombrar**. Al
pulsarlo se mueven los datos y se arreglan solas las transformaciones que la leían;
después la pantalla te dice exactamente qué se tocó.

Lo que no se toca, a propósito:

- **Las versiones del modelo.** Son instantáneas que no se reescriben, para que un
  tablero publicado no cambie de significado porque alguien renombró algo. Si alguna
  nombra esa tabla, **no se renombra** y se te dice qué modelo es. La salida es sacar
  esa entidad del modelo, o crear otra transformación con el nombre nuevo.
- **El alias de los orígenes.** Es el nombre con el que tu consulta o tu paso de unir
  la llaman por dentro; cambiarlo rompería el SQL que escribiste.

Un nombre que ya use otra transformación o un dataset se rechaza: los dos escribirían
en el mismo sitio. Y renombrar **no** lo hace el botón *Guardar* — guardar cambia qué
calcula, renombrar mueve archivos, y son dos cosas distintas.

### Proyectos y secciones

Una transformación sola está bien para una cosa suelta. Cuando son dieciocho que van
juntas —limpiar series, armar el calendario, calcular los hechos de venta, los de
servicio— tenerlas sueltas en una lista plana no dice qué va con qué, y con cuarenta
sucursales deja de ser manejable.

Para eso está el **proyecto**: un grupo de transformaciones que corren en orden, con
un solo horario. Es lo mismo que un script con secciones.

```
▾ PROYECTOS                              1
  ▾ TRANSFORMADOR_VENTAS              4    ▶
      éxito  tramo desde 3   8/8/2026, 6:04 a.m.
      1 ● series                    int
      2 ● calendario                int
      3 ● hechos_venta          469,985
      4 ● hechos_servicio       128,400
    + Sección      Borrar proyecto
▾ SIN PROYECTO                           2
```

- **Crear uno**: escribe el nombre abajo de la lista y pulsa *Crear*. Nace vacío.
- **Meterle transformaciones**: despliega el proyecto y pulsa el `+` de cualquiera de
  las de *Sin proyecto*. O pulsa *+ Sección* para crear una nueva ya dentro.
- **Ordenarlas**: con `↑` y `↓`. **El número que se ve es el paso en el que corre.**
- **Sacar una**: la `✕` la deja suelta. **No la borra** y no toca sus datos: sacar
  algo de una carpeta no es tirarlo.

El punto de color de cada sección dice cómo salió la última vez, así que de un golpe
se ve cuál de las dieciocho es la que rompe.

Borrar el proyecto borra el orden y el horario. **Las secciones quedan sueltas, con
sus datos**: pueden estar alimentando un tablero.

Lo que ya tenías no cambia. Las transformaciones de antes siguen donde estaban, ahora
bajo *Sin proyecto*, y se mueven cuando tú decidas dónde van.

#### Ejecutar solo una parte

El `▶` del proyecto corre las secciones en orden, de la primera a la última.

El `▶` de una **sección** corre **de ahí al final**. Es lo que se usa a diario:
cuando estás afinando la sección 12 de dieciocho, rehacer las once anteriores son
veinte minutos de espera por nada.

Las secciones anteriores quedan anotadas como **«no se pidió»** —que no es lo mismo
que «salió bien» ni que «se omitió por un fallo»— y la corrida se marca **«tramo
desde 3»**. Esa marca importa: sin ella, dos secciones en verde de dieciocho se leen
como *el proyecto está al día*, y no lo está. Los datos de las que no se pidieron son
de antes.

Por lo mismo, un tramo que sale bien no manda el correo de «ya se arregló»: lo que
fallaba puede ser justo lo que no se pidió.

#### Secciones intermedias

Marca **intermedia** una sección que es andamiaje: un mapeo de códigos, la tabla de
series, un calendario auxiliar. Su resultado se sigue calculando y guardando —es lo
que permite ejecutarla sola y ver sus filas— pero **solo se ofrece como origen dentro
de su propio proyecto**, y no aparece en las listas de datos ni se puede usar en un
modelo.

Con dieciocho secciones por sucursal, sin esta marca el catálogo se llena de tablas
de andamiaje que nadie va a graficar.

#### Un proyecto dentro de un flujo

Por dentro, un proyecto **es** un flujo al que solo se le pueden poner
transformaciones. De ahí que tenga horario propio, salga en *Tareas* y se detenga con
el mismo botón que todo lo demás.

Y de ahí también que un flujo pueda llamarlo como un paso, que es el caso útil: el
maestro trae las cuarenta sucursales y después llama al proyecto que las transforma.
En la pantalla de *Flujos*, los proyectos salen en su propia lista y solo se pueden
encadenar — editarlos se hace aquí, donde sus pasos son secciones.

### Qué es cada grupo de orígenes

No son cuatro vistas de lo mismo: de cada grupo sale un origen distinto, y eso cambia
lo que la transformación acaba leyendo.

| Grupo | Qué es | Cómo se lee |
|---|---|---|
| **Tablas del motor** | Tablas que viven dentro del archivo del motor analítico | Directo, como tabla |
| **Datos cargados** | Los datasets que trajo una conexión. No están en el motor: cada uno es un directorio de Parquet | Como Parquet, **más las etiquetas de su conexión** |
| **La misma tabla en varias conexiones** | Esa tabla traída por todas las conexiones que la tienen, apilada | Como arriba, pero de todas a la vez |
| **Secciones de este proyecto** / **Resultados de otras** | Lo que produjo otra transformación | Como Parquet |

Lo que de verdad los separa no es el formato, son tres cosas prácticas:

1. **Las etiquetas de la conexión.** Al leer un dataset se le añaden como columnas las
   constantes de su conexión —`id_sucursal`, la marca, lo que hayas puesto—. Se añaden
   *al leer*, no se escriben en el Parquet, para que renumerar una sucursal no obligue
   a volver a extraer cuarenta tablas. Una tabla del motor no trae nada de eso.
2. **Tienen actualización detrás.** Un dataset lo refresca una carga, y una carga se
   programa en *Flujos*. Una tabla del motor no tiene nada que la refresque.
3. **Apilar sucursales sólo funciona con datasets.** El grupo «La misma tabla en varias
   conexiones» —el que sustituye al bucle sobre sucursales del script de Qlik— se
   construye sobre ellos.

Lo que tú cargas y lo que tú transformas **nunca** aparece en «Tablas del motor». Si
ves ahí un nombre tuyo, es un fallo: repórtalo.

### Encontrar algo entre mil orígenes

Los orígenes están agrupados y **cada grupo se pliega** pulsando su título, con su
contador al lado. Lo que no uses se quita de en medio una vez y se queda quitado — se
recuerda por pantalla y por navegador.

Arriba hay un **buscador** que no se desplaza. Escribe trozos, en el orden que sea:

```
oriente presu     →  SUC_ORIENTE__presupuesto
orcamento         →  SUC_SUR__Orçamento_Produtos
```

No hace falta acertar los acentos, las mayúsculas ni los guiones bajos. La cabecera te
dice cuántos coinciden («23 de 1,065»), y si un grupo estaba plegado **se abre solo**
mientras haya resultados dentro; al limpiar la búsqueda vuelve a plegarse.

El mismo buscador está en *Proyectos*, y ahí un proyecto aparece si coincide su nombre
**o el de una de sus secciones**: buscar `hechos_venta` te lleva al proyecto que la
tiene sin abrirlos uno por uno.

> Si buscas algo y no aparece, acuérdate de que aquí solo está **lo que ya se trajo**.
> Una tabla de tu MySQL o de Pervasive no aparece hasta que existe como dataset.

### El panel de la izquierda

Con cuarenta sucursales, el nombre de un dataset es el de la conexión más el de
la tabla —`SUC_SUR__Orcamento_Produtos`— y no cabe. **Arrastra el borde
derecho del panel** para ensancharlo; doble clic lo devuelve a su ancho normal.
El ancho se recuerda por pantalla.

Y **cada sección se pliega** pulsando su título. Plegar las que no estás usando
le da su alto a la que sí.

---

## 6. El modelo: cómo se cruzan las tablas

![El lienzo del modelo](img/modelo.png)

El modelo dice qué es cada tabla (dimensión o hecho), cómo se relacionan y qué
métricas existen. Se dibuja arrastrando de un campo a otro.

### Crear uno

**Modelo → + Nuevo modelo.** Se pide el nombre y **la primera tabla**, en el mismo
paso: un modelo sin ninguna entidad no se puede guardar, así que un «crear» que lo
dejara vacío estaría prometiendo algo que no se cumple. Lo demás —más tablas, las
relaciones, las métricas— se arma en el lienzo.

En el desplegable de tablas sale **todo lo que se puede modelar**, en tres grupos:

| Grupo | Qué es |
|---|---|
| **Tablas del motor** | Las que viven dentro del archivo analítico |
| **Datos cargados** | Las tablas que trajiste de tus orígenes |
| **Resultados de transformaciones** | Lo que produjeron tus transformaciones |

Los dos últimos grupos son Parquet, no tablas, y aun así se usan igual: se les pone
una vista encima al consultarlos. Dos consecuencias prácticas: **un Parquet no
declara clave primaria**, así que hay que marcar cuál es en la lista de columnas —o
dejarla sin clave, y el diagnóstico avisará de que falta el grano—; y **los datos
frescos se ven solos**, sin reiniciar nada, porque la vista se resuelve en cada
consulta.

Si un resultado tuyo se llama igual que una tabla del motor, **gana la del motor**:
es lo que ya estaban leyendo los tableros. Las secciones marcadas como
**intermedias** no aparecen aquí; son andamiaje de una transformación.

**Las métricas se definen una vez.** «Utilidad» es una fórmula que vive en el
modelo, no algo que cada quien reescribe en su tablero. Es lo que hace que dos
personas no tengan dos utilidades distintas.

### Dividir una cifra de un hecho entre la de otro

El porcentaje de logro es lo vendido entre lo presupuestado. Lo vendido está en las
facturas; el presupuesto, en otra tabla y a otro grano —una fila por sucursal y mes,
no una por factura—. Una métrica normal no puede escribir eso: se agrega desde **un**
hecho, y desde las facturas la columna del objetivo no existe.

Para eso está la última opción de **Calcula desde**: **· otras métricas
(compuesta)**. Una compuesta no sale de ninguna tabla. Combina métricas que ya
existen, y puede nombrar cualquiera del modelo:

```
DIVIDIR([Unidades Vendidas], [Objetivo de Ventas], 0)
```

Lo que la hace correcta es **cuándo** se calcula: cada hecho agrega primero por su
lado, y la división se hace después, sobre las cifras ya sumadas. Si en vez de eso se
unieran las dos tablas antes de sumar, el objetivo del mes se repetiría una vez por
factura y saldría multiplicado por cuatrocientos. El número tendría buena pinta y
estaría mal, que es la peor combinación.

Dos cosas no se pueden escribir en una compuesta, y las dos por la misma razón:

- **Columnas.** `DIVIDIR(unidades, [Objetivo])` no vale: no hay ninguna tabla de la
  cual sacar `unidades`. Si esa cuenta hace falta, se hace en una métrica del hecho
  donde vive la columna y aquí se nombra el resultado.
- **`SUMA`, `PROMEDIO`, `CONTAR`…** Lo que recibe ya viene sumado; volver a sumarlo
  sería agrupar dos veces sobre el mismo grupo.

Las dos te las dice al **guardar**, no en el primer tablero que la use.

Una compuesta puede apoyarse en otra —`SI([% Logro] > 1, 1, [% Logro])`— y si dos se
llaman entre sí sin final, se avisa en vez de colgarse. Y pedirla en un tablero
devuelve **una** columna: las métricas de las que depende se calculan por dentro,
pero no se enseñan.

En el panel aparecen bajo **Compuestas**, con el punto hueco: los puntos rellenos
marcan algo que existe —una tabla—, y esto es un cálculo encima de lo que existe.

### Acotar por una columna que está en otra tabla

«Las ventas cuyo canal es digital» tiene un problema: el canal no está en la
factura, está en el catálogo de orígenes. Se escribe poniéndole delante el nombre de
la tabla:

```
CALCULAR(SUMA(Unidades), DIM_ORIGEN_VENTA.categoria_canal = 'Digital')
```

El autocompletado ofrece esas columnas ya con su prefijo, detrás de las del propio
hecho.

**El prefijo es obligatorio**, y no por gusto: `id_origen` está en la factura y en el
catálogo, y si se pudiera escribir suelto habría que adivinar de cuál se hablaba.
Adivinar es lo que este motor no hace.

Lo que ocurre por dentro es que esa tabla se une **antes de sumar**, dentro del
cálculo del hecho. Acotar después no se puede: para entonces el hecho ya está sumado
y ya no hay filas que dejar fuera.

Y se une **por la izquierda**, que es lo que hace que las demás métricas del hecho no
se enteren. Una factura con el origen vacío, o con un código que no está en el
catálogo, sigue contando en el total: sólo queda fuera de la métrica acotada, que es
lo único que se pidió acotar. Con una unión normal ese total habría bajado sin que
nadie lo pidiera.

Si el hecho no tiene camino hasta esa tabla —o tiene dos, y entonces habría dos
cifras posibles—, lo dice el **diagnóstico del modelo**. Ahí y no en el tablero de
quien sólo estaba mirando una cifra.

### Cuando una tabla se une por más de una fecha

Un contacto tiene fecha de primera visita, de asignación a sucursal y de prueba de
manejo. Las tres apuntan al calendario y las tres son ciertas, pero **cada
indicador cuenta por la suya**: el tráfico de piso por la visita, los leads
asignados por la asignación.

Sólo una relación puede estar **activa**. Si estuvieran dos, cada consulta tendría
dos caminos igual de válidos hacia el calendario y el total dependería de cuál
eligiera el compilador — que es exactamente lo que este motor no hace.

Así que se dibujan todas y se dejan **inactivas** menos una. Después, en el editor
de cada métrica, aparece **Se une por** con una casilla por cada relación inactiva
que toque su hecho:

```
Se une por      sin marcar nada, por la relación activa
  ☐ fecha_1ra_visita_piso      → dim_calendario.fecha
  ☑ fecha_asignacion_sucursal  → dim_calendario.fecha
  ☐ fecha_prueba_de_manejo     → dim_calendario.fecha
```

Marcar una la enciende **para esa métrica y sólo para esa**, y de paso apaga la que
estuviera activa entre esas dos tablas — si no, volverían a quedar dos caminos.
Dos métricas del mismo hecho pueden ir cada una por su fecha y salir juntas en el
mismo tablero.

Al guardar se comprueba que la relación exista y que toque al hecho de la métrica.
Elegir una que no lo toca no daría error al calcular: la cifra saldría por la
relación activa como si nada, y eso es peor que un error.

### Comparar contra otro mes

«Cuánto crecí respecto al mes pasado» se escribe con cuatro funciones, y las cuatro
van dentro de una **compuesta**:

| | |
|---|---|
| `MESANTERIOR([Unidades])` | la misma cifra, del mes de antes |
| `MISMOMESANIOANTERIOR([Unidades])` | del mismo mes del año pasado |
| `ACUMANIO([Unidades])` | lo que va del año, desde enero |
| `PROMEDIOMESES([Unidades], 3)` | promedio de los 3 meses anteriores, sin contar el de la fila |

Así queda el crecimiento mensual:

```
DIVIDIR([Unidades] - MESANTERIOR([Unidades]), MESANTERIOR([Unidades]), 0)
```

**Antes hay que decir cuál es la columna del mes.** En la tabla de campos de la
entidad del calendario hay una casilla **mes**: se marca la columna que nombra un
mes concreto —`Periodo_YYYYMM`, o una fecha—. **No** se marca un `Mes` de 1 a 12:
ese se repite todos los años, y correrlo un mes hacia atrás no significa nada. Por
eso la casilla sólo se puede marcar donde el tipo lo permite.

#### ¿De qué mes se compara?

Hay dos formas, y no hace falta elegir: el motor usa la que corresponda.

**Si la columna del mes está en el desglose**, cada fila es su propio mes y compara
contra el suyo. Es la tabla de «ventas por sucursal y mes».

**Si no está** —una tabla de una fila por sucursal, con «Ventas Mes Anterior» al
lado, que es como se lee un informe de dirección— el mes lo pone el **contexto**: el
que esté filtrado arriba. Es lo que hace Power BI, donde el periodo sale del
segmentador de la página y no de las filas de la tabla. Por dentro el cálculo baja
los meses a una capa escondida —hacen falta, o no habría mes anterior que mirar— y
arriba se queda solo el mes que manda.

Cuál manda: **el último mes que sobreviva a los filtros**. Con un mes filtrado, ese.
Con solo el año filtrado, su último mes. Y **sin ningún filtro de fecha, el último
mes con datos**.

Los filtros valen **estén en la columna que estén**, siempre que sean del calendario:
filtrar Año = 2026 y Nombre del mes = July elige julio de 2026 igual que filtrar la
columna «Año-Mes». Lo que se levanta para poder mirar atrás es la tabla de fechas
entera, no una columna suelta — de otro modo la capa de dentro se quedaría con un solo
mes y la comparación saldría vacía. Por eso las columnas de esos filtros tienen que
ser del **mismo origen** que la columna marcada como mes: un «Año» que venga del hecho
y no del calendario no elige el periodo.

Lo que **no** se puede es filtrar un día: el mes anterior de un día no existe, y
estirarlo al mes entero devolvería las unidades del mes en una fila que pedía un día.
Ahí el widget lo dice y no calcula.

Ese último caso tiene una consecuencia que conviene tener presente: la cifra cambia
en cuanto entre el mes siguiente, sin que nadie toque el informe. Por eso el widget
dice siempre, encima de la tabla, **«Comparado contra 202607»** — para que un número
firmado se pueda fechar. Si quieres que no se mueva, filtra el mes.

Lo único que sigue dando error es que el modelo **no marque ninguna** columna como
mes: entonces no hay contexto del que sacar el periodo, y en vez de repetirte el
total —que parecería una comparación— te lo dice.

Tres cosas que conviene saber, porque son decisiones y no accidentes:

- **Un mes sin datos sale vacío**, no el de dos meses atrás. Si en marzo no se
  facturó, el crecimiento de abril queda en blanco. Es lo correcto: la alternativa
  es enseñar una comparación falsa sin ninguna señal.
- **El promedio de 3 meses divide entre 3**, aunque alguno de esos meses no tenga
  datos. Es lo que hace Power BI, y es a propósito: un mes malo tiene que bajar el
  promedio, no desaparecer del denominador.
- **Lo que no se puede sumar, no se acumula.** El acumulado del año de un conteo de
  clientes distintos contaría dos veces a quien compró en enero y en marzo, así que
  se rechaza. Contra un solo mes sí vale.

Una función de tiempo puede ir **dentro de otra**, que es como se escribe el
acumulado del año pasado:

```
MISMOMESANIOANTERIOR(ACUMANIO([Unidades]))
```

Se calcula en dos pasos —primero el acumulado de cada mes, luego el salto de doce—
y da exactamente el acumulado del mismo mes del año anterior.

### Ordenar las métricas: tablas de medidas

Una métrica sale en el panel con su signo **Σ**, así que no se confunde con una
tabla ni con una columna. Y se pueden agrupar en **tablas de medidas**: cajones que
tú inventas —«KPIs de venta», «KPIs de taller»— con **+ Tabla de medidas**. Es lo
mismo que en Power BI, incluido lo importante:

- **No son entidades.** No tienen datos, no se relacionan con nada y no aparecen en
  el lienzo ni en el diagnóstico. Solo ordenan.
- **No cambian ninguna cifra.** En la métrica hay dos campos distintos a propósito:
  **Calcula desde** es el hecho —lo que decide de dónde sale el número— y **Aparece
  en** es el cajón. Mover una métrica de cajón no le toca el resultado.
- Lo que no esté en ningún cajón sigue viéndose **bajo su hecho**, como antes.

Quitar un cajón (`✕`) **no borra sus métricas**: vuelven a verse bajo su hecho.
Cambiarle el nombre (`✎`) arrastra a las suyas con él.

**Cada grupo se pliega** pulsando su cabecera, igual que los grupos de *Transformar*
y *Flujos*: lo que se pulsa es toda la cabecera, no sólo el triángulo. Con cinco
cajones de seis métricas, llegar al último pide atravesar treinta renglones que en
ese momento no te interesan; pliegas el que no estás usando y **se queda plegado**.
Se recuerda por modelo y por cajón, en tu navegador, así que no es un cambio del
modelo: no marca cambios sin guardar ni hay que publicar nada.

### El grano, y por qué conviene comprobarlo

El **grano** son las columnas que *juntas* identifican una fila. En una tabla de
objetivos mensuales son la sucursal y el mes: por separado las dos se repiten —cada
mes vuelven todas las sucursales— y juntas no deberían.

No es la clave primaria. La clave primaria es **una** columna, y es por donde se
une; si declaras como clave primaria una que sí se repite, estás afirmando algo
falso y el motor deja de avisarte cuando una relación duplica filas. Cuando no hay
ninguna columna que valga sola, deja la clave primaria en **(ninguna)** y declara el
grano con las dos.

Las columnas se **eligen de la lista**, no se escriben: cada una queda como una
etiqueta con su × para quitarla, y el desplegable de al lado añade la siguiente. Un
`Fecha_objetivo` con la o minúscula no sería un error de tipografía, sería un grano
que habla de una columna que no existe.

El grano es una afirmación, así que hay un botón **Comprobar** al lado. Cuenta las
filas y las combinaciones distintas:

> No se cumple. 5 080 filas para 40 combinaciones de `sucursal_id`: sobran 5 040.

Vale la pena hacerlo al declararlo y después de cada carga grande. Si un mes se
cargó dos veces, el objetivo queda duplicado y el porcentaje de logro sale a la
mitad **sin que nada falle** — que es la forma de error más cara de encontrar.

Cambiar el grano borra el resultado anterior. Ese cuadro afirma algo de unas columnas
concretas; dejarlo puesto tras quitar una sería afirmar de un grano nuevo lo que se
comprobó del viejo.

### Ver el modelo como texto

La pestaña **YAML** enseña el modelo tal cual se guarda. Cuando tienes trabajo sin
publicar hay **dos**, y conviene tener claro cuál miras:

- **Borrador** — lo que estás armando. Es lo que se abre primero.
- **Publicada vN** — lo que ven los tableros **ahora mismo**.

Si el lienzo tiene cambios que todavía no guardaste, el borrador tampoco los lleva:
guarda primero. El aviso de arriba te lo dice.

Es el texto que hay que pasar cuando alguien te pide «el modelo»: llevar el
publicado cuando lo que trabajaste está en el borrador es enseñar un modelo que no
es el tuyo.

**Y se puede traer un YAML de fuera.** El botón **Importar YAML…** abre un cuadro
donde pegarlo: un modelo escrito a mano, un respaldo, o un juego de métricas
traducido de otra herramienta. Sin eso, meter noventa métricas significaba teclearlas
una por una.

Valen dos cosas:

| Lo que pegas | Qué hace |
|---|---|
| El **modelo completo** — empieza por `modelo:` y lleva `entidades:` | Reemplaza el borrador |
| Un **trozo con sólo `metricas:`** (y `tablas_medidas:` si hace falta) | Se mezcla con lo que ya tienes |

La mezcla es lo normal cuando las tablas ya están dibujadas y lo que llega de fuera
son las métricas. Va **por nombre**: las de igual nombre se sustituyen y las demás se
quedan, así que no desaparece nada que hayas escrito. Al terminar te dice qué hizo:
«96 métricas nuevas, 0 reemplazadas y 1 sin tocar».

En los dos casos se toca el **borrador**, nunca una versión publicada — lo que ven los
tableros no cambia hasta que publiques. Y se revisa igual que si lo hubieras armado
en el lienzo: si una métrica nombra una columna o un hecho que no existe, no entra, y
el error habla de la métrica.

El editor de arriba sigue siendo de sólo lectura. Teclear encima de lo que estás
mirando invita a editar por error la versión publicada; importar es un acto con su
botón, que dice qué va a reemplazar.

### Ordenar el lienzo

Con más de media docena de tablas, colocarlas a mano deja de ser posible. El botón
**⊞** de los controles del lienzo las recoloca: **hechos en la primera columna**,
las dimensiones que tocan un hecho en la siguiente, las de copo de nieve después, y
lo que no se relaciona con nada al final, apartado —verlo apartado es información—.
Dentro de cada columna cada tabla se pone a la altura media de aquellas con las que
se relaciona, que es lo que quita la mayoría de los cruces.

Ninguna tabla queda encima de otra y ninguna línea pasa por encima de una tabla.

Es un botón y no algo automático a propósito: la disposición se guarda con el modelo,
y mover de sitio un lienzo que alguien ordenó a mano sin que lo haya pedido es peor
que dejarlo desordenado. Se deshace con **un** «Deshacer».

Y para seguir una relación concreta en un modelo con muchas: **pasa el ratón por una
tabla** y se apagan todas las líneas que no son suyas.

### Tablas con muchas columnas

Cada tabla del lienzo enseña **todas** sus columnas, para que puedas arrastrar desde
cualquiera de ellas: una relación se crea arrastrando de un campo a otro, así que un
campo que no se ve es un campo por el que no se puede unir.

Un catálogo de veintidós columnas ocupa sitio, claro. Para quitarlo de en medio sin
perderlo, el botón de su cabecera la deja en **solo los campos unidos** —los de sus
relaciones y su clave— y te dice cuántos esconde: `+9`. Pulsándolo otra vez vuelven
todos. Los conectores de los campos que quedan siguen funcionando igual, así que las
relaciones que ya tenía se ven perfectamente.

Compactar una tabla **no cambia el modelo**: no marca cambios sin guardar, no sale en
el YAML y no hay que publicar nada. Es como el ancho de los paneles — se guarda en tu
navegador, por modelo, y cada quien la ve como la dejó.

### Los paneles se ensanchan

Los dos paneles laterales —el de la izquierda y el de la derecha— se ensanchan
**arrastrando su borde**, y con **doble clic** vuelven a su ancho normal. El ancho se
recuerda por pantalla y en tu navegador: es una preferencia de este monitor, no algo
que viaje con tu usuario.

Merece la pena para el de la derecha cuando inspeccionas una tabla de muchas columnas:
en su ancho normal los nombres salen cortados, y ahí no se distingue
`Nombre_Conexion` de `Nombre_DB` — que es lo que necesitas leer para elegir por dónde
unirla.

### Cuando cambias la transformación por debajo

El modelo guarda su propia copia de las columnas, tomada el día que agregaste la
tabla. Es a propósito: así el modelo se abre y compila sin tocar la base. El precio es
que si luego cambias la transformación, esa copia se queda vieja — y el inspector de
la entidad te lo dice en un aviso amarillo en cuanto la seleccionas.

El aviso separa tres cosas, porque no se arreglan igual:

| Lo que pasó | Qué hacer |
|---|---|
| Cambió el tipo de una columna, o hay columnas nuevas | **Actualizar columnas desde el origen**. Tu trabajo se conserva: el rol, la etiqueta, «ver» y «PII» no se vuelven a adivinar |
| Una columna ya no está **y no la usa nadie** | Se quita al actualizar, sin más |
| Una columna ya no está **y algo la usa** | El aviso te dice exactamente qué la usa —qué relación, qué métrica, si es la clave o está en el grano— y lo decides tú |

**Si lo que hiciste fue renombrar**, que es el caso normal, díselo: cada columna que
desapareció tiene al lado un desplegable y un botón **«Es la misma»**. Al confirmarlo,
el nombre nuevo se lleva consigo el rol, la etiqueta, «ver», «PII», «única», la clave
primaria, el grano y **las relaciones**. Si hay una sola columna que desapareció y una
sola candidata, te la propone ya elegida.

Lo único que no se arregla solo es la **fórmula de una métrica** que nombre la columna
vieja. Ahí el nombre es texto dentro de una fórmula que puede tener variables, y
cambiarlo por ti podría pisar una `VAR` que se llame igual. Astrolabio te dice qué
métricas hay que revisar, y las revisas tú.

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

### El estante: carpetas

Los tableros se guardan en **carpetas**, y en la columna de la izquierda están todas
con cuántos tienen dentro, más «Todos» y «Sin carpeta». El buscador de arriba busca
por el nombre del tablero, por su carpeta y por su modelo.

La carpeta se escribe al crear el tablero, y se cambia después en **Editar → Tablero →
Carpeta**. Se teclea: si ya existe, se ofrece. No hay que crear la carpeta antes ni
borrarla después — una carpeta existe mientras haya algo dentro.

> **Una carpeta solo ordena. No da ni quita acceso a nada.**
>
> Esto es lo único importante que hay que saber de las carpetas. En Qlik un *stream*
> es a la vez la carpeta y el permiso; aquí no. Quién ve qué lo siguen decidiendo el
> **rol** y si el tablero está **publicado**: un lector no ve un borrador aunque esté
> en una carpeta que se llame «Público», y sí ve uno publicado aunque esté en una que
> se llame «Dirección».
>
> Si hace falta que un tablero lo vean solo unas personas, eso se hace con los roles y
> las políticas por fila (capítulo 8), no metiéndolo en una carpeta.

Mover un tablero de carpeta **no le quita la certificación**, y tampoco renombrarlo:
ninguna de las dos cosas toca una cifra. Lo que sí quita el sello es cambiar lo que el
tablero mide.

Cada widget lleva dimensiones (por qué se desglosa) y métricas (qué se mide), y
salen de listas del modelo. Cuando la lista es larga —noventa y seis métricas— tiene
un buscador arriba: busca por el nombre que se ve, por el técnico y por la tabla, sin
acentos y por trozos en cualquier orden, así que `logro unid` encuentra
«% Logro Unidades». Lo que ya está elegido no desaparece al buscar; si lo hiciera, no
habría forma de quitarlo sin acordarse de cómo se llamaba.

### Semáforos: la flecha verde o roja

En las propiedades de una columna, **Semáforo → Poner semáforo**. Se compara contra
un **objetivo fijo** (45 días, 100 %, 0) o contra **otra columna del mismo widget**
(lo facturado contra su objetivo, el mes contra el anterior), y hay que decir **hacia
dónde está bien**:

- *Más es mejor* — un logro, unas unidades.
- *Menos es mejor* — los días que un auto lleva en inventario, un gasto.

Esa segunda opción es la razón de que la dirección se declare en vez de adivinarse.
«Más es mejor» no vale para todo: 224 días en inventario contra un objetivo de 45 es
el peor número de la tabla, y un semáforo que pintara verde hacia arriba lo pondría en
verde. Si la columna es un porcentaje, el objetivo se escribe **como se ve** —`100`,
no `1`—.

Se puede mostrar la flecha, el fondo, o los dos. **Siempre hay flecha además de
color**: uno de cada doce hombres no distingue verde de rojo, y una cifra que solo se
lee por el color no se lee.

Un caso que conviene conocer, porque es el que más engaña: **una sucursal con objetivo
y sin ninguna venta**. No trae cifra —el hecho no tiene filas para ella—, así que no
hay nada que comparar. Sale en **ámbar con `?`**, no en verde ni en rojo, y al pasar
el ratón se explica. Dejarla sin marcar la haría parecer neutral justo cuando es el
peor caso de la tabla, y pintarla como cero sería que la pantalla decidiera que «sin
filas» significa «cero» — que es una decisión de la métrica, no del semáforo.

### La tabla dinámica: la matriz con los meses a lo ancho

**Tipo → Tabla dinámica.** Lleva **dos desgloses**: uno se queda en las filas y otro
se abre en columnas, que es la matriz de «inventario por modelo y mes». Cuál se abre
se elige en **Se abre en columnas**; los demás se quedan a la izquierda, en el orden
de la lista de columnas de desglose.

Con una métrica, cada celda es esa cifra. Con varias, cada valor de columna se abre en
tantas subcolumnas como métricas, y la cabecera queda en dos pisos. A la derecha
aparece una columna **Total** por fila, que se puede quitar.

**Una celda vacía se queda en blanco, no en cero.** No es lo mismo «ese mes no hubo
ninguno» que «no hay dato para ese mes»: un cero afirma algo que el dato no dice.

Dos cosas que conviene saber:

- **El orden de las columnas.** Si los valores son números —el mes como número,
  año-mes— van en orden numérico. Si son texto, van en el orden en que el modelo los
  devuelve, que es alfabético: un mes guardado como nombre saldría abril, agosto,
  diciembre. Eso no es un orden, es un error que parece un orden, así que la tabla lo
  avisa arriba y te dice que abras en columnas una columna numérica.
- **El cruce se hace en el navegador**, sobre la misma consulta plana que pide
  cualquier otro widget. Es lo que hace que una tabla dinámica pase por la misma
  seguridad por fila, el mismo anclaje de versión y el mismo Excel que todo lo demás,
  en vez de ser el widget especial que trae sus datos por otro lado. El **máximo de
  filas** se aplica a esas filas planas: si lo alcanzas, faltan combinaciones.

### El catálogo: las métricas por la tabla de la que salen

Debajo de **Métricas** y de **Dimensiones**, lo que se puede elegir viene agrupado
por la tabla de la que sale —`fact_venta`, `fact_servicio`, `fact_refaccion`…— y cada
grupo se abre y se cierra pulsando su nombre. Con casi cien métricas, una lista
plana obliga a atravesar las de ventas para llegar a las de refacciones y no deja ver de
un golpe qué trae cada tabla.

Tres detalles que importan:

- La cabecera de un grupo cerrado **sigue diciendo cuántas hay dentro y cuántas usa
  este widget** («2 de 12»). Un grupo cerrado que esconde una métrica en uso sería
  una trampa.
- Nacen abiertos los grupos que aportan algo a este widget, y cerrados los demás. En
  cuanto abres o cierras uno a mano, se acuerda —en este navegador— y manda tu
  decisión.
- **Al buscar se abren todos**, y lo ya elegido no desaparece nunca de la lista
  aunque no coincida con lo que buscas.

**`compuesta`** no es una tabla: son las métricas calculadas sobre otras métricas.
Por eso va al final y con ese nombre, en vez de mezclada entre las tablas como si
existiera un origen que se llama así.

### Las columnas de un widget: orden y propiedades

Debajo del título, **Columnas de cifras** lista lo elegido **en el orden en que
sale**, numerado, con flechas `↑` y `↓` para subir y bajar. Ese es el orden de las
columnas de la tabla: si quieres «Unidades Vendidas» antes de «Objetivo de Ventas»,
se cambia ahí y se guarda con el tablero. Igual con **Columnas de desglose**, que
son las de la izquierda.

Es una lista aparte del catálogo a propósito: en el catálogo el orden es el del
modelo, y aquí importa otro —el de las columnas de la tabla y de las series del
gráfico—. Mezclarlos obligaría a elegir entre poder buscar y poder ordenar.

Cada columna se abre con `▸` y tiene sus propias propiedades:

- **Etiqueta.** El nombre en *este* widget. En el modelo sigue llamándose igual, que
  es lo que ven los demás tableros: un ajuste de estética no debe cambiarle el
  vocabulario a nadie más.
- **Formato.** Entero, con decimales, moneda o porcentaje. El del modelo viene
  marcado como «(del modelo)», y si lo eliges vuelve a seguir al modelo.
- **Fila de totales** (en las tablas). Suma, promedio o sin total.

Sobre los totales: se ponen solos **suma** en dinero y en conteos, y **sin total** en
porcentajes y en cifras con decimales. No es pereza: la suma de cuarenta porcentajes
no significa nada, y una cifra con decimales casi siempre es un promedio o una razón,
así que sumarla daría un número que parece bueno y no lo es. Se puede forzar la suma
—la pantalla te deja y te dice por qué no deberías—, pero el total correcto de un
logro se calcula con una métrica que divida los dos totales, no sumando los
porcentajes de cada fila.

El total es de **las filas que se trajeron**. Si el widget tiene un máximo de filas y
se alcanzó, es el total de ésas.

### «Faltan filas»

Si un widget alcanza su **Máximo de filas** y había más, aparece una banda ámbar encima
del dato:

> **Faltan filas.** Se alcanzó el máximo de 10 filas y hay más. Lo que se ve es una
> parte, y los totales son los de esa parte. Sube el máximo o filtra para que quepa.

No se puede cerrar: mientras la tabla esté cortada, el aviso está. Una tabla recortada
que no dice que lo está se lee como completa, se suma y se firma, y eso es peor que un
error —un error se ve.

En una **tabla dinámica** el aviso dice algo distinto, porque el motivo es otro: cada
fila de la tabla cuesta tantas filas de datos como columnas abra el cruce. Sube el
máximo, o reduce las columnas filtrando el desglose que se abre.

El «Máximo de filas» siempre significa **filas de la tabla que ves**, también en la
dinámica: el cálculo de cuántas filas de datos hacen falta se hace por dentro.

### Hojas: un tablero es un libro

Un tablero tiene **hojas**, como un libro, y se cambia de una a otra en la barra de
pestañas. Cada hoja tiene su propio espacio: un widget vive en una hoja y las
posiciones son de esa hoja, así que dos hojas no se estorban.

**Las selecciones son del libro, no de la hoja.** Si filtras julio en una hoja y
pasas a la siguiente, sigue en julio. Que cada hoja tuviera su propio filtro es la
forma más cara de leer dos cifras que no se pueden comparar.

En **Editar → Hoja** se le pone nombre, se cambia de sitio en el libro, y se elige el
tamaño del espacio de trabajo:

- **Cabe en la pantalla** (por omisión): la hoja entera se ve de un golpe. El alto se
  reparte entre las filas que pidas, así que no hay que desplazar para saber si hay
  algo más abajo. Un widget que nadie ve es una cifra que nadie revisa.
- **Se desplaza**: la fila mide siempre lo mismo y la página baja. Es para un informe
  largo que se lee de arriba abajo, como una hoja con diez secciones.

**Columnas** y **filas** definen la rejilla — de 12 columnas por omisión, hasta 24.
Con más columnas las cajas se ajustan más fino; con 24 columnas de dos centímetros ya
no se lee nada, y por eso ahí está el tope.

Si pones widgets más abajo de las filas que declara la hoja, la hoja **se desplaza de
todos modos** y te lo dice. Recortar lo que sobra dejaría widgets que no se pueden ni
ver ni alcanzar.

### Filtros asociativos

Al hacer clic en un valor, **todo el tablero se filtra**, y los demás filtros
muestran qué valores siguen siendo posibles con esa selección y cuáles ya no. Es el
comportamiento al que uno se acostumbra en Qlik.

Un widget de tipo **Filtro** lleva los campos que quepan, no uno solo. Nace ancho y
bajo —la barra de arriba de la hoja: Año, Mes, Estado, Marca, Sucursal en fila— y en
ese alto cada campo se colapsa en un desplegable que dice en una línea qué hay
elegido. Si lo estiras hacia abajo, los desplegables se convierten en listas abiertas
que se reparten el alto. No hay que configurar nada: lo decide el espacio que le
dejes.

### Exportar

Cada widget tiene su flecha: **Excel** o **CSV**. El archivo lleva una hoja con el
contexto —qué filtros estaban puestos, qué versión del modelo, quién lo exportó y
cuándo— para que una tabla que alguien manda por correo siga diciendo de dónde salió.

### La hoja entera en PDF

El botón **PDF** de la barra de arriba saca la hoja que estás viendo como informe,
con los filtros puestos, y da dos formas:

**Una sola hoja.** Para presentar o mandar por correo. Una única página, del alto
que haga falta y todo lo ancha que necesite la hoja, con **todo dentro**: nada
queda cortado ni partido entre dos páginas porque no hay dos páginas. Es la que
quieres para proyectar.

**Páginas A4.** Para papel. Se pagina en apaisado; una tabla larga sigue en la
página siguiente repitiendo sus encabezados, y la fila de totales sale una sola vez
y al final.

Las dos abren el diálogo del navegador: ahí eliges **«Guardar como PDF»** —o una
impresora, si es para papel—. Deja los márgenes y la escala como vienen: la medida
de la página ya la trae el documento.

El informe empieza por una cabecera que solo existe en el PDF: el nombre del
tablero, la hoja, **los filtros aplicados**, el modelo y su versión, y quién lo
emitió y cuándo. Es lo mismo que lleva la hoja de procedencia del Excel, y por lo
mismo: un PDF que circula por correo tiene que poder decir de qué mes es sin que
nadie tenga que preguntarlo.

Sale **la hoja activa** —si el tablero tiene varias, cambia de pestaña y saca cada
una—, con sus widgets en el sitio donde los pusiste y en la paleta clara aunque
tengas la pantalla en oscuro.

Dos cosas que conviene saber:

- **Va lo que el widget cargó.** Si a una tabla le faltan filas, el aviso ámbar sale
  con ella, así que el PDF lo dice; pero para el detalle completo lo que hay es el
  Excel del widget, que se trae hasta 50 000 filas.
- El texto de las tablas es **texto de verdad**: se puede buscar y copiar del PDF.
  Los gráficos se redibujan al tamaño que les toca en el informe, así que las
  etiquetas que en pantalla salían recortadas se leen enteras.

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
