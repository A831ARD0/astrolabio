# Fase 1 — Datos de verdad

Estado: **conectores MySQL y archivos, recarga por partición, programador de cargas
e interfaz completos**. Pendiente en esta fase: el conector ODBC y la unión de las
~40 bases por sucursal.

Las pruebas contra MySQL corren sobre una base local de trabajo y se saltan solas
si no está disponible. Sirven para verificar las funciones; la validación de
cifras contra el Qlik es otra fase (§11).

---

## 1. Arquitectura de ingesta

```
MySQL / archivos  ──►  Parquet particionado  ──►  DuckDB  ──►  modelo semántico
    (origen)              (anio=/mes=)          (consultas)
```

El origen **nunca** se consulta desde un dashboard. Se copia a Parquet local y
todo lo demás lee de ahí. Tres razones: no se carga el sistema operativo del
negocio, las consultas no dependen de la red, y el dato queda reproducible
(sabes exactamente qué se trajo y cuándo).

### La decisión que define el rendimiento

Para mover datos se usa **la extensión MySQL de DuckDB**, no un cursor de Python.
Medido contra la base real:

| | |
|---|---|
| `tbl_contactos` completa | **1,174,536 filas en 4.2 s** (279,000 filas/s) |
| Tamaño en MySQL | 248 MB |
| Tamaño en Parquet zstd | **40.4 MB** (6× menos) |
| Archivos de partición generados | 65 |
| Consulta filtrada por `anio=2024` | **5 ms** (39,473 filas) |

Un cursor fila por fila en Python es dos órdenes de magnitud más lento. La
introspección sí usa `pymysql`, porque ahí lo que importa es SQL confiable sobre
`information_schema`, no velocidad.

---

## 2. Los dos dialectos — un bug que costó encontrar

Los datos vienen de MySQL pero el SQL de la copia lo **ejecuta DuckDB**. Son
dialectos distintos: el backtick de MySQL (`` `tabla` ``) es error de sintaxis en
DuckDB, que usa comillas dobles.

Hay dos funciones separadas a propósito, `_ident()` y `_ident_duck()`, en vez de
una sola con reemplazos. Mezclarlas fue el primer fallo real de esta fase.

---

## 3. Las fechas que vienen como texto

Hallazgo al probar contra datos reales: en `tbl_contactos`, **ninguna** de
las 11 columnas `fecha_*` es de tipo fecha. Todas son `varchar`, con cadenas
vacías mezcladas con fechas válidas:

```
fecha_asignacion_a_sucursal   varchar(45)   valores: '', '2021-12-02', '2021-07-14'
```

Esto explica por qué el Qlik actual hace parseo manual de fechas ~40 veces. Y
tiene consecuencia directa de diseño: el particionado usa **`TRY_CAST` y no
`CAST`**. Un `CAST` duro tumbaría la carga completa por una cadena vacía.

Lo que no se pudo interpretar va a su propia partición y **se reporta**, en vez de
fallar o de callarse:

```json
{"filas": 1174536, "filas_sin_particion": 999985}
```

Ese contador es parte del producto, no del diagnóstico de estos datos de prueba:
una columna de fecha en texto puede tener cualquier proporción de valores
ilegibles, y quien carga necesita ver cuántos fueron. Sin el número, un análisis
por eje de tiempo puede estar mirando una fracción de las filas sin saberlo.

Nota relacionada: la base **sí** tiene 1,326 columnas de fecha real en otras
tablas. Conviven los dos casos, así que el conector tiene que soportar ambos.

---

## 4. Carga incremental

Un dataset guarda su **marca máxima**: el último valor traído de la columna
incremental. La siguiente carga trae solo lo posterior.

Detalle que estuvo mal al principio y vale documentar: **la primera carga
completa también tiene que registrar la marca máxima.** Si no, nunca hay punto de
partida y el modo incremental jamás se activa. Ahora la columna incremental se
pasa siempre al conector; lo que distingue el modo es si se pasa `desde` o no.

Probado: primera carga trae 41 filas de `cat_marca` y guarda la marca; la segunda
trae 0 en modo incremental.

---

## 4.1 Los tres modos de escritura

