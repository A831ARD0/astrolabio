"""
Conector ODBC: el comodin universal.

Es el que cubre Informix, SQL Server, Access, Oracle y casi cualquier
origen con driver. La contrapartida es que ODBC promete portabilidad y no la
cumple del todo, asi que este conector esta escrito para no dar nada por sentado
del dialecto de destino. Lo que aprende de cada origen lo PREGUNTA al driver:

1. **Las comillas de identificador las dice el driver**
   (`SQL_IDENTIFIER_QUOTE_CHAR`): backtick en MySQL, corchete en SQL Server,
   comilla doble en Informix y Postgres. Escribirlas a mano es como se rompe un
   conector al cambiar de origen.

2. **Catalogo o esquema, no los dos.** MySQL pone la base de datos en el
   *catalogo* y no admite esquemas —el driver de MariaDB responde literalmente
   "Schemas are not supported"—, mientras que SQL Server e Informix usan
   *esquema*. Se intenta uno y se cae al otro, sin suponer.

3. **Ni LIMIT ni TOP ni FIRST.** No hay forma portable de limitar filas en SQL:
   son tres sintaxis distintas y ninguna esta en el estandar que todos cumplen.
   Aqui se pide la consulta entera y se **deja de leer** al llegar al limite; el
   driver trae las filas por bloques, asi que una muestra de 25 filas no arrastra
   la tabla completa.

4. **Los tipos los declara el driver, no los adivina nadie.** El esquema sale de
   `cursor.description` —tipo, precision y escala— antes de leer la primera fila,
   y con el se construye un esquema de Arrow que es el que define las columnas del
   Parquet.

   Esto no es teoria. Dejando que pandas dedujera los tipos de los datos, la carga
   de `tbl_movimientos` reventaba con *Casting value "1189519.10" to type
   DECIMAL(8,2) failed*: pandas habia deducido la precision de las primeras filas
   y la cuarta parte de la tabla no cabia. Peor aun es cuando no revienta y una
   cifra de dinero acaba guardada como texto.

Precio a pagar: la ingesta pasa fila por fila por Python. Medido contra la misma
tabla, 60,000 filas particionadas por mes:

    MySQL por su conector nativo    0.3 s
    MySQL por ODBC                  6.4 s      (2.9 s leer + 3.5 s insertar)

Veinte veces mas lento, con las mismas 60,000 filas y las mismas 43 particiones en
los dos casos. Por eso ODBC **no reemplaza** al conector de MySQL: es para los
origenes que no tienen conector propio.
"""

from __future__ import annotations

import datetime
import decimal
import time
from pathlib import Path

import duckdb
import pyarrow as pa
import pyodbc

from app.conectores import perfiles_odbc as perfiles
from app.conectores.base import (
    ColumnaOrigen, Conector, ErrorConector, PeticionIngesta, ResultadoIngesta,
    ResultadoPrueba, TablaOrigen, cita_origen, escribir_lote,
)

# Esquemas/catalogos que son del motor y no de nadie.
SISTEMA = {
    "information_schema", "performance_schema", "mysql", "sys",
    "master", "tempdb", "model", "msdb",          # SQL Server
    "pg_catalog",                                  # Postgres
}

# Cuantas filas se traen del origen por vuelta. Suficiente para que el coste por
# lote se diluya, y poco para que la memoria no dependa del tamano de la tabla.
LOTE = 20_000

#: Tipo Python que declara el driver -> tipo de Arrow, que sera el del Parquet.
_TIPOS = {
    str: pa.string(),
    int: pa.int64(),
    float: pa.float64(),
    bool: pa.bool_(),
    bytes: pa.binary(),
    bytearray: pa.binary(),
    datetime.date: pa.date32(),
    datetime.datetime: pa.timestamp("us"),
    datetime.time: pa.time64("us"),
}


