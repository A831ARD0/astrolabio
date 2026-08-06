"""
Programador de cargas y recarga por particion.

Lo que se verifica aqui no es que "funcione": es que no haga dano callado. Una
carga programada que duplica filas, o que reescribe diez años de historia para
corregir un mes, se nota semanas despues en un numero que no cuadra.
"""

import csv
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app import programador
from app.conectores.base import ErrorConector, particiones_del_rango
from app.config import config
from app.db import CrearSesion, motor
from tests.conftest import necesita_mysql


def _ruta(nombre: str) -> Path:
    return Path(config().ruta_duckdb).parent / "datasets" / nombre


@pytest.fixture
def dataset_csv(cliente, cab_admin):
    """Dataset de archivo: no necesita MySQL, sirve para probar el programador."""
    d = Path(tempfile.mkdtemp(prefix="meridian_prog_"))
    with open(d / "ventas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sucursal", "monto"])
        w.writerow(["Aurex Valle", "480000.50"])
        w.writerow(["Dalia Valle Alto", "310000.00"])

    r = cliente.post("/api/conexiones", headers=cab_admin, json={
        "nombre": f"prog_{d.name}", "tipo": "archivo",
        "config": {"ruta_base": str(d)},
    })
    assert r.status_code == 201, r.text
    conexion = r.json()["id"]

    r = cliente.post(f"/api/conexiones/{conexion}/datasets", headers=cab_admin,
                     json={"nombre": f"ventas_{d.name}", "tabla": "ventas.csv"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# Calculo de particiones
# --------------------------------------------------------------------------- #

def test_el_rango_se_traduce_a_meses_completos():
    """Recargar del 15 de febrero al 2 de abril toca tres meses, no dos dias."""
    assert particiones_del_rango("2026-02-15", "2026-04-02") == [
        "anio=2026/mes=2", "anio=2026/mes=3", "anio=2026/mes=4",
    ]


def test_el_rango_cruza_el_fin_de_anio():
    assert particiones_del_rango("2025-12-01", "2026-01-31") == [
        "anio=2025/mes=12", "anio=2026/mes=1",
    ]


def test_un_solo_dia_es_un_solo_mes():
    assert particiones_del_rango("2026-03-10", "2026-03-10") == ["anio=2026/mes=3"]


def test_rango_invertido_se_rechaza():
    with pytest.raises(ErrorConector, match="termina antes de empezar"):
        particiones_del_rango("2026-05-01", "2026-01-01")


def test_fecha_mal_escrita_se_rechaza():
    with pytest.raises(ErrorConector, match="AAAA-MM-DD"):
        particiones_del_rango("01/03/2026", "31/03/2026")


def test_no_se_puede_borrar_fuera_del_destino(tmp_path):
    """Una particion viene de los datos; un dato no debe senalar hacia afuera."""
    from app.conectores.base import borrar_particiones

    afuera = tmp_path / "importante"
    afuera.mkdir()
    destino = tmp_path / "dataset"
    destino.mkdir()

    with pytest.raises(ErrorConector, match="fuera del destino"):
        borrar_particiones(destino, ["../importante"])
    assert afuera.is_dir()


# --------------------------------------------------------------------------- #
# Cargas repetidas
# --------------------------------------------------------------------------- #

def test_recargar_no_duplica_filas(cliente, cab_admin, dataset_csv):
    """
    Dos cargas completas del mismo archivo dejan 2 filas, no 4. Sin limpiar el
    destino, cada carga agregaria un Parquet mas y el dataset creceria solo.
    """
    nombre = None
    for _ in range(3):
        r = cliente.post(f"/api/conexiones/datasets/{dataset_csv}/cargar",
                         headers=cab_admin)
        assert r.status_code == 200, r.text
        assert r.json()["filas"] == 2

    with CrearSesion() as s:
        nombre = s.execute(text("SELECT nombre FROM dataset WHERE id=:i"),
                           {"i": dataset_csv}).scalar_one()
    archivos = list(_ruta(nombre).glob("*.parquet"))
    assert len(archivos) == 1, f"quedaron Parquet de cargas anteriores: {archivos}"


def test_recargar_rango_sin_particion_avisa(cliente, cab_admin, dataset_csv):
    r = cliente.post(f"/api/conexiones/datasets/{dataset_csv}/recargar-rango",
                     headers=cab_admin,
                     json={"desde": "2026-01-01", "hasta": "2026-01-31"})
    assert r.status_code == 400
    assert "no esta particionado" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# Programacion
# --------------------------------------------------------------------------- #

def test_cron_invalido_se_rechaza_al_guardarlo(cliente, cab_admin, dataset_csv):
    """Debe fallar en la peticion, no de madrugada dentro del programador."""
    r = cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                    headers=cab_admin, json={"cron": "todos los dias a las 6"})
    assert r.status_code == 422
    assert "cron invalida" in r.json()["detail"]


def test_programar_calcula_la_proxima_corrida(cliente, cab_admin, dataset_csv):
    r = cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                    headers=cab_admin,
                    json={"cron": "0 6 * * *", "zona_horaria": "America/Mexico_City"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["activa"] is True
    assert d["proxima"] is not None

    r = cliente.get("/api/conexiones/programacion", headers=cab_admin)
    ids = {t["id"] for t in r.json()["trabajos"]}
    assert f"dataset:{dataset_csv}" in ids


def test_la_programacion_queda_persistida(cliente, cab_admin, dataset_csv):
    """
    El trabajo vive en la base, no en memoria: un reinicio de madrugada no debe
    dejar los datos sin actualizar.
    """
    cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                headers=cab_admin, json={"cron": "30 2 * * *"})
    with motor.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM tarea_programada WHERE id=:i"),
                      {"i": f"dataset:{dataset_csv}"}).scalar_one()
    assert n == 1


