# ADR 0002 — Alembic para el esquema de metadatos

Fecha: 2026-08-04
Estado: aceptada

## Contexto

Hasta ahora el esquema de metadatos se creaba con `Base.metadata.create_all()` al
arrancar. Estaba anotado como deuda consciente, con el disparador escrito en el
código: *"al primer cambio de esquema en producción se pasa a Alembic"*.

Ese momento llegó. Al agregar las columnas de programación de cargas
(`dataset.cron`, `zona_horaria`, `programacion_activa`, `carga_ejecucion.origen`,
`detalle`), el servidor dejó de arrancar:

```
sqlite3.OperationalError: no such column: dataset.cron
```

`create_all` crea tablas que no existen; **no altera** las que ya están. Las
pruebas no lo detectaron porque cada corrida parte de una base temporal vacía. La
base de desarrollo, con usuarios y auditoría dentro, quedó inservible.

## Decisión

**Alembic gestiona el esquema, y el arranque aplica las migraciones pendientes.**

Adopción sobre una base que ya tenía datos, en dos revisiones:

- **0001 `esquema_base`** — usa `create_all(checkfirst=True)`. En una base nueva
  crea todo; en la que ya existía no toca nada. Es la única revisión que se
  permite ser declarativa, y solo porque su trabajo es marcar el punto de partida.
- **0002 `programacion_de_cargas`** — agrega cada columna **solo si falta**. La
  comprobación es necesaria porque 0001 crea el esquema con los modelos actuales
  (así que en una base nueva las columnas ya vienen), mientras que en la base vieja
  faltan. Sin ella, una de las dos rutas falla.

Otros detalles:

- La URL de la base la lee `migraciones/env.py` de la configuración de la
  aplicación, no de `alembic.ini`: un solo sitio donde cambiarla, y las
  migraciones no pueden apuntar a otra base que el servidor.
- `render_as_batch=True`, obligatorio con SQLite: SQLite no sabe hacer
  `ALTER TABLE` para casi nada, así que Alembic recrea la tabla y copia los datos.
- Las **pruebas siguen usando `create_all`** sobre una base temporal: es más
  rápido y no depende del historial de migraciones.

## Por qué aplicarlas al arrancar y no a mano

Con un solo mantenedor, un paso manual de despliegue que se puede olvidar es un
paso que se olvidará; y olvidarlo deja el servidor corriendo contra un esquema
viejo, que es el fallo que motivó esta decisión. El riesgo contrario —migrar sin
querer— se acota con SQLite (un archivo que se respalda copiándolo) y con que las
migraciones se escriben a mano y se revisan.

## La prueba que evita la repetición

`tests/test_esquema.py` aplica todas las migraciones sobre una base vacía y
compara el resultado contra los modelos con `compare_metadata`. Cualquier
diferencia significa que falta una migración, y falla en pytest en vez de fallar en
un arranque.

También se comprueba que las migraciones se pueden aplicar dos veces y que son
idempotentes sobre un esquema ya completo.

## Consecuencias

- Todo cambio de modelo necesita ahora su migración. Es el costo, y es el punto.
- `alembic revision --autogenerate -m "..."` propone el diff; **hay que leerlo**,
  sobre todo con SQLite, donde un cambio de tipo implica recrear la tabla.
- Antes de una migración sobre datos que importen: copiar el archivo `.db`. Es un
  `cp`; no hay excusa para no hacerlo.