def _tipo(desc) -> pa.DataType:
    """
    Tipo de destino de una columna, a partir de lo que DECLARA el driver.

    `desc` es una fila de `cursor.description`:
    (nombre, tipo_python, tamano, bytes, precision, escala, admite_nulos).
    """
    tipo, precision, escala = desc[1], desc[4] or 0, desc[5] or 0
    if tipo is decimal.Decimal:
        # Con la precision declarada en el origen. Si no cabe en un decimal de
        # Arrow (38 digitos) se va a float, que pierde exactitud pero no tumba la
        # carga entera.
        if 0 < precision <= 38 and 0 <= escala <= precision:
            return pa.decimal128(precision, escala)
        return pa.float64()
    # Lo que no se reconoce entra como texto, y su valor se convierte con str().
    # Perder el tipo es malo; inventarlo es peor.
    return _TIPOS.get(tipo, pa.string())


class ConectorODBC(Conector):
    """
    `config` admite tres formas de decir a donde conectarse:

      {"dsn": "origen_informix"}                        DSN ya configurado en el servidor
      {"cadena": "DRIVER={...};SERVER=..."}    cadena ODBC completa
      {"driver": "...", "host": ..., "user": ..., "password": ..., "database": ...}

    La tercera es la comoda desde la interfaz; las dos primeras son las que va a
    usar sistemas cuando entregue el acceso al origen, porque un DSN ya trae dentro
    las mil opciones raras del driver.
    """

    tipo = "odbc"

    # -- conexion ----------------------------------------------------------- #

    def _cadena(self) -> str:
        cfg = self.config
        if cfg.get("cadena"):
            return str(cfg["cadena"])
        # Perfil del catalogo: el formulario guarda los campos por separado y la
        # cadena se arma aqui. Guardar la cadena ya armada seria mas simple y
        # dejaria la conexion imposible de editar despues sin volver a escribirla
        # entera, incluida la contrasena.
        if cfg.get("perfil"):
            elegido = perfiles.perfil(str(cfg["perfil"]))
            if elegido is None:
                raise ErrorConector(f"Perfil ODBC desconocido: '{cfg['perfil']}'.")
            if sin_llenar := perfiles.faltan(str(cfg["perfil"]), cfg):
                # Con el nombre del campo tal como se ve en la pantalla. El error
                # del driver cuando falta uno no dice cual.
                raise ErrorConector(
                    "Falta " + ", ".join(sin_llenar) + " para este origen.")
            # Los perfiles libres —'dsn' y 'manual'— no llevan plantilla porque no
            # arman nada: el DSN o la cadena ya traen todo dentro. Esos siguen al
            # camino de abajo. Antes se les pedia la plantilla igual y contestaban
            # "Perfil ODBC desconocido", que es justo lo contrario de lo que pasaba.
            if elegido.get("plantilla"):
                return perfiles.armar(str(cfg["perfil"]), cfg)
        if cfg.get("dsn"):
            partes = [f"DSN={cfg['dsn']}"]
        elif cfg.get("driver"):
            partes = [f"DRIVER={cfg['driver']}"]
            if cfg.get("host"):
                servidor = str(cfg["host"])
                partes.append(f"SERVER={servidor}")
            if cfg.get("port"):
                partes.append(f"PORT={int(cfg['port'])}")
        else:
            raise ErrorConector(
                "Una conexion ODBC necesita un DSN, una cadena completa, o el "
                "driver con el servidor. Si no sabes cual usar, pide a sistemas "
                "el DSN del origen."
            )
        if cfg.get("user"):
            partes.append(f"UID={cfg['user']}")
        if cfg.get("password"):
            partes.append(f"PWD={cfg['password']}")
        if cfg.get("database"):
            partes.append(f"DATABASE={cfg['database']}")
        if cfg.get("extra"):
            partes.append(str(cfg["extra"]).strip(";"))
        return ";".join(partes)

    @property
    def por_puente(self) -> bool:
        """Si esta conexion carga su driver en el proceso de 32 bits."""
        return bool(self.config.get("puente"))

    def _abrir(self) -> pyodbc.Connection:
        if self.por_puente:
            return self._abrir_por_puente()
        try:
            con = pyodbc.connect(self._cadena(), timeout=10, readonly=True)
        except pyodbc.Error as e:
            raise ErrorConector(
                f"No se pudo conectar por ODBC: {_limpio(e)}"
                + _pista_dsn(self.config, _limpio(e), _dsn_locales)) from e
        # Astrolabio nunca escribe en un origen. `readonly` es una peticion que
        # algunos drivers ignoran, asi que se repite en el atributo.
        try:
            con.autocommit = True
        except pyodbc.Error:
            pass
        return con

    def _abrir_por_puente(self):
        """
        La conexion la abre el proceso de 32 bits y esta solo la maneja.

        Lo que vuelve responde a las mismas llamadas que un `pyodbc.Connection`,
        asi que de aqui hacia abajo el conector es exactamente el mismo. Ver
        `app.conectores.puente`.
        """
        from app.conectores import puente          # perezoso: no todos lo usan

        url, token = _ajustes_del_puente()
        cadena = self._cadena()
        try:
            return puente.abrir(cadena, url, token)
        except pyodbc.Error as e:
            # El driver de 32 bits contesto que no. Se presenta igual que si
            # hubiera pasado en casa, con la pista mirando los DSN que ve el
            # puente —no los de este proceso, que son otros registros distintos.
            raise ErrorConector(
                f"No se pudo conectar por ODBC: {_limpio(e)}"
                + _pista_dsn(self.config, _limpio(e),
                             lambda: _dsn_del_puente(url, token))) from e

    # -- dialecto, preguntado al driver ------------------------------------- #

    def _dialecto(self, con: pyodbc.Connection) -> tuple[str, str, bool]:
        """(nombre del motor, caracter de comillas, usa catalogo en vez de esquema)"""
        try:
            motor = str(con.getinfo(pyodbc.SQL_DBMS_NAME) or "")
        except pyodbc.Error:
            motor = ""
        try:
            cita = str(con.getinfo(pyodbc.SQL_IDENTIFIER_QUOTE_CHAR) or '"').strip()
        except pyodbc.Error:
            cita = '"'
        cita = cita or '"'
        # MySQL y MariaDB llaman "catalogo" a la base de datos y no admiten
        # esquemas. Los demas motores que nos importan usan esquema.
        catalogo = any(x in motor.lower() for x in ("mysql", "maria"))
        return motor, cita, catalogo

    def _cita(self, nombre: str, cita: str) -> str:
        """
        Comillas del ORIGEN, con la comilla doblada dentro.

        Antes esto exigia un identificador de manual —letras, digitos y guion
        bajo— y con eso no se podia traer 'NF Header', que es como se llama una
        tabla de verdad en el Pervasive de una agencia. El nombre del origen no
        lo elegimos nosotros.
        """
        return cita_origen(nombre, cita)

    def _donde(self, esquema: str | None, con: pyodbc.Connection) -> dict:
        """Argumentos de catalogo/esquema para las funciones de catalogo de ODBC."""
        _, _, catalogo = self._dialecto(con)
        destino = esquema or self.config.get("database")
        if not destino:
            return {}
        return {"catalog": destino} if catalogo else {"schema": destino}

    def _nombre_tabla(self, tabla: str, esquema: str | None,
                      con: pyodbc.Connection) -> str:
        _, cita, _ = self._dialecto(con)
        destino = esquema or self.config.get("database")
        pieza = self._cita(tabla, cita)
        return f"{self._cita(destino, cita)}.{pieza}" if destino else pieza

    # -- identidad ---------------------------------------------------------- #

    def probar(self) -> ResultadoPrueba:
        try:
            con = self._abrir()
        except ErrorConector as e:
            return ResultadoPrueba(ok=False, mensaje=str(e))
        try:
            motor, cita, catalogo = self._dialecto(con)
            version = str(con.getinfo(pyodbc.SQL_DBMS_VER) or "?")
            tablas = None
            base = self.config.get("database")
            if base:
                try:
                    cur = con.cursor()
                    tablas = sum(1 for _ in cur.tables(**self._donde(None, con)))
                except pyodbc.Error:
                    tablas = None      # el driver puede no soportar el catalogo
            return ResultadoPrueba(
                ok=True,
                mensaje=f"Conexion ODBC correcta a {motor or 'origen desconocido'} "
                        f"{version}"
                        + (f" — {tablas} tabla{'' if tablas == 1 else 's'} "
                           f"en '{base}'" if tablas is not None else ""),
                detalle={"motor": motor, "version": version,
                         "identificadores": f"{cita}…{cita}",
                         "usa": "catalogo" if catalogo else "esquema",
                         "tablas": tablas},
            )
        except pyodbc.Error as e:
            return ResultadoPrueba(ok=False, mensaje=_limpio(e))
        finally:
            con.close()

    def config_publica(self) -> dict:
        """
        La cadena completa puede traer la contraseña dentro (`PWD=...`), asi que
        se enmascara. Es el unico campo de toda la aplicacion donde un secreto
        viaja mezclado con configuracion.
        """
        publica = super().config_publica()
        if publica.get("cadena"):
            publica["cadena"] = _sin_secretos(str(publica["cadena"]))
        return publica

    # -- introspeccion ------------------------------------------------------ #

    def listar_esquemas(self) -> list[str]:
        con = self._abrir()
        try:
            cur = con.cursor()
            _, _, catalogo = self._dialecto(con)
            # Se pide en el orden que el motor admite, y si el primero no esta
            # soportado se prueba el otro. Un driver que no soporta esquemas no
            # devuelve vacio: lanza error.
            intentos = ([{"catalog": "%", "schema": "", "table": ""},
                         {"catalog": "", "schema": "%", "table": ""}]
                        if catalogo else
                        [{"catalog": "", "schema": "%", "table": ""},
                         {"catalog": "%", "schema": "", "table": ""}])
            for args in intentos:
                try:
                    filas = list(cur.tables(**args))
                except pyodbc.Error:
                    continue
                nombres = {(f.table_cat or f.table_schem) for f in filas}
                encontrados = sorted(n for n in nombres
                                     if n and n.lower() not in SISTEMA)
                if encontrados:
                    return encontrados
            # Sin catalogo utilizable queda lo que diga la conexion.
            base = self.config.get("database")
            return [base] if base else []
        finally:
            con.close()

    def listar_tablas(self, esquema: str | None = None) -> list[TablaOrigen]:
        con = self._abrir()
        try:
            cur = con.cursor()
            donde = self._donde(esquema, con)
            # Sin esquema ni base indicados NO se falla. Hay motores -Pervasive
            # y en general los de fichero- donde el DSN ya apunta a los datos y
            # el concepto de esquema no existe: pedirlo es pedir algo que el
            # origen no tiene, y antes esto dejaba la conexion inservible.
            # Se listan todas las tablas visibles y cada una se queda con el
            # esquema que declare el driver, que puede ser ninguno.
            try:
                filas = list(cur.tables(**donde))
            except pyodbc.Error as e:
                raise ErrorConector(_limpio(e)) from e
            destino = esquema or self.config.get("database")
            salida = []
            for f in filas:
                if (f.table_type or "").upper() not in ("TABLE", "VIEW", "BASE TABLE"):
                    continue
                propio = destino or f.table_cat or f.table_schem or None
                # Al listar sin filtro se cuelan los catalogos del motor.
                if not destino and propio and propio.lower() in SISTEMA:
                    continue
                salida.append(TablaOrigen(
                    esquema=propio, nombre=f.table_name,
                    # ODBC no da un estimado de filas barato. Se deja en None en
                    # vez de inventar un cero, que se leeria como "tabla vacia".
                    filas_estimadas=None,
                    es_vista=(f.table_type or "").upper() == "VIEW",
                ))
            return salida
        finally:
            con.close()

    def describir_tabla(self, tabla: str, esquema: str | None = None) -> TablaOrigen:
        con = self._abrir()
        try:
            cur = con.cursor()
            donde = self._donde(esquema, con)
            try:
                filas = list(cur.columns(table=tabla, **donde))
            except pyodbc.Error as e:
                raise ErrorConector(_limpio(e)) from e
            if not filas:
                destino = esquema or self.config.get("database")
                raise ErrorConector(f"La tabla '{destino}.{tabla}' no existe")

            claves: set[str] = set()
            try:
                claves = {f.column_name
                          for f in cur.primaryKeys(table=tabla, **donde)}
            except pyodbc.Error:
                pass          # muchos drivers no lo implementan; no es un fallo

            columnas = [
                ColumnaOrigen(
                    nombre=f.column_name,
                    tipo_origen=_tipo_texto(f),
                    nulable=bool(f.nullable),
                    es_clave=f.column_name in claves,
                )
                for f in filas
            ]

            es_vista = False
            try:
                es_vista = any((t.table_type or "").upper() == "VIEW"
                               for t in cur.tables(table=tabla, **donde))
            except pyodbc.Error:
                pass

            nombre = self._nombre_tabla(tabla, esquema, con)
            try:
                total = cur.execute(f"SELECT COUNT(*) FROM {nombre}").fetchone()[0]
            except pyodbc.Error as e:
                raise ErrorConector(_limpio(e)) from e

            return TablaOrigen(
                esquema=esquema or self.config.get("database"), nombre=tabla,
                filas_estimadas=int(total or 0), es_vista=es_vista,
                columnas=columnas,
            )
        finally:
            con.close()

    def muestra(self, tabla: str, esquema: str | None = None,
                limite: int = 50,
                columnas: list[str] | None = None) -> tuple[list[str], list[tuple]]:
        con = self._abrir()
        try:
            cur = con.cursor()
            nombre = self._nombre_tabla(tabla, esquema, con)
            _, cita, _ = self._dialecto(con)
            cols = (", ".join(self._cita(c, cita) for c in columnas)
                    if columnas else "*")
            try:
                # Sin LIMIT: se deja de leer. Ver la cabecera del modulo.
                cur.execute(f"SELECT {cols} FROM {nombre}")
                filas = cur.fetchmany(int(limite))
            except pyodbc.Error as e:
                raise ErrorConector(_limpio(e)) from e
            cols = [d[0] for d in cur.description]
            return cols, [tuple(f) for f in filas]
        finally:
            con.close()

    # -- ingesta ------------------------------------------------------------ #

    def ingestar(self, p: PeticionIngesta, ruta_destino: str) -> ResultadoIngesta:
        # Las columnas se validan ANTES de mover datos: un error a media copia es
        # incomprensible, y en las bases reales abundan los nombres que parecen
        # existir y no existen.
        tabla = self.describir_tabla(p.tabla, p.esquema)
        disponibles = {c.nombre for c in tabla.columnas}
        for etiqueta, col in (("particionar_por", p.particionar_por),
                              ("columna_incremental", p.columna_incremental)):
            if col and col not in disponibles:
                cercanas = sorted(c for c in disponibles if col.split("_")[0] in c)[:5]
                raise ErrorConector(
                    f"La columna '{col}' ({etiqueta}) no existe en "
                    f"'{tabla.esquema}.{p.tabla}'."
                    + (f" Columnas parecidas: {', '.join(cercanas)}" if cercanas else "")
                )
        if p.columnas:
            faltan = set(p.columnas) - disponibles
            if faltan:
                raise ErrorConector(
                    f"Columnas inexistentes en '{p.tabla}': {', '.join(sorted(faltan))}"
                )
        if p.rango_desde or p.rango_hasta:
            if not p.particionar_por:
                raise ErrorConector(
                    "Recargar un rango de fechas requiere que el dataset este "
                    "particionado: sin particiones no hay nada que reemplazar sin "
                    "reescribir todo."
                )
            if not (p.rango_desde and p.rango_hasta):
                raise ErrorConector(
                    "La recarga por rango necesita inicio y fin. Un rango abierto "
                    "no dice cuantas particiones hay que reemplazar."
                )

        destino = Path(ruta_destino)
        destino.mkdir(parents=True, exist_ok=True)

        origen = self._abrir()
        duck = duckdb.connect()
        t0 = time.perf_counter()
        try:
            cur = origen.cursor()
            _, cita, _ = self._dialecto(origen)
            cols = (", ".join(self._cita(c, cita) for c in p.columnas)
                    if p.columnas else "*")
            sql = f"SELECT {cols} FROM {self._nombre_tabla(p.tabla, p.esquema, origen)}"

            # Los filtros se ligan como parametros: `?` es lo unico que ODBC
            # garantiza igual en todos los drivers.
            donde, params = [], []
            if p.columna_incremental and p.desde:
                donde.append(f"{self._cita(p.columna_incremental, cita)} > ?")
                params.append(p.desde)
            if p.rango_desde:
                donde.append(f"{self._cita(p.particionar_por, cita)} >= ?")
                params.append(p.rango_desde)
            if p.rango_hasta:
                # Hasta el final del dia: si la columna es DATETIME, comparar con
                # '2026-03-31' se dejaria fuera todo lo de ese dia despues de las
                # 00:00. Es el error clasico de una recarga por rango.
                donde.append(f"{self._cita(p.particionar_por, cita)} < ?")
                params.append(_dia_siguiente(p.rango_hasta))
            if donde:
                sql += " WHERE " + " AND ".join(donde)

            try:
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
            except pyodbc.Error as e:
                raise ErrorConector(f"{_limpio(e)} — al leer {p.tabla}") from e

            # El esquema se fija ANTES de leer una sola fila, con lo que declara el
            # driver. La tabla destino nace de ese esquema, no de los datos.
            esquema = pa.schema([(d[0], _tipo(d)) for d in cur.description])
            duck.register("vacio", esquema.empty_table())
            duck.execute("CREATE TEMP TABLE lote AS SELECT * FROM vacio")
            # Columnas que cayeron a texto sin ser texto en el origen: su valor se
            # convierte explicitamente, porque Arrow no acepta el objeto crudo.
            texto = [i for i, d in enumerate(cur.description)
                     if esquema.field(i).type == pa.string() and d[1] is not str]

            traidas = 0
            while True:
                pendiente = (min(LOTE, p.limite - traidas) if p.limite else LOTE)
                if pendiente <= 0:
                    break
                try:
                    bloque = cur.fetchmany(pendiente)
                except pyodbc.Error as e:
                    raise ErrorConector(_limpio(e)) from e
                if not bloque:
                    break
                duck.register("bloque", _a_arrow(bloque, esquema, texto))
                duck.execute("INSERT INTO lote SELECT * FROM bloque")
                traidas += len(bloque)

            return escribir_lote(duck, destino, p, t0)
        finally:
            duck.close()
            origen.close()


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _a_arrow(bloque, esquema: pa.Schema, texto: list[int]) -> pa.Table:
    """
    Un bloque de filas de ODBC como tabla de Arrow, con el esquema ya decidido.

    Se transpone a columnas porque Arrow es columnar; es la parte que cuesta en
    Python y la razon de que ODBC no llegue a la velocidad del conector nativo.
    """
    filas = [tuple(f) for f in bloque]
    columnas = list(zip(*filas)) if filas else [()] * len(esquema)
    arreglos = []
    for i, columna in enumerate(columnas):
        if i in texto:
            columna = tuple(None if v is None else str(v) for v in columna)
        campo = esquema.field(i)
        try:
            arreglos.append(pa.array(columna, type=campo.type))
        except (pa.ArrowInvalid, pa.ArrowTypeError) as e:
            # Pasa cuando el origen declara una columna mas estrecha de lo que
            # guarda. Se dice cual es: convertirla a texto por lo bajo dejaria una
            # cifra guardada como cadena y nadie se enteraria hasta sumarla.
            raise ErrorConector(
                f"La columna '{campo.name}' no cabe en el tipo que declara el "
                f"origen ({campo.type}): {e}"
            ) from e
    return pa.Table.from_arrays(arreglos, schema=esquema)


