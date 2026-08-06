"""
Perfiles ODBC: la cadena de conexion armada por tipo de origen.

Escribir a mano `DRIVER={Pervasive ODBC Client Interface};SERVERNAME=...;
SERVERDSN=...` es la parte de ODBC donde se pierde media tarde, porque cada driver
llama distinto a lo mismo: el servidor es SERVER en SQL Server, SERVERNAME en
Pervasive y HOST en Informix, y la base es DATABASE, SERVERDSN o DATABASE segun
quien contesta. El error de un nombre mal puesto no dice cual esta mal.

Aqui vive el catalogo: por cada origen, los campos que de verdad hace falta llenar
y la plantilla con la que se arma la cadena. El formulario se dibuja desde esto, y
la cadena se arma en el conector —no en el navegador— para que quede un solo sitio
donde esta escrito como se conecta a cada motor.

**Lo que NO se puede hacer, y conviene decirlo claro:** descargar el driver solo,
como hace DBeaver. DBeaver descarga drivers **JDBC**, que son archivos .jar de Java
y son portables; un driver ODBC es una libreria nativa del sistema operativo (.dll,
.so, .dylib) que se instala y se registra en la maquina, y los dos que importan
aqui —Pervasive/Actian y el de Informix— vienen del cliente licenciado del
fabricante, no de una descarga publica. Lo que si se puede es lo de abajo: detectar
lo que hay instalado, decir exactamente que falta, y de donde sale.
"""

from __future__ import annotations

import re
from typing import Any

#: Campos reutilizados. `clave` es la del config de la conexion.
_HOST = {"clave": "host", "etiqueta": "Servidor", "requerido": True,
         "pista": "Nombre o IP de la maquina donde vive la base."}
_PUERTO = {"clave": "port", "etiqueta": "Puerto", "requerido": False}
_BASE = {"clave": "database", "etiqueta": "Base de datos", "requerido": True}
_USUARIO = {"clave": "user", "etiqueta": "Usuario", "requerido": False}
_CLAVE = {"clave": "password", "etiqueta": "Contraseña", "requerido": False,
          "secreto": True}
_EXTRA = {"clave": "extra", "etiqueta": "Opciones extra", "requerido": False,
          "pista": "Se pega tal cual al final de la cadena, separado por ';'."}


def _campo(base: dict, **cambios: Any) -> dict:
    return {**base, **cambios}


