"""
El lado de 64 bits del puente: objetos que se hacen pasar por los de pyodbc.

La tentacion era escribir un `ConectorODBCPorPuente` con sus propios `probar`,
`listar_tablas`, `describir_tabla` e `ingestar` hablando HTTP. Habrian sido dos
conectores ODBC que hay que mantener a la par, y el dia que se arregle un tipo mal
convertido en uno, el otro sigue mal. Peor: la parte delicada —los tipos que
declara el driver, el dialecto preguntado, el esquema de Arrow fijado antes de la
primera fila— se habria duplicado entera.

Asi que el puente no se mete a ese nivel. Se mete **debajo**: `ConexionRemota` y
`CursorRemoto` responden a las mismas llamadas que los de pyodbc, y `ConectorODBC`
sigue siendo uno solo y no sabe con cual esta hablando. Lo unico que cambia es de
donde sale la conexion.

Lo que se paga es menos de lo que parece. Cada `fetchmany` es una peticion HTTP y
las filas pasan por JSON, pero lo caro de ODBC ya era sacar las filas del driver
fila a fila en Python; el viaje por el bucle local se pierde en comparacion.
Medido contra la misma tabla, 200,000 filas por el mismo driver:

    ODBC directo    4.77 s
    Por el puente   5.44 s      (un 12% mas)

Se esperaba peor —la primera version de este comentario decia "alrededor del
doble"— y por eso se midio antes de escribirlo. El lote de 20,000 filas es lo que
lo salva: son diez peticiones para 200,000 filas, no 200,000.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pyodbc

from app.conectores.base import ErrorConector
from puente32 import protocolo


class ErrorPuente(ErrorConector):
    """El puente no contesta o contesta que no. No es un fallo del origen."""


class FilaRemota:
    """
    Una fila de catalogo, con acceso por atributo.

    El conector lee `f.table_name`, `f.column_name`, `f.decimal_digits`… tal como
    los nombra ODBC, y cada driver anade los suyos. Se guardan todos los que
    vinieron y `getattr` de uno que no vino devuelve None, igual que haria un
    driver que no lo implementa.
    """

    __slots__ = ("_valores",)

    def __init__(self, nombres: list[str], valores: tuple) -> None:
        object.__setattr__(self, "_valores", dict(zip(nombres, valores)))

    def __getattr__(self, nombre: str) -> Any:
        try:
            return self._valores[nombre]
        except KeyError:
            return None

    def __getitem__(self, i: int) -> Any:
        return list(self._valores.values())[i]

    def __iter__(self):
        return iter(self._valores.values())

    def __repr__(self) -> str:
        return f"FilaRemota({self._valores!r})"


class CursorRemoto:
    def __init__(self, conexion: ConexionRemota, clave: str) -> None:
        self._con = conexion
        self._clave = clave
        self.description: list[tuple] | None = None

    # -- catalogo ----------------------------------------------------------- #

    def _catalogo(self, funcion: str, **argumentos) -> list[FilaRemota]:
        # pyodbc admite argumentos en None y los ignora; mandarlos por la red no
        # aporta y algunos drivers distinguen ausente de nulo.
        limpios = {k: v for k, v in argumentos.items() if v is not None}
        r = self._con._pedir("catalogo", cursor=self._clave, funcion=funcion,
                             argumentos=limpios)
        nombres = r["nombres"]
        return [FilaRemota(nombres, fila)
                for fila in protocolo.decodificar_lote(r["lote"])]

    def tables(self, **argumentos) -> list[FilaRemota]:
        return self._catalogo("tables", **argumentos)

    def columns(self, **argumentos) -> list[FilaRemota]:
        return self._catalogo("columns", **argumentos)

    def primaryKeys(self, **argumentos) -> list[FilaRemota]:   # noqa: N802
        return self._catalogo("primaryKeys", **argumentos)

    # -- consultas ---------------------------------------------------------- #

    def execute(self, sql: str, parametros: list | None = None) -> CursorRemoto:
        # pyodbc devuelve el cursor, y hay codigo que encadena
        # `cur.execute(...).fetchone()`.
        r = self._con._pedir(
            "ejecutar", cursor=self._clave, sql=sql,
            parametros=[protocolo.codificar_columna([p]) for p in (parametros or [])])
        self.description = protocolo.decodificar_descripcion(r["descripcion"])
        return self

    def fetchmany(self, cuantas: int) -> list[tuple]:
        r = self._con._pedir("traer", cursor=self._clave, cuantas=int(cuantas))
        return protocolo.decodificar_lote(r)

    def fetchone(self) -> tuple | None:
        filas = self.fetchmany(1)
        return filas[0] if filas else None

    def fetchall(self) -> list[tuple]:
        todas: list[tuple] = []
        while bloque := self.fetchmany(10_000):
            todas.extend(bloque)
        return todas

    def close(self) -> None:
        try:
            self._con._pedir("cerrar-cursor", cursor=self._clave)
        except ErrorPuente:
            pass          # cerrar es cortesia: si el puente ya no esta, da igual


class ConexionRemota:
    """
    Una conexion ODBC que vive en el otro proceso.

    `autocommit` se acepta y se ignora: el puente ya lo pone al abrir, y el
    conector lo asigna dentro de un try porque hay drivers que no lo admiten.
    """

    def __init__(self, cliente: httpx.Client, token: str, sesion: str) -> None:
        self._cliente = cliente
        self._token = token
        self._sesion = sesion
        self._cerrada = False

    autocommit = True

    def _pedir(self, operacion: str, **cuerpo) -> dict:
        return _pedir(self._cliente, self._token, operacion,
                      sesion=self._sesion, **cuerpo)

    def getinfo(self, info: int) -> Any:
        return self._pedir("getinfo", info=int(info))["valor"]

    def cursor(self) -> CursorRemoto:
        return CursorRemoto(self, self._pedir("cursor")["cursor"])

    def close(self) -> None:
        if self._cerrada:
            return
        self._cerrada = True
        try:
            self._pedir("cerrar")
        except ErrorPuente:
            pass
        finally:
            self._cliente.close()


# --------------------------------------------------------------------------- #
# Transporte
# --------------------------------------------------------------------------- #

def _pedir(cliente: httpx.Client, token: str, operacion: str, **cuerpo) -> dict:
    try:
        r = cliente.post(f"/{operacion}", json=cuerpo,
                         headers={"X-Puente-Token": token})
    except httpx.HTTPError as e:
        raise ErrorPuente(
            f"No se pudo hablar con el puente ODBC de 32 bits: {e}. "
            "Comprueba que el servicio 'AstrolabioPuente32' esta arrancado."
        ) from e

    if r.status_code == 401:
        raise ErrorPuente(
            "El puente ODBC rechazo el token. Astrolabio y el puente tienen que "
            "leer el mismo archivo de token; si se regenero uno, reinicia los dos."
        )
    try:
        datos = r.json()
    except json.JSONDecodeError as e:
        raise ErrorPuente(
            f"El puente ODBC contesto algo que no es JSON ({r.status_code}). "
            "Suele ser otra cosa escuchando en ese puerto."
        ) from e

    # Un error del driver se vuelve a levantar como pyodbc.Error para que el
    # conector lo trate igual que si hubiera pasado en este proceso: es lo que
    # hace que no haya dos caminos de manejo de errores.
    if "error_odbc" in datos:
        raise pyodbc.Error(*datos["error_odbc"])
    if "error" in datos:
        raise ErrorPuente(f"El puente ODBC: {datos['error']}")
    if r.status_code != 200:
        raise ErrorPuente(f"El puente ODBC contesto {r.status_code}.")
    return datos


def abrir(cadena: str, url: str, token: str,
          segundos: float = 300.0) -> ConexionRemota:
    """
    Abre una conexion contra el origen a traves del puente.

    El plazo es largo a proposito: por aqui pasa un `SELECT COUNT(*)` sobre una
    tabla de millones de filas, que en Pervasive tarda lo que tarda. Lo que no
    puede tardar es abrir el socket, y de eso se encarga `connect`.
    """
    cliente = httpx.Client(base_url=url.rstrip("/"),
                           timeout=httpx.Timeout(segundos, connect=5.0))
    try:
        r = _pedir(cliente, token, "abrir", cadena=cadena)
    except BaseException:
        cliente.close()
        raise
    return ConexionRemota(cliente, token, r["sesion"])


def salud(url: str, token: str) -> dict:
    """Lo que el puente ve desde su lado: bits, drivers y DSN."""
    with httpx.Client(base_url=url.rstrip("/"),
                      timeout=httpx.Timeout(10.0, connect=5.0)) as cliente:
        return _pedir(cliente, token, "salud")
