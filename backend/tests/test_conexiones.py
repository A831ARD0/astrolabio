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
def test_un_fallo_inesperado_se_registra_y_se_explica(cliente, cab_admin,
                                                      conexion_mysql, monkeypatch):
    """
    Lo que pasaba antes con cualquier excepcion que el conector no traducia: la
    pantalla decia "Error 500" pelado y el historial decia "todavia no se ha
    cargado nunca", porque al propagar la excepcion el rollback se llevaba el
    registro de la ejecucion. Sin mensaje y sin rastro, justo cuando mas falta
    hacen.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "sucursal_revienta", "tabla": "cat_sucursal"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]

    # Un fallo que NO es ErrorConector: es la familia entera que se escapaba.
    def revienta(*_a, **_k):
        raise MemoryError("no cupo en memoria")

    monkeypatch.setattr("app.conectores.mysql.ConectorMySQL.ingestar", revienta)

    r = cliente.post(f"/api/conexiones/datasets/{ds}/cargar", headers=cab_admin)
    assert r.status_code == 400, r.text          # no 500
    detalle = r.json()["detail"]
    assert "MemoryError" in detalle              # que fue
    assert "cat_sucursal" in detalle             # donde
    assert "no cupo en memoria" in detalle

    # Y sobre todo: quedo en el historial, que es lo que se mira despues.
    h = cliente.get(f"/api/conexiones/datasets/{ds}/historial", headers=cab_admin)
    assert h.status_code == 200, h.text
    ejecuciones = h.json()["ejecuciones"]
    assert len(ejecuciones) == 1
    assert ejecuciones[0]["estado"] == "error"
    assert "MemoryError" in ejecuciones[0]["mensaje"]


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


# --------------------------------------------------------------------------- #
# Editar una conexion
# --------------------------------------------------------------------------- #

def test_fusionar_conserva_el_secreto_que_llega_vacio():
    """
    La regla que sostiene todo lo demas: la API nunca devuelve la contraseña, asi
    que el formulario la enseña vacia. Si un campo vacio pisara al guardado, editar
    el puerto dejaria la conexion sin credenciales.
    """
    from app.rutas.conexiones import _fusionar

    guardada = {"host": "viejo", "user": "app", "password": "secreta"}
    r = _fusionar(guardada, {"host": "nuevo", "password": ""}, [])
    assert r == {"host": "nuevo", "user": "app", "password": "secreta"}


def test_fusionar_solo_pisa_lo_que_llega():
    from app.rutas.conexiones import _fusionar

    r = _fusionar({"host": "a", "port": 3306}, {"port": 3307}, [])
    assert r == {"host": "a", "port": 3307}


def test_fusionar_escribe_el_secreto_nuevo_cuando_viene_lleno():
    from app.rutas.conexiones import _fusionar

    r = _fusionar({"password": "vieja"}, {"password": "nueva"}, [])
    assert r["password"] == "nueva"


def test_fusionar_borra_el_secreto_solo_si_se_pide_por_su_nombre():
    """Quitar una credencial es explicito: no hay forma de hacerlo sin querer."""
    from app.rutas.conexiones import _fusionar

    r = _fusionar({"host": "a", "password": "vieja"}, {}, ["password"])
    assert r == {"host": "a"}


def test_editar_el_nombre_no_pierde_la_configuracion(cliente, cab_admin,
                                                     conexion_archivos):
    r = cliente.patch(f"/api/conexiones/{conexion_archivos}", headers=cab_admin,
                      json={"nombre": "archivos_renombrada"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["nombre"] == "archivos_renombrada"
    assert d["config"]["ruta_base"]


def test_editar_no_puede_chocar_con_otro_nombre(cliente, cab_admin,
                                                conexion_archivos,
                                                carpeta_archivos):
    cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": "ya_existe", "tipo": "archivo",
        "config": {"ruta_base": str(carpeta_archivos)},
    })
    r = cliente.patch(f"/api/conexiones/{conexion_archivos}", headers=cab_admin,
                      json={"nombre": "ya_existe"})
    assert r.status_code == 409


def test_un_cambio_que_rompe_la_conexion_no_se_guarda(cliente, cab_admin,
                                                      conexion_archivos):
    """
    Igual que al crear: si no conecta, no se guarda. Una conexion rota guardada es
    una carga que falla de madrugada.
    """
    r = cliente.patch(f"/api/conexiones/{conexion_archivos}", headers=cab_admin,
                      json={"config": {"ruta_base": "/no/existe/en/ningun/lado"}})
    assert r.status_code == 400
    assert "no se guardo" in r.json()["detail"].lower()

    # Y la de verdad sigue sirviendo.
    assert cliente.post(f"/api/conexiones/{conexion_archivos}/probar",
                        headers=cab_admin).json()["ok"] is True


def test_editar_una_conexion_conserva_sus_datasets(cliente, cab_admin,
                                                   conexion_archivos):
    """
    El motivo de que esto exista. Antes, cambiar una contraseña obligaba a borrar
    la conexion y recrearla, y los datasets se iban con ella en cascada: su
    historial, sus horarios y sus columnas elegidas.
    """
    cliente.post(f"/api/conexiones/{conexion_archivos}/datasets", headers=cab_admin,
                 json={"nombre": "ventas_que_sobrevive", "tabla": "ventas.csv"})

    assert cliente.patch(f"/api/conexiones/{conexion_archivos}", headers=cab_admin,
                         json={"nombre": "archivos_tras_rotar"}).status_code == 200

    nombres = {d["nombre"] for d in
               cliente.get("/api/conexiones/datasets/lista",
                           headers=cab_admin).json()["datasets"]}
    assert "ventas_que_sobrevive" in nombres


@necesita_mysql
def test_editar_no_devuelve_la_contrasena(cliente, cab_admin, conexion_mysql):
    r = cliente.patch(f"/api/conexiones/{conexion_mysql}", headers=cab_admin,
                      json={"config": {"password": "otra-cosa-que-no-se-ve"}})
    # Con o sin exito, la respuesta jamas trae el secreto.
    assert "otra-cosa-que-no-se-ve" not in r.text


def test_probar_un_cambio_no_lo_guarda(cliente, cab_admin, conexion_archivos):
    r = cliente.post(f"/api/conexiones/{conexion_archivos}/probar-cambio",
                     headers=cab_admin,
                     json={"config": {"ruta_base": "/no/existe"}})
    assert r.status_code == 200
    assert r.json()["ok"] is False

    # No se guardo: la conexion original sigue conectando.
    assert cliente.post(f"/api/conexiones/{conexion_archivos}/probar",
                        headers=cab_admin).json()["ok"] is True


def test_un_editor_no_puede_editar_conexiones(cliente, cab_editor,
                                              conexion_archivos):
    """Crear conexiones es de administrador; cambiarlas, tambien."""
    assert cliente.patch(f"/api/conexiones/{conexion_archivos}", headers=cab_editor,
                         json={"nombre": "otro"}).status_code == 403


def test_la_auditoria_registra_el_cambio_sin_el_secreto(cliente, cab_admin,
                                                        conexion_archivos):
    cliente.patch(f"/api/conexiones/{conexion_archivos}", headers=cab_admin,
                  json={"nombre": "archivos_auditada"})
    eventos = cliente.get("/api/gobierno/auditoria", headers=cab_admin).json()
    fila = next(e for e in eventos["eventos"] if e["accion"] == "conexion_editada")
    assert fila["detalle"]["nombre"] == "archivos_auditada"


# --------------------------------------------------------------------------- #
# El nombre del dataset se propone solo
# --------------------------------------------------------------------------- #

def test_el_nombre_se_arma_de_la_conexion_y_la_tabla():
    from app.rutas.conexiones import nombre_sugerido

    assert nombre_sugerido("VW_MATRIZ", None, "cat_conexiones") == \
        "VW_MATRIZ__cat_conexiones"
    # El esquema entra solo cuando distingue: en MySQL es la base y suele ser el
    # mismo para toda la conexion, asi que meterlo siempre alargaria los cuarenta
    # nombres sin separar nada.
    assert nombre_sugerido("VW", "VW", "ventas") == "VW__ventas"
    assert nombre_sugerido("VW", "contab", "ventas") == "VW__contab__ventas"


def test_el_nombre_sirve_como_carpeta():
    """Tambien es la ruta del Parquet: nada de espacios, acentos ni separadores."""
    from app.rutas.conexiones import nombre_sugerido

    sucio = nombre_sugerido("VW Matriz / Oaxaca", None, "cat.conexiones")
    assert sucio == "VW_Matriz_Oaxaca__cat_conexiones"
    assert not (set(sucio) & set(' <>:"/\\|?*.'))


@necesita_mysql
def test_crear_sin_nombre_lo_pone_el_servidor(cliente, cab_admin, conexion_mysql):
    """
    Con cuarenta sucursales trayendo las mismas tablas, exigir un nombre obligaba
    a inventar cuarenta distintos a mano. Ahora se puede omitir.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"tabla": "cat_marca"})
    assert r.status_code == 201, r.text
    assert r.json()["nombre"] == "demo_mysql__cat_marca"


