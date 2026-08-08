"""
Catalogo de lo que el modelo puede usar como tabla: nombres, columnas y tipos.

Es lo que permite construir el modelo sin escribir YAML: la interfaz ofrece las
tablas que existen de verdad, con sus tipos, y adivina el rol de cada campo. Sin
esto, el usuario tendria que teclear nombres de columna de memoria — la forma mas
segura de que el modelo apunte a una columna que no existe.

Son tres procedencias y las tres se ofrecen igual, porque para el modelo son lo
mismo —un nombre con columnas— y para quien lo arma no: **el motor** son las tablas
del propio archivo analitico, **las cargas** son las tablas traidas de los origenes,
y **los resultados** son lo que produjeron las transformaciones. Las dos ultimas
viven en Parquet, asi que se les pone una vista encima al mirarlas
(`analitico.registrar_vistas`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.analitico import conexion, registrar_vistas, tablas_del_motor
from app.materializar import ruta_datos_dataset
from app.modelos_db import Dataset, Rol, Transformacion, Usuario
from app.dependencias import SesionDep, exigir_rol

router = APIRouter(prefix="/api/catalogo", tags=["catalogo"])

# Tipos de DuckDB agrupados en los tipos del modelo semantico. Lo que el usuario
# necesita saber es si algo se suma, se agrupa o es una fecha.
_TIPOS = {
    "BIGINT": "entero", "HUGEINT": "entero", "INTEGER": "entero",
    "SMALLINT": "entero", "TINYINT": "entero", "UBIGINT": "entero",
    "UINTEGER": "entero", "USMALLINT": "entero", "UTINYINT": "entero",
    "DECIMAL": "decimal", "DOUBLE": "decimal", "FLOAT": "decimal",
    "REAL": "decimal",
    "DATE": "fecha", "TIMESTAMP": "fecha", "TIMESTAMP WITH TIME ZONE": "fecha",
    "TIME": "fecha",
    "BOOLEAN": "booleano",
}


def tipo_modelo(tipo_duckdb: str) -> str:
    base = tipo_duckdb.upper().split("(")[0].strip()
    return _TIPOS.get(base, "texto")


def rol_sugerido(columna: str, tipo: str, clave_primaria: str | None) -> str:
    """
    Rol probable de una columna. Es una SUGERENCIA que la interfaz muestra
    editable, no una decision: acertar el rol de 'sucursal_id' es facil, pero
    'monto_objetivo' podria ser medida o dimension segun el negocio, y quien lo
    sabe es la persona, no una heuristica.
    """
    if columna == clave_primaria:
        return "clave"
    if columna.endswith("_id") or columna.endswith("_key"):
        return "clave_externa"
    if tipo == "fecha":
        return "clave_externa"          # se relaciona con el calendario
    if tipo in ("decimal",):
        return "medida_base"
    return "dimension"


def _en_parquet(sesion: SesionDep) -> dict[str, dict]:
    """
    Cargas y resultados que ya tienen datos escritos, por nombre.

    El filtro es la marca de tiempo de la ultima corrida y no la existencia de los
    archivos a proposito: comprobar el disco son mil y pico de recorridos de
    directorio para pintar un desplegable. Si los archivos ya no estan, el error
    sale al describir la tabla, con su nombre y una sola frase.

    Las intermedias no entran: son andamiaje de una transformacion, no algo que
    nadie vaya a modelar, y con dieciocho secciones por sucursal el desplegable se
    vuelve inservible por volumen.
    """
    salida: dict[str, dict] = {}
    for d in sesion.scalars(
        select(Dataset).where(Dataset.ultima_carga.is_not(None))
        .order_by(Dataset.nombre)
    ):
        salida[d.nombre] = {"nombre": d.nombre, "filas": d.filas, "origen": "carga"}
    for t in sesion.scalars(
        select(Transformacion)
        .where(Transformacion.ultima_ejecucion.is_not(None),
               Transformacion.intermedia.is_(False))
        .order_by(Transformacion.nombre)
    ):
        salida[t.nombre] = {"nombre": t.nombre, "filas": t.filas,
                            "origen": "resultado"}
    return salida


@router.get("/tablas")
def tablas(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Todo lo que el modelo puede nombrar como tabla, con su conteo de filas.

    El orden de las procedencias es el mismo que en el panel de origenes del ETL
    —motor, cargas, resultados—: es la misma pregunta en dos pantallas, y quien ya
    sabe donde mirar en una no tiene por que volver a aprenderlo en la otra.
    """
    con = conexion()
    filas = con.execute("""
        SELECT table_name, estimated_size
        FROM duckdb_tables()
        WHERE NOT internal
        ORDER BY table_name
    """).fetchall()
    salida = [{"nombre": n, "filas": int(f or 0), "origen": "motor"}
              for n, f in filas]

    # Una tabla del motor gana sobre un Parquet homonimo, igual que al consultar:
    # mostrar dos renglones con el mismo nombre seria ofrecer una eleccion que no
    # existe.
    del_motor = {t["nombre"] for t in salida}
    for t in _en_parquet(sesion).values():
        if t["nombre"] not in del_motor:
            salida.append(t)
    return {"tablas": salida}


