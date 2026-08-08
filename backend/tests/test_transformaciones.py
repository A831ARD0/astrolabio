"""
Fase 3 — el ETL.

Lo que se protege: que los pasos visuales produzcan el SQL que dicen producir, que
una transformación no pueda escribir en la base analítica, y que la conversión
desde SQL diga la verdad sobre lo que no puede convertir.
"""

import pytest

from semantic.transformacion import ErrorTransformacion


def _def(nombre: str, **extra) -> dict:
    base = {
        "nombre": nombre,
        "origenes": [{"nombre": "ventas", "tipo": "tabla",
                      "referencia": "fact_venta"}],
        "pasos": [],
    }
    base.update(extra)
    return base


# --------------------------------------------------------------------------- #
# Compilación
# --------------------------------------------------------------------------- #

def test_el_sql_se_lee_como_la_lista_de_pasos():
    """
    Cada paso es un CTE con nombre. Cuando una cifra no cuadra, poder leer el SQL
    paso por paso es la diferencia entre depurarlo y adivinar.
    """
    from semantic.transformacion import Transformacion, compilar

    t = Transformacion.model_validate(_def("x", pasos=[
        {"tipo": "filtrar", "condiciones": [
            {"campo": "es_cancelacion", "op": "=", "valor": False}]},
        {"tipo": "agrupar", "por": ["sucursal_id"], "agregados": [
            {"nombre": "venta", "funcion": "suma", "campo": "monto_base"}]},
    ]))
    c = compilar(t, {"ventas": '"fact_venta"'})

    assert "p0_origen AS" in c.sql
    assert "p1_filtrar AS" in c.sql
    assert "p2_agrupar AS" in c.sql
    assert c.sql.rstrip().endswith("SELECT * FROM p2_agrupar")
    assert [d for _, d in c.etapas] == [
        "origen: fact_venta", "filtrar: 1 condición(es)",
        "agrupar: por 1, 1 agregado(s)"]


def test_los_valores_de_los_filtros_van_como_parametros():
    """Un valor interpolado en el texto es una inyección esperando a pasar."""
    from semantic.transformacion import Transformacion, compilar

    t = Transformacion.model_validate(_def("x", pasos=[
        {"tipo": "filtrar", "condiciones": [
            {"campo": "serie", "op": "=", "valor": "'; DROP TABLE x; --"}]},
    ]))
    c = compilar(t, {"ventas": '"fact_venta"'})
    assert "DROP" not in c.sql
    assert c.parametros == ["'; DROP TABLE x; --"]


def test_una_expresion_derivada_con_subconsulta_se_rechaza():
    from semantic.transformacion import expresion_segura

    with pytest.raises(ErrorTransformacion, match="expresión de columna"):
        expresion_segura("(SELECT 1)", "derivar 'x'")


def test_una_expresion_derivada_con_ddl_se_rechaza():
    """
    Se revisa el árbol y no el texto: buscar la palabra 'DROP' se salta con
    comentarios o mayúsculas raras, el árbol no.
    """
    from semantic.transformacion import expresion_segura

    with pytest.raises(ErrorTransformacion):
        expresion_segura("1; DROP TABLE fact_venta", "derivar 'x'")


def test_una_expresion_derivada_valida_pasa():
    from semantic.transformacion import expresion_segura

    assert "monto_base" in expresion_segura(
        "monto_base - monto_impuesto", "derivar 'neto'")


def test_el_modo_sql_rechaza_lo_que_no_sea_lectura():
    from semantic.transformacion import Transformacion, compilar

    t = Transformacion.model_validate(
        _def("x", sql="DELETE FROM ventas WHERE 1=1"))
    with pytest.raises(ErrorTransformacion, match="lectura|permite"):
        compilar(t, {"ventas": '"fact_venta"'})


def test_el_modo_sql_rechaza_varias_sentencias():
    from semantic.transformacion import Transformacion, compilar

    t = Transformacion.model_validate(
        _def("x", sql="SELECT 1; SELECT 2"))
    with pytest.raises(ErrorTransformacion, match="una sola consulta"):
        compilar(t, {"ventas": '"fact_venta"'})


