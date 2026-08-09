"""
Configuracion de pytest.

Cada corrida usa una base de metadatos limpia y temporal; la base analitica de
demostracion se lee tal cual, en solo lectura.

**Si la base analitica no existe, se genera.** Asi `pytest` funciona en un clon
recien hecho sin ningun paso previo: una suite que exige preparar datos a mano es
una suite que se deja de correr. Tarda un par de minutos la primera vez y despues
ya esta ahi; con `ASTROLABIO_DEMO_RAPIDO=1` genera una version 20 veces mas chica,
que es lo que conviene en CI.
"""

import os
import tempfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

# El entorno, ANTES de cualquier import que toque la configuracion: `config()`
# esta cacheada con lru_cache, asi que el primero que la llame fija los valores
# para toda la corrida. Generar la base de demostracion tambien la llama —lee de
# ahi donde escribir—, de modo que esto tiene que ir primero o las pruebas se
# irian contra la base de metadatos de verdad en vez de la temporal.
_tmp = tempfile.mkdtemp(prefix="astrolabio_test_")
os.environ["ASTROLABIO_URL_METADATOS"] = f"sqlite:///{_tmp}/prueba.db"
os.environ["ASTROLABIO_RUTA_DUCKDB"] = str(RAIZ / "datos" / "analitico.duckdb")
os.environ["ASTROLABIO_CLAVE_SECRETA"] = "clave-solo-para-pruebas-no-produccion"
os.environ["ASTROLABIO_ENTORNO"] = "desarrollo"

BASE_ANALITICA = Path(os.environ["ASTROLABIO_RUTA_DUCKDB"])
if not BASE_ANALITICA.exists():
    import sys
    sys.path.insert(0, str(RAIZ))
    from demo.generar_datos import generar

    print(f"\nNo hay base de demostracion en {BASE_ANALITICA}; generandola...")
    generar(rapido=os.environ.get("ASTROLABIO_DEMO_RAPIDO") == "1")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import CrearSesion, motor  # noqa: E402
from app.main import app  # noqa: E402
from app.modelos_db import AtributoUsuario, Base, Rol, Usuario  # noqa: E402
from app.seguridad import hashear  # noqa: E402

CONTRASENA = "prueba-larga-1234"


@pytest.fixture(scope="session", autouse=True)
def base_lista():
    Base.metadata.create_all(motor)
    with CrearSesion() as s:
        s.add(Usuario(email="admin@pruebas.example.com", nombre="Admin",
                      hash_contrasena=hashear(CONTRASENA), rol=Rol.administrador))
        s.add(Usuario(email="editor@pruebas.example.com", nombre="Editor",
                      hash_contrasena=hashear(CONTRASENA), rol=Rol.editor))

        # Lector regional: solo debe ver el estado 3 (Veracruz), donde hay
        # exactamente una sucursal (Ekos Río Blanco). Eso hace la prueba verificable.
        lector = Usuario(email="norte@pruebas.example.com", nombre="Direccion Regional",
                         hash_contrasena=hashear(CONTRASENA), rol=Rol.lector)
        lector.atributos = [AtributoUsuario(clave="region_id", valor="3")]
        s.add(lector)

        # Lector sin el atributo que la politica necesita: debe fallar cerrado.
        s.add(Usuario(email="incompleto@pruebas.example.com", nombre="Sin atributo",
                      hash_contrasena=hashear(CONTRASENA), rol=Rol.lector))
        s.commit()
    yield


@pytest.fixture(autouse=True)
def sin_bloqueos():
    """
    El freno a los intentos de ingreso vive en memoria del proceso y sobrevive
    entre pruebas. Sin esto, una prueba que falla al entrar a proposito dejaria
    bloqueada a la siguiente y el fallo apareceria en el sitio equivocado.
    """
    from app import intentos
    intentos.limpiar()
    yield


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def _token(cliente, email: str) -> str:
    r = cliente.post("/api/auth/token",
                     data={"username": email, "password": CONTRASENA})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def cab_admin(cliente):
    return {"Authorization": f"Bearer {_token(cliente, 'admin@pruebas.example.com')}"}


@pytest.fixture
def cab_editor(cliente):
    return {"Authorization": f"Bearer {_token(cliente, 'editor@pruebas.example.com')}"}


