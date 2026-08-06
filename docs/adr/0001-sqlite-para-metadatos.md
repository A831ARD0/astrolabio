# ADR 0001 — SQLite para metadatos en vez de PostgreSQL

Fecha: 2026-08-04
Estado: aceptado

## Contexto

Astrolabio necesita dos almacenes distintos:

- **Metadatos**: usuarios, conexiones, versiones del modelo, dashboards,
  auditoría. Escritura escasa, lectura frecuente, transaccional.
- **Analítico**: los datos del negocio. Millones de filas, solo lectura para
  consultas. Va en DuckDB.

La recomendación inicial fue PostgreSQL para los metadatos. Al confirmarse que
**el proyecto lo desarrolla y mantiene una sola persona**, esa decisión se
revisó.

## Decisión

**SQLite en modo WAL** para los metadatos, vía SQLAlchemy.

## Razones

1. **Un servicio menos que administrar.** Sin Postgres no hay servidor que
   configurar, actualizar, monitorear ni afinar. Con un solo mantenedor, cada
   componente extra es algo que puede fallar de noche.
2. **Respaldar es copiar un archivo.** Sin `pg_dump`, sin políticas de retención,
   sin credenciales de respaldo. Un `cp` del volumen basta.
3. **La carga real lo justifica.** ~24 usuarios internos. Las escrituras de
   metadatos son eventos humanos (guardar un modelo, un dashboard), no tráfico.
   Las consultas analíticas van a DuckDB, no aquí. El modo WAL permite lectores
   concurrentes sin bloqueo; solo las escrituras se serializan, y son raras.
4. **La sesión no escribe.** La autenticación es JWT sin estado, así que un
   ingreso no genera escritura de sesión.

## Consecuencias

**A favor:** despliegue de dos servicios en vez de tres. Menos superficie de
fallo. Arranque local sin dependencias externas.

**En contra:** una sola escritura concurrente a la vez. Sin réplicas de lectura.
Sin acceso concurrente desde varias máquinas al mismo archivo — si algún día la
API se escala horizontalmente, esta decisión se cae.

**Mitigación:** todo el acceso pasa por SQLAlchemy y ninguna consulta usa SQL
específico de SQLite. Cambiar a PostgreSQL es cambiar la variable
`ASTROLABIO_URL_METADATOS` y correr las migraciones; el código de la aplicación no
se entera.

## Cuándo revisar esta decisión

Migrar a PostgreSQL si ocurre cualquiera de estas:

- Más de una instancia de la API (escalado horizontal o alta disponibilidad)
- Aparecen errores `database is locked` en el log a pesar del `busy_timeout`
- Se supera aproximadamente el centenar de usuarios concurrentes
- Se necesita replicación o recuperación a un punto en el tiempo
