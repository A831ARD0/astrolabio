"""Autenticacion y gestion de usuarios."""

import re
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.auditoria import registrar
from app import intentos
from app.dependencias import SesionDep, UsuarioDep, exigir_rol
from app.modelos_db import AtributoUsuario, Rol, Usuario
from app.seguridad import crear_token, hashear, verificar

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: str
    nombre: str


class UsuarioSalida(BaseModel):
    id: int
    email: str
    nombre: str
    rol: Rol
    activo: bool
    atributos: dict[str, str] = {}
    ultimo_ingreso: str | None = None
    creado_en: str | None = None


class CrearUsuario(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=1, max_length=255)
    contrasena: str = Field(min_length=10, description="Minimo 10 caracteres")
    rol: Rol = Rol.lector
    atributos: dict[str, str] = {}


class EditarUsuario(BaseModel):
    """
    Todo opcional: la interfaz manda solo lo que cambio. `atributos`, cuando viene,
    REEMPLAZA el juego completo — es lo que hace posible quitar uno, que con una
    mezcla no se podria.
    """
    nombre: str | None = Field(default=None, min_length=1, max_length=255)
    rol: Rol | None = None
    activo: bool | None = None
    atributos: dict[str, str] | None = None


class CambiarContrasena(BaseModel):
    actual: str
    nueva: str = Field(min_length=10)


class RestablecerContrasena(BaseModel):
    nueva: str = Field(min_length=10)


# Las claves de atributo se usan en las politicas como {{ usuario.clave }}, asi que
# tienen que ser identificadores: un espacio o un acento ahi rompe el predicado.
CLAVE_ATRIBUTO = re.compile(r"^[a-z][a-z0-9_]*$")


def _revisar_atributos(atributos: dict[str, str]) -> None:
    malas = [k for k in atributos if not CLAVE_ATRIBUTO.match(k)]
    if malas:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Estas claves de atributo no sirven en una politica: {malas}. "
            f"Usa minusculas, numeros y guion bajo, empezando por letra "
            f"(por ejemplo: region_id).")


def _poner_atributos(sesion, usuario: Usuario, atributos: dict[str, str]) -> None:
    """
    Reemplaza el juego completo de atributos.

    El borrado va con su propio flush ANTES de insertar: en un solo flush
    SQLAlchemy inserta primero y borra despues, y reasignar el mismo atributo con
    otro valor choca contra UNIQUE(usuario_id, clave).
    """
    usuario.atributos.clear()
    sesion.flush()
    usuario.atributos = [
        AtributoUsuario(clave=k, valor=str(v)) for k, v in atributos.items()
    ]


def _salida(u: Usuario) -> UsuarioSalida:
    return UsuarioSalida(
        id=u.id, email=u.email, nombre=u.nombre, rol=u.rol,
        activo=u.activo, atributos=u.dict_atributos,
        ultimo_ingreso=u.ultimo_ingreso.isoformat() if u.ultimo_ingreso else None,
        creado_en=u.creado_en.isoformat() if u.creado_en else None,
    )


def _cuidar_ultimo_administrador(sesion, usuario: Usuario, *,
                                 rol: Rol | None, activo: bool | None) -> None:
    """
    Nadie puede dejar el sistema sin administradores activos.

    Sin este candado, un administrador se quita el rol a si mismo por descuido y ya
    no hay forma de volver a entrar a la administracion: haria falta editar la base
    a mano. Es un error de un clic y sin vuelta atras, asi que se bloquea.
    """
    quitando_rol = rol is not None and rol != Rol.administrador
    desactivando = activo is False
    if usuario.rol != Rol.administrador or not (quitando_rol or desactivando):
        return

    otros = sesion.scalar(
        select(func.count()).select_from(Usuario)
        .where(Usuario.rol == Rol.administrador, Usuario.activo.is_(True),
               Usuario.id != usuario.id)) or 0
    if otros == 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Es el unico administrador activo. Nombra a otro antes de quitarle "
            "el rol o desactivarlo, o nadie podra volver a administrar Astrolabio.")


@router.post("/token", response_model=Token)
def iniciar_sesion(
    datos: Annotated[OAuth2PasswordRequestForm, Depends()],
    sesion: SesionDep,
):
    # El freno va ANTES de comprobar nada: si no, cada intento seguiria costando
    # un hash de Argon2 y el bloqueo no ahorraria el trabajo que lo hace lento.
    if (faltan := intentos.bloqueado(datos.username)):
        registrar(sesion, accion="ingreso_bloqueado", email=datos.username,
                  detalle={"faltan_segundos": faltan})
        sesion.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Demasiados intentos fallidos. Vuelve a probar en "
            f"{max(1, faltan // 60)} minuto(s).",
            headers={"Retry-After": str(faltan)},
        )

    usuario = sesion.scalar(select(Usuario).where(Usuario.email == datos.username))
    # Mismo mensaje para usuario inexistente y contraseña mala: no revelar cuales
    # correos existen.
    if not usuario or not verificar(datos.password, usuario.hash_contrasena):
        intentos.fallo(datos.username)
        registrar(sesion, accion="ingreso_fallido", email=datos.username)
        # Se confirma antes de lanzar: la dependencia de sesion hace rollback
        # cuando la ruta falla, y sin este commit los intentos fallidos —lo
        # primero que se mira cuando se sospecha de algo— no quedaban en ninguna
        # parte.
        sesion.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not usuario.activo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La cuenta esta desactivada")

    intentos.exito(datos.username)
    usuario.ultimo_ingreso = datetime.now(timezone.utc)
    registrar(sesion, accion="ingreso", usuario_id=usuario.id, email=usuario.email)
    return Token(
        access_token=crear_token(usuario.email, usuario.rol.value),
        rol=usuario.rol.value,
        nombre=usuario.nombre,
    )


