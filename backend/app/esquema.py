"""
Puesta al dia del esquema de metadatos.

Se ejecuta al arrancar. La razon de hacerlo automatico y no a mano: el servidor
nunca debe quedar corriendo contra un esquema viejo. Ya paso — se agregaron
columnas al modelo, `create_all` no altera tablas existentes, y el arranque
reventó con "no such column: dataset.cron" sobre una base que si tenia datos.

Las pruebas no pasan por aqui: crean su esquema con `create_all` sobre una base
temporal, que es mas rapido y no depende del historial de migraciones.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

log = logging.getLogger("astrolabio.esquema")

RAIZ = Path(__file__).resolve().parent.parent


def actualizar() -> None:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migraciones"))
    command.upgrade(cfg, "head")
    log.info("Esquema de metadatos al dia")