@pytest.fixture
def cab_lector(cliente):
    return {"Authorization": f"Bearer {_token(cliente, 'norte@pruebas.example.com')}"}


# --------------------------------------------------------------------------- #
# MySQL real
#
# Las pruebas que lo usan se saltan solas si la base no esta disponible, para que
# la suite corra en cualquier maquina.
# --------------------------------------------------------------------------- #

BASE_MYSQL = os.environ.get("ASTROLABIO_PRUEBA_BASE", "astrolabio_demo")


def _mysql_disponible() -> bool:
    """
    Hay MySQL Y la base de demostracion esta cargada.

    Se comprueban las dos cosas: con el servidor arriba pero sin la base, estas
    pruebas fallarian con un error de SQL que no dice que hacer, en vez de
    saltarse diciendo el motivo. Para cargarla: python demo/cargar_mysql.py
    """
    try:
        import pymysql
        c = pymysql.connect(host="127.0.0.1", port=3306, user="root",
                            password="", database=BASE_MYSQL, connect_timeout=3)
        c.close()
        return True
    except Exception:
        return False


necesita_mysql = pytest.mark.skipif(
    not _mysql_disponible(),
    reason=f"Falta MySQL con la base {BASE_MYSQL!r}. "
           f"Cargala con: python demo/cargar_mysql.py",
)


@pytest.fixture
def conexion_mysql(cliente, cab_admin):
    r = cliente.get("/api/conexiones", headers=cab_admin)
    for c in r.json():
        if c["nombre"] == "demo_mysql":
            return c["id"]
    r = cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": "demo_mysql", "tipo": "mysql",
        "config": {"host": "127.0.0.1", "port": 3306, "user": "root",
                   "password": "", "database": BASE_MYSQL},
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# ODBC
#
# El conector ODBC se prueba contra el MISMO MySQL, por dos razones: es el unico
# origen real que hay a mano, y comparar las dos rutas contra la misma tabla es la
# forma de demostrar que ODBC trae exactamente los mismos datos que el conector
# nativo. no hay otro origen ODBC a mano.
#
# El driver no se busca por nombre registrado (`pyodbc.drivers()` esta vacio si
# nadie escribio odbcinst.ini) sino por ruta del .dylib/.so, que es lo que se
# puede resolver sin tocar la configuracion de la maquina.
# --------------------------------------------------------------------------- #

_RUTAS_DRIVER = (
    "/opt/homebrew/lib/mariadb/libmaodbc.dylib",
    "/opt/homebrew/opt/mariadb-connector-odbc/lib/mariadb/libmaodbc.dylib",
    "/usr/local/lib/mariadb/libmaodbc.dylib",
    "/usr/lib/x86_64-linux-gnu/odbc/libmaodbc.so",
    "/usr/lib/aarch64-linux-gnu/odbc/libmaodbc.so",
)


def driver_odbc() -> str | None:
    """Ruta del driver ODBC de MySQL/MariaDB en esta maquina, si hay alguno."""
    from glob import glob
    from pathlib import Path
    for ruta in _RUTAS_DRIVER:
        if Path(ruta).exists():
            return ruta
    # Homebrew versiona el directorio del Cellar; se busca sin fijar la version.
    for patron in ("/opt/homebrew/Cellar/mariadb-connector-odbc/*/lib/mariadb/libmaodbc.dylib",
                   "/opt/homebrew/Cellar/mysql-connector-odbc/*/lib/*.so"):
        encontrados = sorted(glob(patron))
        if encontrados:
            return encontrados[-1]
    return None


def _odbc_disponible() -> bool:
    try:
        import pyodbc  # noqa: F401
    except ImportError:
        return False
    return _mysql_disponible() and driver_odbc() is not None


necesita_odbc = pytest.mark.skipif(
    not _odbc_disponible(),
    reason="Falta pyodbc, el driver ODBC de MySQL, o el MySQL local",
)


def config_odbc() -> dict:
    return {"driver": driver_odbc(), "host": "127.0.0.1", "port": 3306,
            "user": "root", "database": BASE_MYSQL}