def test_el_modo_sql_expone_los_origenes_por_su_alias():
    """
    Una consulta pegada puede referirse a 'ventas' sin saber si detrás hay una
    tabla o un Parquet particionado.
    """
    from semantic.transformacion import Transformacion, compilar

    t = Transformacion.model_validate(
        _def("x", sql="SELECT COUNT(*) AS n FROM ventas"))
    c = compilar(t, {"ventas": "read_parquet('/x/**/*.parquet')"})
    assert '"ventas" AS (SELECT * FROM read_parquet' in c.sql


# --------------------------------------------------------------------------- #
# Ejecución contra datos reales
# --------------------------------------------------------------------------- #

@pytest.fixture
def transformacion(cliente, cab_admin):
    """Ventas netas por sucursal: filtrar cancelaciones, derivar y agrupar."""
    definicion = _def("ventas_netas_prueba", pasos=[
        {"tipo": "filtrar", "condiciones": [
            {"campo": "es_cancelacion", "op": "=", "valor": False}]},
        {"tipo": "derivar", "nombre": "neto",
         "expresion": "monto_base - monto_impuesto"},
        {"tipo": "agrupar", "por": ["sucursal_id"], "agregados": [
            {"nombre": "venta_neta", "funcion": "suma", "campo": "neto"},
            {"nombre": "operaciones", "funcion": "cuenta"}]},
        {"tipo": "ordenar", "por": ["venta_neta"], "descendente": True},
    ])
    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    for t in lista:
        if t["nombre"] == "ventas_netas_prueba":
            return t["id"]
    r = cliente.post("/api/transformaciones", headers=cab_admin,
                     json={"definicion": definicion})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_la_vista_previa_cuenta_filas_por_paso(cliente, cab_admin):
    """
    El conteo por etapa es lo que convierte un "no cuadra" en "se pierde en el
    paso 3".
    """
    r = cliente.post("/api/transformaciones/previsualizar", headers=cab_admin,
                     json={"definicion": _def("previa", pasos=[
                         {"tipo": "filtrar", "condiciones": [
                             {"campo": "es_cancelacion", "op": "=",
                              "valor": True}]},
                         {"tipo": "agrupar", "por": ["sucursal_id"],
                          "agregados": [{"nombre": "n", "funcion": "cuenta"}]},
                     ])})
    assert r.status_code == 200, r.text
    d = r.json()
    conteos = {c["paso"]: c["filas"] for c in d["conteos"]}
    assert conteos["origen: fact_venta"] > conteos["filtrar: 1 condición(es)"] > 0
    assert conteos["agrupar: por 1, 1 agregado(s)"] <= 40
    assert d["columnas"] == ["sucursal_id", "n"]


def test_ejecutar_materializa_a_parquet(cliente, cab_admin, transformacion):
    r = cliente.post(f"/api/transformaciones/{transformacion}/ejecutar",
                     headers=cab_admin)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["filas"] > 0
    assert set(d["columnas"]) == {"sucursal_id", "venta_neta", "operaciones"}

    from app.materializar import ruta_salida

    carpeta = ruta_salida("ventas_netas_prueba")
    assert list(carpeta.glob("*.parquet")), "no se escribio ningun Parquet"


def test_la_base_analitica_sigue_siendo_de_solo_lectura(cliente, cab_admin,
                                                       transformacion):
    """
    La garantía del diseño: nada de lo que pase por el ETL puede modificar una
    tabla que un tablero está leyendo.
    """
    import duckdb

    from app.config import config

    cliente.post(f"/api/transformaciones/{transformacion}/ejecutar",
                 headers=cab_admin)

    con = duckdb.connect(config().ruta_duckdb, read_only=True)
    try:
        tablas = {f[0] for f in con.execute(
            "SELECT table_name FROM duckdb_tables()").fetchall()}
    finally:
        con.close()
    assert "ventas_netas_prueba" not in tablas, (
        "la transformación escribió en la base analítica")


def test_el_resultado_se_puede_usar_como_origen(cliente, cab_admin, transformacion):
    """Encadenar transformaciones es lo que hace que el ETL sirva para algo."""
    cliente.post(f"/api/transformaciones/{transformacion}/ejecutar",
                 headers=cab_admin)

    r = cliente.post("/api/transformaciones/previsualizar", headers=cab_admin, json={
        "definicion": {
            "nombre": "encadenada",
            "origenes": [{"nombre": "netas", "tipo": "dataset",
                          "referencia": "ventas_netas_prueba"}],
            "pasos": [{"tipo": "filtrar", "condiciones": [
                {"campo": "operaciones", "op": ">", "valor": 0}]}],
        }})
    assert r.status_code == 200, r.text
    assert r.json()["filas"]