Quién borra qué es la parte delicada de la ingesta: un borrado de más pierde
histórico y uno de menos duplica filas. Por eso el modo es **explícito** y no se
deduce del contexto, y vive en un solo sitio
([`conectores/base.py`](../backend/app/conectores/base.py)) para que todos los
conectores se comporten igual.

| Modo | Qué borra antes de escribir | Cuándo |
|---|---|---|
| `completo` | el destino entero | primera carga, o rehacer el dataset |
| `incremental` | nada, agrega | trae lo posterior a la marca máxima |
| `particion` | solo las particiones del rango | corregir un mes suelto |

Bug que esto arregló: hasta ahora las cargas repetidas **agregaban** un Parquet
más cada vez, así que un dataset recargado tres veces tenía las filas
triplicadas. Y dentro de una partición pasaba lo contrario: el nombre de archivo
por defecto (`data_0.parquet`) hacía que un lote incremental **pisara** lo
anterior. Ahora el nombre lleva un uuid y quien decide qué se borra es el modo,
no el nombre del archivo.

---

## 4.2 Recarga de una partición sola

Recargar diez años de historia para corregir un mes no es practicable. La recarga
por rango reemplaza **solo las particiones que el rango cubre**:

```
POST /api/conexiones/datasets/{id}/recargar-rango
{"desde": "2024-01-01", "hasta": "2024-01-31"}
```

Medido sobre `tbl_contactos`:

```
carga inicial      : 40,000 filas   296 ms   37 archivos
  enero 2024       :      7 filas
recarga enero 2024 :  2,290 filas  3,380 ms  particiones ['anio=2024/mes=1']
  enero 2024       :  2,290 filas   total 42,283
  particiones ajenas reescritas: 0  (de 36)
```

Enero pasó de 7 filas a las 2,290 que hay en el origen, y **ninguna** de las
otras 36 particiones se volvió a escribir (comparado archivo por archivo con su
fecha de modificación).

Dos decisiones que importan:

- **Las particiones a reemplazar se calculan del rango pedido, no de los datos
  traídos.** Recargar marzo debe dejar marzo igual que el origen, incluso si en
  el origen ya no hay filas de marzo porque se borraron. Si se calcularan de los
  datos, esas bajas nunca desaparecerían del Parquet.
- **El rango necesita inicio y fin.** Un rango abierto no dice cuántas
  particiones hay que reemplazar.

El borrado está confinado al directorio del dataset: una partición viene de los
datos, y un dato no debe poder señalar a un directorio de fuera.

---

## 5. Validación antes de mover datos

Las columnas de partición e incremental se validan **antes** de copiar nada,
contra el esquema real, y el mensaje sugiere columnas parecidas:

```
La columna 'rs_fecha_asignado' (particionar_por) no existe en
'BASE_MYSQL.tbl_contactos'. Columnas parecidas: rs_asesor,
rs_fecha_1er_contacto, rs_status
```

Ese caso es real: el README del Qlik nombra `rs_fecha_asignado`, que no existe en
la base. Sin la validación, el usuario recibiría un `BinderException` de DuckDB a
media copia.

---

## 6. Los fallos quedan registrados

Bug encontrado al probar: al lanzar el error HTTP, la sesión hacía rollback y
**borraba el registro del fallo**. El historial de cargas fallidas es justo lo que
se necesita para depurar una cifra que no cuadra, así que ahora la ejecución con
estado `error` se confirma antes de propagar la excepción.

---

## 7. Seguridad de las credenciales

- Se guardan cifradas con Fernet. Probado: la cadena en la base no contiene ni el
  nombre de la base ni el host en claro.
- **Nunca se devuelven.** `config_publica()` filtra `password`, `contrasena`,
  `clave`, `secret`, `token`, `pwd`. La auditoría también guarda solo la config
  pública.
- Una conexión que no funciona **no se guarda**: se prueba antes de persistir.
- El `ATTACH` de DuckDB es `READ_ONLY`. Astrolabio nunca escribe en un origen.
- Los identificadores (tabla, columna) no se pueden ligar como parámetros, así
  que se **validan** contra `^[A-Za-z_][A-Za-z0-9_$]{0,63}$`.
