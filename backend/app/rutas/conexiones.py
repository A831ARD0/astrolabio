"""
Conexiones a origenes, introspeccion e ingesta.

Las credenciales se guardan cifradas y NUNCA se devuelven: `config_publica()`
las filtra. Las respuestas de esta API no deben poder usarse para reconstruir
una contraseña.
"""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app import programador, ventanas
from app.auditoria import registrar
from app.cargas import Actor, ErrorCarga, ejecutar_carga, ruta_dataset
from app.conectores import OPCIONALES, REQUERIDOS, ErrorConector, TIPOS, crear
from app.config import config
from app.dependencias import SesionDep, UsuarioDep, exigir_rol
from app.modelos_db import Conexion, Dataset, Rol, Usuario
from app.seguridad import cifrar, descifrar
from app.ventanas import VentanaInvalida

router = APIRouter(prefix="/api/conexiones", tags=["conexiones"])

SECRETOS = {"password", "contrasena", "clave", "secret", "token", "pwd"}


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class CrearConexion(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    tipo: str
    config: dict


class EditarConexion(BaseModel):
    """
    Cambio parcial. Las claves que vengan en `config` pisan a las guardadas; las
    que no vengan se quedan como estaban.

    **Un secreto vacío significa "no lo toques", nunca "déjalo en blanco".** La API
    no devuelve las contraseñas, así que el formulario las enseña vacías: si un
    campo vacío borrara el secreto, editar el puerto dejaría la conexión sin
    contraseña. Para quitarlo de verdad se nombra en `borrar_secretos`.

    El tipo no se puede cambiar. Convertir una conexión de MySQL en una de archivos
    no es editar: es otra conexión, y los datasets que cuelgan de ella dejarían de
    tener sentido.
    """
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    config: dict | None = None
    borrar_secretos: list[str] = Field(default_factory=list)


class ConexionSalida(BaseModel):
    id: int
    nombre: str
    tipo: str
    config: dict                  # sin secretos
    tiene_credenciales: bool


class RecargarRango(BaseModel):
    desde: str = Field(description="AAAA-MM-DD, inclusive")
    hasta: str = Field(description="AAAA-MM-DD, inclusive")


class Programacion(BaseModel):
    cron: str = Field(description="5 campos: minuto hora dia mes dia_semana")
    zona_horaria: str = "America/Mexico_City"
    activa: bool = True


class CrearDataset(BaseModel):
    """
    `nombre` es opcional: si no viene, lo arma el servidor como
    `CONEXION__tabla`.

    Con cuarenta sucursales trayendo las mismas tablas, exigirlo obligaba a
    inventar cuarenta nombres distintos a mano —y a acertar, porque el nombre es
    unico en todo el sistema y ademas es la carpeta del Parquet—. Lo que
    identifica a un dataset es de donde sale: conexion, esquema y tabla.
    """
    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    esquema: str | None = None
    tabla: str
    columna_incremental: str | None = None
    particionar_por: str | None = None
    limite: int | None = None
    #: None = todas. Ver la nota en `Dataset.columnas`.
    columnas: list[str] | None = None
    ventana: str | None = None


class EditarDataset(BaseModel):
    """
    Todo opcional, y `None` significa "no lo toques". Para quitar la ventana o
    volver a todas las columnas se manda el centinela vacio: `ventana: ""` y
    `columnas: []`. Sin esa distincion no habria forma de deshacer una eleccion.
    """
    columnas: list[str] | None = None
    ventana: str | None = None
    columna_incremental: str | None = None
    particionar_por: str | None = None


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _conector(fila: Conexion):
    cfg = json.loads(descifrar(fila.config_cifrada))
    try:
        return crear(fila.tipo, cfg)
    except ErrorConector as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


def _salida(fila: Conexion) -> ConexionSalida:
    con = _conector(fila)
    cfg = json.loads(descifrar(fila.config_cifrada))
    return ConexionSalida(
        id=fila.id, nombre=fila.nombre, tipo=fila.tipo,
        config=con.config_publica(),
        tiene_credenciales=any(k.lower() in SECRETOS and v for k, v in cfg.items()),
    )


def _revisar_columnas(conector, tabla: str, esquema: str | None,
                      columnas: list[str] | None,
                      incremental: str | None, particion: str | None) -> None:
    """
    Que las columnas elegidas existan y que no falte ninguna imprescindible.

    Dejar fuera la columna de partición o la incremental es el error que hay que
    atajar aqui: el dataset se guardaria bien y la carga fallaria de madrugada
    diciendo que la columna no existe, cuando el problema es que no se pidio.
    """
    if not columnas:
        return
    try:
        t = conector.describir_tabla(tabla, esquema)
    except ErrorConector as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    disponibles = {c.nombre for c in t.columnas}
    faltan = [c for c in columnas if c not in disponibles]
    if faltan:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Estas columnas no existen en '{tabla}': {', '.join(sorted(faltan))}")

    for etiqueta, col in (("de partición", particion),
                          ("incremental", incremental)):
        if col and col not in columnas:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"La columna {etiqueta} '{col}' tiene que estar entre las que se "
                f"traen. Sin ella la carga no puede {'partir' if col == particion else 'saber por dónde seguir'}.")


