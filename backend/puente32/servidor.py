"""
El lado de 32 bits: el unico proceso que carga el driver.

    python -m puente32.servidor --token-archivo C:\\astrolabio\\datos\\puente.token

Se arranca con el interprete de **32 bits**, que es lo unico que puede cargar un
driver ODBC de 32 bits. Solo necesita `pyodbc`; todo lo demas es de la biblioteca
estandar, a proposito, porque en 32 bits ya no hay ruedas de pyarrow ni de duckdb
y no las va a haber.

**Lo que este proceso puede hacer, dicho claro:** abre cualquier origen ODBC que
el driver alcance, con la cadena que le manden, y devuelve las filas. Es tan
poderoso como el propio Astrolabio sobre esos origenes. Por eso escucha **solo en
127.0.0.1** —nunca en la red— y exige un token compartido en cada peticion. Si
alguien puede hablar con este puerto, puede leer los origenes; si alguien puede
leer el archivo del token, tambien. Los dos son del administrador de la maquina,
que ya podia de todos modos.

Las cadenas de conexion llevan contrasenas dentro, asi que **no se escribe ninguna
en el registro**, ni siquiera al fallar.
"""

from __future__ import annotations

import argparse
import hmac
import http.server
import json
import logging
import os
import secrets
import socketserver
import sys
import threading
import time
import uuid

import pyodbc

from puente32 import protocolo

log = logging.getLogger("puente32")

#: Una sesion abandonada deja una conexion abierta contra el origen, y los motores
#: cuentan conexiones. Si nadie la toca en este tiempo, se cierra sola.
MINUTOS_INACTIVA = 30

#: Tope de filas por peticion. Es el mismo lote que usa el conector; esto es el
#: cinturon por si llega una peticion con un numero absurdo.
MAXIMO_LOTE = 100_000


class Sesion:
    def __init__(self, con: pyodbc.Connection) -> None:
        self.con = con
        self.cursores: dict[str, pyodbc.Cursor] = {}
        self.tocada = time.monotonic()
        # Dos peticiones a la vez sobre la misma conexion ODBC no son seguras:
        # muchos drivers no son reentrantes y el de Pervasive es de esos.
        self.candado = threading.Lock()

    def cerrar(self) -> None:
        for cur in self.cursores.values():
            try:
                cur.close()
            except pyodbc.Error:
                pass
        try:
            self.con.close()
        except pyodbc.Error:
            pass


class Registro:
    """Las sesiones vivas, con su limpieza."""

    def __init__(self) -> None:
        self._sesiones: dict[str, Sesion] = {}
        self._candado = threading.Lock()

    def abrir(self, cadena: str) -> str:
        con = pyodbc.connect(cadena, timeout=10, readonly=True)
        try:
            con.autocommit = True
        except pyodbc.Error:
            pass
        clave = uuid.uuid4().hex
        with self._candado:
            self._sesiones[clave] = Sesion(con)
        return clave

    def toma(self, clave: str) -> Sesion:
        with self._candado:
            sesion = self._sesiones.get(clave)
        if sesion is None:
            # Pasa cuando el puente se reinicio a media carga. Decirlo asi evita
            # que se lea como un fallo del origen.
            raise ErrorPeticion(
                "La sesion no existe o ya se cerro. Si el puente se reinicio, "
                "vuelve a intentar la operacion.", 410)
        sesion.tocada = time.monotonic()
        return sesion

    def cerrar(self, clave: str) -> None:
        with self._candado:
            sesion = self._sesiones.pop(clave, None)
        if sesion is not None:
            sesion.cerrar()

    def barrer(self) -> None:
        limite = time.monotonic() - MINUTOS_INACTIVA * 60
        with self._candado:
            viejas = [k for k, s in self._sesiones.items() if s.tocada < limite]
            for k in viejas:
                self._sesiones.pop(k).cerrar()
        if viejas:
            log.info("Cerradas %d sesiones inactivas", len(viejas))

    def cuantas(self) -> int:
        with self._candado:
            return len(self._sesiones)


