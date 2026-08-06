"""
Configuracion por variables de entorno. Un solo lugar donde vive todo lo que
cambia entre una maquina de desarrollo y el servidor.

Todas las variables llevan el prefijo `ASTROLABIO_`. Se pueden poner en el
entorno o en un archivo `.env` junto a `docker-compose.yml`; hay un `.env.ejemplo`
con las que importan y como se generan.

Lo importante de este archivo: **en produccion el arranque falla** si faltan las
claves. Un sistema que arranca con la clave de ejemplo es un sistema en el que
cualquiera puede firmar un token de administrador, y eso no debe poder pasar por
descuido.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parent.parent

#: Version del producto. La usa la API (`/api/salud`) y la pantalla.
VERSION = "0.1.0"

CLAVE_DE_EJEMPLO = "cambiame-en-produccion"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="ASTROLABIO_", extra="ignore"
    )

    # --- entorno ---
    entorno: str = "desarrollo"          # desarrollo | produccion

    # --- metadatos ---
    # SQLite por decision explicita: un mantenedor, un archivo que respaldar.
    # Ver docs/adr/0001-sqlite-para-metadatos.md
    url_metadatos: str = f"sqlite:///{RAIZ / 'datos' / 'astrolabio.db'}"

    # --- motor analitico ---
    ruta_duckdb: str = str(RAIZ / "datos" / "analitico.duckdb")
    duckdb_solo_lectura: bool = True

    # --- seguridad ---
    # OBLIGATORIO cambiar en produccion. El arranque falla si sigue en el valor
    # por defecto y el entorno es produccion.
    clave_secreta: str = CLAVE_DE_EJEMPLO
    minutos_expiracion_token: int = 60 * 8
    algoritmo_jwt: str = "HS256"

    # Clave Fernet para cifrar credenciales de conexiones. Se genera con:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    clave_cifrado: str = ""

    # Correo del administrador que se crea en el primer arranque, con una
    # contrasena temporal que solo se ve en el log de ese arranque.
    correo_admin: str = "admin@example.com"

    # Intentos de ingreso fallidos seguidos, por correo, antes de rechazar sin ni
    # siquiera comprobar la contrasena. 0 lo desactiva.
    intentos_maximos: int = 8
    minutos_bloqueo: int = 15

    # --- programador de cargas ---
    # Se apaga en pruebas y en cualquier proceso que no deba ejecutar cargas
    # (por ejemplo un segundo worker: dos programadores compitiendo por el mismo
    # jobstore duplicarian las cargas).
    programador_activo: bool = True

    # --- avisos ---
    # Sin smtp_host los avisos por correo no se mandan; la pantalla lo dice en vez
    # de dejar creer que hay cobertura. El canal webhook (Teams, Slack) funciona
    # sin configurar nada aqui, porque la URL ya es el destino.
    smtp_host: str = ""
    smtp_puerto: int = 587
    smtp_usuario: str = ""
    smtp_contrasena: str = ""
    smtp_tls: bool = True
    smtp_remitente: str = ""
    # Obligatorio y corto: el envio ocurre dentro de la carga, y un servidor de
    # correo que no contesta no debe dejar la transaccion abierta media hora.
    smtp_timeout: int = 10
    # Permitir webhooks hacia direcciones internas de la red donde corre el
    # servidor. Apagado por defecto: ver la nota en `avisos.destino_permitido`.
    webhooks_a_red_interna: bool = False

    # --- api ---
    origenes_cors: list[str] = ["http://localhost:5173"]

    @property
    def es_produccion(self) -> bool:
        return self.entorno == "produccion"

    def validar(self) -> None:
        if not self.es_produccion:
            return
        if self.clave_secreta == CLAVE_DE_EJEMPLO:
            raise RuntimeError(
                "ASTROLABIO_CLAVE_SECRETA sigue en el valor de ejemplo. "
                "Generala con: openssl rand -hex 32"
            )
        if len(self.clave_secreta) < 32:
            # Con una clave corta, firmar un token de administrador es cuestion de
            # tiempo de CPU. HS256 no avisa de esto por su cuenta.
            raise RuntimeError(
                "ASTROLABIO_CLAVE_SECRETA es demasiado corta: se necesitan al "
                "menos 32 caracteres. Generala con: openssl rand -hex 32"
            )
        if not self.clave_cifrado:
            raise RuntimeError(
                "ASTROLABIO_CLAVE_CIFRADO esta vacia. Generala con: python -c "
                '"from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )


@lru_cache
def config() -> Config:
    c = Config()
    c.validar()
    return c