def _revisar_ventana(ventana: str | None, particion: str | None,
                     zona: str) -> str | None:
    """Devuelve la descripcion de la ventana, o revienta con el motivo."""
    if not ventana:
        return None
    if not particion:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Una ventana móvil recarga particiones, así que el dataset tiene que "
            "estar partido por una fecha. Elige primero 'Partir por'.")
    try:
        return ventanas.describir(ventana, zona)
    except VentanaInvalida as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))


def _fusionar(guardada: dict, entrante: dict | None,
              borrar: list[str]) -> dict:
    """
    La configuración guardada con los cambios encima.

    Tres reglas, y la segunda es la que importa:

    1. Una clave que viene, pisa.
    2. Un **secreto** que viene vacío, no pisa: se conserva el guardado. El
       formulario no puede mostrar la contraseña, así que llega vacía siempre que
       no se reescriba, y tomarla al pie de la letra dejaría sin credenciales a
       cualquier conexión que se editara por otro motivo.
    3. Un secreto nombrado en `borrar_secretos` se va. Es la única forma de
       quitarlo, y es explícita a propósito.
    """
    fusionada = dict(guardada)
    for clave, valor in (entrante or {}).items():
        if clave.lower() in SECRETOS and not str(valor or "").strip():
            continue
        fusionada[clave] = valor
    for clave in borrar:
        fusionada.pop(clave, None)
    return fusionada


#: Lo que puede llevar el nombre de un dataset. Es tambien el nombre de la
#: carpeta del Parquet, asi que nada de separadores ni de caracteres que Windows
#: rechace en una ruta.
_LIMPIO = re.compile(r"[^A-Za-z0-9_-]+")


def nombre_sugerido(conexion: str, esquema: str | None, tabla: str) -> str:
    """
    `CONEXION__tabla`, que es como uno lo escribiria a mano.

    El esquema entra solo cuando hace falta para distinguir: en MySQL el esquema
    es la base y suele ser el mismo para toda la conexion, asi que meterlo
    siempre alargaria los cuarenta nombres sin distinguir nada.
    """
    partes = [conexion, tabla] if not esquema or esquema == conexion else \
             [conexion, esquema, tabla]
    limpio = "__".join(_LIMPIO.sub("_", p).strip("_") for p in partes if p)
    return limpio[:120].strip("_") or "dataset"


def _nombre_libre(sesion, base: str) -> str:
    """`base`, o `base_2`, `base_3`… hasta encontrar uno que no exista."""
    if not sesion.scalar(select(func.count()).select_from(Dataset)
                         .where(Dataset.nombre == base)):
        return base
    for n in range(2, 1000):
        # El sufijo va DENTRO del limite de 120: recortar despues volveria a
        # chocar justo con el nombre del que se venia huyendo.
        candidato = f"{base[:120 - len(str(n)) - 1]}_{n}"
        if not sesion.scalar(select(func.count()).select_from(Dataset)
                             .where(Dataset.nombre == candidato)):
            return candidato
    raise HTTPException(status.HTTP_409_CONFLICT,
                        f"Hay demasiados datasets llamados '{base}'.")


def _conector_de(tipo: str, cfg: dict):
    try:
        return crear(tipo, cfg)
    except ErrorConector as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))