- El conector de archivos confina todo acceso a su `ruta_base`: `..` y rutas
  absolutas se rechazan.

---

## 8. El `.xls` que es HTML

Los archivos de bonificaciones canceladas de un origen real tienen extensión `.xls` pero son
HTML exportado con `charset=Windows-1252`. El formato se detecta **por contenido**
(bytes iniciales), no por extensión, porque la extensión miente:

| Bytes iniciales | Formato real |
|---|---|
| `PK` | xlsx (es un zip) |
| `D0 CF 11 E0…` | xls real (OLE2) |
| `<` o `<!doctype` | **HTML disfrazado** |

Probado con un archivo así: se lee, se describe y se ingesta igual que un CSV.

---

## 9. Programador de cargas

Un dataset puede llevar una expresión cron con su zona horaria:

```
PUT /api/conexiones/datasets/{id}/programacion
{"cron": "0 6 * * *", "zona_horaria": "America/Mexico_City", "activa": true}
```

**El programador ejecuta exactamente la misma función que el botón.** La lógica de
carga vive en [`app/cargas.py`](../backend/app/cargas.py), fuera de las rutas
HTTP, precisamente por eso: si fueran dos caminos parecidos, el historial y la
auditoría de una carga automática acabarían distintos de los de una manual, y con
eso se pierde justo lo que sirve para depurar a las 3 de la mañana. Cada ejecución
queda marcada con su disparo (`manual` o `programado`).

Las decisiones que evitan daño callado:

| Ajuste | Por qué |
|---|---|
| Jobstore en la misma base SQLite | reiniciar el servidor no borra las programaciones; en memoria, un reinicio de madrugada dejaría los datos sin actualizar y nadie se enteraría |
| Comparte el motor de la app | hereda WAL y `busy_timeout`; con un motor propio, dos escritores sobre el mismo archivo se bloqueaban — pasó y está en las pruebas |
| `coalesce=True` + `misfire_grace_time` | si el servidor estuvo apagado tres días, al arrancar corre **una** carga, no 72 atrasadas; acumular atrasos es la forma clásica de tumbar el origen justo al volver |
| `max_instances=1` | una carga que tarda más que su intervalo no se solapa consigo misma; dos ingestas escribiendo el mismo Parquet es corrupción |
| La excepción no escapa del job | si escapara, APScheduler apagaría el trabajo y el dataset dejaría de actualizarse en silencio |
| La zona horaria se guarda con el cron | "a las 6" en un servidor en UTC no es a las 6 en Monterrey, y una carga a la hora equivocada trae el día incompleto |
| El cron se valida al guardarlo | debe fallar en la petición del usuario, no de madrugada dentro del programador |
| `sincronizar()` al arrancar | la base manda: los trabajos huérfanos se corrigen solos |
| `ASTROLABIO_PROGRAMADOR_ACTIVO=false` | dos procesos con el mismo jobstore duplicarían las cargas; solo uno debe programar |

Qué va a correr y cuándo: `GET /api/conexiones/programacion`.

---

## 10. La interfaz, que llegó tarde a propósito y se notó

Durante cinco fases esta API no tuvo pantalla: las conexiones y los datasets se
creaban llamando a la API a mano. Funcionaba porque el único que traía datos era
quien escribía el código.

Es el peor sitio donde puede faltar una interfaz: **la puerta de entrada del
producto**. Con la Fase 6 ya se podía dar acceso a otras personas, y esas personas
no podían traer una tabla. Así que la pantalla es parte de lo mismo.

`Conexiones` tiene las dos listas juntas, porque son un solo flujo:

- **Conexión**: se crea por tipo, con los campos obligatorios que dice el propio
  servidor (`/conexiones/tipos`) — cuando entre el conector ODBC, el formulario ya
  lo sabrá sin tocarlo. **No se guarda lo que no se ha probado** (§10.1).
- **Explorar**: esquemas → tablas → columnas → 25 filas de muestra. Y el dataset se
  crea **desde ahí**, con las columnas y la muestra a la vista: la columna
  incremental y la de partición son las dos elecciones que deciden si la siguiente
  carga tarda 4 segundos o 4 minutos, y elegirlas de memoria es cómo se acaba
  particionando por una columna que viene casi toda nula.