def test_un_origen_sin_datos_avisa_claro(cliente, cab_admin):
    r = cliente.post("/api/transformaciones/previsualizar", headers=cab_admin, json={
        "definicion": {
            "nombre": "sin_datos",
            "origenes": [{"nombre": "x", "tipo": "dataset",
                          "referencia": "no_cargado_nunca"}],
            "pasos": [],
        }})
    assert r.status_code == 422
    assert "no tiene datos cargados" in r.json()["detail"]


def test_el_historial_guarda_los_fallos(cliente, cab_admin):
    """Igual que en las cargas: sin historial de fallos no se depura nada."""
    r = cliente.post("/api/transformaciones", headers=cab_admin, json={
        "definicion": _def("fallara", pasos=[
            {"tipo": "filtrar", "condiciones": [
                {"campo": "columna_que_no_existe", "op": "=", "valor": 1}]}])})
    assert r.status_code == 201, r.text
    id_ = r.json()["id"]

    assert cliente.post(f"/api/transformaciones/{id_}/ejecutar",
                        headers=cab_admin).status_code == 400
    h = cliente.get(f"/api/transformaciones/{id_}/historial",
                    headers=cab_admin).json()
    assert h["ejecuciones"][0]["estado"] == "error"
    assert "columna_que_no_existe" in h["ejecuciones"][0]["mensaje"]


def test_una_union_de_dos_tablas_funciona(cliente, cab_admin):
    r = cliente.post("/api/transformaciones/previsualizar", headers=cab_admin, json={
        "definicion": {
            "nombre": "con_sucursal",
            "origenes": [
                {"nombre": "ventas", "tipo": "tabla", "referencia": "fact_venta"},
                {"nombre": "suc", "tipo": "tabla", "referencia": "cat_sucursal"},
            ],
            "pasos": [
                {"tipo": "unir", "con": "suc", "como": "izquierda",
                 "en": [["sucursal_id", "sucursal_id"]],
                 "traer": ["sucursal_nombre"]},
                {"tipo": "columnas",
                 "mantener": ["sucursal_nombre", "monto_base"]},
            ],
        }})
    assert r.status_code == 200, r.text
    assert r.json()["columnas"] == ["sucursal_nombre", "monto_base"]


# --------------------------------------------------------------------------- #
# Guardas
# --------------------------------------------------------------------------- #

def test_no_se_puede_leer_de_si_misma(cliente, cab_admin, transformacion):
    d = _def("ventas_netas_prueba")
    d["origenes"] = [{"nombre": "yo", "tipo": "dataset",
                      "referencia": "ventas_netas_prueba"}]
    r = cliente.put(f"/api/transformaciones/{transformacion}", headers=cab_admin,
                    json={"definicion": d})
    assert r.status_code == 422
    assert "sí misma" in r.json()["detail"]


def test_el_nombre_no_puede_chocar_con_un_dataset(cliente, cab_admin,
                                                  conexion_archivos_etl):
    """Los dos escribirían en el mismo directorio y uno pisaría al otro."""
    r = cliente.post("/api/transformaciones", headers=cab_admin,
                     json={"definicion": _def("ventas_csv_etl")})
    assert r.status_code == 409
    assert "dataset" in r.json()["detail"]


def test_cambiar_el_nombre_se_rechaza(cliente, cab_admin, transformacion):
    r = cliente.put(f"/api/transformaciones/{transformacion}", headers=cab_admin,
                    json={"definicion": _def("otro_nombre")})
    assert r.status_code == 400
    assert "huérfano" in r.json()["detail"]


def test_borrar_no_borra_los_datos_por_defecto(cliente, cab_admin):
    r = cliente.post("/api/transformaciones", headers=cab_admin,
                     json={"definicion": _def("para_borrar", pasos=[
                         {"tipo": "limitar", "n": 10}])})
    id_ = r.json()["id"]
    cliente.post(f"/api/transformaciones/{id_}/ejecutar", headers=cab_admin)

    from app.materializar import ruta_salida

    assert cliente.delete(f"/api/transformaciones/{id_}",
                          headers=cab_admin).status_code == 204
    assert ruta_salida("para_borrar").is_dir(), (
        "el resultado puede estar alimentando un modelo: no se borra sin pedirlo")


