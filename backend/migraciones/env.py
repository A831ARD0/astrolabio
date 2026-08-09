"""
Entorno de Alembic.

La URL de la base sale de la configuracion de la aplicacion, no de alembic.ini:
un solo sitio donde cambiarla, y las migraciones corren contra la misma base que
el servidor sin poder desalinearse.

`render_as_batch=True` es obligatorio con SQLite: SQLite no sabe hacer
ALTER TABLE para casi nada, asi que Alembic recrea la tabla y copia los datos.
Sin esa bandera, cualquier cambio que no sea agregar una columna falla.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import config as config_app
from app.modelos_db import Base

config = context.config
if config.config_file_name is not None:
    # `disable_existing_loggers=False` NO es opcional aqui, aunque sea el valor
    # contrario al que trae fileConfig por defecto.
    #
    # Las migraciones corren DENTRO del arranque de la API (app.main.arranque),
    # con los loggers de `astrolabio` y de `uvicorn` ya creados. Con el valor por
    # defecto, esta linea los apagaba a todos: se perdia el aviso con la
    # contrasena del administrador del primer arranque —que solo se muestra esa
    # vez— y, a partir de ahi, tambien todo el registro de peticiones.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", config_app().url_metadatos)
target_metadata = Base.metadata


def sin_conexion() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def con_conexion() -> None:
    motor = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with motor.connect() as conexion:
        context.configure(
            connection=conexion,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    sin_conexion()
else:
    con_conexion()