def _obtener(sesion: SesionDep, conexion_id: int) -> Conexion:
    fila = sesion.get(Conexion, conexion_id)
    if fila is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conexion no encontrada")
    return fila


# --------------------------------------------------------------------------- #
# Conexiones
# --------------------------------------------------------------------------- #

@router.get("/tipos")
def tipos_disponibles(_: UsuarioDep):
    """
    Los campos de cada tipo los dice el servidor, no el formulario. Al agregar un
    conector, la pantalla lo sabe sin tocarla.
    """
    return {
        "tipos": [
            {"tipo": t,
             "requeridos": sorted(REQUERIDOS.get(t, set())),
             "opcionales": OPCIONALES.get(t, [])}
            for t in sorted(TIPOS)
        ]
    }


@router.get("/odbc/instalado")
def odbc_instalado(_: UsuarioDep):
    """
    Que drivers y DSN ve el servidor. Sin esto, configurar ODBC es adivinar: el
    nombre del driver tiene que coincidir **exactamente** con el registrado en la
    maquina, y el error cuando no coincide ("Data source name not found") no dice
    cual era el nombre bueno.
    """
    try:
        import pyodbc
    except ImportError:
        return {"disponible": False, "drivers": [], "dsn": [],
                "aviso": "pyodbc no esta instalado en este servidor."}
    return {
        "disponible": True,
        "drivers": sorted(pyodbc.drivers()),
        "dsn": sorted(pyodbc.dataSources()),
        "puente": _estado_del_puente(),
        "aviso": None if pyodbc.drivers() else
                 "No hay ningun driver ODBC registrado en esta maquina. Se puede "
                 "usar la ruta del driver (.so/.dylib/.dll) en el campo Driver, o "
                 "pedir a sistemas que lo registre en odbcinst.ini.",
    }


def _estado_del_puente() -> dict:
    """
    Si el puente de 32 bits esta arriba, y que ve el desde su lado.

    Sus drivers y sus DSN son OTROS: 32 y 64 bits son dos registros separados en
    Windows. Ensenarlos juntos sin distinguirlos seria peor que no ensenarlos.
    """
    from app.conectores.base import ErrorConector
    from app.conectores.odbc import _ajustes_del_puente

    try:
        from app.conectores import puente
        url, token = _ajustes_del_puente()
    except ErrorConector as e:
        return {"activo": False, "motivo": str(e), "drivers": [], "dsn": []}
    try:
        salud = puente.salud(url, token)
    except ErrorConector as e:
        return {"activo": False, "motivo": str(e), "url": url,
                "drivers": [], "dsn": []}
    return {"activo": True, "url": url, "bits": salud.get("bits"),
            "drivers": salud.get("drivers") or [], "dsn": salud.get("dsn") or []}


@router.get("/odbc/perfiles")
def odbc_perfiles(_: UsuarioDep):
    """
    Los origenes ODBC conocidos, con los campos que pide cada uno y si su driver
    esta instalado en este servidor.

    Es lo mas cerca que se puede estar de como DBeaver descarga drivers: DBeaver
    baja archivos .jar de JDBC, que son portables, y un driver ODBC es una
    libreria nativa que se instala en el sistema —y las dos que hacen falta aqui,
    Pervasive y la de Informix, salen del cliente licenciado del fabricante. Lo
    que si se puede es esto: armar la cadena por origen, detectar lo instalado y
    decir de donde sale lo que falta.
    """
    from app.conectores.perfiles_odbc import catalogo

    try:
        import pyodbc
        instalados = sorted(pyodbc.drivers())
        disponible = True
    except ImportError:
        instalados, disponible = [], False
    return {"disponible": disponible, "drivers": instalados,
            "perfiles": catalogo(instalados)}