def _tipo_texto(fila) -> str:
    """`varchar(45)` a partir de lo que declara el catalogo ODBC."""
    nombre = (fila.type_name or "?").lower()
    tamano = fila.column_size
    if tamano and any(x in nombre for x in ("char", "binary")):
        return f"{nombre}({tamano})"
    escala = getattr(fila, "decimal_digits", None)
    if tamano and escala and any(x in nombre for x in ("dec", "numeric")):
        return f"{nombre}({tamano},{escala})"
    return nombre


def _dia_siguiente(fecha: str) -> str:
    try:
        d = datetime.date.fromisoformat(fecha[:10])
    except ValueError as e:
        raise ErrorConector(f"Fecha invalida: {fecha!r} (se espera AAAA-MM-DD)") from e
    return (d + datetime.timedelta(days=1)).isoformat()


def _limpio(e: Exception) -> str:
    """
    Mensaje de pyodbc sin la envoltura de tuplas.

    Un error ODBC crudo llega como ('HYC00', '[HYC00] [ma-3.2.9][9.6.0] texto…')
    y puesto tal cual en una pantalla no se entiende.
    """
    partes = [str(a) for a in getattr(e, "args", ()) if a]
    texto = partes[-1] if partes else str(e)
    return _sin_secretos(texto.strip())


