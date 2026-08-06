FROM python:3.12-slim

# unixodbc es el intermediario de ODBC, no un driver. Con esto el conector ODBC
# funciona, pero cada origen necesita ADEMAS su propio driver:
#
#   MySQL/MariaDB     apt-get install -y odbc-mariadb        (ya incluido abajo)
#   PostgreSQL        apt-get install -y odbc-postgresql
#   SQL Server        msodbcsql18, del repositorio de Microsoft
#   Pervasive/Actian  licenciado: se deja en drivers/ y se instala solo (abajo)
#   Informix          del Client SDK de IBM
#
# Los demas se dejan fuera a proposito: instalar drivers que nadie usa engorda la
# imagen. Para agregar uno, se copia y se registra en /etc/odbcinst.ini.
RUN apt-get update && apt-get install -y --no-install-recommends \
        unixodbc unixodbc-dev odbc-mariadb curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Cliente ODBC de Actian Zen / Pervasive PSQL, si lo hay ---------------- #
#
# Va ANTES de copiar el codigo a proposito: el driver cambia una vez al año y el
# codigo cada dia. Al reves, cada edicion de un .py volveria a reinstalar el
# cliente.
#
# `drivers/` esta vacia en el repositorio y su contenido en .gitignore: el
# cliente de Actian es licenciado y no se puede redistribuir. Sistemas lo deja
# ahi y esta linea lo instala. Sin paquete, la imagen se construye igual y sin
# ese driver; con paquete y algo mal, la construccion FALLA en vez de dejar una
# imagen que parece buena y no tiene el driver que se pidio.
COPY drivers/ /tmp/drivers/
COPY instalar-driver-actian.sh .
RUN sh instalar-driver-actian.sh && rm instalar-driver-actian.sh

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY semantic/ ./semantic/
# Las migraciones y su configuracion NO son opcionales: el arranque las ejecuta,
# y sin ellas el contenedor levanta contra un esquema que no existe.
COPY migraciones/ ./migraciones/
COPY alembic.ini .
# La demo va dentro para poder sembrar un contenedor recien creado:
#   docker compose exec api python demo/generar_datos.py
COPY demo/ ./demo/

# Usuario sin privilegios: nada corre como root.
RUN useradd --create-home --shell /bin/bash astrolabio \
    && mkdir -p /app/datos /app/analitico \
    && chown -R astrolabio:astrolabio /app
USER astrolabio

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ASTROLABIO_URL_METADATOS=sqlite:////app/datos/astrolabio.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/salud || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
