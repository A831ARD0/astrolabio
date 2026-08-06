"""
Catalogo del motor analitico: que tablas y columnas hay disponibles.

Es lo que permite construir el modelo sin escribir YAML: la interfaz ofrece las
tablas que existen de verdad, con sus tipos, y adivina el rol de cada campo. Sin
esto, el usuario tendria que teclear nombres de columna de memoria — la forma mas
segura de que el modelo apunte a una columna que no existe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.analitico import conexion
from app.modelos_db import Rol, Usuario
from app.dependencias import exigir_rol

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


@router.get("/tablas")
def tablas(_: Usuario = Depends(exigir_rol(Rol.editor))):
    """Tablas del motor analitico con su conteo de filas."""
    con = conexion()
    filas = con.execute("""
        SELECT table_name, estimated_size
        FROM duckdb_tables()
        WHERE NOT internal
        ORDER BY table_name
    """).fetchall()
    return {"tablas": [{"nombre": n, "filas": int(f or 0)} for n, f in filas]}


@router.get("/tablas/{tabla}")
def describir(tabla: str, _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Columnas de una tabla, ya traducidas a los tipos del modelo y con un rol
    sugerido para cada una.
    """
    con = conexion()
    existe = con.execute(
        "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = ?", [tabla]
    ).fetchone()[0]
    if not existe:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"La tabla '{tabla}' no existe en el motor analitico")

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
        base = tabla.split("_", 1)[-1]
        candidato = f"{base}_id"
        if any(c[0] == candidato for c in columnas):
            clave = candidato

    return {
        "nombre": tabla,
        "clave_primaria": clave,
        "columnas": [
            {"nombre": n, "tipo_origen": t, "tipo": tipo_modelo(t),
             "nulable": (nul == "YES" if isinstance(nul, str) else bool(nul)),
             "rol_sugerido": rol_sugerido(n, tipo_modelo(t), clave)}
            for n, t, nul in columnas
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
