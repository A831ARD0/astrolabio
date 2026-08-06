"""
Fase 1 contra una base MySQL real en localhost.

Se saltan solas si MySQL no esta disponible, para que la suite siga corriendo en
cualquier maquina sin la base.
"""

import csv
import tempfile
from pathlib import Path

import pytest

from tests.conftest import BASE_MYSQL as BASE, necesita_mysql


# --------------------------------------------------------------------------- #
# Registro y cifrado
# --------------------------------------------------------------------------- #

@necesita_mysql
def test_la_contrasena_nunca_se_devuelve(cliente, cab_admin):
    r = cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": "con_secreto", "tipo": "mysql",
        "config": {"host": "127.0.0.1", "port": 3306, "user": "root",
                   "password": "", "database": BASE},
    })
    assert r.status_code == 201, r.text
    cfg = r.json()["config"]
    assert "password" not in cfg
    assert cfg["user"] == "root"


@necesita_mysql
def test_la_config_se_guarda_cifrada(cliente, cab_admin, conexion_mysql):
    """En la base no debe poder leerse la config en claro."""
    from sqlalchemy import select

    from app.db import CrearSesion
    from app.modelos_db import Conexion

    with CrearSesion() as s:
        crudo = s.scalar(select(Conexion.config_cifrada)
                         .where(Conexion.id == conexion_mysql))
    assert BASE not in crudo
    assert "127.0.0.1" not in crudo


def test_conexion_que_falla_no_se_guarda(cliente, cab_admin):
    r = cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": "inexistente", "tipo": "mysql",
        "config": {"host": "127.0.0.1", "port": 65432, "user": "x",
                   "database": "y"},
    })
    assert r.status_code == 400
    assert "no se guardo" in r.json()["detail"].lower()


def test_faltan_campos_obligatorios(cliente, cab_admin):
    r = cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": "incompleta", "tipo": "mysql", "config": {"host": "x"},
    })
    assert r.status_code == 422
    assert "obligatorios" in r.json()["detail"]


def test_tipo_desconocido(cliente, cab_admin):
    r = cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": "rara", "tipo": "oracle_inventado", "config": {},
    })
    assert r.status_code == 422


def test_editor_no_puede_crear_conexiones(cliente, cab_editor):
    r = cliente.post("/api/conexiones", headers=cab_editor, json={
        "nombre": "x", "tipo": "mysql", "config": {},
    })
    assert r.status_code == 403


def test_lector_no_ve_conexiones(cliente, cab_lector):
    assert cliente.get("/api/conexiones", headers=cab_lector).status_code == 403


# --------------------------------------------------------------------------- #
# Introspeccion contra datos reales
# --------------------------------------------------------------------------- #