def test_el_lector_no_entra_al_etl(cliente, cab_lector):
    assert cliente.get("/api/transformaciones",
                       headers=cab_lector).status_code == 403
    assert cliente.post("/api/transformaciones/previsualizar", headers=cab_lector,
                        json={"definicion": _def("x")}).status_code == 403


# --------------------------------------------------------------------------- #
# SQL a visual
# --------------------------------------------------------------------------- #

def test_convierte_una_consulta_tipica(cliente, cab_admin):
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin, json={
        "sql": """
            SELECT s.sucursal_nombre, SUM(v.monto_base) AS venta,
                   COUNT(*) AS operaciones
            FROM fact_venta AS v
            LEFT JOIN cat_sucursal AS s ON v.sucursal_id = s.sucursal_id
            WHERE v.es_cancelacion = false
            GROUP BY s.sucursal_nombre
            ORDER BY venta DESC
            LIMIT 20
        """})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["convertible"] is True, d["no_representable"]
    assert [o["referencia"] for o in d["origenes"]] == ["fact_venta", "cat_sucursal"]

    # El filtro va DESPUÉS del join, como en SQL. Adelantarlo cambiaría el
    # resultado de un LEFT JOIN.
    tipos = [p["tipo"] for p in d["pasos"]]
    assert tipos == ["unir", "filtrar", "agrupar", "ordenar", "limitar"]

    agrupar = next(p for p in d["pasos"] if p["tipo"] == "agrupar")
    assert agrupar["por"] == ["sucursal_nombre"]
    assert {a["funcion"] for a in agrupar["agregados"]} == {"suma", "cuenta"}


def test_dice_que_no_puede_con_una_ventana(cliente, cab_admin):
    """No adivinar: una conversión aproximada cambia lo que la consulta hacía."""
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin, json={
        "sql": "SELECT sucursal_id, "
               "ROW_NUMBER() OVER (PARTITION BY sucursal_id ORDER BY venta_id) AS n "
               "FROM fact_venta"})
    assert r.status_code == 200
    d = r.json()
    assert d["convertible"] is False
    assert any("ventana" in m for m in d["no_representable"])


def test_dice_que_no_puede_con_un_having(cliente, cab_admin):
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin, json={
        "sql": "SELECT sucursal_id, SUM(monto_base) AS v FROM fact_venta "
               "GROUP BY sucursal_id HAVING SUM(monto_base) > 100"})
    d = r.json()
    assert d["convertible"] is False
    assert any("HAVING" in m for m in d["no_representable"])


def test_dice_que_no_puede_con_una_subconsulta(cliente, cab_admin):
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin, json={
        "sql": "SELECT * FROM (SELECT sucursal_id FROM fact_venta) AS t"})
    d = r.json()
    assert d["convertible"] is False


def test_convierte_filtros_con_in_y_nulos(cliente, cab_admin):
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin, json={
        "sql": "SELECT * FROM fact_venta WHERE serie IN ('A', 'B') "
               "AND cliente_id IS NOT NULL"})
    d = r.json()
    assert d["convertible"] is True, d["no_representable"]
    filtrar = d["pasos"][0]
    ops = {c["op"] for c in filtrar["condiciones"]}
    assert ops == {"en", "no_es_nulo"}


def test_lo_convertido_vuelve_a_compilar(cliente, cab_admin):
    """
    La prueba de que la conversión sirve: los pasos que devuelve se pueden ejecutar
    y dan un resultado. Si no cerrara el círculo, sería un adorno.
    """
    consulta = ("SELECT sucursal_id, SUM(monto_base) AS venta FROM fact_venta "
                "WHERE es_cancelacion = false GROUP BY sucursal_id")
    d = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin,
                     json={"sql": consulta}).json()
    assert d["convertible"] is True, d["no_representable"]

    r = cliente.post("/api/transformaciones/previsualizar", headers=cab_admin, json={
        "definicion": {"nombre": "ida_y_vuelta", "origenes": d["origenes"],
                       "pasos": d["pasos"]}})
    assert r.status_code == 200, r.text
    assert r.json()["columnas"] == ["sucursal_id", "venta"]