class ErrorPeticion(Exception):
    """Algo mal en la peticion, no en el origen."""

    def __init__(self, mensaje: str, codigo: int = 400) -> None:
        super().__init__(mensaje)
        self.codigo = codigo


# --------------------------------------------------------------------------- #
# Operaciones
# --------------------------------------------------------------------------- #

#: Funciones de catalogo de ODBC que el conector usa. Lista cerrada a proposito:
#: el nombre llega de la red y no se va a buscar como atributo suelto del cursor.
CATALOGO = {"tables", "columns", "primaryKeys"}


def _cursor(sesion: Sesion, clave: str) -> pyodbc.Cursor:
    cur = sesion.cursores.get(clave)
    if cur is None:
        raise ErrorPeticion("Ese cursor no existe en esta sesion.", 410)
    return cur


def _filas_de_catalogo(cur: pyodbc.Cursor) -> dict:
    """
    El resultado de `tables`/`columns` con los nombres de sus campos.

    Se manda generico —los nombres salen de `description`— en vez de una lista
    fija: cada driver anade los suyos y el conector lee unos cuantos por atributo.
    """
    filas = list(cur)
    nombres = [d[0] for d in (cur.description or [])]
    return {"nombres": nombres, "lote": protocolo.codificar_lote(filas)}


def atender(registro: Registro, operacion: str, cuerpo: dict) -> dict:
    if operacion == "salud":
        return {"ok": True, "version": protocolo.VERSION,
                "sesiones": registro.cuantas(),
                "bits": 8 * (sys.maxsize.bit_length() + 1) // 8,
                "drivers": sorted(pyodbc.drivers()),
                "dsn": sorted(pyodbc.dataSources())}

    if operacion == "abrir":
        cadena = cuerpo.get("cadena")
        if not isinstance(cadena, str) or not cadena.strip():
            raise ErrorPeticion("Falta la cadena de conexion.")
        return {"sesion": registro.abrir(cadena)}

    if operacion == "cerrar":
        registro.cerrar(str(cuerpo.get("sesion") or ""))
        return {"ok": True}

    sesion = registro.toma(str(cuerpo.get("sesion") or ""))

    with sesion.candado:
        if operacion == "getinfo":
            return {"valor": sesion.con.getinfo(int(cuerpo["info"]))}

        if operacion == "cursor":
            clave = uuid.uuid4().hex
            sesion.cursores[clave] = sesion.con.cursor()
            return {"cursor": clave}

        if operacion == "cerrar-cursor":
            cur = sesion.cursores.pop(str(cuerpo.get("cursor") or ""), None)
            if cur is not None:
                try:
                    cur.close()
                except pyodbc.Error:
                    pass
            return {"ok": True}

        cur = _cursor(sesion, str(cuerpo.get("cursor") or ""))

        if operacion == "catalogo":
            funcion = str(cuerpo.get("funcion") or "")
            if funcion not in CATALOGO:
                raise ErrorPeticion(f"Funcion de catalogo no permitida: {funcion!r}")
            argumentos = cuerpo.get("argumentos") or {}
            if not isinstance(argumentos, dict):
                raise ErrorPeticion("Los argumentos del catalogo deben ser objeto.")
            getattr(cur, funcion)(**argumentos)
            return _filas_de_catalogo(cur)

        if operacion == "ejecutar":
            sql = cuerpo.get("sql")
            if not isinstance(sql, str):
                raise ErrorPeticion("Falta el SQL.")
            crudos = cuerpo.get("parametros") or []
            parametros = [protocolo.decodificar_columna(p)[0] for p in crudos]
            if parametros:
                cur.execute(sql, parametros)
            else:
                cur.execute(sql)
            return {"descripcion": protocolo.codificar_descripcion(cur.description)}

        if operacion == "traer":
            cuantas = int(cuerpo.get("cuantas") or 1)
            if cuantas < 1 or cuantas > MAXIMO_LOTE:
                raise ErrorPeticion(f"Lote fuera de rango: {cuantas}")
            return protocolo.codificar_lote(cur.fetchmany(cuantas))

    raise ErrorPeticion(f"Operacion desconocida: {operacion!r}", 404)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class Manejador(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "puente32"
    sys_version = ""

    registro: Registro
    token: str

    def log_message(self, formato: str, *args) -> None:      # noqa: A002
        # El registro por defecto escribe la linea de peticion entera. Aqui las
        # rutas son inofensivas, pero se pasa por logging para que acabe donde
        # NSSM lo recoge en vez de en stderr suelto.
        log.info("%s %s", self.address_string(), formato % args)

    def _responder(self, codigo: int, datos: dict) -> None:
        cuerpo = json.dumps(datos).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self) -> None:                               # noqa: N802
        enviado = self.headers.get("X-Puente-Token", "")
        if not hmac.compare_digest(enviado, self.token):
            # Sin detalle: un mensaje que distinga "falta" de "no coincide" le
            # dice a quien prueba por donde va.
            self._responder(401, {"error": "Token invalido."})
            return

        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            largo = 0
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except ValueError:
            self._responder(400, {"error": "Cuerpo JSON invalido."})
            return
        if not isinstance(cuerpo, dict):
            self._responder(400, {"error": "El cuerpo debe ser un objeto."})
            return

        operacion = self.path.strip("/")
        try:
            self._responder(200, atender(self.registro, operacion, cuerpo))
        except ErrorPeticion as e:
            self._responder(e.codigo, {"error": str(e)})
        except pyodbc.Error as e:
            # El error del driver viaja entero para que el otro lado lo vuelva a
            # levantar como pyodbc.Error y el conector lo trate igual que si
            # hubiera pasado en casa.
            self._responder(200, {"error_odbc": [str(a) for a in e.args]})
        except Exception as e:                               # pragma: no cover
            log.exception("Fallo atendiendo %s", operacion)
            self._responder(500, {"error": f"{type(e).__name__}: {e}"})


