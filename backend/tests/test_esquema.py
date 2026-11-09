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


def test_la_0016_pasa_las_expresiones_comunes_a_formato_y_vuelve(base_vacia):
    """
    Los datasets con una expresión de las formas comunes pasan a formato_fecha (y
    con eso a filtrar en el origen) sin que nadie los toque. Las demás expresiones
    se quedan. Y al bajar de versión, el formato vuelve a quedar como expresión.
    """
    from sqlalchemy import text

    cfg = _config(base_vacia)
    command.upgrade(cfg, "0015")
    motor = create_engine(base_vacia)
    texto = "try_strptime(\"Dt Emissao\", '%Y%m%d')"
    rara = "try_strptime(CAST(c + 19000000 AS VARCHAR), '%Y%m%d')"
    with motor.begin() as con:
        con.execute(text("INSERT INTO conexion (id, nombre, tipo, config_cifrada, "
                         "etiquetas, creado_en) VALUES (1, 'c', 'odbc', '', '{}', "
                         "CURRENT_TIMESTAMP)"))
        for i, (col, expr) in enumerate([("Dt Emissao", texto), ("c", rara)], 1):
            con.execute(text(
                "INSERT INTO dataset (id, nombre, conexion_id, tabla_origen, "
                "particionar_por, expresion_particion, filas, bytes_parquet, "
                "zona_horaria, programacion_activa, creado_en) "
                "VALUES (:i, :n, 1, 't', :c, :e, 0, 0, 'UTC', 0, CURRENT_TIMESTAMP)"),
                {"i": i, "n": f"d{i}", "c": col, "e": expr})

    command.upgrade(cfg, "head")
    with motor.connect() as con:
        filas = dict(con.execute(text(
            "SELECT id, formato_fecha || '|' || COALESCE(expresion_particion, '') "
            "FROM dataset WHERE formato_fecha IS NOT NULL")).fetchall())
        quedan = con.execute(text(
            "SELECT expresion_particion FROM dataset WHERE id = 2")).scalar()
    assert filas == {1: "texto:%Y%m%d|"}
    assert quedan == rara

    command.downgrade(cfg, "0015")
    with motor.connect() as con:
        vuelta = con.execute(text(
            "SELECT expresion_particion FROM dataset WHERE id = 1")).scalar()
    assert "Dt Emissao" in vuelta and "%Y%m%d" in vuelta
