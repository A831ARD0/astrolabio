"""Astrolabio — punto de entrada de la API."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app import programador, trabajos
from app.config import VERSION, config
from app.db import CrearSesion
from app.esquema import actualizar as actualizar_esquema
from app.modelos_db import Rol, Usuario
from app.rutas import (
    auth, avisos, catalogo, conexiones, dashboards, envios, flujos, gobierno,
    modelos, proyectos, transformaciones,
)
from app.seguridad import hashear

log = logging.getLogger("astrolabio")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# El nivel, explicito en NUESTRO logger y no heredado de la raiz: las migraciones
# corren dentro del arranque y `alembic.ini` deja la raiz en WARNING, con lo que
# todo lo que la aplicacion registrara con log.info() se perderia a partir de ahi.
log.setLevel(logging.INFO)

@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    """
    Arranque y apagado. Es un `lifespan` y no `@app.on_event` porque los eventos
    estan obsoletos desde Starlette 0.26 y avisan en cada corrida de pruebas.

    `arranque` se define mas abajo a proposito: el orden de lectura del archivo es
    primero que es la app y luego que hace al arrancar.
    """
    arranque()
    yield
    programador.detener()


app = FastAPI(
    title="Astrolabio",
    description="Plataforma de BI: conectar, transformar, modelar y publicar",
    version=VERSION,
    lifespan=ciclo_de_vida,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config().origenes_cors,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(avisos.router)
app.include_router(catalogo.router)
app.include_router(conexiones.router)
app.include_router(dashboards.router)
app.include_router(envios.router)
app.include_router(flujos.router)
app.include_router(gobierno.router)
app.include_router(modelos.router)
app.include_router(proyectos.router)
app.include_router(transformaciones.router)


def arranque() -> None:
    # Migraciones, no create_all: create_all crea tablas pero no las altera, y
    # una columna nueva sobre una base con datos dejaba el arranque roto.
    actualizar_esquema()

    with CrearSesion() as sesion:
        hay_usuarios = sesion.scalar(select(func.count()).select_from(Usuario))
        if not hay_usuarios:
            # Contraseña temporal, visible solo en el log del primer arranque.
            import secrets
            temporal = secrets.token_urlsafe(12)
            sesion.add(Usuario(
                email=config().correo_admin, nombre="Administrador",
                hash_contrasena=hashear(temporal), rol=Rol.administrador,
            ))
            sesion.commit()
            log.warning(
                "\n%s\n  Usuario administrador creado\n"
                "    correo     : %s\n"
                "    contrasena : %s\n"
                "  Cambiala en el primer ingreso. No se vuelve a mostrar.\n%s",
                "=" * 66, config().correo_admin, temporal, "=" * 66,
            )

    # El motor analitico se abre en SOLO LECTURA, y en solo lectura DuckDB no
    # crea el archivo que le falta. En una instalacion nueva que nunca sembro la
    # demo ese archivo no existe, y entonces el ETL, los tableros y el modelo
    # fallan con «database does not exist» aunque todo lo demas este bien.
    from app.analitico import asegurar_base

    if asegurar_base():
        log.info("Motor analitico creado vacio en %s", config().ruta_duckdb)

    # Lo que quedo a medias en el reinicio anterior. Si no se cierra, la pantalla
    # de tareas ensena 'corriendo' para siempre algo que nadie va a terminar.
    trabajos.limpiar_interrumpidos()

    # Despues de las migraciones: el jobstore necesita su tabla, y sincronizar()
    # necesita leer los datasets.
    programador.arrancar()

    log.info("Astrolabio arriba — entorno=%s  metadatos=%s  analitico=%s",
             config().entorno, config().url_metadatos, config().ruta_duckdb)




@app.get("/api/salud", tags=["sistema"])
def salud():
    return {"estado": "ok", "version": app.version, "entorno": config().entorno}
