# Registro de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el
versionado es [semántico](https://semver.org/lang/es/).

## [No publicado]

Lo que falta y está decidido que se hará: más conectores (PostgreSQL, SQL Server,
SQLite), editar una conexión existente, y que el fin de un flujo dispare otro flujo.
La lista completa vive al final de cada documento de fase.

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
