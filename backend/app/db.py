"""
Almacen de metadatos: SQLite via SQLAlchemy.

SQLite en modo WAL aguanta de sobra la carga de metadatos de Astrolabio: las
escrituras son escasas (guardar un modelo, un dashboard) y las consultas
analiticas van a DuckDB, no aqui. Cambiar a PostgreSQL despues es cambiar
ASTROLABIO_URL_METADATOS; el resto del codigo no se entera.
"""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import config


def _crear_motor():
    url = config().url_metadatos
    kwargs: dict = {"echo": False, "future": True}

    if url.startswith("sqlite"):
        archivo = url.replace("sqlite:///", "")
        Path(archivo).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False porque FastAPI atiende en varios hilos.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}

    motor = create_engine(url, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(motor, "connect")
        def _ajustes_sqlite(dbapi_con, _):
            cur = dbapi_con.cursor()
            cur.execute("PRAGMA journal_mode=WAL")      # lectores no bloquean
            cur.execute("PRAGMA foreign_keys=ON")       # integridad referencial
            cur.execute("PRAGMA busy_timeout=15000")    # espera en vez de fallar
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return motor


motor = _crear_motor()
CrearSesion = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


def obtener_sesion() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesion por peticion."""
    sesion = CrearSesion()
    try:
        yield sesion
        sesion.commit()
    except Exception:
        sesion.rollback()
        raise
    finally:
        sesion.close()