@pytest.fixture
def conexion_odbc(cliente, cab_admin):
    # La base de metadatos de pruebas sobrevive entre pruebas, asi que se reutiliza
    # la conexion si ya esta, igual que con `conexion_mysql`.
    for c in cliente.get("/api/conexiones", headers=cab_admin).json():
        if c["nombre"] == "demo_odbc":
            return c["id"]
    r = cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": "demo_odbc", "tipo": "odbc", "config": config_odbc(),
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def cab_incompleto(cliente):
    return {"Authorization": f"Bearer {_token(cliente, 'incompleto@pruebas.example.com')}"}


@pytest.fixture(scope="session")
def yaml_modelo() -> str:
    """El modelo de demostracion, tal cual se publica."""
    return (RAIZ / "demo" / "modelo_demo.yaml").read_text(encoding="utf-8")


@pytest.fixture
def modelo_id(cliente, cab_admin, yaml_modelo) -> int:
    """Crea el modelo una vez y reutiliza su id."""
    r = cliente.get("/api/modelos", headers=cab_admin)
    for m in r.json():
        if m["nombre"] == "demo_comercial":
            return m["id"]
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": "demo_comercial",
        "descripcion": "Modelo de pruebas",
        "yaml": yaml_modelo,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def conexion_archivos_etl(cliente, cab_admin):
    """
    Un dataset real llamado 'ventas_csv_etl'. Existe para probar que el nombre de
    una transformacion no puede chocar con el de un dataset.
    """
    import csv
    import tempfile
    from pathlib import Path

    lista = cliente.get("/api/conexiones", headers=cab_admin).json()
    conexion = next((c["id"] for c in lista if c["nombre"] == "archivos_etl"), None)
    if conexion is None:
        d = Path(tempfile.mkdtemp(prefix="meridian_etl_"))
        with open(d / "ventas.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["sucursal", "monto"])
            w.writerow(["Aurex Valle", "1000"])
        r = cliente.post("/api/conexiones", headers=cab_admin, json={
            "nombre": "archivos_etl", "tipo": "archivo",
            "config": {"ruta_base": str(d)}})
        assert r.status_code == 201, r.text
        conexion = r.json()["id"]

    datasets = cliente.get("/api/conexiones/datasets/lista",
                           headers=cab_admin).json()["datasets"]
    for ds in datasets:
        if ds["nombre"] == "ventas_csv_etl":
            return ds["id"]
    r = cliente.post(f"/api/conexiones/{conexion}/datasets", headers=cab_admin,
                     json={"nombre": "ventas_csv_etl", "tabla": "ventas.csv"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def cargar(cliente, cab, dataset_id: int, espera: float = 120, **params) -> dict:
    """
    Lanza la carga de un dataset y devuelve como salio.

    Desde que las cargas van en segundo plano, la peticion contesta 202 y no
    trae resultado: esta ahora en el historial, que ademas guarda mas que antes
    -archivos, particiones, marca maxima-. Este ayudante hace las dos cosas y
    espera al trabajador, porque comprobar sin esperar seria una carrera.

    Lanza AssertionError si la carga fallo, con el mensaje del historial: es lo
    que antes hacia el 400 de la peticion.
    """
    from app import trabajos

    r = cliente.post(f"/api/conexiones/datasets/{dataset_id}/cargar",
                     headers=cab, params=params or None)
    assert r.status_code == 202, r.text
    assert trabajos.esperar(espera), "la carga no termino a tiempo"
    return ultima_carga(cliente, cab, dataset_id)


def recargar_rango(cliente, cab, dataset_id: int, desde: str, hasta: str,
                   espera: float = 120) -> dict:
    """Como `cargar`, para la recarga de un rango de fechas."""
    from app import trabajos

    r = cliente.post(f"/api/conexiones/datasets/{dataset_id}/recargar-rango",
                     headers=cab, json={"desde": desde, "hasta": hasta})
    assert r.status_code == 202, r.text
    assert trabajos.esperar(espera), "la recarga no termino a tiempo"
    return ultima_carga(cliente, cab, dataset_id)


def ultima_carga(cliente, cab, dataset_id: int) -> dict:
    h = cliente.get(f"/api/conexiones/datasets/{dataset_id}/historial",
                    headers=cab).json()
    assert h["ejecuciones"], "la carga no dejo historial"
    return h["ejecuciones"][0]
