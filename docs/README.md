# Documentación

## Para usar y para mantener

| | |
|---|---|
| [Manual de usuario](manual-usuario.md) | Conectar, transformar, modelar, publicar |
| [Manual técnico](manual-tecnico.md) | Instalar, configurar, desplegar, respaldar, actualizar |
| [La marca](marca/README.md) | El nombre, el símbolo, los colores y el tono |

## Notas de ingeniería

No son un tutorial: son el registro de **por qué** cada parte está hecha así, qué se
intentó primero y qué se rompió. Se escribieron mientras se construía, y es lo que
hace que dentro de dos años se pueda cambiar algo sin volver a tropezar en lo mismo.

| | |
|---|---|
| [01 · El modelo semántico](01-modelo-semantico.md) | Entidades, relaciones, métricas, y las trampas que producen cifras mal |
| [02 · Cimientos](02-fase-0-cimientos.md) | Autenticación, políticas, auditoría, y por qué van desde el primer día |
| [03 · Datos](03-fase-1-datos.md) | Conectores, ingesta a Parquet, cargas incrementales, ODBC, ventanas móviles |
| [06 · ETL](06-fase-3-etl.md) | Transformaciones, flujos y avisos |
| [04 · Modelo](04-fase-2-modelo.md) | El lienzo y el diagnóstico |
| [05 · Tableros](05-fase-4-tableros.md) | Widgets, filtros asociativos, exportación |
| [07 · Gobierno](07-fase-6-gobierno.md) | Usuarios, políticas, simulador, auditoría |

### Decisiones de arquitectura

| | |
|---|---|
| [0001 · SQLite para los metadatos](adr/0001-sqlite-para-metadatos.md) | Por qué un archivo y no un servidor de base de datos |

## Cómo leer esto

Si vas a tocar el código, hay un atajo mejor que la documentación: **los comentarios
del propio código**. Casi todas las decisiones raras están explicadas donde ocurren,
y casi siempre en la forma «esto se hace así porque de la otra manera pasó tal cosa».
Si algo parece innecesariamente cuidadoso, probablemente haya una nota al lado
diciendo qué se rompió la primera vez.