- **Dataset**: cargar (incremental o completa), recargar un rango de fechas,
  historial y horario, todo en el mismo panel. Están juntos a propósito: una carga
  incremental que trae 0 filas puede ser correcta —no hay nada nuevo— o significar
  que la marca máxima quedó en el futuro, y eso solo se distingue viendo la marca y
  el historial al mismo tiempo.

Dos cosas que se agregaron al backend para que la pantalla fuera honesta:

- `POST /api/conexiones/probar-config` — prueba sin persistir. El intento **sí**
  queda en auditoría: es una conexión saliente con credenciales aunque no se guarde.
  Y la auditoría guarda la config pública, nunca el secreto (hay una prueba que
  busca la contraseña en el registro y exige no encontrarla).
- `DELETE /api/conexiones/datasets/{id}` — da de baja el registro, su historial y su
  horario, y **conserva los archivos Parquet**, diciendo en la respuesta dónde
  quedaron. Un dataset se da de baja casi siempre por un nombre mal puesto, no
  porque los datos sobren; borrar datos no tiene vuelta atrás, así que eso se hace
  a mano. Si el dataset tenía horario, el trabajo se quita del programador — un
  trabajo huérfano correría de madrugada buscando un dataset que ya no está, y hay
  una prueba para eso.

La pestaña del ETL pasó a llamarse **Transformar**. Dos secciones llamadas «Datos»
una al lado de la otra no se distinguen.

---

## 10.1 Probar y luego guardar, y el botón que no explicaba nada

La primera versión dejaba guardar sin probar, apoyada en que el servidor prueba
otra vez al crear. Es verdad, pero la garantía del servidor no es lo mismo que la
secuencia correcta en pantalla: **`Guardar` solo se activa con una prueba
correcta**, y cualquier cambio en la configuración la invalida.

La comprobación no es «¿se pulsó el botón?» sino **«¿la configuración probada es
exactamente esta?»**. Se guarda una huella (`JSON.stringify([tipo, valores])`) de
lo que se probó y se compara con lo que hay en el formulario. Así no hay forma de
probar con un servidor, cambiar el host, y guardar apoyado en un visto bueno que ya
no vale. Y tiene una consecuencia agradable: si se deshace el cambio, el visto bueno
vuelve solo, porque vuelve a ser la misma conexión.

El nombre no entra en la huella. Es una etiqueta nuestra, no algo que el servidor de
datos vea: corregir una errata no cambia si la conexión conecta, y obligar a probar
otra vez por eso enseña que el botón es arbitrario.

### Un botón gris sin motivo parece una aplicación rota

El fallo de verdad no era el orden, era el silencio. Con el nombre vacío, `Probar` y
`Guardar` estaban los dos desactivados y **nada decía por qué** — y el texto de
ejemplo del campo Nombre (`ventas_servidor`) se leía como un valor escrito, así que el
formulario parecía completo.

Dos arreglos, los dos de una línea:

- Junto a los botones va siempre la razón: `Falta: Nombre, Carpeta.` → `Prueba la
  conexión antes de guardar.` → `La configuración cambió. Vuelve a probar.` Es una
  lista y no una frase a propósito: «Falta el nombre y Carpeta» obliga a concordar
  artículos con etiquetas que vienen del servidor.
- Los textos de ejemplo van en gris tenue **y en cursiva**. Solo con el color, quien
  no distinga los grises sigue viendo un campo lleno.

Y el desplegable de tipo ya no muestra el identificador crudo (`mysql`, `archivo`)
sino `MySQL / MariaDB` y `Archivos — CSV, Excel, Parquet`.

---

## 10.2 El conector ODBC

Es el comodín: cubre Informix, SQL Server, Access, Oracle y casi cualquier
origen con driver. **Probado contra el MySQL local**, que es el único origen real
disponible hasta que sistemas entregue el acceso al origen.

ODBC promete portabilidad y no la cumple del todo, así que el conector está escrito
para no dar nada por sentado del dialecto. Lo que necesita saber, lo **pregunta al
driver**:

