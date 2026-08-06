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
| SO | Linux, macOS o Docker | Linux con Docker |

Software: **Python 3.12+**, **Node 20+** (solo para compilar la interfaz), y
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
cd backend && ./venv/bin/python -m pytest -q          # 308
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

cd frontend && npm ci && npm run build && cd ..    # deja frontend/dist
docker compose up -d
```

Dos contenedores: `api` (FastAPI) y `web` (Caddy, que sirve la interfaz compilada y
hace de puerta a la API). Dos y no cinco a propósito: con un mantenedor, cada
servicio de más es algo más que administrar, respaldar y que puede fallar de noche.

Para HTTPS con certificado automático, pon tu dominio en el `Caddyfile` en lugar de
`:80`. Caddy lo pide y lo renueva solo.

### Sin Docker

Un servicio de systemd con `uvicorn`, y Caddy o nginx delante. Lo esencial:

- Corre como un usuario **sin privilegios**.
- `WorkingDirectory` en `backend/`.
- Las variables de entorno en el archivo de la unidad o en un `EnvironmentFile`.
- Un solo trabajador, o el programador en uno solo.

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
viejos de Pervasive.

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