#: El catalogo. `plantilla` se arma por segmentos separados por ';': los que
#: mencionan un campo vacio se caen solos, asi que un origen sin usuario no deja
#: un 'UID=' colgando (que algunos drivers rechazan).
PERFILES: list[dict[str, Any]] = [
    {
        "clave": "pervasive",
        "nombre": "Pervasive PSQL / Actian Zen",
        # Estos son los nombres tal como los registra el instalador del cliente.
        "patrones": [r"pervasive odbc", r"actian zen", r"^zen odbc"],
        "plantilla": ("DRIVER={driver};SERVERNAME={host};SERVERDSN={database};"
                      "UID={user};PWD={password};{extra}"),
        "campos": [
            _campo(_HOST, pista="La maquina donde corre el motor de Pervasive."),
            _campo(_BASE, etiqueta="DSN del servidor",
                   pista="El nombre del origen tal como aparece en el "
                         "Administrador de origenes de datos ODBC del servidor "
                         "(por ejemplo VENTAS_SUCURSAL1)."),
            _campo(_USUARIO), _campo(_CLAVE), _campo(_EXTRA),
        ],
        "notas": [
            # Sin asteriscos: estas notas se pintan como texto, no como markdown.
            "El cliente de Pervasive suele instalarse de 32 bits, y un proceso "
            "de 64 bits no puede cargar un driver de 32 bits: no es un problema de "
            "permisos ni de cadena, simplemente no se cargan juntos. Si los DSN se "
            "ven en el 'Administrador de origenes de datos ODBC (32 bits)' hace "
            "falta el cliente de 64 bits, o un servicio aparte que corra en 32.",
            "Un DSN de Pervasive es local a la maquina donde esta configurado. Los "
            "que aparecen en el servidor del sistema de origen no existen para Astrolabio "
            "hasta que se configuren tambien donde corre Astrolabio.",
            "Cada agencia es un DSN distinto, asi que va una conexion por agencia.",
        ],
        "driver": {
            "de_donde": "Del cliente de Pervasive PSQL / Actian Zen que ya está "
                        "instalado en el servidor del sistema de origen. No hay descarga "
                        "pública: sale del instalador licenciado.",
            "quien": "sistemas",
        },
    },
    {
        "clave": "sqlserver",
        "nombre": "SQL Server",
        "patrones": [r"sql server"],
        "plantilla": ("DRIVER={driver};SERVER={host},{port};DATABASE={database};"
                      "UID={user};PWD={password};{extra}"),
        "campos": [
            _campo(_HOST), _campo(_PUERTO, defecto="1433"), _campo(_BASE),
            _campo(_USUARIO, requerido=True), _campo(_CLAVE, requerido=True),
            _campo(_EXTRA, defecto="TrustServerCertificate=yes",
                   pista="El driver 18 exige cifrado y falla con un certificado "
                         "propio; esto es lo que lo permite en una red interna."),
        ],
        "notas": [],
        "driver": {
            "de_donde": "Microsoft lo publica libremente: 'ODBC Driver 18 for SQL "
                        "Server'. En la imagen de Docker se instala con apt "
                        "(msodbcsql18).",
            "quien": "se puede instalar sin pedir licencia",
        },
    },
    {
        "clave": "informix",
        "nombre": "Informix",
        "patrones": [r"informix"],
        # Informix necesita DOS nombres: la maquina (HOST) y el nombre del
        # servidor de base de datos (SERVER), que no es el mismo y no se deduce.
        "plantilla": ("DRIVER={driver};HOST={host};SERVICE={port};"
                      "SERVER={servidor_informix};DATABASE={database};"
                      "PROTOCOL=onsoctcp;UID={user};PWD={password};{extra}"),
        "campos": [
            _campo(_HOST), _campo(_PUERTO, defecto="9088", requerido=True),
            {"clave": "servidor_informix", "etiqueta": "Servidor Informix",
             "requerido": True,
             "pista": "El INFORMIXSERVER: el nombre de la instancia, no el de la "
                      "maquina. Lo dice sistemas; sin el, el driver rechaza la "
                      "conexion sin explicar por que."},
            _campo(_BASE), _campo(_USUARIO, requerido=True),
            _campo(_CLAVE, requerido=True), _campo(_EXTRA),
        ],
        "notas": [
            "Informix distingue la maquina del nombre de la instancia, y pide los "
            "dos. Es el motivo mas comun de 'no se pudo conectar' con Informix.",
        ],
        "driver": {
            "de_donde": "Del Informix Client SDK de IBM. No está en apt ni en "
                        "Homebrew; hay que descargarlo con cuenta de IBM.",
            "quien": "sistemas",
        },
    },
    {
        "clave": "postgres",
        "nombre": "PostgreSQL",
        "patrones": [r"postgres"],
        "plantilla": ("DRIVER={driver};SERVER={host};PORT={port};"
                      "DATABASE={database};UID={user};PWD={password};{extra}"),
        "campos": [
            _campo(_HOST), _campo(_PUERTO, defecto="5432"), _campo(_BASE),
            _campo(_USUARIO, requerido=True), _campo(_CLAVE), _campo(_EXTRA),
        ],
        "notas": [],
        "driver": {"de_donde": "Libre: paquete odbc-postgresql (apt) o psqlodbc.",
                   "quien": "se puede instalar sin pedir licencia"},
    },
    {
        "clave": "mysql",
        "nombre": "MySQL / MariaDB (por ODBC)",
        "patrones": [r"mysql", r"maria"],
        "plantilla": ("DRIVER={driver};SERVER={host};PORT={port};"
                      "DATABASE={database};UID={user};PWD={password};{extra}"),
        "campos": [
            _campo(_HOST, defecto="127.0.0.1"), _campo(_PUERTO, defecto="3306"),
            _campo(_BASE), _campo(_USUARIO, requerido=True), _campo(_CLAVE),
            _campo(_EXTRA),
        ],
        "notas": [
            "Para MySQL conviene el conector nativo, que es unas veinte veces mas "
            "rapido. Este perfil es para probar el camino ODBC.",
        ],
        "driver": {"de_donde": "Libre: odbc-mariadb (apt) o mariadb-connector-odbc "
                               "(Homebrew).",
                   "quien": "se puede instalar sin pedir licencia"},
    },
]