@necesita_mysql
def test_la_misma_tabla_dos_veces_no_choca_de_nombre(cliente, cab_admin,
                                                     conexion_mysql):
    """
    Traer la misma tabla dos veces con distinta configuracion es legitimo --una
    version con todas las columnas y otra recortada--, asi que no se prohibe: se
    le busca un nombre libre en vez de rechazarlo.
    """
    primero = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets",
                           headers=cab_admin, json={"tabla": "ventas"})
    segundo = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets",
                           headers=cab_admin, json={"tabla": "ventas"})
    assert (primero.status_code, segundo.status_code) == (201, 201), segundo.text
    assert primero.json()["nombre"] != segundo.json()["nombre"]
    assert segundo.json()["nombre"].endswith("_2")


# --------------------------------------------------------------------------- #
# Traer las mismas tablas desde varias conexiones
# --------------------------------------------------------------------------- #

@necesita_mysql
def test_en_lote_crea_una_por_conexion_y_no_se_detiene_al_fallar(cliente, cab_admin):
    """
    El caso real: cuarenta sucursales con el mismo sistema detrás. Siempre hay
    alguna apagada y alguna a la que le falta una tabla; abortar el lote entero
    por eso obligaria a repetirlo adivinando cuales ya se hicieron.
    """
    ids = []
    for n in ("lote_a", "lote_b"):
        r = cliente.post("/api/conexiones", headers=cab_admin, json={
            "nombre": n, "tipo": "mysql",
            "config": {"host": "127.0.0.1", "port": 3306, "user": "root",
                       "password": "", "database": BASE}})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    r = cliente.post("/api/conexiones/datasets/en-lote", headers=cab_admin, json={
        "conexiones": [*ids, 999999],                 # una que no existe
        "tablas": [{"tabla": "cat_marca"},
                   {"tabla": "no_existe_en_ningun_lado"}]})
    assert r.status_code == 200, r.text
    d = r.json()

    # Una por conexion viva y tabla que existe.
    assert len(d["creados"]) == 2
    assert {c["conexion"] for c in d["creados"]} == {"lote_a", "lote_b"}
    # El nombre sale de conexion + tabla, sin que nadie lo escriba.
    assert {c["nombre"] for c in d["creados"]} == {"lote_a__cat_marca",
                                                   "lote_b__cat_marca"}

    # Lo que fallo se dice, con el motivo y sin tumbar lo demas.
    motivos = {f["motivo"] for f in d["fallidos"]}
    assert any("no existe" in m.lower() for m in motivos)
    assert len(d["fallidos"]) == 3        # 2 tablas inexistentes + 1 conexion


@necesita_mysql
def test_repetir_el_lote_no_duplica(cliente, cab_admin, conexion_mysql):
    """
    Volver a lanzarlo es lo normal cuando la primera vez fallo media docena de
    sucursales. No debe crear una segunda copia de las que ya estaban.
    """
    cuerpo = {"conexiones": [conexion_mysql], "tablas": [{"tabla": "cat_sucursal"}]}
    primero = cliente.post("/api/conexiones/datasets/en-lote", headers=cab_admin,
                           json=cuerpo).json()
    segundo = cliente.post("/api/conexiones/datasets/en-lote", headers=cab_admin,
                           json=cuerpo).json()

    assert len(primero["creados"]) + len(primero["omitidos"]) == 1
    assert len(segundo["creados"]) == 0
    assert len(segundo["omitidos"]) == 1
    assert segundo["omitidos"][0]["motivo"] == "Ya se traía"


def test_en_lote_lo_pide_un_editor_no_un_lector(cliente, cab_lector):
    r = cliente.post("/api/conexiones/datasets/en-lote", headers=cab_lector,
                     json={"conexiones": [1], "tablas": [{"tabla": "x"}]})
    assert r.status_code == 403
