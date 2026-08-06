# Registro de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el
versionado es [semántico](https://semver.org/lang/es/).

## [No publicado]

### Agregado

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