#: Los dos que no llevan plantilla: el DSN ya trae todo dentro, y la cadena a mano
#: es la salida de emergencia para un origen que no este en el catalogo.
LIBRES: list[dict[str, Any]] = [
    {
        "clave": "dsn",
        "nombre": "Ya tengo un DSN configurado en el servidor",
        "campos": [
            {"clave": "dsn", "etiqueta": "Nombre del DSN", "requerido": True,
             "pista": "Tiene que estar registrado en la maquina donde corre "
                      "Astrolabio, y escrito exactamente igual."},
            _campo(_USUARIO), _campo(_CLAVE), _campo(_EXTRA),
        ],
        "notas": ["Es la forma mas segura cuando sistemas ya dejo el origen "
                  "configurado: el DSN guarda dentro las opciones raras del "
                  "driver, que son las que nadie recuerda."],
    },
    {
        "clave": "manual",
        "nombre": "Escribir la cadena completa a mano",
        "campos": [
            {"clave": "cadena", "etiqueta": "Cadena ODBC", "requerido": True,
             "pista": "DRIVER={...};SERVER=...;… tal cual la pide el driver."},
        ],
        "notas": ["Sirve para cualquier origen que no este en la lista. Si acaba "
                  "funcionando, vale la pena volverlo un perfil."],
    },
]


def perfil(clave: str) -> dict[str, Any] | None:
    for p in [*PERFILES, *LIBRES]:
        if p["clave"] == clave:
            return p
    return None


def armar(clave: str, valores: dict[str, Any]) -> str:
    """
    La cadena ODBC del perfil, con los segmentos vacios fuera.

    Un `UID=` sin valor no es inofensivo: hay drivers que lo toman como usuario
    vacio y contestan un error de autenticacion en vez de usar el del sistema.
    """
    p = perfil(clave)
    if p is None or not p.get("plantilla"):
        raise KeyError(clave)

    def valor(nombre: str) -> str:
        v = valores.get(nombre)
        return "" if v is None else str(v).strip()

    salida: list[str] = []
    for segmento in p["plantilla"].split(";"):
        segmento = segmento.strip()
        if not segmento:
            continue
        campos = re.findall(r"\{(\w+)\}", segmento)
        if campos and any(not valor(c) for c in campos):
            continue                      # falta algo: el segmento entero se cae
        salida.append(re.sub(r"\{(\w+)\}", lambda m: valor(m.group(1)), segmento))
    return ";".join(salida)


def faltan(clave: str, valores: dict[str, Any]) -> list[str]:
    """Etiquetas de los campos obligatorios del perfil que estan vacios."""
    p = perfil(clave)
    if p is None:
        return []
    return [c["etiqueta"] for c in p["campos"]
            if c.get("requerido") and not str(valores.get(c["clave"]) or "").strip()]


def catalogo(instalados: list[str]) -> list[dict[str, Any]]:
    """
    El catalogo con lo que esta instalado ya cruzado.

    `driver_detectado` es la mitad util: el nombre del driver tiene que coincidir
    exactamente con el registrado, y cuando no coincide el error ("Data source
    name not found and no default driver specified") no dice cual era el bueno.
    """
    salida: list[dict[str, Any]] = []
    for p in PERFILES:
        encontrados = [d for d in instalados
                       if any(re.search(x, d, re.I) for x in p["patrones"])]
        salida.append({
            **{k: v for k, v in p.items() if k != "patrones"},
            "drivers_detectados": encontrados,
            "driver_detectado": encontrados[0] if encontrados else None,
            "instalado": bool(encontrados),
        })
    salida.extend({**p, "drivers_detectados": [], "driver_detectado": None,
                   "instalado": True} for p in LIBRES)
    return salida