@router.get("", response_model=list[ConexionSalida])
def listar(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    return [_salida(f) for f in sesion.scalars(select(Conexion).order_by(Conexion.id))]


@router.post("", response_model=ConexionSalida, status_code=201)
def crear_conexion(cuerpo: CrearConexion, sesion: SesionDep,
                   actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    if sesion.scalar(select(func.count()).select_from(Conexion)
                     .where(Conexion.nombre == cuerpo.nombre)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya existe una conexion con ese nombre")
    try:
        conector = crear(cuerpo.tipo, cuerpo.config)
    except ErrorConector as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))

    prueba = conector.probar()
    if not prueba.ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"No se guardo: la conexion falla. {prueba.mensaje}")

    fila = Conexion(nombre=cuerpo.nombre, tipo=cuerpo.tipo,
                    config_cifrada=cifrar(json.dumps(cuerpo.config)),
                    creado_por=actor.id)
    sesion.add(fila)
    sesion.flush()
    # La auditoria guarda la config publica: jamas el secreto.
    registrar(sesion, accion="conexion_creada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="conexion", objeto_id=fila.id,
              detalle={"nombre": fila.nombre, "tipo": fila.tipo,
                       "config": conector.config_publica()})
    return _salida(fila)


@router.post("/probar-config")
def probar_config(cuerpo: CrearConexion, sesion: SesionDep,
                  actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Prueba una configuracion sin guardarla.

    Existe para que la interfaz pueda decir "conecta" o "no conecta" mientras se
    escriben los datos. Crear ya prueba y se niega a guardar si falla, pero llegar
    ahi con una contraseña mal escrita y recibir un 400 es peor experiencia que
    probarlo antes.

    No persiste nada. Si el intento queda en auditoria es a proposito: es una
    conexion saliente con credenciales, aunque no se guarde.
    """
    try:
        conector = crear(cuerpo.tipo, cuerpo.config)
    except ErrorConector as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))

    r = conector.probar()
    registrar(sesion, accion="conexion_probada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="conexion",
              detalle={"nombre": cuerpo.nombre, "tipo": cuerpo.tipo,
                       "config": conector.config_publica(), "ok": r.ok})
    return {"ok": r.ok, "mensaje": r.mensaje, "detalle": r.detalle}


@router.post("/{conexion_id}/probar")
def probar(conexion_id: int, sesion: SesionDep,
           _: Usuario = Depends(exigir_rol(Rol.editor))):
    r = _conector(_obtener(sesion, conexion_id)).probar()
    return {"ok": r.ok, "mensaje": r.mensaje, "detalle": r.detalle}


@router.post("/{conexion_id}/probar-cambio")
def probar_cambio(conexion_id: int, cuerpo: EditarConexion, sesion: SesionDep,
                  actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Prueba un cambio sin guardarlo, con los secretos que ya estaban.

    `probar-config` no sirve para editar: no conoce la contraseña guardada, así que
    probar un cambio de puerto obligaría a volver a escribirla solo para poder
    pulsar el botón. Aquí se fusiona primero y se prueba lo que de verdad se
    guardaría.
    """
    fila = _obtener(sesion, conexion_id)
    guardada = json.loads(descifrar(fila.config_cifrada))
    cfg = _fusionar(guardada, cuerpo.config, cuerpo.borrar_secretos)
    conector = _conector_de(fila.tipo, cfg)

    r = conector.probar()
    registrar(sesion, accion="conexion_probada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="conexion", objeto_id=fila.id,
              detalle={"nombre": fila.nombre, "tipo": fila.tipo,
                       "config": conector.config_publica(), "ok": r.ok})
    return {"ok": r.ok, "mensaje": r.mensaje, "detalle": r.detalle}


@router.patch("/{conexion_id}", response_model=ConexionSalida)
def editar_conexion(conexion_id: int, cuerpo: EditarConexion, sesion: SesionDep,
                    actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Cambia el nombre o la configuración de una conexión ya creada.

    Existe porque sin esto rotar una contraseña obligaba a borrar la conexión y
    volver a crearla, **y con ella se iban todos sus datasets en cascada**: el
    historial de cargas, los horarios y las columnas elegidas. Una contraseña que
    caduca cada noventa días no puede costar eso.

    Se prueba antes de guardar, igual que al crear: una conexión guardada que no
    conecta es una carga que falla de madrugada.
    """
    fila = _obtener(sesion, conexion_id)
    guardada = json.loads(descifrar(fila.config_cifrada))
    antes = _conector_de(fila.tipo, guardada).config_publica()

    if cuerpo.nombre and cuerpo.nombre != fila.nombre:
        if sesion.scalar(select(func.count()).select_from(Conexion)
                         .where(Conexion.nombre == cuerpo.nombre,
                                Conexion.id != conexion_id)):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Ya existe una conexion con ese nombre")

    cfg = _fusionar(guardada, cuerpo.config, cuerpo.borrar_secretos)
    conector = _conector_de(fila.tipo, cfg)

    prueba = conector.probar()
    if not prueba.ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"No se guardo: la conexion falla. {prueba.mensaje}")

    if cuerpo.nombre:
        fila.nombre = cuerpo.nombre
    fila.config_cifrada = cifrar(json.dumps(cfg))
    sesion.flush()

    despues = conector.config_publica()
    # Solo lo publico: el diff jamas puede delatar un secreto, ni por su longitud.
    cambios = {k: [antes.get(k), despues.get(k)]
               for k in set(antes) | set(despues)
               if antes.get(k) != despues.get(k)}
    secretos_tocados = sorted(
        {k for k in (cuerpo.config or {})
         if k.lower() in SECRETOS and str((cuerpo.config or {})[k] or "").strip()}
        | set(cuerpo.borrar_secretos))

    registrar(sesion, accion="conexion_editada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="conexion", objeto_id=fila.id,
              detalle={"nombre": fila.nombre, "tipo": fila.tipo,
                       "cambios": cambios,
                       "secretos_cambiados": secretos_tocados})
    return _salida(fila)


@router.delete("/{conexion_id}", status_code=204)
def borrar(conexion_id: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    fila = _obtener(sesion, conexion_id)
    nombre = fila.nombre
    sesion.delete(fila)
    registrar(sesion, accion="conexion_borrada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="conexion", objeto_id=conexion_id,
              detalle={"nombre": nombre})


# --------------------------------------------------------------------------- #
# Introspeccion
# --------------------------------------------------------------------------- #

@router.get("/{conexion_id}/esquemas")
def esquemas(conexion_id: int, sesion: SesionDep,
             _: Usuario = Depends(exigir_rol(Rol.editor))):
    try:
        return {"esquemas": _conector(_obtener(sesion, conexion_id)).listar_esquemas()}
    except ErrorConector as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/{conexion_id}/tablas")
def tablas(conexion_id: int, sesion: SesionDep, esquema: str | None = None,
           _: Usuario = Depends(exigir_rol(Rol.editor))):
    try:
        lista = _conector(_obtener(sesion, conexion_id)).listar_tablas(esquema)
    except ErrorConector as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"tablas": [
        {"esquema": t.esquema, "nombre": t.nombre,
         "filas_estimadas": t.filas_estimadas, "es_vista": t.es_vista}
        for t in lista
    ]}


@router.get("/{conexion_id}/tablas/{tabla}")
def describir(conexion_id: int, tabla: str, sesion: SesionDep,
              esquema: str | None = None,
              _: Usuario = Depends(exigir_rol(Rol.editor))):
    try:
        t = _conector(_obtener(sesion, conexion_id)).describir_tabla(tabla, esquema)
    except ErrorConector as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {
        "esquema": t.esquema, "nombre": t.nombre, "filas": t.filas_estimadas,
        "es_vista": t.es_vista,
        "columnas": [
            {"nombre": c.nombre, "tipo": c.tipo_origen,
             "nulable": c.nulable, "es_clave": c.es_clave}
            for c in t.columnas
        ],
    }


@router.get("/{conexion_id}/tablas/{tabla}/muestra")
def muestra(conexion_id: int, tabla: str, sesion: SesionDep,
            esquema: str | None = None, limite: int = 50,
            columnas: str | None = None,
            _: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    `columnas` es una lista separada por comas. Vacío o ausente = todas.

    Se le piden al origen esas columnas y no las demás: la vista previa tiene que
    ser una muestra de lo que se va a traer.
    """
    elegidas = [c for c in (columnas or "").split(",") if c.strip()] or None
    try:
        cols, filas = _conector(_obtener(sesion, conexion_id)).muestra(
            tabla, esquema, min(limite, 500), elegidas)
    except ErrorConector as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"columnas": cols,
            "filas": [dict(zip(cols, (str(v) if v is not None else None for v in f)))
                      for f in filas]}


# --------------------------------------------------------------------------- #
# Datasets e ingesta
# --------------------------------------------------------------------------- #

@router.post("/{conexion_id}/datasets", status_code=201)
def crear_dataset(conexion_id: int, cuerpo: CrearDataset, sesion: SesionDep,
                  actor: Usuario = Depends(exigir_rol(Rol.editor))):
    fila = _obtener(sesion, conexion_id)

    if cuerpo.nombre:
        if sesion.scalar(select(func.count()).select_from(Dataset)
                         .where(Dataset.nombre == cuerpo.nombre)):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Ya existe un dataset con ese nombre")
        nombre = cuerpo.nombre
    else:
        nombre = _nombre_libre(
            sesion, nombre_sugerido(fila.nombre, cuerpo.esquema, cuerpo.tabla))

    _revisar_columnas(_conector(fila), cuerpo.tabla, cuerpo.esquema,
                      cuerpo.columnas, cuerpo.columna_incremental,
                      cuerpo.particionar_por)
    zona = "America/Mexico_City"
    ventana_dicha = _revisar_ventana(cuerpo.ventana, cuerpo.particionar_por, zona)

    ds = Dataset(
        nombre=nombre, conexion_id=conexion_id,
        esquema_origen=cuerpo.esquema, tabla_origen=cuerpo.tabla,
        columna_incremental=cuerpo.columna_incremental,
        particionar_por=cuerpo.particionar_por, creado_por=actor.id,
        columnas=cuerpo.columnas or None, ventana=cuerpo.ventana or None,
        zona_horaria=zona,
    )
    sesion.add(ds)
    sesion.flush()
    registrar(sesion, accion="dataset_creado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dataset", objeto_id=ds.id,
              detalle={"nombre": ds.nombre, "tabla": ds.tabla_origen,
                       "columnas": ds.columnas, "ventana": ds.ventana})
    return {"id": ds.id, "nombre": ds.nombre, "ventana": ventana_dicha}


def _describir_sin_reventar(ds: Dataset) -> str | None:
    """
    Lo que va a recargar la ventana, con las fechas de hoy. Listar datasets no
    puede fallar por una ventana mal guardada.
    """
    if not ds.ventana:
        return None
    try:
        return ventanas.describir(ds.ventana, ds.zona_horaria)
    except VentanaInvalida as e:
        return f"Ventana inválida: {e}"


@router.get("/ventanas")
def ventanas_disponibles(_: UsuarioDep):
    """Las ventanas móviles que se pueden elegir, con su etiqueta."""
    return {"ventanas": ventanas.claves()}


@router.get("/datasets/lista")
def listar_datasets(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.editor))):
    salida = []
    for ds in sesion.scalars(select(Dataset).order_by(Dataset.nombre)):
        ultima = ds.ejecuciones[0] if ds.ejecuciones else None
        proxima = programador.proxima_corrida(ds.id)
        salida.append({
            "id": ds.id, "nombre": ds.nombre, "tabla_origen": ds.tabla_origen,
            # La conexion y el esquema hacen falta para poder editar las columnas
            # desde el panel: sin ellos no se puede preguntar al origen que
            # columnas existen.
            "conexion_id": ds.conexion_id, "esquema_origen": ds.esquema_origen,
            "filas": ds.filas, "mb": round(ds.bytes_parquet / 1024 / 1024, 1),
            "incremental": ds.columna_incremental,
            "particionado": ds.particionar_por,
            "columnas": ds.columnas,          # null = todas
            "ventana": ds.ventana,
            "ventana_dicha": _describir_sin_reventar(ds),
            "marca_maxima": ds.marca_maxima,
            "ultima_carga": ds.ultima_carga.isoformat() if ds.ultima_carga else None,
            "ultimo_estado": ultima.estado.value if ultima else None,
            "cron": ds.cron,
            "zona_horaria": ds.zona_horaria,
            "programacion_activa": ds.programacion_activa,
            "proxima_corrida": proxima.isoformat() if proxima else None,
        })
    return {"datasets": salida}


