"""
Modelar sobre lo que uno mismo cargó y transformó.

El agujero que cierran estas pruebas: el modelo semántico solo sabe nombrar tablas,
y una carga o el resultado de una transformación no son una tabla del motor — son un
directorio de Parquet. Sin una vista encima, la transformación corría, escribía sus
archivos, y el lienzo del modelo **no la encontraba**: solo se podía modelar sobre los
datos de demostración que trae el archivo analítico.

Lo que se protege:

- que un resultado en Parquet **aparezca en el catálogo** y se puedan leer sus columnas;
- que un modelo apuntado a él **consulte de verdad** y devuelva sus cifras;
- que una tabla del motor **gane** sobre un Parquet del mismo nombre, siempre, porque
  es la única regla que hace predecible la colisión y la que no cambia lo que ya
  significaban los tableros;
- que las **intermedias** no aparezcan: son andamiaje de una transformación, y con
  dieciocho secciones por sucursal el desplegable se vuelve inservible por volumen;
- que crear un modelo **desde una definición** funcione, para que la interfaz no tenga
  que saber serializar YAML.
"""

import pytest

from app.materializar import ruta_salida

# Chica a propósito: la prueba tiene que decir si el camino funciona, no tardar.
FUENTE = "cat_sucursal"
FILAS_FUENTE = 40


def crear_y_ejecutar(cliente, cab, nombre: str, intermedia: bool = False) -> int:
    r = cliente.post("/api/transformaciones", headers=cab, json={
        "definicion": {"nombre": nombre,
                       "origenes": [{"nombre": "s", "tipo": "tabla",
                                     "referencia": FUENTE}],
                       "pasos": []},
        "intermedia": intermedia})
    assert r.status_code == 201, r.text
    id_ = r.json()["id"]
    assert cliente.post(f"/api/transformaciones/{id_}/ejecutar",
                        headers=cab).status_code == 200
    return id_


def limpiar(*nombres: str) -> None:
    """
    El directorio de datasets es el real, no uno temporal. Una carpeta olvidada hace
    que la MISMA prueba falle la segunda vez que se corre, que es la peor forma de
    fallar.
    """
    from shutil import rmtree

    for nombre in nombres:
        carpeta = ruta_salida(nombre)
        if carpeta.is_dir():
            rmtree(carpeta, ignore_errors=True)


@pytest.fixture
def resultado(cliente, cab_admin, request):
    """Un resultado ya materializado, con nombre propio de esta prueba."""
    nombre = f"res_{request.node.name.replace('test_', '')[:28]}"
    crear_y_ejecutar(cliente, cab_admin, nombre)
    yield nombre
    limpiar(nombre)


def modelo_sobre(cliente, cab, tabla: str) -> int:
    """Un modelo de una sola entidad apuntada a `tabla`, y su métrica."""
    r = cliente.post("/api/modelos", headers=cab, json={
        "nombre": f"modelo de {tabla}",
        "definicion": {
            "modelo": f"modelo de {tabla}",
            "version": 1,
            "entidades": [{
                "nombre": "sucursales", "tipo": "hecho",
                "origen": {"tabla": tabla},
                "clave_primaria": "sucursal_id",
                "grano": ["sucursal_id"],
                "campos": [
                    {"nombre": "sucursal_id", "tipo": "entero", "rol": "clave"},
                    {"nombre": "sucursal_nombre", "tipo": "texto",
                     "rol": "dimension"},
                ],
            }],
            "metricas": [{"nombre": "cuantas", "etiqueta": "Cuántas",
                          "entidad": "sucursales", "expresion": "COUNT(*)"}],
        }})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# El catálogo
# --------------------------------------------------------------------------- #

def test_un_resultado_aparece_en_el_catalogo(cliente, cab_admin, resultado):
    tablas = cliente.get("/api/catalogo/tablas", headers=cab_admin).json()["tablas"]
    mio = next((t for t in tablas if t["nombre"] == resultado), None)
    assert mio is not None, "el resultado de una transformación no se puede modelar"
    assert mio["origen"] == "resultado"
    assert mio["filas"] == FILAS_FUENTE


def test_las_columnas_de_un_resultado_se_leen_del_parquet(cliente, cab_admin,
                                                          resultado):
    r = cliente.get(f"/api/catalogo/tablas/{resultado}", headers=cab_admin)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["origen"] == "resultado"
    nombres = [c["nombre"] for c in datos["columnas"]]
    assert nombres == ["sucursal_id", "sucursal_nombre", "marca_id", "region_id",
                       "nombre_conexion"]
    # El rol llega sugerido: lo que acaba en _id se relaciona, el texto agrupa.
    por_nombre = {c["nombre"]: c for c in datos["columnas"]}
    assert por_nombre["marca_id"]["rol_sugerido"] == "clave_externa"
    assert por_nombre["sucursal_nombre"]["rol_sugerido"] == "dimension"
    assert por_nombre["sucursal_nombre"]["tipo"] == "texto"


def test_una_intermedia_no_se_ofrece_para_modelar(cliente, cab_admin):
    nombre = "res_andamio_de_prueba"
    try:
        crear_y_ejecutar(cliente, cab_admin, nombre, intermedia=True)
        tablas = cliente.get("/api/catalogo/tablas",
                             headers=cab_admin).json()["tablas"]
        assert all(t["nombre"] != nombre for t in tablas)
        assert cliente.get(f"/api/catalogo/tablas/{nombre}",
                           headers=cab_admin).status_code == 404
    finally:
        limpiar(nombre)