def test_una_consulta_convertida_da_el_mismo_numero_que_el_sql(cliente, cab_admin):
    """
    La prueba que de verdad importa: los pasos reconstruidos tienen que dar el
    MISMO resultado que la consulta original. Si difieren, la conversion es una
    trampa — el usuario cree que sigue midiendo lo mismo.

    El caso es un LEFT JOIN con filtro, que es donde el orden de los pasos cambia
    el resultado.
    """
    consulta = """
        SELECT s.sucursal_nombre, SUM(v.monto_base) AS venta
        FROM fact_venta AS v
        LEFT JOIN cat_sucursal AS s ON v.sucursal_id = s.sucursal_id
        WHERE v.es_cancelacion = false
        GROUP BY s.sucursal_nombre
    """

    # Por el modo SQL, tal cual la escribio el usuario.
    directo = cliente.post("/api/transformaciones/previsualizar", headers=cab_admin,
                           json={"definicion": {
                               "nombre": "sql_directo",
                               "origenes": [
                                   {"nombre": "fact_venta", "tipo": "tabla",
                                    "referencia": "fact_venta"},
                                   {"nombre": "cat_sucursal", "tipo": "tabla",
                                    "referencia": "cat_sucursal"}],
                               "sql": consulta}})
    assert directo.status_code == 200, directo.text

    # Por los pasos reconstruidos.
    conv = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin,
                        json={"sql": consulta}).json()
    assert conv["convertible"] is True, conv["no_representable"]
    visual = cliente.post("/api/transformaciones/previsualizar", headers=cab_admin,
                          json={"definicion": {
                              "nombre": "reconstruida",
                              "origenes": conv["origenes"],
                              "pasos": conv["pasos"]}})
    assert visual.status_code == 200, visual.text

    def por_sucursal(respuesta):
        return {f["sucursal_nombre"]: round(float(f["venta"]), 2)
                for f in respuesta.json()["filas"]}

    a, b = por_sucursal(directo), por_sucursal(visual)
    assert a and b
    assert a == b, "los pasos reconstruidos dan otro numero que el SQL original"


def test_un_dataset_con_nombre_raro_no_tumba_la_lista_de_origenes(
        cliente, cab_admin, conexion_archivos_etl):
    """
    Con mil sesenta y cinco datasets, uno con un nombre raro dejaba sin poder
    transformar nada.

    `ruta_datos_dataset` lanza si el nombre trae un caracter que no sirve para
    nombrar un origen. Esa excepcion subia hasta la ruta, la peticion contestaba
    500 y el panel de origenes se quedaba VACIO —sin decir por que—. Ahora ese
    origen se marca como inservible, se dice en `avisos`, y los demas se listan.
    """
    from app.db import CrearSesion
    from app.modelos_db import Dataset

    with CrearSesion() as s:
        base = s.get(Dataset, conexion_archivos_etl)
        malo = Dataset(conexion_id=base.conexion_id, nombre="con espacio y punto.",
                       tabla_origen="ventas.csv")
        s.add(malo)
        s.commit()
        malo_id = malo.id

    try:
        r = cliente.get("/api/transformaciones/origenes", headers=cab_admin)
        assert r.status_code == 200, r.text
        cuerpo = r.json()

        # El bueno sigue en la lista: es lo que se perdia antes.
        nombres = {d["nombre"]: d for d in cuerpo["datasets"]}
        assert base.nombre in nombres
        assert nombres[base.nombre]["usable"] is True

        # Y el malo aparece marcado, con su aviso.
        assert nombres["con espacio y punto."]["usable"] is False
        assert any("con espacio y punto." in a for a in cuerpo["avisos"])
    finally:
        with CrearSesion() as s:
            s.delete(s.get(Dataset, malo_id))
            s.commit()