@necesita_mysql
def test_probar_conexion(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/probar", headers=cab_admin)
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["detalle"]["tablas"] >= 4         # las de demo/cargar_mysql.py


@necesita_mysql
def test_listar_tablas(cliente, cab_admin, conexion_mysql):
    r = cliente.get(f"/api/conexiones/{conexion_mysql}/tablas", headers=cab_admin)
    assert r.status_code == 200
    nombres = {t["nombre"] for t in r.json()["tablas"]}
    assert {"cat_sucursal", "cat_sucursal", "ventas"} <= nombres


@necesita_mysql
def test_describir_una_tabla(cliente, cab_admin, conexion_mysql):
    """El catalogo de sucursales: el que dice a que base apunta cada una."""
    r = cliente.get(f"/api/conexiones/{conexion_mysql}/tablas/cat_sucursal",
                    headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    cols = {c["nombre"] for c in d["columnas"]}
    assert {"sucursal_id", "sucursal_nombre", "marca_id", "region_id",
            "nombre_conexion"} <= cols
    assert d["filas"] == 40


@necesita_mysql
def test_muestra_de_filas(cliente, cab_admin, conexion_mysql):
    r = cliente.get(f"/api/conexiones/{conexion_mysql}/tablas/cat_marca/muestra"
                    f"?limite=5", headers=cab_admin)
    assert r.status_code == 200
    d = r.json()
    assert len(d["filas"]) == 5
    assert "marca_nombre" in d["columnas"]


@necesita_mysql
def test_tabla_inexistente(cliente, cab_admin, conexion_mysql):
    r = cliente.get(f"/api/conexiones/{conexion_mysql}/tablas/no_existe_tabla",
                    headers=cab_admin)
    assert r.status_code == 400


@necesita_mysql
def test_nombre_de_tabla_malicioso(cliente, cab_admin, conexion_mysql):
    """Los identificadores no se pueden ligar como parametros: se validan."""
    r = cliente.get(f"/api/conexiones/{conexion_mysql}/tablas/"
                    f"cat_marca%60%3B%20DROP%20TABLE%20x%3B%20--",
                    headers=cab_admin)
    assert r.status_code in (400, 404)


# --------------------------------------------------------------------------- #
# Ingesta a Parquet
# --------------------------------------------------------------------------- #

@necesita_mysql
def test_ingesta_completa(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets",
                     headers=cab_admin,
                     json={"nombre": "cat_sucursal", "tabla": "cat_sucursal"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]

    r = cliente.post(f"/api/conexiones/datasets/{ds}/cargar", headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["estado"] == "exito"
    assert d["filas"] == 40
    assert d["modo"] == "completo"


@necesita_mysql
def test_ingesta_incremental_trae_solo_lo_nuevo(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets",
                     headers=cab_admin,
                     json={"nombre": "marcas_inc", "tabla": "cat_marca",
                           "columna_incremental": "marca_id"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]

    # Primera carga: completa, y guarda la marca maxima.
    primera = cliente.post(f"/api/conexiones/datasets/{ds}/cargar",
                           headers=cab_admin).json()
    assert primera["modo"] == "completo"
    assert primera["filas"] == 10
    assert primera["marca_maxima"] is not None

    # Segunda: ya no hay nada nuevo, debe traer 0 filas.
    segunda = cliente.post(f"/api/conexiones/datasets/{ds}/cargar",
                           headers=cab_admin).json()
    assert segunda["modo"] == "incremental"
    assert segunda["filas"] == 0


@necesita_mysql
def test_ingesta_particionada_y_grande(cliente, cab_admin, conexion_mysql):
    """
    ventas: 200,000 filas. Se traen 50,000 particionadas por la fecha que viene
    como TEXTO, que es el caso incomodo: una de cada cien esta vacia y tiene que
    quedar contada aparte, no perdida.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets",
                     headers=cab_admin,
                     json={"nombre": "ventas_part", "tabla": "ventas",
                           "particionar_por": "fecha_texto"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]

    r = cliente.post(f"/api/conexiones/datasets/{ds}/cargar?limite=50000",
                     headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["filas"] == 50000
    assert d["archivos"] > 1, "el particionado deberia generar varios archivos"
    # La columna es varchar con cadenas vacias: se reporta, no se calla.
    assert d["filas_sin_particion"] > 0

    from app.config import config
    raiz = Path(config().ruta_duckdb).parent / "datasets" / "ventas_part"
    assert any(p.name.startswith("anio=") for p in raiz.iterdir())


@necesita_mysql
def test_historial_de_cargas(cliente, cab_admin, conexion_mysql):
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets",
                     headers=cab_admin,
                     json={"nombre": "hist", "tabla": "presupuesto"})
    ds = r.json()["id"]
    cliente.post(f"/api/conexiones/datasets/{ds}/cargar", headers=cab_admin)
    cliente.post(f"/api/conexiones/datasets/{ds}/cargar", headers=cab_admin)

    r = cliente.get(f"/api/conexiones/datasets/{ds}/historial", headers=cab_admin)
    assert r.status_code == 200
    ejec = r.json()["ejecuciones"]
    assert len(ejec) == 2
    assert all(e["estado"] == "exito" for e in ejec)


# --------------------------------------------------------------------------- #
# Conector de archivos
# --------------------------------------------------------------------------- #

@pytest.fixture
def carpeta_archivos():
    d = Path(tempfile.mkdtemp(prefix="meridian_archivos_"))
    with open(d / "ventas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sucursal", "monto", "unidades"])
        w.writerow(["Aurex Valle", "480000.50", "1"])
        w.writerow(["Dalia Valle Alto", "310000.00", "1"])
    # Un .xls que en realidad es HTML: un caso real.
    (d / "bonificaciones.xls").write_text(
        "<html><body><table>"
        "<tr><th>sucursal</th><th>bono</th></tr>"
        "<tr><td>VW Dorada</td><td>15000</td></tr>"
        "<tr><td>SEAT Oaxaca</td><td>8200</td></tr>"
        "</table></body></html>", encoding="windows-1252")
    yield d


@pytest.fixture
def conexion_archivos(cliente, cab_admin, carpeta_archivos):
    r = cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": f"archivos_{carpeta_archivos.name}", "tipo": "archivo",
        "config": {"ruta_base": str(carpeta_archivos)},
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_archivos_lista_y_describe_csv(cliente, cab_admin, conexion_archivos):
    r = cliente.get(f"/api/conexiones/{conexion_archivos}/tablas", headers=cab_admin)
    nombres = {t["nombre"] for t in r.json()["tablas"]}
    assert {"ventas.csv", "bonificaciones.xls"} <= nombres

    r = cliente.get(f"/api/conexiones/{conexion_archivos}/tablas/ventas.csv",
                    headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["filas"] == 2
    assert {c["nombre"] for c in d["columnas"]} == {"sucursal", "monto", "unidades"}


def test_xls_que_es_html_se_lee_igual(cliente, cab_admin, conexion_archivos):
    """La extension miente: el formato se detecta por contenido."""
    r = cliente.get(f"/api/conexiones/{conexion_archivos}/tablas/bonificaciones.xls",
                    headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["filas"] == 2
    assert "sucursal" in {c["nombre"] for c in d["columnas"]}
    assert "html" in d["columnas"][0]["tipo"]


def test_no_se_puede_leer_fuera_del_directorio(cliente, cab_admin, conexion_archivos):
    r = cliente.get(f"/api/conexiones/{conexion_archivos}/tablas/"
                    f"..%2F..%2F..%2Fetc%2Fpasswd", headers=cab_admin)
    assert r.status_code in (400, 404)


def test_ingesta_de_csv_a_parquet(cliente, cab_admin, conexion_archivos):
    r = cliente.post(f"/api/conexiones/{conexion_archivos}/datasets",
                     headers=cab_admin,
                     json={"nombre": "ventas_csv", "tabla": "ventas.csv"})
    ds = r.json()["id"]
    r = cliente.post(f"/api/conexiones/datasets/{ds}/cargar", headers=cab_admin)
    assert r.status_code == 200, r.text
    assert r.json()["filas"] == 2


@necesita_mysql
def test_columna_de_particion_inexistente_avisa_claro(cliente, cab_admin,
                                                      conexion_mysql):
    """
    Se valida antes de mover datos, y el mensaje sugiere columnas parecidas.
    Este caso es real: el README del Qlik nombra 'columna_que_no_existe', que no
    existe en la base.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets",
                     headers=cab_admin,
                     json={"nombre": "col_mala", "tabla": "ventas",
                           "particionar_por": "columna_que_no_existe"})
    ds = r.json()["id"]
    r = cliente.post(f"/api/conexiones/datasets/{ds}/cargar?limite=10",
                     headers=cab_admin)
    assert r.status_code == 400, r.text
    assert "no existe" in r.json()["detail"]

    # Y la ejecucion fallida queda en el historial.
    h = cliente.get(f"/api/conexiones/datasets/{ds}/historial", headers=cab_admin)
    assert h.json()["ejecuciones"][0]["estado"] == "error"


# --------------------------------------------------------------------------- #
# Probar antes de guardar, y dar de baja un dataset
# --------------------------------------------------------------------------- #

def test_probar_config_no_guarda_nada(cliente, cab_admin):
    """
    La interfaz necesita decir "conecta" mientras se escriben los datos. Lo que no
    puede es dejar una conexion a medio hacer en el registro.
    """
    antes = len(cliente.get("/api/conexiones", headers=cab_admin).json())
    r = cliente.post("/api/conexiones/probar-config", headers=cab_admin, json={
        "nombre": "solo_prueba", "tipo": "mysql",
        "config": {"host": "127.0.0.1", "port": 65432, "user": "x",
                   "database": "y"},
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert len(cliente.get("/api/conexiones", headers=cab_admin).json()) == antes


@necesita_mysql
def test_probar_config_con_datos_buenos(cliente, cab_admin):
    r = cliente.post("/api/conexiones/probar-config", headers=cab_admin, json={
        "nombre": "solo_prueba_ok", "tipo": "mysql",
        "config": {"host": "127.0.0.1", "port": 3306, "user": "root",
                   "password": "", "database": BASE},
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_probar_config_no_filtra_la_contrasena_a_la_auditoria(cliente, cab_admin):
    cliente.post("/api/conexiones/probar-config", headers=cab_admin, json={
        "nombre": "con_secreto_prueba", "tipo": "mysql",
        "config": {"host": "127.0.0.1", "port": 65432, "user": "x",
                   "password": "no-debe-aparecer", "database": "y"},
    })
    ev = cliente.get("/api/gobierno/auditoria?accion=conexion_probada",
                     headers=cab_admin).json()["eventos"]
    assert ev, "el intento no quedo registrado"
    assert "no-debe-aparecer" not in str(ev[0])


def test_dar_de_baja_un_dataset_conserva_el_parquet(cliente, cab_admin,
                                                    conexion_archivos):
    """
    Se da de baja casi siempre por un nombre mal puesto, no porque los datos
    sobren. Borrar archivos no tiene vuelta atras, asi que no se hace solo.
    """
    from pathlib import Path

    r = cliente.post(f"/api/conexiones/{conexion_archivos}/datasets",
                     headers=cab_admin,
                     json={"nombre": "ventas_para_borrar", "tabla": "ventas.csv"})
    ds = r.json()["id"]
    cliente.post(f"/api/conexiones/datasets/{ds}/cargar", headers=cab_admin)

    r = cliente.delete(f"/api/conexiones/datasets/{ds}", headers=cab_admin)
    assert r.status_code == 200, r.text
    ruta = Path(r.json()["parquet_conservado"])
    assert any(ruta.rglob("*.parquet")), "se borraron los datos sin pedirlo"

    lista = cliente.get("/api/conexiones/datasets/lista",
                        headers=cab_admin).json()["datasets"]
    assert all(d["nombre"] != "ventas_para_borrar" for d in lista)
    assert cliente.get(f"/api/conexiones/datasets/{ds}/historial",
                       headers=cab_admin).status_code == 404


def test_dar_de_baja_un_dataset_programado_quita_su_horario(cliente, cab_admin,
                                                            conexion_archivos):
    r = cliente.post(f"/api/conexiones/{conexion_archivos}/datasets",
                     headers=cab_admin,
                     json={"nombre": "ventas_programada", "tabla": "ventas.csv"})
    ds = r.json()["id"]
    cliente.put(f"/api/conexiones/datasets/{ds}/programacion", headers=cab_admin,
                json={"cron": "0 6 * * *", "activa": True})
    assert cliente.delete(f"/api/conexiones/datasets/{ds}",
                          headers=cab_admin).status_code == 200

    # Un trabajo huerfano correria de madrugada buscando un dataset que ya no esta.
    trabajos = cliente.get("/api/conexiones/programacion",
                           headers=cab_admin).json()["trabajos"]
    assert all(str(ds) not in t["id"] for t in trabajos), trabajos


def test_un_lector_no_da_de_baja_datasets(cliente, cab_lector):
    assert cliente.delete("/api/conexiones/datasets/1",
                          headers=cab_lector).status_code == 403


def test_un_archivo_con_columna_incremental_si_es_incremental(cliente, cab_admin,
                                                             conexion_archivos):
    """
    La interfaz ofrece columna incremental para cualquier origen. Si el conector de
    archivos no guardaba la marca, la segunda carga volvia a traer todo en silencio
    y el dataset acababa con las filas duplicadas.
    """
    r = cliente.post(f"/api/conexiones/{conexion_archivos}/datasets",
                     headers=cab_admin,
                     json={"nombre": "ventas_incr", "tabla": "ventas.csv",
                           "columna_incremental": "monto"})
    ds = r.json()["id"]

    primera = cliente.post(f"/api/conexiones/datasets/{ds}/cargar",
                           headers=cab_admin).json()
    assert primera["filas"] == 2
    assert primera["marca_maxima"] == "480000.5", primera

    # Nada nuevo en el archivo: la segunda carga no debe traer nada.
    segunda = cliente.post(f"/api/conexiones/datasets/{ds}/cargar",
                           headers=cab_admin).json()
    assert segunda["modo"] == "incremental"
    assert segunda["filas"] == 0
    assert segunda["filas_totales"] == 2, "se duplicaron las filas"