def test_una_tabla_del_motor_gana_sobre_un_parquet_homonimo(cliente, cab_admin):
    """
    Alguien puede llamar a su resultado igual que a una tabla del motor. Entonces
    hay que elegir, y el motor gana: es lo que ya estaban leyendo los tableros.
    """
    try:
        crear_y_ejecutar(cliente, cab_admin, "cat_marca")
        tablas = cliente.get("/api/catalogo/tablas",
                             headers=cab_admin).json()["tablas"]
        cuantas = [t for t in tablas if t["nombre"] == "cat_marca"]
        assert len(cuantas) == 1, "el mismo nombre dos veces no es una elección"
        assert cuantas[0]["origen"] == "motor"

        datos = cliente.get("/api/catalogo/tablas/cat_marca",
                            headers=cab_admin).json()
        assert datos["origen"] == "motor"
        assert [c["nombre"] for c in datos["columnas"]] == ["marca_id",
                                                            "marca_nombre"]
    finally:
        limpiar("cat_marca")


def test_lo_que_no_existe_sigue_dando_404(cliente, cab_admin):
    r = cliente.get("/api/catalogo/tablas/ni_tabla_ni_carga", headers=cab_admin)
    assert r.status_code == 404
    assert "ni resultado" in r.json()["detail"]


# --------------------------------------------------------------------------- #
# Consultar de verdad
# --------------------------------------------------------------------------- #

def test_un_modelo_sobre_un_resultado_devuelve_sus_cifras(cliente, cab_admin,
                                                          resultado):
    """
    El pago de todo lo demás: la transformación produjo Parquet y el modelo lo
    consulta como si fuera una tabla.
    """
    id_ = modelo_sobre(cliente, cab_admin, resultado)
    r = cliente.post(f"/api/modelos/{id_}/consultar", headers=cab_admin,
                     json={"dimensiones": [], "metricas": ["cuantas"]})
    assert r.status_code == 200, r.text
    assert r.json()["filas"] == [{"cuantas": FILAS_FUENTE}]


def test_se_puede_agrupar_por_una_columna_del_parquet(cliente, cab_admin,
                                                      resultado):
    id_ = modelo_sobre(cliente, cab_admin, resultado)
    r = cliente.post(f"/api/modelos/{id_}/consultar", headers=cab_admin,
                     json={"dimensiones": ["sucursales.sucursal_nombre"],
                           "metricas": ["cuantas"]})
    assert r.status_code == 200, r.text
    filas = r.json()["filas"]
    assert len(filas) == FILAS_FUENTE
    assert sum(f["cuantas"] for f in filas) == FILAS_FUENTE


def test_una_carga_nueva_se_ve_sin_reiniciar(cliente, cab_admin, resultado):
    """
    La vista apunta a un glob y el glob se resuelve en cada consulta, así que volver
    a ejecutar la transformación cambia la cifra sin tocar nada más. Sin esto habría
    que reiniciar el servidor para ver datos frescos, que es exactamente el tipo de
    cosa que nadie recuerda.
    """
    id_ = modelo_sobre(cliente, cab_admin, resultado)
    primera = cliente.post(f"/api/modelos/{id_}/consultar", headers=cab_admin,
                           json={"dimensiones": [], "metricas": ["cuantas"]})
    assert primera.json()["filas"] == [{"cuantas": FILAS_FUENTE}]

    lista = cliente.get("/api/transformaciones", headers=cab_admin).json()
    tid = next(t["id"] for t in lista if t["nombre"] == resultado)
    assert cliente.post(f"/api/transformaciones/{tid}/ejecutar",
                        headers=cab_admin).status_code == 200

    segunda = cliente.post(f"/api/modelos/{id_}/consultar", headers=cab_admin,
                           json={"dimensiones": [], "metricas": ["cuantas"]})
    assert segunda.json()["filas"] == [{"cuantas": FILAS_FUENTE}]


# --------------------------------------------------------------------------- #
# Crear el modelo
# --------------------------------------------------------------------------- #

def test_crear_desde_una_definicion(cliente, cab_admin, resultado):
    id_ = modelo_sobre(cliente, cab_admin, resultado)
    r = cliente.get(f"/api/modelos/{id_}/definicion", headers=cab_admin)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["version"] == 1
    assert datos["definicion"]["entidades"][0]["origen"]["tabla"] == resultado


def test_crear_exige_yaml_o_definicion_pero_no_los_dos(cliente, cab_admin):
    ninguno = cliente.post("/api/modelos", headers=cab_admin,
                           json={"nombre": "sin nada"})
    assert ninguno.status_code == 422

    ambos = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": "con todo", "yaml": "modelo: x\nversion: 1\nentidades: []\n",
        "definicion": {"modelo": "x", "version": 1, "entidades": []}})
    assert ambos.status_code == 422


def test_una_definicion_incoherente_no_se_guarda(cliente, cab_admin):
    """Una métrica que nombra una entidad inexistente: se dice qué está mal."""
    r = cliente.post("/api/modelos", headers=cab_admin, json={
        "nombre": "modelo incoherente",
        "definicion": {
            "modelo": "modelo incoherente", "version": 1,
            "entidades": [{
                "nombre": "s", "tipo": "dimension",
                "origen": {"tabla": "cat_marca"},
                "campos": [{"nombre": "marca_id", "tipo": "entero",
                            "rol": "clave"}],
            }],
            "metricas": [{"nombre": "m", "etiqueta": "M", "entidad": "no_existe",
                          "expresion": "COUNT(*)"}],
        }})
    assert r.status_code == 422
    assert "no_existe" in str(r.json()["detail"])
