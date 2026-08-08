# Registro de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el
versionado es [semántico](https://semver.org/lang/es/).

## [No publicado]

### Agregado

- **El nombre de una transformación ya se puede cambiar.** Estaba bloqueado con razón
  —el nombre es también el directorio del Parquet y el nombre con el que otras la
  leen— pero bloquearlo era correcto e inservible: dos catálogos que vienen de dos
  sistemas distintos necesitan llamarse distinto, y descubrirlo después de armar la
  transformación obligaba a rehacerla.

  Ahora se renombra de verdad: se **mueve el directorio Parquet** y se **reescriben
  los orígenes** de las transformaciones que la leen. Lo que se toca se dice después,
  con nombres: renombrar algo que otras cuatro cosas leen sin que la pantalla diga
  cuáles es pedir que se confíe a ciegas.

  Tres cosas que no hace, y por qué:

  - **No toca las versiones del modelo**, que son instantáneas inmutables a
    propósito. Si alguna nombra la tabla, el renombrado **se detiene antes de mover
    nada** y dice qué modelo es. Un tablero anclado a una versión no puede cambiar de
    significado porque alguien renombró algo.
  - **No cambia el alias** de un origen, solo su referencia. El alias es el nombre con
    el que la consulta la llama por dentro; cambiarlo rompería el SQL escrito a mano.
  - **No va dentro de «Guardar».** Guardar cambia qué calcula; renombrar mueve datos
    en disco y reescribe definiciones ajenas. Eso no puede colarse en un guardado que
    alguien pulsó para cambiar un filtro, así que tiene su propio botón.

  Un nombre ya usado por otra transformación o por un dataset se rechaza —los dos
  escribirían en el mismo sitio— y también uno que no sirva como nombre de carpeta.

- **Proyectos con secciones en el ETL.** Un proyecto agrupa transformaciones que
  corren en orden, con un solo horario. Es el equivalente a un script con secciones:
  el panel de la izquierda deja de ser una lista plana y pasa a ser
  `PROYECTO ▸ 1 series, 2 calendario, 3 hechos_venta…`, y el número de cada sección
  es el paso en el que corre.

  El problema no era de potencia sino de volumen. Un script de dieciocho secciones se
  convertía en dieciocho transformaciones sueltas más un flujo que las ordenaba:
  correcto pieza por pieza e inmanejable en conjunto — la lista no dice qué va con
  qué, y para probar una hay que ir a otra pantalla. Con cuarenta sucursales deja de
  escalar.

  **Un proyecto es un flujo restringido a transformaciones**, no un objeto nuevo con
  motor propio: comparte la tabla `flujo` y el ejecutor, y por eso hereda los
  reintentos, la cancelación entre pasos, la reanudación por identidad, el historial
  paso a paso y los avisos por correo. Un segundo motor «igual pero para proyectos»
  acabaría siendo el que se queda atrás. Consecuencias buscadas: el proyecto sale en
  Tareas, se detiene con el mismo botón, y un flujo puede llamarlo como paso —el
  maestro trae las cuarenta sucursales y después llama al proyecto que las
  transforma.

  Lo que ya existe no cambia: una transformación sin proyecto sigue funcionando y
  sigue apareciendo, ahora bajo **Sin proyecto**. No se migran solas a un proyecto de
  una sección cada una; eso convertiría doscientas transformaciones en doscientos
  proyectos y el desorden sería el mismo con otro nombre.

- **Ejecutar un tramo: de una sección al final** (`desde_paso`). Cuando la sección 12
  de dieciocho es la que se está afinando, rehacer las once anteriores son veinte
  minutos de espera por nada.

  Los pasos anteriores quedan anotados como **`no se pidió`** —ni `exito`, ni
  `omitido` por un fallo: son tres cosas distintas y el historial tiene que poder
  decir cuál fue—, y la corrida se marca **«tramo desde N»** en el panel y en el
  historial del flujo. Sin esa marca, tres pasos en verde de treinta y cinco se leen
  como «todo al día», que es justo la pantalla con la que se decide sobre un número
  que no se recalculó. Por lo mismo, un tramo que sale bien **no dispara el correo de
  «flujo recuperado»**: los pasos que fallaban pueden ser justo los que no se
  pidieron.

  Sirve igual para el maestro de las treinta y ocho extracciones, no solo para los
  proyectos.

- **Secciones intermedias.** Una sección se puede marcar como andamiaje —un mapeo de
  códigos, una tabla de series, un calendario auxiliar—. Se sigue materializando, que
  es lo que permite ejecutarla sola y ver sus filas, pero **solo se ofrece como
  origen dentro de su propio proyecto** y no ensucia las listas de datos. Con
  dieciocho secciones por sucursal, sin esta marca el catálogo se vuelve inservible
  por volumen.

### Corregido

- **Una tabla de MySQL que el catálogo no describe ya se puede traer.** El selector
  listaba `FACTURAS_PR`, en cualquier cliente SQL se consultaba sin problema, y
  Astrolabio contestaba «La tabla 'ventas_origen.FACTURAS_PR' no existe» — mandando a
  buscar un error de escritura que no existía.

  La causa: se concluía «no existe» de que `information_schema.columns` viniera
  vacío, y eso no es lo que significa. Esa vista filtra por privilegios columna a
  columna y además se queda vacía para una vista que MySQL no puede expandir (su
  definidor perdió permiso, o una tabla de debajo cambió de nombre). En los dos casos
  la tabla está ahí y **se puede leer**.

  Ahora se le pregunta al servidor por la vía que no miente: si hay fila en
  `information_schema.tables`, se pide la forma con un `SELECT … LIMIT 0` y se leen
  las columnas del cursor. Sin clave primaria, así que la carga será completa en vez
  de incremental — que es lo correcto con una tabla de la que no se puede saber más.
  Si tampoco se puede leer, el mensaje dice qué pasó y lo que contestó el servidor,
  en vez de culpar al nombre. Y cuando de verdad no hay fila, se nombra la otra causa
  frecuente: sin permiso de lectura, para Astrolabio no existe.

- **Encadenar flujos: un flujo puede ser el paso de otro.** Con el `+` de la lista
  de flujos se pone uno entero como paso del que se está editando, y así uno
  empieza cuando el anterior termina.

  Era lo único que no se podía decir con horarios. No se sabe cuánto tarda cada
  sucursal, y cuarenta crones a las 6:00 no las ponen en fila: las ponen a
  pelearse por el mismo Pervasive. Un maestro que llame a los cuarenta lo dice
  exacto y lleva un solo horario.

  Cada eslabón corre entero —con sus reintentos y su regla al fallar— y deja su
  propia entrada en su propio historial; en el maestro solo queda el resumen
  («28 pasos · 1,204,331 filas»). Un hijo que falla detiene al maestro.

  Los **ciclos** se rechazan al guardar, directos e indirectos, y hay una segunda
  comprobación al correr por si entre guardar y correr las cosas cambiaron: un
  ciclo no daría un error visible, daría un servidor dando vueltas de madrugada.
  El anidamiento se corta a cinco niveles. *Ordenar solo* deja los pasos de tipo
  flujo donde están y lo dice, en vez de borrarlos en silencio.

- **Detener un flujo que ya arrancó**, con el botón «Detener» en Flujos y en el
  aviso de Tareas. Antes solo se podía sacar de la cola algo que no había empezado:
  una cadena de treinta y ocho extractores lanzada a la una de la tarde no había
  forma de pararla.

  **Se detiene entre pasos, nunca a media tabla.** La que se está trayendo termina y
  los pasos que faltan quedan como `cancelado`. No es prudencia de más: el destino se
  borra ANTES de escribir, así que una recarga completa cortada en el momento justo
  dejaría el dataset vacío. En un maestro se propaga al hijo que esté corriendo.

  Estado nuevo `cancelado` (migración 0009) en vez de reutilizar `error`: en la
  pantalla sale en gris y **no dispara el aviso de fallo**. Un correo de alarma por
  algo que acaba de hacer quien opera es la forma de que esos correos se dejen de
  leer. Hay filtro «Detenidos» en Tareas.

  Una carga suelta no se puede detener y se dice por qué: no tiene pasos donde
  pararse. `DELETE /api/flujos/cola/{id}` ahora contesta 200 con `estado`
  (`sacado` | `parando`) y un mensaje, o 409 explicando por qué no.

- **Continuar una corrida detenida o fallida**, desde su renglón del historial.
  Salta los pasos que ya salieron bien —quedan como `saltado`, que no es `exito`— y
  corre los demás. Nueva ruta `POST /api/flujos/{id}/reanudar/{ejecucion_id}` y
  migración `0010` con la cadena `reanuda_a_id` / `reanudada_por_id`.

  **Las transformaciones se rehacen siempre.** Continuar mezcla dos momentos, y una
  transformación que ya corrió con los datos viejos se quedaría rancia mientras sus
  orígenes se actualizan. Rehacerla cuesta poco: lee Parquet local.

  Los pasos se reconocen por `(tipo, id)` y no por su posición —el flujo puede
  haberse editado entre pausar y continuar—, así que el detalle del historial ahora
  guarda el `id` de cada paso. Un paso sin `id` (corridas anteriores) **no se salta**:
  ante la duda se repite trabajo, que es gratis, en vez de saltarse una tabla.

  Sirve también para las **fallidas**, que es el caso frecuente. En un maestro,
  continuar re-entra en el hijo que se quedó a medias y él se salta lo suyo: reanudar
  38 × 28 no vuelve a traer 1.064 tablas. Solo cuentan las corridas de los hijos
  posteriores a la que se está continuando, para no fiarse de una que alguien paró
  aparte la semana pasada.

  Una corrida se continúa **una sola vez**; el segundo intento dice cuál la retomó.
  La antigüedad de lo completado se muestra y no se prohíbe: un límite en horas sería
  un número inventado.

- **Se rastrea quién dispara a quién.** La lista de flujos trae `llamado_por`, y con
  eso la pantalla de tareas dejó de decir «a mano» de los treinta y ocho extractores
  que en realidad llama el maestro cada noche: dice *dentro de «X»*, y si además
  tienen horario propio, las dos cosas, porque entonces corren dos veces. El filtro
  *Sin horario* ya no los cuenta.

  Las corridas que dispara un flujo se guardan con `origen = "flujo"` y el nombre de
  quien llamó en el detalle, así que el historial del hijo dice *desde «X»* en vez de
  *manual*.

- **El horario se elige por partes, y la zona se elige.** Cada cuánto, a qué hora en
  a. m./p. m., y en qué zona; el cron se genera y sigue a la vista para los casos que
  solo se pueden decir así. Al escribir un cron que no encaja en las formas
  conocidas, el selector pasa a *Avanzado* en vez de mentir sobre lo guardado.

  La zona estaba fija en `America/Mexico_City` —el valor por omisión de la base— sin
  forma de cambiarla desde la interfaz. Ahora hay una lista con las once de México
  por su nombre de a pie y el resto del mundo debajo; un horario nuevo parte de la
  zona del navegador. El mismo selector se usa en flujos y en datasets.

- **Editar una conexión** (`PATCH /api/conexiones/{id}`) y probar el cambio sin
  guardarlo (`POST /api/conexiones/{id}/probar-cambio`). Antes, rotar una
  contraseña obligaba a borrar la conexión y volver a crearla, y con ella se iban
  en cascada todos sus datasets: su historial, sus horarios y sus columnas
  elegidas.

  Un secreto que llega vacío **conserva el guardado**; para quitarlo hay que
  nombrarlo en `borrar_secretos`. La interfaz manda solo los campos que se
  tocaron, porque la API no puede devolver las contraseñas y enmascara la cadena
  de ODBC: reenviar el formulario entero guardaría la máscara.

  El tipo y el perfil de ODBC quedan fijos: cambiarlos sería otra conexión.

- **La interfaz se compila dentro de Docker.** Antes `docker compose` esperaba
  encontrar `frontend/dist` ya compilado en el disco, así que el servidor
  necesitaba Node además de Docker. Ahora hay una etapa de construcción que se
  descarta y la imagen final solo lleva Caddy y los archivos estáticos.
- **El cliente ODBC de Actian Zen / Pervasive se instala solo en la imagen.** Se
  deja el paquete de Linux en `backend/drivers/` y `docker compose build` lo
  instala, localiza `libodbcci.so` y lo registra en `/etc/odbcinst.ini` como
  `Actian Zen ODBC Interface` — el nombre que la pantalla de conexiones
  preselecciona sola.

  Sin paquete la imagen se construye igual, sin ese driver. **Con paquete y algo
  mal, la construcción falla**: una imagen que se construye «bien» y se queda sin
  el driver que se pidió es la forma de descubrir el problema tres semanas
  después, de madrugada, en una carga que no corre.

  El binario no se puede redistribuir, así que `backend/drivers/` está en
  `.gitignore` salvo su README.
- **Instrucciones para un servidor Windows**, con Docker Desktop sobre WSL 2:
  cómo generar las claves sin `openssl`, arranque automático, respaldo desde el
  volumen, finales de línea, cómo salir del error `no matching manifest for
  windows(...)` —Docker en modo contenedores de Windows—, y por qué **un driver
  ODBC de Windows no se puede cargar dentro de un contenedor Linux**.
- **Instalación nativa en Windows Server**, con NSSM como servicio, Caddy delante,
  los DSN de 64 bits y el respaldo por el Programador de tareas. Es la salida para
  **Windows Server 2019**, donde no hay contenedores Linux —WSL 2 pide compilación
  19041+, Docker Desktop no se soporta en Server y LCOW está descontinuado— y
  además es la única donde el driver ODBC de Pervasive carga de verdad.
- **Las pruebas corren también en `windows-latest`.** Hay instalaciones que van a
  vivir en Windows Server; que funcione ahí tiene que estar probado, no supuesto.
- Las claves de producción se generan con **PowerShell puro**, sin `openssl` y sin
  Docker. Las instrucciones anteriores usaban un contenedor, que es justo lo que
  no arranca cuando Docker está en el modo equivocado.

### Arreglado

- **Pegar SQL suponía que toda tabla nombrada era del motor analítico.** `FROM
  cat_zonas` creaba un origen de tipo `tabla` sin comprobar que existiera, y la
  consulta moría con un `Catalog Error: Table with name cat_zonas does not
  exist! Did you mean "information_schema.constraint_column_usage"?` — que culpa a
  la tabla y no dice lo único útil.

  Ahora el nombre se resuelve contra lo que hay: tabla del motor, dataset ya
  cargado, resultado de otra transformación, o una tabla que llegó de varias
  conexiones. Así `SELECT * FROM MI_SUCURSAL__ventas` funciona sin que nadie sepa
  que detrás hay Parquet. Si el nombre no existe se dice en claro, con la sugerencia
  más parecida, y **no se crea un origen roto** que falle más adelante.

  En modo SQL, una tabla que no esté entre los orígenes da el mismo mensaje útil en
  vez de dejar que DuckDB conteste por su cuenta.

- **En «Elegir columnas» solo se podía marcar una.** Los cuadros de cada paso se
  dibujaban con las columnas que devolvía la vista previa, que son las de la
  **salida** de la cadena completa. Al marcar la primera, la salida pasaba a tener
  una sola columna y el propio paso se quedaba con un solo cuadro: imposible marcar
  la segunda. Cualquier paso colocado después de un «Agrupar y resumir» tenía el
  mismo problema.

  Ahora cada paso ofrece las columnas que le **entran**: las del origen después de
  los pasos anteriores, simuladas en el navegador para no ir al servidor por cada
  clic. La simulación es conservadora: cuando un paso puede traer columnas que desde
  la interfaz no se conocen —unir sin decir cuáles traer, apilar— no quita ninguna.
  Para la salida real sigue mandando la vista previa, que la calcula el compilador.

- **En una instalación nueva, el motor analítico no existía y nada podía leerlo.**
  `duckdb_solo_lectura` es `True` por omisión —y debe serlo, la API no escribe en el
  motor, escribe Parquet— pero **en solo lectura DuckDB no crea el archivo que le
  falta**. Si nunca se sembraron los datos de demostración, ese archivo no existía
  nunca, y el ETL, los tableros y el modelo fallaban con:

      IO Error: Cannot open database "...analitico.duckdb" in read-only mode:
      database does not exist

  Ahora el arranque lo crea vacío si falta. `duckdb_tables()` sobre una base vacía
  devuelve cero filas, que es la verdad: todavía no hay tablas en el motor.

- **El panel de orígenes del ETL se quedaba vacío y callado.** `GET
  /api/transformaciones/origenes` calculaba todo en una sola expresión: si
  `ruta_datos_dataset` lanzaba por **un** nombre con un carácter que no sirve para
  nombrar un origen, la petición contestaba 500 y la pantalla mostraba el panel
  vacío sin decir nada. Con mil sesenta y cinco datasets, uno raro dejaba sin poder
  transformar nada.

  Ahora cada bloque se calcula por separado, lo que no se puede usar sale marcado y
  con su motivo en `avisos`, y la pantalla distingue las tres situaciones que antes
  se veían igual: *leyendo*, *no se pudo leer* y *todavía no hay nada*.

  De paso, la comprobación de «¿tiene datos?» se hace una vez por dataset y no dos
  —recorre directorios, y con mil sesenta y cinco se nota—.

- **Una prueba armaba JSON pegando una ruta con una f-string** y en Windows eso
  produce JSON inválido: `C:\Users` lleva un `\U` que no es un escape válido.
  En Linux colaba porque las rutas no tienen barras invertidas. Lo encontró el
  trabajo de integración continua en Windows el mismo día que se añadió, que era
  exactamente para lo que estaba.

- **El guion de Windows ya no imprime las claves en pantalla.** Parecía servicial
  y era un error: la consola queda en el historial, en las capturas y en el texto
  que uno pega para pedir ayuda. Ahora van a `CLAVES-GENERADAS.txt` con permisos
  solo para administradores, y el guion pide que se guarden y se borre el archivo.
  Hay `-RotarClaveCifrado` para el caso en que una se haya visto igual.

- **`backend/administrar.py`**: `listar-usuarios` y `restablecer <correo>`.
  La contraseña del primer administrador solo se escribe en el registro del
  primer arranque; si ese registro se perdió, no había forma de entrar y la
  única salida era borrar la base de metadatos, que se lleva por delante todo lo
  demás.

### Cambiado

- `api` ya solo escucha en `127.0.0.1:8000`. Quien entra de fuera pasa por Caddy,
  que es el que lleva HTTPS y las cabeceras de seguridad.
- Se quitó la referencia a un `docker-compose.prod.yml` que no existía: la
  diferencia entre desarrollo y producción es el `.env`, no un compose distinto.

Lo que falta y está decidido que se hará: más conectores nativos (PostgreSQL,
SQL Server, SQLite), una barra de selecciones con atrás y adelante, y que el fin de
un flujo dispare otro flujo. La lista completa vive al final de cada documento de
fase.

## [0.1.0] — 2026-08-05

Primera versión pública. El recorrido completo funciona: conectar, transformar,
modelar y publicar, con **296 pruebas** automatizadas.

### Datos

- Conectores de **MySQL/MariaDB**, **archivos** (CSV, Excel, Parquet, y los `.xls`
  que en realidad son HTML) y **ODBC**, con perfiles por origen que arman la cadena
  de conexión y detectan qué drivers hay instalados.
- Ingesta a **Parquet particionado** por año y mes, con carga completa, incremental
  y recarga de particiones.
- **Ventanas móviles** de recarga (`el mes en curso`, `los últimos 2 años`,
  `ultimos_dias:N`…), resueltas en el momento de correr y en la zona horaria del
  dataset.
- **Elegir columnas**, con `null` = todas para que las columnas nuevas del origen
  lleguen solas.
- Los tipos los declara el origen, no se deducen de los datos.
- Se prueba la conexión **antes** de guardarla, y cualquier cambio invalida la
  prueba anterior.

### Transformar

- Pasos visuales (filtrar, unir, agrupar, derivar, apilar, ordenar…) y **SQL
  pegado**, con conversión de SQL a pasos que se niega a adivinar.
- **Conteo de filas por paso**, que es lo que convierte un «no cuadra» en «se
  pierde en el paso 3».
- La base analítica se abre en **solo lectura**; el resultado se escribe a un
  temporal y después se reemplaza.

### Modelo

- Lienzo de entidades y relaciones, métricas definidas una sola vez, y versiones
  inmutables a las que los tableros quedan anclados.
- Diagnóstico de **fan traps, rutas ambiguas y tablas huérfanas**. Ante una ruta
  ambigua el motor **pregunta** en vez de elegir.

### Tableros

- KPI, barras, líneas, pastel y tabla; **filtros asociativos** al estilo Qlik.
- Exportación a Excel y CSV **con el contexto** de la consulta.

### Gobierno

- Tres roles, **seguridad por fila** que también filtra los totales y falla cerrado,
  **simulador** para ver como otro usuario, y auditoría que no se puede borrar.

### Avisos

- Reglas por **correo** o **webhook** (Teams, Slack) cuando una carga o un flujo
  falla, con silencio entre repeticiones, aviso al recuperarse, registro de cada
  intento y un botón para probar el canal.

### Seguridad

- Contraseñas con Argon2, credenciales de conexión cifradas con Fernet, y **freno
  a la fuerza bruta** por cuenta.
- El arranque en producción falla si faltan las claves o son débiles.
- Webhooks a direcciones internas bloqueados por defecto; a las de enlace local,
  siempre.
- Dependencias fijas y auditadas: `pip-audit` sin hallazgos.
