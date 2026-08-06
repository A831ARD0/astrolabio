"""
Registro de conectores.

Para agregar un origen nuevo (ODBC, PostgreSQL, API REST) basta escribir la
clase y registrarla aqui. Ni la API ni la ingesta cambian.
"""

from app.conectores.archivos import ConectorArchivos
from app.conectores.base import (
    ColumnaOrigen, Conector, ErrorConector, PeticionIngesta, ResultadoIngesta,
    ResultadoPrueba, TablaOrigen,
)
from app.conectores.mysql import ConectorMySQL
from app.conectores.odbc import ConectorODBC

TIPOS: dict[str, type[Conector]] = {
    ConectorMySQL.tipo: ConectorMySQL,
    ConectorArchivos.tipo: ConectorArchivos,
    ConectorODBC.tipo: ConectorODBC,
}

# Campos obligatorios por tipo, para validar antes de guardar una conexion.
#
# ODBC no tiene ninguno: hay tres formas validas de decir a donde conectarse (un
# DSN, una cadena completa, o driver + servidor) y exigir campos concretos
# descartaria las otras dos. La combinacion la valida el propio conector, que es
# quien sabe, y el mensaje de error dice que falta.
REQUERIDOS: dict[str, set[str]] = {
    "mysql": {"host", "user", "database"},
    "archivo": {"ruta_base"},
    "odbc": set(),
}

# Campos que se ofrecen aunque no sean obligatorios. Los dice el servidor para
# que el formulario no lleve una lista propia que se quede vieja.
OPCIONALES: dict[str, list[str]] = {
    "mysql": ["port", "password"],
    "archivo": [],
    # `perfil` es la clave del catalogo de perfiles_odbc: con ella, la cadena la
    # arma el conector desde los campos que el perfil pide.
    # `puente` manda la conexion por el proceso de 32 bits, para los drivers que
    # solo existen de 32 y no se pueden cambiar. Ver `app.conectores.puente`.
    "odbc": ["perfil", "dsn", "driver", "host", "port", "user", "password",
             "database", "servidor_informix", "cadena", "extra", "puente"],
}


def crear(tipo: str, config: dict) -> Conector:
    if tipo not in TIPOS:
        raise ErrorConector(
            f"Tipo de conexion desconocido: '{tipo}'. "
            f"Disponibles: {', '.join(sorted(TIPOS))}"
        )
    faltan = REQUERIDOS.get(tipo, set()) - set(config)
    if faltan:
        raise ErrorConector(
            f"Faltan campos obligatorios para '{tipo}': {', '.join(sorted(faltan))}"
        )
    return TIPOS[tipo](config)


__all__ = [
    "ColumnaOrigen", "Conector", "ConectorArchivos", "ConectorMySQL",
    "ConectorODBC", "ErrorConector", "OPCIONALES", "PeticionIngesta",
    "REQUERIDOS", "ResultadoIngesta", "ResultadoPrueba", "TablaOrigen", "TIPOS",
    "crear",
]
