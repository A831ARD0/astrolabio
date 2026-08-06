"""
Las migraciones y los modelos tienen que decir lo mismo.

Esta prueba existe por un fallo real: se agregaron columnas a los modelos y el
arranque reventó con "no such column: dataset.cron" sobre una base que ya tenia
datos, porque `create_all` crea tablas pero no las altera. La comprobacion de
abajo detecta ese desfase antes de que lo detecte un servidor en marcha.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.modelos_db import Base

RAIZ = Path(__file__).resolve().parent.parent


def _config(url: str) -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migraciones"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def base_vacia(tmp_path, monkeypatch):
    """Una base nueva, aparte de la de la suite y de la de desarrollo."""
    url = f"sqlite:///{tmp_path / 'esquema.db'}"
    # env.py toma la URL de la configuracion de la app; aqui se fuerza la temporal.
    monkeypatch.setenv("ASTROLABIO_URL_METADATOS", url)
    from app.config import config

    config.cache_clear()
    yield url
    config.cache_clear()


def test_las_migraciones_construyen_el_esquema_de_los_modelos(base_vacia):
    """
    Se aplican todas las migraciones sobre una base vacia y se compara con los
    modelos. Cualquier diferencia significa que falta una migracion.
    """
    command.upgrade(_config(base_vacia), "head")

    motor = create_engine(base_vacia)
    with motor.connect() as con:
        ctx = MigrationContext.configure(con, opts={"compare_type": True})
        diferencias = [
            d for d in compare_metadata(ctx, Base.metadata)
            # La tabla del programador la crea APScheduler, no los modelos.
            if "tarea_programada" not in str(d)
        ]
    assert diferencias == [], (
        "El esquema de las migraciones no coincide con los modelos. "
        f"Falta una migracion para: {diferencias}"
    )


def test_las_migraciones_se_pueden_aplicar_dos_veces(base_vacia):
    """Aplicar sobre una base ya al dia no debe fallar ni duplicar nada."""
    cfg = _config(base_vacia)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")


def test_la_migracion_es_idempotente_sobre_un_esquema_ya_completo(base_vacia):
    """
    El caso que hizo falta resolver: 0001 crea el esquema con los modelos
    actuales (asi que las columnas nuevas ya vienen), y 0002 tiene que darse
    cuenta y no intentar agregarlas otra vez.
    """
    motor = create_engine(base_vacia)
    Base.metadata.create_all(motor)          # como si la base ya existiera al dia
    cfg = _config(base_vacia)
    command.upgrade(cfg, "head")

    # Sin numero fijo: agregar una migracion no deberia romper esta prueba.
    from alembic.script import ScriptDirectory

    cabeza = ScriptDirectory.from_config(cfg).get_current_head()
    with motor.connect() as con:
        ctx = MigrationContext.configure(con)
        assert ctx.get_current_revision() == cabeza
