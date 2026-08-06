"""
Tareas de administracion que hacen falta cuando nadie puede entrar.

    python administrar.py listar-usuarios
    python administrar.py restablecer correo@empresa.com
    python administrar.py restablecer correo@empresa.com --crear

La primera contrasena del administrador solo se escribe en el registro del
primer arranque. Si ese registro se perdio —se rota, se sobrescribe, el
servicio se instalo despues— no habia forma de entrar y la unica salida era
borrar la base de metadatos, que se lleva por delante todo lo demas.

Esto corre en el servidor, con acceso al archivo de metadatos: quien lo ejecuta
ya podria leer la base entera. No es una puerta trasera, es la llave de casa.
"""

from __future__ import annotations

import argparse
import secrets
import sys

from sqlalchemy import select

from app.db import CrearSesion
from app.esquema import actualizar as actualizar_esquema
from app.modelos_db import Rol, Usuario
from app.seguridad import hashear


def listar() -> int:
    with CrearSesion() as sesion:
        usuarios = sesion.scalars(select(Usuario).order_by(Usuario.id)).all()
        if not usuarios:
            print("No hay ningun usuario. La base esta recien creada.")
            return 0
        ancho = max(len(u.email) for u in usuarios)
        for u in usuarios:
            estado = "" if u.activo else "  (inactivo)"
            print(f"  {u.email:<{ancho}}  {u.rol.value}{estado}")
    return 0


def restablecer(correo: str, crear: bool) -> int:
    with CrearSesion() as sesion:
        usuario = sesion.scalar(select(Usuario).where(Usuario.email == correo))

        if usuario is None:
            if not crear:
                print(f"No existe ningun usuario con el correo '{correo}'.",
                      file=sys.stderr)
                print("Mira quien hay con:  python administrar.py listar-usuarios",
                      file=sys.stderr)
                print("O crealo con --crear (queda como administrador).",
                      file=sys.stderr)
                return 1
            usuario = Usuario(email=correo, nombre="Administrador",
                              rol=Rol.administrador, hash_contrasena="")
            sesion.add(usuario)
            accion = "creado"
        else:
            accion = "restablecido"

        temporal = secrets.token_urlsafe(12)
        usuario.hash_contrasena = hashear(temporal)
        # Un usuario desactivado tampoco entra, y restablecerle la contrasena
        # sin reactivarlo daria una contrasena que no sirve para nada.
        usuario.activo = True
        sesion.commit()

    # El freno de fuerza bruta vive en memoria del proceso, no aqui: si la
    # cuenta estaba bloqueada por intentos fallidos, sigue bloqueada hasta que
    # pasen los minutos o se reinicie el servicio.
    print()
    print(f"  Usuario {accion}: {correo}")
    print(f"  Contrasena temporal: {temporal}")
    print()
    print("  Cambiala en cuanto entres. No se vuelve a mostrar.")
    print("  Si la cuenta estaba frenada por intentos fallidos, reinicia el")
    print("  servicio o espera los minutos de bloqueo.")
    print()
    return 0


def main() -> int:
    principal = argparse.ArgumentParser(
        description="Administracion de Astrolabio desde el servidor.")
    ordenes = principal.add_subparsers(dest="orden", required=True)

    ordenes.add_parser("listar-usuarios", help="Quien existe y con que rol.")

    p = ordenes.add_parser("restablecer",
                           help="Nueva contrasena temporal para un usuario.")
    p.add_argument("correo")
    p.add_argument("--crear", action="store_true",
                   help="Si no existe, crearlo como administrador.")

    args = principal.parse_args()

    # Igual que el arranque de la aplicacion. Sin esto, contra una base recien
    # creada esto reventaba con un muro de SQLAlchemy diciendo "no such table:
    # usuario", que no le dice nada a quien solo quiere entrar.
    actualizar_esquema()

    if args.orden == "listar-usuarios":
        return listar()
    return restablecer(args.correo, args.crear)


if __name__ == "__main__":
    raise SystemExit(main())
