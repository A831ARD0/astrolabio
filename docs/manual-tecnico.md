# Manual técnico

Para quien instala y mantiene Astrolabio. Si lo que buscas es usarlo, ese es el
[manual de usuario](manual-usuario.md).

**Índice**

1. [Qué se necesita](#1-qué-se-necesita)
2. [Instalar para desarrollar](#2-instalar-para-desarrollar)
3. [Configuración](#3-configuración)
4. [Poner en producción](#4-poner-en-producción)
5. [Respaldos y recuperación](#5-respaldos-y-recuperación)
6. [Actualizar](#6-actualizar)
7. [Cómo está hecho por dentro](#7-cómo-está-hecho-por-dentro)
8. [Drivers ODBC](#8-drivers-odbc)
9. [Correo y webhooks](#9-correo-y-webhooks)
10. [Cuando algo va mal](#10-cuando-algo-va-mal)
11. [Rendimiento](#11-rendimiento)

---

## 1. Qué se necesita

| | Mínimo | Cómodo |
|---|---|---|
| CPU | 2 núcleos | 4+ |
| RAM | 4 GB | 16 GB |
| Disco | 20 GB | Lo que ocupen tus Parquet ×3 |
| SO | Linux, macOS o Windows | Linux o Windows Server |

**Con Docker no necesitas instalar nada más**: Python y Node viven dentro de las
imágenes, y la interfaz se compila durante la construcción. Funciona en Linux,
macOS y Windows **10/11 o Server 2022** — en Windows Server 2019 no, porque no
tiene WSL 2; ahí la instalación es nativa, y está explicada en §4.

Sin Docker: **Python 3.12+**, **Node 20+** (solo para compilar la interfaz) y
`unixodbc` si vas a usar conectores ODBC.

La memoria es lo que marca el límite real: DuckDB trabaja en memoria y una consulta
sobre decenas de millones de filas quiere espacio. 11.5 millones de filas funcionan
de sobra en una laptop.

---

## 2. Instalar para desarrollar

```bash
git clone https://github.com/a831ard0/astrolabio.git
cd astrolabio

# Backend
cd backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python demo/generar_datos.py     # 11.5M filas ficticias, ~8 s, 116 MB
./venv/bin/python demo/sembrar.py           # modelo, tablero y usuarios de ejemplo
./venv/bin/python -m uvicorn app.main:app --reload --port 8000

# Interfaz, en otra terminal
cd frontend
npm install
npm run dev
```

<http://localhost:5173> — `admin@example.com` / `astrolabio-demo-2026`.

### Las pruebas

```bash
cd backend && ./venv/bin/python -m pytest -q          # 530 pasando, 47 saltadas
```

Si la base de demostración no existe, `pytest` la genera solo. Con
`ASTROLABIO_DEMO_RAPIDO=1` genera una versión 20 veces más chica, que es lo que
conviene en CI.

Las pruebas que hablan con MySQL se saltan solas. Para correrlas de verdad:

```bash
./venv/bin/python demo/cargar_mysql.py      # crea la base astrolabio_demo
./venv/bin/python -m pytest -q              # ahora corren todas
```

Antes de un PR:

```bash
cd backend  && ./venv/bin/python -m pytest -q && ./venv/bin/pip-audit
cd frontend && npx tsc --noEmit && npx oxlint src && npm run build
```

---

## 3. Configuración

Todo por variables de entorno con el prefijo `ASTROLABIO_`, o en un archivo `.env`
junto a `docker-compose.yml`. Hay un [`.env.ejemplo`](../.env.ejemplo) con las que
importan.

| Variable | Por omisión | Para qué |
|---|---|---|
| `ENTORNO` | `desarrollo` | `produccion` activa las comprobaciones de arranque |
| `CLAVE_SECRETA` | valor de ejemplo | Firma los tokens. **≥32 caracteres** |
| `CLAVE_CIFRADO` | vacía | Cifra las credenciales de las conexiones (Fernet) |
| `URL_METADATOS` | `sqlite:///datos/astrolabio.db` | Dónde vive el catálogo |
| `RUTA_DUCKDB` | `datos/analitico.duckdb` | La base analítica |
| `DUCKDB_SOLO_LECTURA` | `true` | Consultar no debe poder escribir |
| `MINUTOS_EXPIRACION_TOKEN` | `480` | Ocho horas: una jornada |
| `INTENTOS_MAXIMOS` | `8` | Fallos seguidos antes de frenar la cuenta. `0` lo apaga |
| `MINUTOS_BLOQUEO` | `15` | Cuánto dura el freno |
| `PROGRAMADOR_ACTIVO` | `true` | **Apágalo en todo proceso que no deba ejecutar cargas** |
| `ORIGENES_CORS` | `["http://localhost:5173"]` | En producción, detrás de Caddy, no hace falta |
| `CORREO_ADMIN` | `admin@example.com` | El administrador del primer arranque |
| `SMTP_*` | vacías | Ver §9 |
| `WEBHOOKS_A_RED_INTERNA` | `false` | Permitir webhooks a direcciones privadas |

**En producción el arranque falla** si `CLAVE_SECRETA` sigue en el valor de
ejemplo, si mide menos de 32 caracteres, o si falta `CLAVE_CIFRADO`. Es a
propósito: arrancar con la clave de ejemplo significa que cualquiera puede firmarse
un token de administrador.

> ⚠️ **`PROGRAMADOR_ACTIVO` con varios trabajadores.** Dos procesos con el
> programador encendido compiten por el mismo almacén de tareas y **duplican las
> cargas**. Si algún día corres varios, déjalo encendido en uno solo.

---

## 4. Poner en producción

### Con Docker (recomendado)

```bash
cp .env.ejemplo .env
# genera las claves y ponlas en .env:
openssl rand -hex 32
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

docker compose up -d --build
```

Dos contenedores: `api` (FastAPI) y `web` (Caddy, que sirve la interfaz y hace de
puerta a la API). Dos y no cinco a propósito: con un mantenedor, cada servicio de
más es algo más que administrar, respaldar y que puede fallar de noche.

La interfaz **se compila dentro de Docker**, en una etapa que se descarta: el
servidor no necesita Node. `api` solo escucha en `127.0.0.1:8000`; quien entra de
fuera pasa por Caddy, que es el que lleva HTTPS y las cabeceras de seguridad.

Para HTTPS con certificado automático, pon tu dominio en el `Caddyfile` en lugar de
`:80`. Caddy lo pide y lo renueva solo.

### En un servidor Windows

Funciona igual, con Docker Desktop sobre WSL 2 (o Docker Engine dentro de WSL 2).
Los contenedores son Linux; Windows solo los hospeda. **Lee antes el aviso sobre
ODBC más abajo: es lo único que cambia de verdad.**

> ### Antes de nada: Docker tiene que estar en contenedores **Linux**
>
> Docker en Windows tiene dos modos, y en el equivocado no arranca nada de esto:
>
> ```
> docker: no matching manifest for windows(10.0.17763)/amd64 in the manifest list entries
> ```
>
> Ese mensaje —con cualquier imagen, no solo las de aquí— significa que el demonio
> está en **contenedores de Windows**. Compruébalo:
>
> ```powershell
> docker version --format '{{.Server.Os}}'
> ```
>
> Tiene que decir `linux`. Si dice `windows`, click derecho en el icono de Docker
> Desktop en la bandeja → **Switch to Linux containers**.
>
> **Si no aparece esa opción, el problema es la versión de Windows.** El número
> entre paréntesis del error es la compilación: `17763` es Windows Server 2019 (o
> Windows 10 1809), y **ahí no hay WSL 2** —hace falta 19041 o superior—, así que
> Docker Desktop no puede correr contenedores Linux. Las salidas, en orden:
>
> | | |
> |---|---|
> | **Windows Server 2022** (compilación 20348) con Docker Desktop o Docker Engine en WSL 2 | Lo recomendable si el servidor se puede actualizar |
> | **Una máquina virtual Linux** en Hyper-V —Ubuntu Server 24.04— y Docker dentro | No toca el Windows de al lado. Es lo que yo haría en un 2019 que no se puede mover |
> | **Astrolabio nativo en Windows**, sin Docker — [instrucciones abajo](#sin-docker-nativo-en-windows-server) | Python 3.12 y Node 20 instalados, la API como servicio. Es la única que además resuelve lo de Pervasive, porque ahí sí carga el driver de Windows. **Es la recomendada en Server 2019** |
>
> Que la máquina sea Windows Server 2019 tiene una consecuencia buena: como el
> driver de Pervasive es de Windows, **la tercera opción mata dos pájaros**. Lee
> el aviso de ODBC al final de esta sección antes de decidir.

Instala **Docker Desktop for Windows** y **Git for Windows**, y en PowerShell:

```powershell
git clone https://github.com/a831ard0/astrolabio.git
cd astrolabio
Copy-Item .env.ejemplo .env
```

Las dos claves se generan con PowerShell, sin `openssl` y sin Docker. La secreta:

```powershell
$b = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); ($b | % { $_.ToString('x2') }) -join ''
```

Y la de cifrado, que Fernet exige en base64 *url-safe* de 32 bytes:

```powershell
$b = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_')
```

Ponlas en `.env` (`ASTROLABIO_CLAVE_SECRETA` y `ASTROLABIO_CLAVE_CIFRADO`), pon
`ASTROLABIO_ENTORNO=produccion`, y levanta:

```powershell
docker compose up -d --build
```

Comprueba que está vivo y entra en <http://localhost>:

```powershell
docker compose ps
curl.exe http://localhost/api/salud
```

Cuatro cosas propias de Windows que conviene saber:

- **Que arranque solo al reiniciar el servidor.** En Docker Desktop → *Settings* →
  *General*, marca *Start Docker Desktop when you log in*. Los contenedores traen
  `restart: unless-stopped`, así que vuelven solos. Si el servidor no inicia sesión
  de nadie —lo normal en un servidor—, usa **Docker Engine dentro de WSL 2** con
  `systemd` activado en vez de Docker Desktop, o registra Docker Desktop como
  tarea programada al arranque.
- **Los datos viven en volúmenes de Docker, no en `C:\`.** Es lo que se quiere:
  los volúmenes están en el disco de WSL 2 y ahí SQLite funciona bien. Montar
  `datos/` en una carpeta de Windows o en una unidad de red **rompe el bloqueo de
  archivos de SQLite** y corrompe los metadatos. No lo hagas.
- **Por eso el respaldo se saca del volumen**, no copiando una carpeta (ver §5,
  hay una versión para Windows).
- **Los finales de línea.** `git config --global core.autocrlf false` antes de
  clonar. Con `autocrlf true`, Git convierte los archivos a CRLF y los guiones que
  corren dentro de los contenedores Linux fallan con un error que no menciona
  nada de esto.

> ### ⚠️ ODBC en Windows: los drivers de Windows NO sirven dentro de Docker
>
> Esto es importante para cualquier origen sobre Pervasive/Actian.
>
> Un contenedor de Docker en Windows es **Linux**. Un driver ODBC de Windows es una
> DLL, y **una DLL no se carga en Linux** — da igual que el DSN esté perfectamente
> configurado en el Administrador de orígenes de datos de la máquina anfitriona: el
> contenedor no lo ve y no podría usarlo aunque lo viera.
>
> Los DSN, además, son locales a la máquina donde se crearon.
>
> Las opciones, en orden de sensatez:
>
> | | Cuándo |
> |---|---|
> | **El cliente Linux de Actian dentro de la imagen. Ya está preparado**: se deja el paquete en `backend/drivers/` y la construcción lo instala y lo registra sola. Ver [su README](../backend/drivers/README.md) | Si sistemas consigue la licencia del cliente **Linux de 64 bits**. Es la salida limpia y deja todo en Docker |
> | **Correr el backend nativo en Windows**, sin Docker, con el cliente Pervasive de **64 bits** | Si solo existe el cliente Windows. Python 3.12 + un servicio; Caddy puede seguir en Docker o instalarse aparte |
> | **Un puente**: el backend en Docker y un pequeño servicio en Windows que exponga los datos de Pervasive | Solo si las otras dos se cierran. Es una pieza más que mantener |
>
> Recuerda el otro problema, que es anterior a Docker: los DSN de las agencias
> están en el Administrador ODBC **de 32 bits**, y ningún proceso de 64 bits puede
> cargar un driver de 32 bits. Haga falta Linux o Windows, el cliente tiene que ser
> de 64 bits.
>
> **Lo que sí funciona hoy en Docker sobre Windows:** MySQL/MariaDB (conector
> nativo), archivos CSV/Excel/Parquet, y por ODBC todo lo que tenga driver de
> Linux —MariaDB ya viene instalado en la imagen, PostgreSQL y SQL Server son una
> línea de `apt-get` en el `Dockerfile`, que está comentado con cuál—.
>
> Mi recomendación: **monta Docker ya** con los orígenes que sí funcionan y empieza
> a hacer tableros. La decisión de Pervasive depende de qué licencia consiga
> sistemas, y no debería frenar todo lo demás.

### Sin Docker, en Linux

Un servicio de systemd con `uvicorn`, y Caddy o nginx delante. Lo esencial:

- Corre como un usuario **sin privilegios**.
- `WorkingDirectory` en `backend/`.
- Las variables de entorno en el archivo de la unidad o en un `EnvironmentFile`.
- Un solo trabajador, o el programador en uno solo.

### Sin Docker, nativo en Windows Server

**Esta es la instalación recomendada si el servidor es Windows Server 2019 y los
datos salen de Pervasive/Actian**, por dos razones que se juntan:

- En Server 2019 **no hay contenedores Linux**: WSL 2 pide compilación 19041 o
  superior, Docker Desktop no se soporta en Windows Server, y LCOW —el apaño que
  existía— está descontinuado.
- El driver ODBC de Pervasive es de Windows. Nativo **sí carga**; dentro de un
  contenedor Linux, no. Ver el aviso de ODBC más arriba.

El código no usa nada exclusivo de POSIX y todas las rutas van por `pathlib`. Hay
un trabajo de integración continua que corre las pruebas en `windows-latest`, así
que esto está probado y no supuesto.

#### Lo que hay que instalar antes

| | Dónde | Ojo con |
|---|---|---|
| **Python 3.12** | [python.org](https://www.python.org/downloads/windows/) → *Windows installer (**64-bit**)* | Marca **Add python.exe to PATH** e **Install for all users** (lo segundo hace falta para correrlo como servicio) |
| **Node 20+** | [nodejs.org](https://nodejs.org) → *Windows Installer (.msi), 64-bit* | Solo se usa para compilar la interfaz, una vez |
| **Git for Windows** | [git-scm.com](https://git-scm.com/download/win) | |

> **Python tiene que ser de 64 bits.** Con el de 32, DuckDB se queda en unos 3 GB
> de memoria y una consulta sobre millones de filas se muere. Y además cargaría
> los drivers ODBC de 32 bits, que es justo de lo que hay que salir. Compruébalo
> con `py -0` (tiene que listar `3.12`) y:
>
> ```powershell
> py -3.12 -c "import struct; print(struct.calcsize('P') * 8)"
> ```

#### El guion que hace todo

```powershell
git config --global core.autocrlf false
git clone https://github.com/a831ard0/astrolabio.git C:\astrolabio
cd C:\astrolabio
.\instalar-windows.ps1
```

Crea el entorno de Python, instala las dependencias, compila la interfaz, genera
las dos claves si faltan y **comprueba que la API arranca y responde** antes de
darse por bueno. Se puede volver a correr: no pisa nada que ya esté bien.

Si `Get-ExecutionPolicy` lo impide:
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

> **Las claves generadas no se vuelven a generar nunca.** Si `CLAVE_CIFRADO` ya
> existe, el guion no la toca — cambiarla deja **ilegibles todas las contraseñas
> de las conexiones ya guardadas**, sin recuperación posible.
>
> Las escribe en `CLAVES-GENERADAS.txt`, con permisos solo para administradores.
> **Cópialas al gestor de secretos y borra ese archivo.** No se imprimen en
> pantalla a propósito: la consola acaba en el historial, en capturas y en el
> texto que uno pega para pedir ayuda.
>
> Si aun así una se ve, rotarla es barato **mientras no haya conexiones
> guardadas**:
>
> ```powershell
> .\instalar-windows.ps1 -RotarClaveCifrado
> ```
>
> Después ya no: las contraseñas guardadas están cifradas con la vieja y hay que
> reescribirlas una por una en **Conexiones → Editar**. Los datasets, modelos y
> tableros no se ven afectados.

Y para dejarlo como servicio, en una consola **de administrador** y con
[NSSM](https://nssm.cc) en el `PATH`:

```powershell
.\instalar-windows.ps1 -Servicios
```

#### A mano, si prefieres verlo paso a paso

```powershell
cd C:\astrolabio\backend
py -3.12 -m venv venv
.\venv\Scripts\pip install -r requirements.txt
```

```powershell
cd C:\astrolabio\frontend
npm ci
npm run build
```

Las variables van en el entorno de la máquina, no en un `.env` suelto que acaba
copiado a donde no debe. Con las claves de los comandos de PowerShell de más
arriba:

```powershell
[Environment]::SetEnvironmentVariable('ASTROLABIO_ENTORNO','produccion','Machine')
[Environment]::SetEnvironmentVariable('ASTROLABIO_CLAVE_SECRETA','<la-secreta>','Machine')
[Environment]::SetEnvironmentVariable('ASTROLABIO_CLAVE_CIFRADO','<la-de-cifrado>','Machine')
```

Y la prueba de humo antes de montar el servicio — tiene que responder
`{"estado":"ok"}`:

```powershell
cd C:\astrolabio\backend
.\venv\Scripts\python -m uvicorn app.main:app --port 8000
```

#### Como servicio de Windows

Para que arranque solo al reiniciar y se levante si se cae, con
[NSSM](https://nssm.cc) (un ejecutable, sin instalador):

```powershell
nssm install Astrolabio C:\astrolabio\backend\venv\Scripts\python.exe
nssm set Astrolabio AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
nssm set Astrolabio AppDirectory C:\astrolabio\backend
nssm set Astrolabio AppStdout C:\astrolabio\registros\salida.log
nssm set Astrolabio AppStderr C:\astrolabio\registros\error.log
nssm set Astrolabio Start SERVICE_AUTO_START
nssm start Astrolabio
```

- **`--host 127.0.0.1`, no `0.0.0.0`.** Quien entra de fuera pasa por Caddy, que
  es el que lleva HTTPS y las cabeceras de seguridad.
- **Un solo proceso.** Con varios, el programador duplica las cargas (ver §3).
- Ponlo a correr con una **cuenta de servicio sin privilegios de administrador**
  (`nssm set Astrolabio ObjectName <dominio\cuenta> <clave>`), con permiso de
  escritura solo sobre `C:\astrolabio\backend\datos`.

Delante va Caddy, que en Windows es un solo `caddy.exe`. Hay un
[`Caddyfile.windows`](../Caddyfile.windows) listo, con las dos diferencias que
importan frente al de Docker: `reverse_proxy 127.0.0.1:8000` en vez del nombre
del contenedor, y `root` con una ruta de Windows.

**Si ya tienes un Caddy** sirviendo otras cosas, no lo reemplaces: copia el
bloque de `Caddyfile.windows` dentro de tu Caddyfile y recarga.

```powershell
caddy reload --config C:\ruta\a\tu\Caddyfile
```

**Si no tenías Caddy**, baja `caddy.exe` y regístralo como servicio:

```powershell
nssm install AstrolabioWeb C:\caddy\caddy.exe
nssm set AstrolabioWeb AppParameters "run --config C:\astrolabio\Caddyfile.windows"
nssm start AstrolabioWeb
```

#### Entrar la primera vez, y qué hacer si no puedes

En el primer arranque, si no hay ningún usuario, Astrolabio crea el
administrador con el correo de `ASTROLABIO_CORREO_ADMIN` y una contraseña
temporal **que solo escribe en el registro de ese arranque** — y como va por
`log.warning`, sale por la salida de error:

```powershell
Select-String -Path C:\astrolabio\registros\error.log -Pattern 'contrasena' -Context 3
```

Si ese registro se perdió —se rotó, se sobrescribió, el servicio se instaló
después de la primera prueba—, no hay que borrar nada. Desde el servidor:

```powershell
cd C:\astrolabio\backend
.\venv\Scripts\python administrar.py listar-usuarios
.\venv\Scripts\python administrar.py restablecer admin@example.com
```

Imprime una contraseña temporal nueva. **Cámbiala al entrar.** Si nunca llegó a
crearse el usuario, `--crear` lo crea como administrador.

> Esto corre en el servidor y con acceso al archivo de metadatos. No es una
> puerta trasera: quien puede ejecutarlo ya podría leer la base entera. Es la
> llave de casa, y por eso el archivo de metadatos tiene que estar en un
> directorio con permisos.

**SQLite admite un escritor a la vez.** Por eso las operaciones largas —traer una
tabla, materializar una transformacion— apuntan su ejecucion en el historial y
**confirman antes de empezar**, en vez de dejar la transaccion abierta mientras
trabajan. Si no, cualquier otra escritura espera el `busy_timeout` (15 s) y
despues falla con «database is locked»; eso se veia como un Error 500 al crear
un flujo mientras corria una extraccion. Si algun dia se agrega otra operacion
larga, esa es la regla a respetar.

Ojo con una cosa: el freno de fuerza bruta vive en memoria del proceso. Si te
frenó la cuenta a base de intentos, restablecer la contraseña no lo levanta —
espera los 15 minutos o reinicia el servicio.

#### El ODBC de Pervasive, aquí sí

Instala en **este mismo servidor** el cliente de Pervasive/Actian de **64 bits** y
crea los DSN de las agencias en el **Administrador de orígenes de datos ODBC (64
bits)** — `odbcad32.exe` de `C:\Windows\System32`, no el de `SysWOW64`, que es el
de 32 bits.

Un DSN es local a la máquina donde se crea: los que están hoy en el servidor del
sistema de origen no existen para Astrolabio hasta que se creen también aquí. Y
va **una conexión por sucursal**, porque va un DSN por sucursal.

Comprueba qué ve Astrolabio:

```powershell
C:\astrolabio\backend\venv\Scripts\python -c "import pyodbc; print(pyodbc.drivers()); print(pyodbc.dataSources())"
```

Eso mismo lo enseña la pantalla de conexiones al elegir el origen Pervasive, y
preselecciona el driver detectado.

**Estos orígenes no tienen esquemas.** El DSN ya apunta a los datos y `SQLTables`
devuelve las tablas sin catálogo ni esquema, así que el explorador no ofrece
ninguno que elegir y las lista todas. En un origen que sí los tenga —un MySQL por
ODBC, por ejemplo— cada tabla se queda con el que declare el driver y los
catálogos del motor (`information_schema`, `mysql`, `pg_catalog`…) no se enseñan.

#### Cuando el driver solo existe de 32 bits: el puente

Lo de arriba supone que se puede instalar el cliente de 64 bits. A veces no: la
aplicación que ya usa ese driver —un sistema de gestión sobre Pervasive es el
caso típico— exige el de 32 bits, y en una máquina solo cabe una versión del
cliente.

Entonces aparece este error, y no hay configuración que lo arregle:

```
[IM014] [Microsoft][Administrador de controladores ODBC] La arquitectura del DSN
especificado no coincide entre el controlador y la aplicación.
```

**Un proceso de 64 bits no puede cargar una librería de 32.** No es un permiso ni
una ruta: son formatos de binario distintos. La única salida es que el driver lo
cargue otro proceso, de 32 bits, y que Astrolabio le hable por el bucle local.

Eso es el puente. Se instala así, como administrador:

```powershell
cd C:\astrolabio; .\instalar-windows.ps1 -Puente32 -Servicios
```

Deja un segundo servicio, `AstrolabioPuente32`, con su propio intérprete de 32
bits en `backend\venv32` y **solo pyodbc** dentro. Escucha en `127.0.0.1:8001` y
exige un token compartido que el guion genera en `backend\datos\puente.token`,
legible solo por administradores y SYSTEM.

Antes hace falta **un Python de 32 bits** instalado al lado del de 64 (el
instalador "Windows installer (32-bit)" de python.org, marcando *Install for all
users* y **sin** marcar *Add python.exe to PATH*). Sirve cualquiera de 3.10 en
adelante y **no tiene que ser la misma versión que usa la API**: el puente no
comparte código con ella, solo usa `pyodbc` y la biblioteca estándar. Después,
`py -0` debe listar alguno acabado en `-32`.

Una vez arriba, en **Conexiones → Nueva → ODBC** aparece la casilla *Cargar el
driver en el puente de 32 bits*, y la lista de DSN de debajo pasa a enseñar los
que ve el puente, que son otros: en Windows, 32 y 64 bits son dos registros
separados y no se ven entre sí.

Qué esperar:

| | |
|---|---|
| **Coste** | 12% más lento que ODBC directo, medido sobre 200,000 filas. Se pierde en el ruido de una carga nocturna. |
| **Qué NO cambia** | Los tipos. Un DECIMAL sigue siendo DECIMAL y una fecha una fecha: los valores viajan por columnas y con su tipo, nunca convertidos a texto ni a float. Hay una prueba que trae la misma tabla por los dos caminos y los compara fila a fila. |
| **Qué vigilar** | Si el puente se cae, las conexiones que lo usan fallan con un mensaje que lo dice por su nombre. Las demás siguen igual. |

Comprobar qué ve el puente desde su lado:

```powershell
Get-Service AstrolabioPuente32; Get-Content C:\astrolabio\registros\AstrolabioPuente32-salida.log -Tail 20
```

El primer renglón de ese registro dice de cuántos bits es y qué drivers ve. Si
dice 64 bits, el servicio está apuntando a `backend\venv` en vez de a
`backend\venv32` y no sirve de nada.

#### Respaldo en Windows

Sin Docker, los metadatos son un archivo normal, pero **no lo copies con
`Copy-Item`**: una copia hecha a mitad de una escritura parece buena y no lo es.

```powershell
C:\astrolabio\backend\venv\Scripts\python -c "import sqlite3; o=sqlite3.connect(r'C:\astrolabio\backend\datos\astrolabio.db'); d=sqlite3.connect(r'C:\respaldos\astrolabio.db'); o.backup(d); d.close(); o.close()"
```

Ponlo en el Programador de tareas, diario, y **prueba una restauración**: parar el
servicio, copiar el respaldo encima, arrancar.

### La lista antes de abrir

- [ ] `ASTROLABIO_ENTORNO=produccion`
- [ ] Las dos claves generadas y guardadas donde guardas los secretos
- [ ] HTTPS delante
- [ ] Contraseña del administrador cambiada
- [ ] Un usuario **de solo lectura** en cada origen de datos
- [ ] Respaldo automático de `datos/` (§5) y **una restauración probada**
- [ ] Una regla de aviso creada **y probada** con su botón
- [ ] `pip-audit` sin hallazgos

---

## 5. Respaldos y recuperación

Tres cosas, y una es la importante:

| Qué | Dónde | Importancia |
|---|---|---|
| **Metadatos** | `datos/astrolabio.db` | **Crítico.** Conexiones, modelos, tableros, políticas, usuarios, historial |
| Datos analíticos | `datos/*.duckdb`, `datos/datasets/` | Reproducible: se puede volver a cargar de los orígenes |
| Configuración | `.env` | Crítico: sin `CLAVE_CIFRADO` **no se pueden descifrar las credenciales guardadas** |

```bash
# Respaldo consistente aunque el servidor esté corriendo (SQLite en modo WAL):
sqlite3 datos/astrolabio.db ".backup '/respaldos/astrolabio-$(date +%F).db'"
```

`.backup` y no `cp`: copiar el archivo mientras hay una escritura a medias produce
un respaldo que parece bueno y no lo es.

**Con Docker** los metadatos están en un volumen, así que el respaldo sale de
dentro del contenedor. Vale igual en Linux, macOS y Windows (PowerShell):

```powershell
docker compose exec api python -c "import sqlite3,datetime; o=sqlite3.connect('/app/datos/astrolabio.db'); d=sqlite3.connect('/app/datos/respaldo.db'); o.backup(d); d.close(); o.close()"
docker compose cp api:/app/datos/respaldo.db "C:\respaldos\astrolabio-$(Get-Date -f yyyy-MM-dd).db"
docker compose exec api rm /app/datos/respaldo.db
```

Restaurar: parar los contenedores, `docker compose cp` del respaldo a
`api:/app/datos/astrolabio.db`, y volver a levantar.

> **No sustituyas el volumen por una carpeta de Windows ni por una unidad de red
> para "poder respaldar copiando".** SQLite necesita bloqueo de archivos, y ahí no
> lo tiene: el resultado es una base corrupta, casi siempre descubierta tarde.

> **Guarda `CLAVE_CIFRADO` junto al respaldo, en un gestor de secretos.** Un
> respaldo de metadatos sin esa clave restaura todo menos las contraseñas de las
> conexiones, y hay que escribirlas una por una en **Conexiones → Editar**.

### Rotar la contraseña de un origen

En **Conexiones → Editar**, se escribe la nueva y se guarda. El resto de los campos
se quedan como estaban y **los datasets de esa conexión no se tocan**: conservan su
historial, su horario y sus columnas elegidas.

Un campo de contraseña en blanco significa «no la cambies», nunca «déjala vacía»:
la API no puede devolver la guardada, así que el formulario la enseña vacía. Editar
prueba la conexión antes de guardar, así que una contraseña mal copiada se detecta
ahí y no en la carga de las 6 de la mañana.

Restaurar: parar el servicio, copiar el archivo a su sitio, arrancar. Las
migraciones se aplican solas.

---

## 6. Actualizar

```bash
git pull
cd backend && ./venv/bin/pip install -r requirements.txt
cd ../frontend && npm ci && npm run build
# reiniciar el servicio
```

El **motor analítico** (`datos/analitico.duckdb`) se crea vacío en el primer
arranque si no existe. Se abre en solo lectura —la API no escribe en él, escribe
Parquet— y en solo lectura DuckDB no puede crear el archivo que le falta, así que
crearlo al arrancar es lo que evita un «database does not exist» en el ETL, los
tableros y el modelo de una instalación por lo demás correcta.

Las migraciones del esquema **se aplican al arrancar**. Son aditivas e idempotentes:
agregan columnas y tablas, nunca borran. Aun así, **respalda antes**.

Con Docker: `docker compose build && docker compose up -d`.

---

## 7. Cómo está hecho por dentro

```
backend/
  app/
    conectores/   MySQL, archivos, ODBC. Molde común en base.py
    rutas/        La API HTTP
    analitico.py  Ejecuta consultas del modelo con las políticas aplicadas
    politicas.py  Seguridad por fila: el ÚNICO camino a una consulta
    cargas.py     Un solo camino para traer datos, del botón y del programador
    flujos.py     Cadenas de pasos
    avisos.py     Correo y webhook cuando algo falla
    programador.py  APScheduler, con su almacén en la misma base
  semantic/       El motor: modelo, compilador de SQL, motor asociativo
  migraciones/    Alembic
  demo/           Datos ficticios y semilla
frontend/src/
  api/            Un solo cliente HTTP; el token viaja siempre
  paginas/        Una por sección
  tablero/        Widgets, filtros, exportación
  modelo/         El lienzo
```

Cuatro decisiones que explican casi todo lo demás:

**1. La base analítica se abre en solo lectura para consultar.** Nada de lo que
pase por el ETL puede modificar una tabla que un tablero está leyendo. Las
transformaciones escriben Parquet en un directorio temporal y **después** lo
reemplazan: si el proceso muere a media escritura, lo que había sigue completo.

**2. Todas las consultas pasan por la capa de políticas.** No hay una vía «sin
políticas». Si el usuario es administrador se resuelve a lista vacía, pero pasa por
ahí igual.

**3. SQLite para los metadatos.** Un archivo que se respalda copiándolo. Está
razonado en [adr/0001](adr/0001-sqlite-para-metadatos.md); el límite conocido es
que no admite varios escritores, y por eso el programador va en un solo proceso.

**4. Parquet en disco, no una base propietaria.** Los datos se leen con pandas,
polars, DuckDB o lo que venga después. No quedan encerrados aquí.

Las notas de por qué cada fase está hecha así están en [docs/README.md](README.md).

---

## 8. Drivers ODBC

`unixodbc` es el intermediario, **no** un driver. Cada origen necesita el suyo:

```
MySQL/MariaDB     apt-get install odbc-mariadb        (ya en la imagen)
PostgreSQL        apt-get install odbc-postgresql
SQL Server        msodbcsql18, del repositorio de Microsoft
Pervasive/Actian  del cliente licenciado del fabricante
Informix          del Client SDK de IBM
```

`GET /api/conexiones/odbc/perfiles` dice qué perfiles conoce Astrolabio y qué
drivers ve el servidor, y la pantalla preselecciona el detectado. Sin eso,
configurar ODBC es adivinar: el nombre del driver tiene que coincidir **exacto** y
el error cuando no coincide («Data source name not found») no dice cuál era el
bueno.

**Un driver ODBC no se puede descargar solo**, como hace DBeaver con los JDBC: es
una librería nativa del sistema, y varias vienen de clientes licenciados.

⚠️ **32 vs 64 bits.** Un proceso de 64 bits no puede cargar un driver de 32 bits. No
es permisos ni cadena: no se cargan juntos. Es el problema típico con clientes
viejos de Pervasive. Si el de 32 no se puede cambiar porque otra aplicación
depende de él, la salida es el **puente de 32 bits** (§4, «Cuando el driver solo
existe de 32 bits»).

---

## 9. Correo y webhooks

Para que los avisos salgan por correo:

```
ASTROLABIO_SMTP_HOST=smtp.tuempresa.com
ASTROLABIO_SMTP_PUERTO=587
ASTROLABIO_SMTP_USUARIO=avisos@tuempresa.com
ASTROLABIO_SMTP_CONTRASENA=...
ASTROLABIO_SMTP_TLS=true
ASTROLABIO_SMTP_REMITENTE=avisos@tuempresa.com
```

El canal **webhook** (Teams, Slack) no necesita nada de esto: la URL es el destino.

Los webhooks hacia direcciones privadas están **bloqueados por defecto**; se
encienden con `ASTROLABIO_WEBHOOKS_A_RED_INTERNA=true`. Las de enlace local
(`169.254.0.0/16`) se rechazan siempre: ahí es donde las nubes publican las
credenciales de la máquina.

Después de configurarlo, **prueba la regla con su botón**. Un canal que nadie probó
no es cobertura.

---

## 10. Cuando algo va mal

**El arranque falla con «CLAVE_SECRETA sigue en el valor de ejemplo».**
Está haciendo su trabajo. Genera las claves (§3).

**«database is locked».**
Dos procesos escribiendo en el SQLite. Casi siempre es un segundo trabajador con el
programador encendido: déjalo en uno solo.

**Una carga programada no corrió.**
Mira el historial del dataset y `GET /api/conexiones/programacion`. Si el servidor
estuvo apagado, no se disparan las corridas atrasadas: se ejecuta una y se sigue
(acumularlas es la forma clásica de tumbar el origen al volver).

**Una consulta va lenta.**
El SQL está a la vista para editores y administradores. Lo habitual es una
dimensión de altísima cardinalidad, o un dataset sin partición por fecha.

**Un tablero dice que hay que elegir un camino.**
No es un error: hay dos formas legítimas de cruzar esas tablas y dan cifras
distintas. Elige la que corresponde; queda guardada en el tablero.

**Los avisos no llegan.**
Pantalla de Avisos → el historial muestra **todo intento**, incluidos los
silenciados y los que fallaron, con el error del canal.

**Después de restaurar, las conexiones no conectan.**
Falta la `CLAVE_CIFRADO` con la que se cifraron. Sin ella hay que volver a crearlas.

### Registros

La API escribe a la salida estándar (`docker compose logs -f api`). Lo que interesa
suele estar en la aplicación, no en el log: **historial** por dataset, flujo y
transformación, y **auditoría** en Gobierno.

---

## 11. Rendimiento

Medido sobre la base de demostración (11.5M filas) en una laptop:

| Operación | Tiempo |
|---|---|
| Consulta de tablero (agregado sobre 500k filas) | < 100 ms |
| Transformación de 500k filas a Parquet | ~2 s |
| Carga MySQL nativo, 60k filas × 20 columnas | 0.3 s |
| La misma por ODBC | 6.4 s |
| Generar la base de demostración entera | 8 s |

**ODBC es unas veinte veces más lento** que un conector nativo, porque pasa fila a
fila por Python. Y su costo es por **celda**, no por fila: elegir columnas es la
palanca que de verdad importa ahí.

Si algo va lento, en este orden: ¿el dataset está partido por fecha?, ¿la carga es
incremental o trae todo cada vez?, ¿la transformación agrupa antes de unir?