def _dataset(sesion: SesionDep, dataset_id: int) -> Dataset:
    ds = sesion.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset no encontrado")
    return ds


@router.patch("/datasets/{dataset_id}")
def editar_dataset(dataset_id: int, cuerpo: EditarDataset, sesion: SesionDep,
                   actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Cambia qué columnas se traen, la ventana móvil, la columna incremental o la de
    partición.

    Cambiar el juego de columnas **obliga a una carga completa**, y aquí se hace
    explícito: se borra la marca máxima, con lo que la siguiente carga reescribe el
    dataset entero. No es una precaución exagerada. El Parquet que ya está en disco
    tiene las columnas viejas; si se agregara un lote con columnas distintas, leer
    el dataset fallaría o —peor— devolvería nulos donde antes había datos. Se avisa
    en la respuesta para que nadie lo descubra por el tiempo que tardó la carga.
    """
    ds = _dataset(sesion, dataset_id)
    antes = {"columnas": ds.columnas, "ventana": ds.ventana,
             "columna_incremental": ds.columna_incremental,
             "particionar_por": ds.particionar_por}

    if cuerpo.columna_incremental is not None:
        ds.columna_incremental = cuerpo.columna_incremental or None
    if cuerpo.particionar_por is not None:
        ds.particionar_por = cuerpo.particionar_por or None

    cambio_columnas = False
    if cuerpo.columnas is not None:
        nuevas = cuerpo.columnas or None
        cambio_columnas = set(nuevas or []) != set(ds.columnas or [])
        _revisar_columnas(_conector(_obtener(sesion, ds.conexion_id)),
                          ds.tabla_origen, ds.esquema_origen, nuevas,
                          ds.columna_incremental, ds.particionar_por)
        ds.columnas = nuevas

    ventana_dicha = None
    if cuerpo.ventana is not None:
        ds.ventana = cuerpo.ventana or None
        ventana_dicha = _revisar_ventana(ds.ventana, ds.particionar_por,
                                         ds.zona_horaria)

    # Si se quitó la partición, la ventana se queda sin sentido.
    if ds.ventana and not ds.particionar_por:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Este dataset tiene una ventana móvil, así que no se le puede quitar "
            "la columna de partición. Quita primero la ventana.")

    avisos = []
    if cambio_columnas:
        ds.marca_maxima = None
        avisos.append("Cambió el juego de columnas: la siguiente carga será "
                      "completa y reescribirá el dataset. Los datos que ya están "
                      "en disco tienen las columnas viejas.")

    despues = {"columnas": ds.columnas, "ventana": ds.ventana,
               "columna_incremental": ds.columna_incremental,
               "particionar_por": ds.particionar_por}
    registrar(sesion, accion="dataset_editado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dataset", objeto_id=ds.id,
              detalle={"nombre": ds.nombre,
                       "cambios": {k: [antes[k], despues[k]]
                                   for k in antes if antes[k] != despues[k]}})
    return {"id": ds.id, "nombre": ds.nombre, "columnas": ds.columnas,
            "ventana": ds.ventana, "ventana_dicha": ventana_dicha,
            "avisos": avisos}


@router.post("/datasets/{dataset_id}/cargar")
def cargar(dataset_id: int, sesion: SesionDep,
           incremental: bool = True, limite: int | None = None,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Ejecuta la carga. Si el dataset tiene columna incremental y ya hay marca
    previa, trae solo lo nuevo; si tiene ventana móvil, recarga la ventana.

    `incremental=false` es "volver a traer todo", y por eso **se salta la ventana**:
    quien pide una carga completa quiere el dataset entero, no el mes en curso.
    """
    ds = _dataset(sesion, dataset_id)
    try:
        return ejecutar_carga(sesion, ds, Actor(id=actor.id, email=actor.email),
                              incremental=incremental, limite=limite,
                              usar_ventana=incremental)
    except ErrorCarga as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"La carga fallo: {e}")