def _clave_por_convencion(tabla: str, columnas: list[str]) -> str | None:
    """La convencion <tabla_sin_prefijo>_id, cuando la tabla no declara clave."""
    candidato = f"{tabla.split('_', 1)[-1]}_id"
    return candidato if candidato in columnas else None


@router.get("/tablas/{tabla}")
def describir(tabla: str, sesion: SesionDep,
              _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Columnas de una tabla, ya traducidas a los tipos del modelo y con un rol
    sugerido para cada una.
    """
    con = conexion()
    if tabla in tablas_del_motor(con):
        return _describir_del_motor(con, tabla)

    en_parquet = _en_parquet(sesion)
    if tabla not in en_parquet:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No hay ninguna tabla, carga ni resultado que se llame '{tabla}'")
    # Se pregunta por el disco en vez de fiarse de lo que devuelva el registro:
    # `registrar_vistas` solo informa de las vistas que acaba de crear, y en la
    # segunda visita a la misma tabla ya no crea ninguna.
    if ruta_datos_dataset(tabla) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"'{tabla}' esta registrado pero no tiene archivos Parquet en disco. "
            f"Vuelve a ejecutar su carga o su transformacion.")
    registrar_vistas([tabla])
    return _describir_parquet(con, tabla, en_parquet[tabla]["origen"])


def _describir_del_motor(con, tabla: str) -> dict:
    # duckdb_columns() con parametro ligado: el nombre de tabla nunca entra en el
    # texto del SQL.
    columnas = con.execute("""
        SELECT column_name, data_type, is_nullable
        FROM duckdb_columns()
        WHERE table_name = ?
        ORDER BY column_index
    """, [tabla]).fetchall()

    # La clave primaria se deduce de la propia tabla si la declara; si no, de la
    # convencion <tabla_sin_prefijo>_id.
    clave = None
    restricciones = con.execute("""
        SELECT constraint_column_names
        FROM duckdb_constraints()
        WHERE table_name = ? AND constraint_type = 'PRIMARY KEY'
    """, [tabla]).fetchall()
    if restricciones and restricciones[0][0]:
        clave = restricciones[0][0][0]
    else:
        clave = _clave_por_convencion(tabla, [c[0] for c in columnas])

    return {
        "nombre": tabla,
        "origen": "motor",
        "clave_primaria": clave,
        "columnas": [
            {"nombre": n, "tipo_origen": t, "tipo": tipo_modelo(t),
             "nulable": (nul == "YES" if isinstance(nul, str) else bool(nul)),
             "rol_sugerido": rol_sugerido(n, tipo_modelo(t), clave)}
            for n, t, nul in columnas
        ],
    }


def _describir_parquet(con, tabla: str, origen: str) -> dict:
    """
    Las columnas de una vista de Parquet.

    `DESCRIBE` y no `duckdb_columns()`: la vista es temporal y lo que interesa es
    la forma del resultado, que es exactamente lo que `DESCRIBE` contesta. Un
    Parquet no declara clave primaria, asi que solo queda la convencion — y si no
    la cumple, se queda sin clave y la elige la persona en el dialogo, que es
    quien sabe.
    """
    filas = con.execute(f'DESCRIBE SELECT * FROM "{tabla}"').fetchall()
    nombres = [f[0] for f in filas]
    clave = _clave_por_convencion(tabla, nombres)
    return {
        "nombre": tabla,
        "origen": origen,
        "clave_primaria": clave,
        "columnas": [
            {"nombre": n, "tipo_origen": t, "tipo": tipo_modelo(t),
             # Un Parquet dice si una columna admite nulos, pero para armar el
             # modelo no cambia nada: se informa lo que se sabe sin inventar.
             "nulable": True,
             "rol_sugerido": rol_sugerido(n, tipo_modelo(t), clave)}
            for n, t, *_ in filas
        ],
    }


@router.get("/tablas/{tabla}/muestra")
def muestra(tabla: str, limite: int = 20,
            _: Usuario = Depends(exigir_rol(Rol.editor))):
    """Primeras filas, para confirmar que la tabla es la que se cree."""
    con = conexion()
    existe = con.execute(
        "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = ?", [tabla]
    ).fetchone()[0]
    if not existe:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"La tabla '{tabla}' no existe en el motor analitico")
    # El nombre de tabla no se puede ligar como parametro. Ya se verifico contra
    # el catalogo, y aun asi se escapan las comillas: dos cinturones.
    seguro = tabla.replace('"', '""')
    cur = con.execute(f'SELECT * FROM "{seguro}" LIMIT {min(int(limite), 200)}')
    cols = [d[0] for d in cur.description]
    return {"columnas": cols,
            "filas": [{c: (str(v) if v is not None else None)
                       for c, v in zip(cols, f)} for f in cur.fetchall()]}