class Servidor(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    # Una carga puede tener varias sesiones a la vez (el programador no espera a
    # que termine una para empezar otra), asi que se atiende con hilos. Cada
    # sesion tiene su candado, que es lo que de verdad protege al driver.
    allow_reuse_address = True


def leer_token(ruta: str | None, generar: bool) -> str:
    if ruta and os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            token = f.read().strip()
        if not token:
            raise SystemExit(f"El archivo del token esta vacio: {ruta}")
        return token
    if not generar:
        raise SystemExit(
            "Falta el token. Es lo unico que separa a este proceso de cualquiera\n"
            "que pueda hablar con el puerto. Pasa --token-archivo con la ruta del\n"
            "archivo que comparte con Astrolabio, o --generar-token la primera vez."
        )
    token = secrets.token_urlsafe(32)
    if ruta:
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(token)
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass          # en Windows los permisos los pone el instalador
        print(f"Token nuevo escrito en {ruta}")
    else:
        print(token)
    return token


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--puerto", type=int, default=8001)
    p.add_argument("--token-archivo", default=None)
    p.add_argument("--generar-token", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    bits = 8 * (sys.maxsize.bit_length() + 1) // 8
    if bits != 32:
        # No es un error: el puente funciona igual en 64 bits y asi se prueba. Pero
        # si se arranca en 64 en el servidor, no vera el driver de 32 y el fallo
        # apareceria mucho mas tarde, disfrazado de "no se encuentra el DSN".
        log.warning("Este interprete es de %d bits. El puente existe para cargar "
                    "drivers de 32; con este no vera ninguno.", bits)

    Manejador.registro = Registro()
    Manejador.token = leer_token(args.token_archivo, args.generar_token)

    def barrendero() -> None:
        while True:
            time.sleep(60)
            try:
                Manejador.registro.barrer()
            except Exception:                                # pragma: no cover
                log.exception("Fallo barriendo sesiones")

    threading.Thread(target=barrendero, daemon=True).start()

    servidor = Servidor(("127.0.0.1", args.puerto), Manejador)
    log.info("Puente ODBC de %d bits escuchando en 127.0.0.1:%d", bits, args.puerto)
    log.info("Drivers que ve: %s", ", ".join(sorted(pyodbc.drivers())) or "(ninguno)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        log.info("Parando")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