def _ajustes_del_puente() -> tuple[str, str]:
    """(url, token) del puente de 32 bits, con el token leido del archivo."""
    from app.config import config

    c = config()
    token = c.puente_token
    if not token:
        ruta = Path(c.puente_token_archivo)
        try:
            token = ruta.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ErrorConector(
                f"Esta conexion usa el puente ODBC de 32 bits y no se pudo leer "
                f"su token en {ruta}: {e}. Lo crea el instalador con "
                f"'.\\instalar-windows.ps1 -Puente32'."
            ) from e
    if not token:
        raise ErrorConector(
            f"El archivo del token del puente esta vacio "
            f"({c.puente_token_archivo}).")
    return c.puente_url, token


def _dsn_locales() -> list[str]:
    return sorted(pyodbc.dataSources())


def _dsn_del_puente(url: str, token: str) -> list[str]:
    from app.conectores import puente

    try:
        return list(puente.salud(url, token).get("dsn") or [])
    except ErrorConector:
        return []


def _pista_dsn(cfg: dict, mensaje: str, visibles=_dsn_locales) -> str:
    """
    Lo que le falta al error del driver cuando el DSN no aparece.

    "Data source name not found" es de los errores mas engañosos que hay: el DSN
    normalmente SI existe, se ve en el Administrador de origenes de datos, y aun
    asi el driver jura que no. Casi siempre es cuestion de bits —un DSN de 32 bits
    es invisible para un proceso de 64, y son dos registros distintos— o de que se
    configuro en la maquina del origen y no en esta. El driver no distingue esos
    tres casos; aqui se dicen los tres, con la lista de los que si se ven.

    El primo hermano es IM014, "la arquitectura del DSN no coincide": ese si es
    claro sobre QUE pasa, pero no sobre que hacer, y lo que hay que hacer no es
    obvio cuando el driver de 32 bits no se puede cambiar.
    """
    bajo = mensaje.lower()
    pedido = str(cfg.get("dsn") or "").strip()

    if "im014" in bajo or "architecture" in bajo or "arquitectura" in bajo:
        return (
            "\n\nEs el choque de 32 contra 64 bits: el DSN apunta a un driver de "
            "32 bits y Astrolabio corre en 64. No es configuracion — un proceso "
            "de 64 bits no puede cargar una libreria de 32, nunca.\n"
            "Salidas: instalar el driver del origen de 64 bits (el DSN se vuelve "
            "a crear en C:\\Windows\\System32\\odbcad32.exe), o —cuando el de 32 "
            "no se puede tocar porque otra aplicacion depende de el— un puente "
            "que hable ODBC desde un proceso de 32 bits aparte."
        )

    if "data source name not found" not in bajo:
        return ""
    if not pedido:
        return ""
    try:
        # Con el puente, los DSN que importan son los que ve el proceso de 32
        # bits. Listar aqui los de 64 mandaria a buscar en el registro que no es.
        lista_visible = sorted(visibles())
    except Exception:                                   # pragma: no cover
        return ""
    if any(v.lower() == pedido.lower() for v in lista_visible):
        return ""                        # el DSN se ve: el fallo es otro
    lista = ", ".join(lista_visible) if lista_visible else "(ninguno)"
    return (
        f"\n\nEl DSN '{pedido}' no esta registrado para este proceso. "
        f"Los que si se ven desde aqui: {lista}.\n"
        "Si lo ves en el Administrador de origenes de datos pero no en esa lista, "
        "casi seguro esta creado de 32 bits y Astrolabio corre en 64: son dos "
        "registros separados y no se ven entre si. Hace falta el cliente de 64 "
        "bits del origen y volver a crear el DSN en el Administrador de origenes "
        "de datos de 64 bits (C:\\Windows\\System32\\odbcad32.exe), o —si el "
        "driver de 64 bits ya esta— usar el perfil del origen en vez del DSN, "
        "que arma la cadena sin depender del registro."
    )


def _sin_secretos(texto: str) -> str:
    """Enmascara PWD= y PASSWORD= en cadenas de conexion."""
    salida = []
    for trozo in texto.split(";"):
        clave = trozo.split("=", 1)[0].strip().upper()
        salida.append(f"{trozo.split('=', 1)[0]}=***"
                      if clave in ("PWD", "PASSWORD") and "=" in trozo else trozo)
    return ";".join(salida)