def test_el_motor_analitico_se_crea_si_no_existe(tmp_path, monkeypatch):
    """
    En una instalacion nueva ese archivo no existe, y no puede crearse solo.

    `duckdb_solo_lectura` es True por omision —y debe serlo: la API no escribe en
    el motor, escribe Parquet—, pero en solo lectura DuckDB no crea el archivo que
    le falta. El resultado era «Cannot open database ... in read-only mode:
    database does not exist» en el ETL, en los tableros y en el modelo, con una
    instalacion que por lo demas estaba bien.
    """
    import duckdb

    from app.analitico import asegurar_base
    from app.config import config

    ruta = tmp_path / "sin_crear" / "analitico.duckdb"
    monkeypatch.setattr(config(), "ruta_duckdb", str(ruta))
    assert not ruta.exists()

    # Antes de crearla, abrirla en solo lectura falla: es el error del usuario.
    with pytest.raises(duckdb.Error):
        duckdb.connect(str(ruta), read_only=True)

    assert asegurar_base() is True
    assert ruta.exists()

    # Y ahora sí se puede leer, con cero tablas, que es la verdad.
    con = duckdb.connect(str(ruta), read_only=True)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM duckdb_tables() WHERE NOT internal"
        ).fetchone()[0] == 0
    finally:
        con.close()

    # Llamarla otra vez no toca nada: no debe borrar una base que ya tiene datos.
    assert asegurar_base() is False


# --------------------------------------------------------------------------- #
# Pegar SQL que nombra algo que existe —o que no
# --------------------------------------------------------------------------- #

def test_pegar_sql_resuelve_un_dataset_como_dataset(cliente, cab_admin,
                                                    conexion_archivos_etl):
    """
    Escribir `FROM ventas_csv_etl` tiene que funcionar sin que nadie sepa que
    detras hay Parquet y no una tabla del motor.

    Antes se suponia que toda tabla nombrada era del motor analitico, y la
    consulta moria con «Catalog Error: Table with name ... does not exist!».
    """
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin,
                     json={"sql": "SELECT * FROM ventas_csv_etl"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["convertible"] is True, d["no_representable"]
    assert d["origenes"] == [{"nombre": "ventas_csv_etl", "tipo": "dataset",
                              "referencia": "ventas_csv_etl"}]


def test_pegar_sql_con_una_tabla_del_motor_la_deja_como_tabla(cliente, cab_admin):
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin,
                     json={"sql": "SELECT * FROM fact_venta"})
    assert r.status_code == 200, r.text
    assert r.json()["origenes"][0]["tipo"] == "tabla"


def test_pegar_sql_que_nombra_algo_inexistente_lo_dice_en_claro(cliente, cab_admin):
    """
    El caso que le paso a quien uso esto: `SELECT * FROM cat_conexiones`, una tabla
    que vive en la base de la que salieron los datos y no aqui.

    Lo que salia era un «Catalog Error ... Did you mean
    "information_schema.constraint_column_usage"?». Eso no se puede accionar.
    """
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin,
                     json={"sql": "SELECT * FROM tabla_que_no_existe_en_ningun_sitio"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["convertible"] is False
    motivo = " ".join(d["no_representable"])
    assert "tabla_que_no_existe_en_ningun_sitio" in motivo
    assert "tiene que existir aquí" in motivo
    # Y no se ofrece un origen roto que falle mas adelante.
    assert d["origenes"] == []


def test_pegar_sql_sugiere_el_nombre_parecido(cliente, cab_admin):
    """Negar sin sugerir deja a alguien adivinando entre mil nombres."""
    r = cliente.post("/api/transformaciones/desde-sql", headers=cab_admin,
                     json={"sql": "SELECT * FROM fact_ventas"})   # sobra la 's'
    assert r.status_code == 200, r.text
    motivo = " ".join(r.json()["no_representable"])
    assert "fact_venta" in motivo


def test_en_modo_sql_una_tabla_sin_origen_da_un_error_util(cliente, cab_admin):
    """
    En modo SQL los orígenes se exponen como CTEs con su alias. Si la consulta
    nombra algo que no está entre ellos, el error tiene que decir eso —y no
    dejar que DuckDB culpe a la tabla.
    """
    r = cliente.post("/api/transformaciones/previsualizar", headers=cab_admin,
                     json={
        "definicion": {
            "nombre": "sql_sin_origen",
            "origenes": [{"nombre": "v", "tipo": "tabla", "referencia": "fact_venta"}],
            "pasos": [],
            "sql": "SELECT * FROM cat_conexiones",
        }})
    assert r.status_code == 422, r.text
    detalle = str(r.json()["detail"])
    assert "cat_conexiones" in detalle
    assert "no está entre los orígenes" in detalle
    assert "Orígenes de esta transformación: v" in detalle