| Lo que cambia entre orígenes | Cómo se resuelve |
|---|---|
| Las comillas de identificador (`` ` ``, `[ ]`, `"`) | `SQL_IDENTIFIER_QUOTE_CHAR`, preguntado a la conexión |
| Si la base es un *catálogo* o un *esquema* | MySQL usa catálogo y **no admite esquemas** — el driver de MariaDB responde literalmente «Schemas are not supported». Se intenta uno y se cae al otro |
| Limitar filas (`LIMIT` / `TOP` / `FIRST`) | No hay forma portable: no se limita en SQL, **se deja de leer**. El driver trae las filas por bloques, así que una muestra de 25 no arrastra la tabla |
| Los tipos de las columnas | De `cursor.description` —tipo, precisión y escala— **antes de leer la primera fila** |

### El tipo lo declara el origen, no lo adivina nadie

Dejando que pandas dedujera los tipos de los datos, la carga de `tbl_movimientos`
reventaba con *Casting value "1189519.10" to type DECIMAL(8,2) failed*: había
deducido la precisión de las primeras filas y una parte de la tabla no cabía. Peor
que reventar es lo otro: que una cifra de dinero acabe guardada como texto y nadie
se entere hasta sumarla.

Con el esquema declarado por el driver se construye un esquema de Arrow, y ese es el
que define las columnas del Parquet.

### La prueba que importa: los dos caminos dan lo mismo

Un conector nuevo puede parecer que funciona —conecta, lista tablas, escribe el
número de filas correcto— y estar perdiendo la hora de un `DATETIME`. Contar filas no
lo detecta. Así que la misma tabla se trae por los dos caminos y se comparan los
Parquet con `EXCEPT` **en los dos sentidos**:

```
odbc EXCEPT nativo : 0 filas
nativo EXCEPT odbc : 0 filas
```

### Cuánto cuesta

Medido con la misma tabla, 60,000 filas de 20 columnas particionadas por mes:

| | |
|---|---|
| MySQL por su conector nativo | **0.3 s** |
| MySQL por ODBC | **6.4 s** (2.9 s leer + 3.5 s insertar) |

Veinte veces más lento: la ingesta pasa fila por fila por Python, no por la extensión
nativa de DuckDB. Por eso ODBC **no reemplaza** al conector de MySQL. Con inserción
fila por fila en DuckDB eran 15.7 s; el lote por Arrow lo bajó 4.6 veces.

El coste es por **celda**, no por fila, así que elegir columnas es la palanca:
242,109 filas de 2 columnas por ODBC tardaron **613 ms**.

### Lo que se aprende al enchufarlo a un sistema viejo de verdad

ODBC se probó contra MySQL, porque comparar las dos rutas contra la misma tabla es
lo que demuestra que trae exactamente los mismos datos. Pero el caso que motivó el
conector fue un sistema de gestión de concesionarios sobre **Pervasive PSQL / Actian
Zen**, y de ahí salieron tres lecciones que no son de código y que aplican a
cualquier origen parecido:

1. **32 bits contra 64 bits.** Si los DSN aparecen en el «Administrador de orígenes
   de datos ODBC (32 bits)», un proceso de 64 bits **no puede cargar ese driver**. No
   es permisos ni cadena: simplemente no se cargan juntos. O se instala el cliente de
   64 bits, o hace falta un recolector aparte corriendo en 32 que sirva los datos.

2. **Un DSN es local a su máquina.** Los DSN configurados en el servidor de origen no
   existen para Astrolabio hasta que se configuren **donde corre Astrolabio**, o hasta
   que se use la forma «driver + servidor» en vez del DSN.

3. **Una base por sucursal es una conexión por sucursal.** En estos sistemas es común
   que cada sucursal tenga su propio DSN. Traer «la misma tabla de las N sucursales a
   un solo dataset» todavía no existe: hoy son N datasets y una transformación que
   los une. Está en los pendientes.

### Los perfiles: la cadena armada por origen

Escribir `DRIVER={Pervasive ODBC Client Interface};SERVERNAME=…;SERVERDSN=…` a mano
es donde se pierde media tarde, porque cada driver llama distinto a lo mismo:

| | El servidor | La base |
|---|---|---|
| Pervasive / Zen | `SERVERNAME` | `SERVERDSN` |
| SQL Server | `SERVER=host,puerto` | `DATABASE` |
| Informix | `HOST` + `SERVER` (¡los dos!) | `DATABASE` |
| PostgreSQL / MySQL | `SERVER` + `PORT` | `DATABASE` |

`app/conectores/perfiles_odbc.py` tiene el catálogo: por cada origen, los campos que
hace falta llenar y la plantilla con la que se arma la cadena. El formulario se dibuja
desde ahí y **la cadena la arma el conector**, no el navegador — así hay un solo sitio
donde está escrito cómo se conecta a cada motor, y la conexión queda guardada por
campos, que es lo que la hace editable después sin volver a teclear la contraseña.

Dos detalles que parecen menores:

- Los segmentos con un campo vacío **se caen enteros**. Un `UID=` sin valor no es
  inofensivo: hay drivers que lo toman como usuario vacío y contestan un error de
  autenticación en vez de usar el del sistema.
- Informix pide la máquina (`HOST`) **y** el nombre de la instancia (`SERVER`), que no
  es el mismo y no se deduce. Es el motivo más común de «no se pudo conectar» con
  Informix, así que el campo lo pide aparte y explica cuál es cuál.

### Descargar el driver solo, como DBeaver: no se puede, y por qué

DBeaver descarga drivers **JDBC**: archivos `.jar` de Java, portables y publicados en
repositorios abiertos. Un driver **ODBC** es una librería nativa del sistema operativo
(`.dll`, `.so`, `.dylib`) que se instala y se registra en la máquina; y los dos que
importan aquí —Pervasive/Actian y el de Informix— vienen del cliente licenciado del
fabricante, sin descarga pública.

Lo que sí se puede, y es lo que hace `GET /api/conexiones/odbc/perfiles`: cruzar el
catálogo con lo que está instalado, preseleccionar el driver detectado —su nombre
tiene que coincidir **exacto** con el registrado, y el error cuando no coincide
(«Data source name not found and no default driver specified») no dice cuál era el
bueno—, y cuando no está, decir de dónde sale y quién lo instala:

```
MySQL/MariaDB        apt-get install odbc-mariadb        (ya está en la imagen)
PostgreSQL           apt-get install odbc-postgresql
SQL Server           msodbcsql18, del repositorio de Microsoft
Pervasive/Zen        del cliente de Actian Zen — licenciado, lo instala sistemas
Informix             del Client SDK de IBM — no está en apt, se descarga con cuenta
```

Y por eso `GET /api/conexiones/odbc/instalado` existe: dice qué drivers y qué DSN ve
el servidor. Sin eso, configurar ODBC es adivinar — el nombre del driver tiene que
coincidir **exacto** con el registrado en la máquina, y el error cuando no coincide
(«Data source name not found») no dice cuál era el bueno. Si no hay ninguno
registrado, la pantalla lo dice y acepta la ruta del `.dylib`/`.so`/`.dll`.

---

## 10.3 Elegir columnas, y las ventanas móviles de recarga

### Columnas: por defecto todas, y eso se guarda como `null`

Un dataset trae las columnas que se le digan, y por defecto todas. Lo que se guarda
cuando se quieren todas es **`null`, no la lista completa**. Un dataset creado hoy
con las 45 columnas de hoy tiene que seguir trayendo la 46 cuando el origen la
agregue; con la lista congelada, la columna nueva no llegaría nunca y nadie sabría
por qué.

La muestra de filas **se vuelve a pedir** con las columnas elegidas; no se recorta en
el navegador. La vista previa es de lo que se va a traer: si mostrara columnas
descartadas, la columna de partición se elegiría mirando datos que no van a estar.

Tres cosas que el editor no deja hacer, porque fallarían de madrugada:

- **Dejar fuera la columna de partición o la incremental.** Elegirlas como tal las
  vuelve a incluir; en un dataset que ya existe, la casilla está bloqueada.
- **Dejarlo todo fuera.** Un dataset sin columnas no es un dataset.
- **Cambiar el juego de columnas y seguir en incremental.** Se borra la marca máxima,
  así que la siguiente carga reescribe todo — y se avisa antes de guardar. El Parquet
  en disco tiene las columnas viejas: mezclar un lote con otras haría que leer el
  dataset fallara o, peor, devolviera nulos donde antes había datos.

### Ventanas móviles: el problema que resuelven

Una carga incremental por clave (`id > 60026`) trae lo **nuevo**, y no vuelve a mirar
lo que **cambió**. En un sistema de ventas, una venta de hace tres semanas se corrige
—cambia el importe, se cancela, se reasigna la sucursal— y su `id` no cambia, así que
el Parquet se queda con la versión vieja. La cifra sigue pareciendo un número.

Una ventana móvil dice «reemplaza siempre estas particiones»:

| | |
|---|---|
| `dia_anterior`, `ultimos_7_dias`, `ultimos_30_dias`, `ultimos_dias:N` | por días |
| `mes_actual`, `mes_actual_y_anterior` | por calendario |
| `anio_actual`, `ultimos_2_anios` | por calendario |

Tres decisiones:

- **El rango se resuelve en el momento de correr**, no al guardarlo. Guardar el rango
  calculado sería un error silencioso: el dataset configurado en enero seguiría
  recargando enero para siempre.
- **Se calcula con la zona horaria del dataset.** «Ayer» a las 00:30 en un servidor en
  UTC es hoy en Monterrey; una carga de madrugada con la fecha del servidor recarga el
  día equivocado, y el que falta no lo recarga nadie.
- **La ventana pide partición.** Lo que hace es reemplazar particiones; sin ellas no
  hay nada que reemplazar sin reescribir todo. La interfaz solo la ofrece si el
  dataset está partido.

«Cargar» respeta la ventana; **«Recargar completo» se la salta**, porque quien pide
volver a traer todo quiere todo, no el mes en curso. Y la ventana queda en el
historial de cada corrida: mirando una de madrugada, sin eso, no se sabría por qué
solo se tocaron unas particiones.

Verificado por ODBC con `ultimos_dias:3000` sobre `tbl_movimientos`: 242,109 filas en
98 particiones, y la fecha mínima del Parquet es **2018-05-19**, exactamente el
`desde` que resolvió la ventana.

---

## 11. Lo que falta en esta fase

| Pendiente | Qué se necesita |
|---|---|
| **Más conectores nativos** | PostgreSQL, SQL Server y SQLite. El molde está en `conectores/base.py`; hoy van por ODBC, que es unas veinte veces más lento |
| **Una tabla repartida en N orígenes, a un solo dataset** | frecuente cuando cada sucursal tiene su propia base: hoy son N datasets y una transformación que los une. Sería una carga con lista de orígenes |
| **Editar una conexión** | hoy se crea y se borra; cambiar una contraseña obliga a crearla de nuevo |
| **Perfilado al explorar** | nulos y distintos por columna antes de elegir la partición; hoy se ve la muestra, que ayuda pero no basta |
| **Subir un archivo desde el navegador** | el conector de archivos lee una carpeta del servidor; no hay cómo dejar caer un Excel |

---

## 12. Cómo usarlo

```bash
cd /backend && ./venv/bin/python3 -m pytest tests/ -q
```

Las pruebas de MySQL se saltan solas si la base no está disponible, así que la
suite corre en cualquier máquina.

Flujo de la API:

1. `POST /api/conexiones` — crear conexión (la prueba antes de guardar)
2. `GET /api/conexiones/{id}/tablas` — explorar el origen
3. `GET /api/conexiones/{id}/tablas/{tabla}` — columnas y conteo real
4. `POST /api/conexiones/{id}/datasets` — definir qué traer y cómo
5. `POST /api/conexiones/datasets/{id}/cargar` — ejecutar
6. `PUT /api/conexiones/datasets/{id}/programacion` — que corra sola
7. `POST /api/conexiones/datasets/{id}/recargar-rango` — corregir un mes
8. `GET /api/conexiones/datasets/{id}/historial` — qué pasó en cada carga
9. `GET /api/conexiones/programacion` — qué va a correr y cuándo