@router.get("/yo", response_model=UsuarioSalida)
def quien_soy(usuario: UsuarioDep):
    return _salida(usuario)


@router.get("/usuarios", response_model=list[UsuarioSalida])
def listar_usuarios(sesion: SesionDep, _: Usuario = Depends(exigir_rol(Rol.administrador))):
    return [_salida(u) for u in sesion.scalars(select(Usuario).order_by(Usuario.id))]


@router.post("/usuarios", response_model=UsuarioSalida, status_code=201)
def crear_usuario(
    cuerpo: CrearUsuario,
    sesion: SesionDep,
    actor: Usuario = Depends(exigir_rol(Rol.administrador)),
):
    if sesion.scalar(select(func.count()).select_from(Usuario)
                     .where(Usuario.email == str(cuerpo.email))):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ese correo ya esta registrado")

    _revisar_atributos(cuerpo.atributos)

    usuario = Usuario(
        email=str(cuerpo.email), nombre=cuerpo.nombre,
        hash_contrasena=hashear(cuerpo.contrasena), rol=cuerpo.rol,
    )
    usuario.atributos = [
        AtributoUsuario(clave=k, valor=str(v)) for k, v in cuerpo.atributos.items()
    ]
    sesion.add(usuario)
    sesion.flush()
    registrar(sesion, accion="usuario_creado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="usuario", objeto_id=usuario.id,
              detalle={"email": usuario.email, "rol": usuario.rol.value,
                       "atributos": cuerpo.atributos})
    return _salida(usuario)


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioSalida)
def editar_usuario(usuario_id: int, cuerpo: EditarUsuario, sesion: SesionDep,
                   actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Cambia nombre, rol, si esta activo y sus atributos.

    El correo no se cambia: es la identidad con la que esta escrito todo el registro
    de auditoria, y renombrarlo dejaria el historial apuntando a alguien que ya no
    se llama asi. Si hace falta otro correo, es otra cuenta.
    """
    usuario = sesion.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")

    _cuidar_ultimo_administrador(sesion, usuario, rol=cuerpo.rol,
                                 activo=cuerpo.activo)

    antes = {"nombre": usuario.nombre, "rol": usuario.rol.value,
             "activo": usuario.activo, "atributos": usuario.dict_atributos}

    if cuerpo.nombre is not None:
        usuario.nombre = cuerpo.nombre
    if cuerpo.rol is not None:
        usuario.rol = cuerpo.rol
    if cuerpo.activo is not None:
        usuario.activo = cuerpo.activo
    if cuerpo.atributos is not None:
        _revisar_atributos(cuerpo.atributos)
        _poner_atributos(sesion, usuario, cuerpo.atributos)

    sesion.flush()
    despues = {"nombre": usuario.nombre, "rol": usuario.rol.value,
               "activo": usuario.activo, "atributos": usuario.dict_atributos}
    # Se guarda el antes y el despues, no solo lo nuevo: cambiar un atributo cambia
    # que filas ve esa persona, y sin el valor anterior no se puede reconstruir que
    # veia el mes pasado.
    registrar(sesion, accion="usuario_editado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="usuario", objeto_id=usuario.id,
              detalle={"objetivo": usuario.email,
                       "cambios": {k: [antes[k], despues[k]]
                                   for k in antes if antes[k] != despues[k]}})
    return _salida(usuario)


@router.post("/usuarios/{usuario_id}/contrasena", status_code=204)
def restablecer_contrasena(usuario_id: int, cuerpo: RestablecerContrasena,
                           sesion: SesionDep,
                           actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """Restablecer, no consultar: la contraseña anterior no se puede leer."""
    usuario = sesion.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuario no encontrado")
    usuario.hash_contrasena = hashear(cuerpo.nueva)
    registrar(sesion, accion="contrasena_restablecida", usuario_id=actor.id,
              email=actor.email, objeto_tipo="usuario", objeto_id=usuario.id,
              detalle={"objetivo": usuario.email})


@router.post("/cambiar-contrasena", status_code=204)
def cambiar_contrasena(cuerpo: CambiarContrasena, sesion: SesionDep,
                       usuario: UsuarioDep):
    """
    La propia. Pide la actual aunque el token ya pruebe quien eres: una sesion
    abierta en una maquina ajena no debe poder quedarse con la cuenta.
    """
    if not verificar(cuerpo.actual, usuario.hash_contrasena):
        registrar(sesion, accion="cambio_contrasena_fallido",
                  usuario_id=usuario.id, email=usuario.email)
        sesion.commit()                 # igual que el ingreso fallido: no se pierde
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "La contraseña actual no es correcta")
    usuario.hash_contrasena = hashear(cuerpo.nueva)
    registrar(sesion, accion="contrasena_cambiada", usuario_id=usuario.id,
              email=usuario.email)