@router.post("/datasets/{dataset_id}/recargar-rango")
def recargar_rango(dataset_id: int, cuerpo: RecargarRango, sesion: SesionDep,
                   actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Recarga un rango de fechas reemplazando SOLO las particiones que cubre.

    Es lo que hace practicable corregir un mes de hace tres años sin volver a
    traer diez años de historia. El rango se reemplaza completo, asi que las
    bajas en el origen tambien se reflejan.
    """
    ds = _dataset(sesion, dataset_id)
    if not ds.particionar_por:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El dataset '{ds.nombre}' no esta particionado: no hay particiones "
            f"que reemplazar. Usa la carga completa.")
    try:
        return ejecutar_carga(sesion, ds, Actor(id=actor.id, email=actor.email),
                              rango_desde=cuerpo.desde, rango_hasta=cuerpo.hasta)
    except ErrorCarga as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"La recarga fallo: {e}")


@router.delete("/datasets/{dataset_id}", status_code=200)
def borrar_dataset(dataset_id: int, sesion: SesionDep,
                   actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Da de baja el dataset: su registro, su historial y su horario.

    Los archivos Parquet NO se borran, y la respuesta dice donde quedaron. Es
    deliberado: borrar datos es la accion que no tiene vuelta atras, y un dataset
    se da de baja casi siempre por un nombre mal puesto, no porque los datos
    sobren. Quien quiera el espacio borra el directorio a mano, viendolo.
    """
    ds = _dataset(sesion, dataset_id)
    nombre, ruta = ds.nombre, str(ruta_dataset(ds.nombre))
    tenia_horario = bool(ds.cron)

    sesion.delete(ds)
    sesion.commit()                  # ver la nota en programar()
    if tenia_horario:
        programador.quitar(dataset_id)

    registrar(sesion, accion="dataset_borrado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dataset", objeto_id=dataset_id,
              detalle={"nombre": nombre, "parquet_conservado": ruta})
    return {"nombre": nombre, "parquet_conservado": ruta,
            "aviso": ("Se dio de baja el registro. Los archivos Parquet siguen en "
                      f"{ruta}: borralos a mano si quieres el espacio.")}


@router.get("/datasets/{dataset_id}/historial")
def historial(dataset_id: int, sesion: SesionDep,
              _: Usuario = Depends(exigir_rol(Rol.editor))):
    ds = _dataset(sesion, dataset_id)
    return {"ejecuciones": [
        {"id": e.id, "estado": e.estado.value, "modo": e.modo,
         "disparo": e.origen, "filas": e.filas, "ms": e.ms,
         "mensaje": e.mensaje, "detalle": e.detalle,
         "cuando": e.creado_en.isoformat()}
        for e in ds.ejecuciones[:50]
    ]}


# --------------------------------------------------------------------------- #
# Programacion
# --------------------------------------------------------------------------- #

@router.put("/datasets/{dataset_id}/programacion")
def programar(dataset_id: int, cuerpo: Programacion, sesion: SesionDep,
              actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Programa la carga con una expresion cron. Se valida aqui: un cron invalido
    debe fallar en la peticion, no de madrugada dentro del programador.
    """
    ds = _dataset(sesion, dataset_id)
    try:
        programador.validar_cron(cuerpo.cron, cuerpo.zona_horaria)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))

    ds.cron = cuerpo.cron
    ds.zona_horaria = cuerpo.zona_horaria
    ds.programacion_activa = cuerpo.activa
    # Confirmar ANTES de tocar el programador: su jobstore escribe en la misma
    # base, y dos escritores sobre el mismo SQLite se bloquean entre si. Ademas
    # no tiene sentido programar algo que todavia no esta guardado.
    sesion.commit()
    programador.aplicar(ds)

    registrar(sesion, accion="programacion_guardada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dataset", objeto_id=ds.id,
              detalle={"cron": ds.cron, "zona": ds.zona_horaria,
                       "activa": ds.programacion_activa})
    proxima = programador.proxima_corrida(ds.id)
    return {"cron": ds.cron, "zona_horaria": ds.zona_horaria,
            "activa": ds.programacion_activa,
            "proxima": proxima.isoformat() if proxima else None}


@router.delete("/datasets/{dataset_id}/programacion", status_code=204)
def desprogramar(dataset_id: int, sesion: SesionDep,
                 actor: Usuario = Depends(exigir_rol(Rol.editor))):
    ds = _dataset(sesion, dataset_id)
    ds.cron = None
    ds.programacion_activa = False
    sesion.commit()                  # ver la nota en programar()
    programador.quitar(ds.id)
    registrar(sesion, accion="programacion_borrada", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dataset", objeto_id=ds.id,
              detalle={"nombre": ds.nombre})


@router.get("/programacion")
def ver_programacion(_: Usuario = Depends(exigir_rol(Rol.editor))):
    """Que va a correr y cuando, tal como lo ve el programador."""
    return {"activo": config().programador_activo, "trabajos": programador.listar()}