def test_sincronizar_reconstruye_los_trabajos(cliente, cab_admin, dataset_csv):
    """Lo que manda es la base: si un trabajo se pierde, sincronizar lo repone."""
    cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                headers=cab_admin, json={"cron": "0 5 * * *"})
    programador.planificador().remove_job(f"dataset:{dataset_csv}")
    assert programador.proxima_corrida(dataset_csv) is None

    programador.sincronizar()
    assert programador.proxima_corrida(dataset_csv) is not None


def test_desprogramar_quita_el_trabajo(cliente, cab_admin, dataset_csv):
    cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                headers=cab_admin, json={"cron": "0 6 * * *"})
    r = cliente.delete(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                       headers=cab_admin)
    assert r.status_code == 204
    assert programador.proxima_corrida(dataset_csv) is None


def test_la_carga_programada_usa_el_mismo_camino(cliente, cab_admin, dataset_csv):
    """
    El programador tiene que dejar el mismo rastro que el boton: misma ejecucion
    en el historial, con el disparo marcado como programado.
    """
    cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                headers=cab_admin, json={"cron": "0 6 * * *"})
    programador.correr_dataset(dataset_csv)

    r = cliente.get(f"/api/conexiones/datasets/{dataset_csv}/historial",
                    headers=cab_admin)
    ejec = r.json()["ejecuciones"]
    assert len(ejec) == 1
    assert ejec[0]["estado"] == "exito"
    assert ejec[0]["disparo"] == "programado"
    assert ejec[0]["filas"] == 2


def test_programacion_en_pausa_no_carga(cliente, cab_admin, dataset_csv):
    """Pausar debe pausar de verdad, aunque el trabajo llegue a dispararse."""
    cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                headers=cab_admin, json={"cron": "0 6 * * *", "activa": False})
    programador.correr_dataset(dataset_csv)

    r = cliente.get(f"/api/conexiones/datasets/{dataset_csv}/historial",
                    headers=cab_admin)
    assert r.json()["ejecuciones"] == []


def test_dataset_borrado_no_deja_trabajo_zombi(cliente, cab_admin, dataset_csv):
    cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                headers=cab_admin, json={"cron": "0 6 * * *"})
    with CrearSesion() as s:
        s.execute(text("DELETE FROM dataset WHERE id=:i"), {"i": dataset_csv})
        s.commit()

    programador.correr_dataset(dataset_csv)      # no debe lanzar
    assert programador.proxima_corrida(dataset_csv) is None


def test_una_carga_que_falla_no_apaga_el_programador(cliente, cab_admin, dataset_csv):
    """
    Si la excepcion escapara, APScheduler apagaria el trabajo y el dataset
    dejaria de actualizarse sin que nadie se enterara.
    """
    cliente.put(f"/api/conexiones/datasets/{dataset_csv}/programacion",
                headers=cab_admin, json={"cron": "0 6 * * *"})
    with CrearSesion() as s:
        s.execute(text("UPDATE dataset SET tabla_origen='no_existe.csv' WHERE id=:i"),
                  {"i": dataset_csv})
        s.commit()

    programador.correr_dataset(dataset_csv)      # no debe lanzar

    r = cliente.get(f"/api/conexiones/datasets/{dataset_csv}/historial",
                    headers=cab_admin)
    ejec = r.json()["ejecuciones"]
    assert ejec[0]["estado"] == "error"
    assert ejec[0]["disparo"] == "programado"


# --------------------------------------------------------------------------- #
# Recarga por particion contra datos reales
# --------------------------------------------------------------------------- #

@necesita_mysql
def test_recargar_un_mes_no_toca_las_demas_particiones(cliente, cab_admin,
                                                       conexion_mysql):
    """
    Lo que hace practicable corregir un mes de hace años: el resto del historico
    no se vuelve a escribir. Se compara archivo por archivo.
    """
    r = cliente.post(f"/api/conexiones/{conexion_mysql}/datasets", headers=cab_admin,
                     json={"nombre": "ventas_rango",
                           "tabla": "ventas",
                           "particionar_por": "fecha_emision"})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]

    r = cliente.post(f"/api/conexiones/datasets/{ds}/cargar?limite=40000",
                     headers=cab_admin)
    assert r.status_code == 200, r.text

    raiz = _ruta("ventas_rango")
    antes = {str(p.relative_to(raiz)): p.stat().st_mtime_ns
             for p in raiz.rglob("*.parquet")}
    assert (raiz / "anio=2024" / "mes=1").is_dir(), "hace falta ese mes para la prueba"

    r = cliente.post(f"/api/conexiones/datasets/{ds}/recargar-rango",
                     headers=cab_admin,
                     json={"desde": "2024-01-01", "hasta": "2024-01-31"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["modo"] == "particion"
    assert d["particiones"] == ["anio=2024/mes=1"]

    despues = {str(p.relative_to(raiz)): p.stat().st_mtime_ns
               for p in raiz.rglob("*.parquet")}
    intactos = {k: v for k, v in antes.items() if not k.startswith("anio=2024/mes=1/")}
    for ruta, mtime in intactos.items():
        assert despues.get(ruta) == mtime, f"se reescribio una particion ajena: {ruta}"

    # Y el mes recargado trae ahora TODAS las filas de enero 2024 del origen, no
    # solo las que cayeron en el limite de la carga inicial.
    import duckdb
    con = duckdb.connect()
    try:
        n = con.execute(
            "SELECT COUNT(*) FROM read_parquet(?, hive_partitioning=true)",
            [f"{raiz}/anio=2024/mes=1/**/*.parquet"]).fetchone()[0]
    finally:
        con.close()
    assert n > 0
