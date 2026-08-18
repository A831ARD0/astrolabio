"""
Tablas de metadatos.

Decision de diseño: `VersionModelo` es INMUTABLE. Guardar un modelo no
sobreescribe: crea una version nueva. Los dashboards se anclan a una version
concreta, asi que editar el modelo no rompe en silencio lo ya publicado.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    """
    ISO **con la marca de UTC**, para todo lo que salga de una columna de fecha.

    `ahora()` guarda en UTC, pero la columna es `DateTime` sin zona: al leerla
    vuelve naive, y un `isoformat()` pelado produce '2026-08-07T00:15:00', que el
    navegador interpreta como hora local. Una carga de las seis de la tarde se
    ensenaba como las doce y cuarto de la noche del dia siguiente.

    Lo que ya viene con zona —las proximas corridas, que las calcula el
    programador— se deja tal cual.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class Base(DeclarativeBase):
    pass


class Rol(str, enum.Enum):
    administrador = "administrador"
    editor = "editor"
    lector = "lector"


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(255))
    hash_contrasena: Mapped[str] = mapped_column(String(255))
    rol: Mapped[Rol] = mapped_column(Enum(Rol), default=Rol.lector)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    ultimo_ingreso: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    atributos: Mapped[list[AtributoUsuario]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def dict_atributos(self) -> dict[str, str]:
        """Contexto para la seguridad por fila: {'region_id': '1', ...}"""
        return {a.clave: a.valor for a in self.atributos}


class AtributoUsuario(Base):
    """
    Atributos que alimentan la seguridad por fila. Por ejemplo region_id=1 para
    que 'Direccion Regional Norte' solo vea sus sucursales.
    """

    __tablename__ = "atributo_usuario"
    __table_args__ = (UniqueConstraint("usuario_id", "clave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"))
    clave: Mapped[str] = mapped_column(String(64))
    valor: Mapped[str] = mapped_column(String(255))

    usuario: Mapped[Usuario] = relationship(back_populates="atributos")


class Conexion(Base):
    __tablename__ = "conexion"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    tipo: Mapped[str] = mapped_column(String(40))          # odbc | mariadb | archivo
    # Credenciales cifradas con Fernet; nunca en claro, ni en la BD ni en logs.
    config_cifrada: Mapped[str] = mapped_column(Text)
    # Constantes de esta conexion: {"id_sucursal": 3, "marca": "VW"}. Salen como
    # columnas al leer cualquiera de sus datasets.
    #
    # Cuarenta sucursales con el mismo sistema dan cuarenta veces la misma tabla,
    # y una vez juntas no hay forma de saber de cual venia cada fila. La etiqueta
    # es ese dato, y vive en la conexion porque es de la sucursal entera, no de
    # una tabla suya. NO se cifra: no es un secreto, es un identificador de
    # negocio que se ve en los tableros.
    etiquetas: Mapped[dict] = mapped_column(JSON, default=dict)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)


class Dataset(Base):
    """
    Una tabla del origen ya traida a Parquet local. Guarda como recargarla, para
    que la siguiente carga sea un boton y no volver a configurar todo.
    """

    __tablename__ = "dataset"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    conexion_id: Mapped[int] = mapped_column(ForeignKey("conexion.id", ondelete="CASCADE"))
    esquema_origen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tabla_origen: Mapped[str] = mapped_column(String(160))
    columna_incremental: Mapped[str | None] = mapped_column(String(120), nullable=True)
    particionar_por: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Columnas a traer. NULL = todas, y es lo que hay que guardar cuando se
    # quieren todas: una lista congelada dejaria fuera para siempre las columnas
    # que el origen agregue despues, sin avisar.
    columnas: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Ventana movil de recarga: 'mes_actual', 'ultimos_dias:30'… Se resuelve a un
    # rango de fechas EN EL MOMENTO de correr, no al guardarla. Requiere
    # `particionar_por`, porque lo que hace es reemplazar particiones.
    ventana: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Ultimo valor traido: el punto de partida de la proxima carga incremental.
    marca_maxima: Mapped[str | None] = mapped_column(String(120), nullable=True)
    filas: Mapped[int] = mapped_column(Integer, default=0)
    bytes_parquet: Mapped[int] = mapped_column(Integer, default=0)
    ultima_carga: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Programacion: expresion cron de 5 campos. La zona se guarda junto porque
    # "a las 6 de la manana" en un servidor en UTC no es a las 6 en Monterrey, y
    # una carga que corre a la hora equivocada trae el dia incompleto.
    cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zona_horaria: Mapped[str] = mapped_column(String(64), default="America/Mexico_City")
    programacion_activa: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    ejecuciones: Mapped[list[CargaEjecucion]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan",
        order_by="CargaEjecucion.id.desc()",
    )


class EstadoCarga(str, enum.Enum):
    corriendo = "corriendo"
    exito = "exito"
    error = "error"
    #: Lo paro alguien a proposito. Es un estado propio y no `error` por dos
    #: razones: en la pantalla no debe salir en rojo como si algo se hubiera
    #: roto, y sobre todo no debe disparar el aviso de fallo — mandar un correo
    #: de alarma por algo que acaba de hacer quien opera es la forma de que esos
    #: correos se dejen de leer.
    cancelado = "cancelado"


class CargaEjecucion(Base):
    """Historial de cargas: sin esto no se puede depurar una cifra que no cuadra."""

    __tablename__ = "carga_ejecucion"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("dataset.id", ondelete="CASCADE"))
    estado: Mapped[EstadoCarga] = mapped_column(Enum(EstadoCarga), default=EstadoCarga.corriendo)
    # completo | incremental | particion
    modo: Mapped[str] = mapped_column(String(20), default="completo")
    # manual | programado. Sin esto no se distingue una carga que alguien pidio
    # de una que corrio sola de madrugada.
    origen: Mapped[str] = mapped_column(String(20), default="manual")
    detalle: Mapped[dict] = mapped_column(JSON, default=dict)
    filas: Mapped[int] = mapped_column(Integer, default=0)
    bytes_escritos: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    mensaje: Mapped[str | None] = mapped_column(Text, nullable=True)
    iniciado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)

    dataset: Mapped[Dataset] = relationship(back_populates="ejecuciones")


class Transformacion(Base):
    """
    Una transformación guardada. La definición vive en JSON porque los pasos son
    una lista abierta que va a crecer; el motor la valida al compilar.

    `produce` es el nombre del resultado, que es también el nombre del directorio
    Parquet y el de la vista con la que el modelo semántico lo ve.
    """

    __tablename__ = "transformacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    definicion: Mapped[dict] = mapped_column(JSON, default=dict)
    # Linaje: de qué lee. Se guarda al ejecutar, no al guardar la definición, para
    # que refleje lo que de verdad se leyó.
    lee_de: Mapped[dict] = mapped_column(JSON, default=dict)

    # Andamiaje: un resultado que existe para que otra sección lo use, no para que
    # nadie lo grafique. Un mapeo de códigos, una tabla de series, un calendario
    # auxiliar. Sigue materializándose —es lo que permite ejecutar una sección
    # sola y ver sus filas— pero no se ofrece como origen fuera de su proyecto ni
    # aparece en las listas de datos. Con dieciocho secciones por sucursal, sin
    # esta marca el catálogo se vuelve inservible por volumen.
    intermedia: Mapped[bool] = mapped_column(Boolean, default=False)
    filas: Mapped[int] = mapped_column(Integer, default=0)
    bytes_parquet: Mapped[int] = mapped_column(Integer, default=0)
    ultima_ejecucion: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora,
                                                     onupdate=ahora)

    ejecuciones: Mapped[list[TransformacionEjecucion]] = relationship(
        back_populates="transformacion", cascade="all, delete-orphan",
        order_by="TransformacionEjecucion.id.desc()",
    )


class TransformacionEjecucion(Base):
    """Historial. Sin esto no se puede saber cuándo cambió una cifra ni por qué."""

    __tablename__ = "transformacion_ejecucion"

    id: Mapped[int] = mapped_column(primary_key=True)
    transformacion_id: Mapped[int] = mapped_column(
        ForeignKey("transformacion.id", ondelete="CASCADE"))
    estado: Mapped[EstadoCarga] = mapped_column(Enum(EstadoCarga),
                                                default=EstadoCarga.corriendo)
    filas: Mapped[int] = mapped_column(Integer, default=0)
    bytes_escritos: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    mensaje: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    iniciado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"),
                                                     nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)

    transformacion: Mapped[Transformacion] = relationship(back_populates="ejecuciones")


class Flujo(Base):
    """
    Una cadena de pasos con un solo horario: "cada día a las 6, carga estas tablas
    y luego recalcula estas transformaciones".

    Es una lista ordenada y no un grafo de dependencias a propósito. Un grafo es
    más potente y también más difícil de mirar y de razonar; una lista se lee de
    arriba abajo y basta para el 95% de los casos. El orden correcto no se deja al
    azar: se comprueba contra el linaje y se avisa si está mal.
    """

    __tablename__ = "flujo"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"tipo": "carga"|"transformacion"|"flujo", "id": n, "nombre": "..."}]
    pasos: Mapped[list] = mapped_column(JSON, default=list)

    # Un PROYECTO es este mismo flujo restringido a transformaciones: lo que en
    # Qlik es un script con secciones. Sus pasos son sus secciones, en orden.
    #
    # Comparte tabla con los flujos a propósito. Un proyecto es literalmente «un
    # grupo de transformaciones que corren en orden, con un horario», que es la
    # definición de un flujo; darle su propio motor significaría mantener dos
    # copias de los reintentos, la cancelación cooperativa, la reanudación y el
    # historial por paso, y que una de las dos se quedara atrás. Lo que cambia es
    # el vocabulario de la pantalla y qué pasos se admiten, no la ejecución.
    es_proyecto: Mapped[bool] = mapped_column(Boolean, default=False)

    # Al fallar, por defecto se DETIENE. Seguir recalculando sobre datos que no se
    # cargaron produce un número que parece fresco y no lo es.
    al_fallar: Mapped[str] = mapped_column(String(20), default="detener")

    # Cuantas veces se vuelve a intentar UN PASO antes de darlo por fallido, y
    # cuanto se espera entre intentos. Con cuarenta sucursales, que una este
    # apagada a las seis de la manana pasa seguido, y eso no es un fallo del
    # dato: es un fallo de la red que a los dos minutos ya no esta.
    #
    # Por defecto CERO. Reintentar sin que nadie lo pida esconde un origen que
    # va mal: la primera vez que algo falla hay que verlo.
    reintentos: Mapped[int] = mapped_column(Integer, default=0)
    espera_reintento_seg: Mapped[int] = mapped_column(Integer, default=60)

    cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zona_horaria: Mapped[str] = mapped_column(String(64), default="America/Mexico_City")
    programacion_activa: Mapped[bool] = mapped_column(Boolean, default=False)

    ultima_ejecucion: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    ejecuciones: Mapped[list[FlujoEjecucion]] = relationship(
        back_populates="flujo", cascade="all, delete-orphan",
        order_by="FlujoEjecucion.id.desc()",
    )


class FlujoEjecucion(Base):
    """
    Una corrida del flujo entero, con el resultado de cada paso en `detalle`.

    El resumen por flujo y el detalle por paso hacen falta los dos: el primero para
    saber si la noche salió bien, el segundo para saber cuál paso la arruinó.
    """

    __tablename__ = "flujo_ejecucion"

    id: Mapped[int] = mapped_column(primary_key=True)
    flujo_id: Mapped[int] = mapped_column(ForeignKey("flujo.id", ondelete="CASCADE"))
    estado: Mapped[EstadoCarga] = mapped_column(Enum(EstadoCarga),
                                                default=EstadoCarga.corriendo)
    origen: Mapped[str] = mapped_column(String(20), default="manual")
    ms: Mapped[int] = mapped_column(Integer, default=0)
    mensaje: Mapped[str | None] = mapped_column(Text, nullable=True)
    detalle: Mapped[dict] = mapped_column(JSON, default=dict)
    iniciado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"),
                                                     nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)

    # La cadena de continuaciones. Sin esto, mananan hay tres corridas «a medias»
    # del mismo flujo y nadie sabe cual cuenta.
    #
    # `reanuda_a_id` es la corrida que esta continua; `reanudada_por_id` es la que
    # la continuo. Los dos lados y no uno: el primero para leer el historial hacia
    # atras, el segundo para poder rechazar que dos personas continuen la misma.
    reanuda_a_id: Mapped[int | None] = mapped_column(
        ForeignKey("flujo_ejecucion.id", ondelete="SET NULL"), nullable=True)
    reanudada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("flujo_ejecucion.id", ondelete="SET NULL"), nullable=True)

    flujo: Mapped[Flujo] = relationship(back_populates="ejecuciones")


class ReglaAviso(Base):
    """
    A quién avisar cuando algo falla.

    El alcance es opcional a propósito: `objeto_tipo=None` es "todo", y así la
    regla que de verdad hace falta —"avísame de cualquier cosa que falle"— se
    configura una vez y cubre lo que se cree después. Una regla por dataset
    parece más fina y en la práctica deja sin cubrir justo el dataset nuevo.
    """

    __tablename__ = "regla_aviso"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    canal: Mapped[str] = mapped_column(String(20), default="correo")   # correo | webhook
    # Correos separados por coma, o la URL del webhook.
    destino: Mapped[str] = mapped_column(Text)
    eventos: Mapped[list] = mapped_column(JSON, default=list)
    # Alcance: NULL = todo. Con tipo y sin id = todos los de ese tipo.
    objeto_tipo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    objeto_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # No repetir el mismo aviso antes de estos minutos. Una carga rota cada 15
    # minutos manda 96 correos al día y consigue que se archiven todos.
    silencio_minutos: Mapped[int] = mapped_column(Integer, default=60)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    envios: Mapped[list[AvisoEnviado]] = relationship(
        back_populates="regla", cascade="all, delete-orphan",
        order_by="AvisoEnviado.id.desc()",
    )


class AvisoEnviado(Base):
    """
    Cada intento de aviso, incluidos los que se silenciaron y los que fallaron.

    Sin esta tabla, "no me llegó nada" y "no falló nada" se ven igual, y el modo
    de fallo de un sistema de avisos no es avisar mal: es que uno crea que está
    avisando.
    """

    __tablename__ = "aviso_enviado"

    id: Mapped[int] = mapped_column(primary_key=True)
    regla_id: Mapped[int] = mapped_column(ForeignKey("regla_aviso.id", ondelete="CASCADE"))
    evento: Mapped[str] = mapped_column(String(40))
    objeto_tipo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    objeto_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asunto: Mapped[str] = mapped_column(Text)
    # enviado | silenciado | error
    estado: Mapped[str] = mapped_column(String(20), default="enviado")
    mensaje: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)

    regla: Mapped[ReglaAviso] = relationship(back_populates="envios")


class Modelo(Base):
    __tablename__ = "modelo"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    versiones: Mapped[list[VersionModelo]] = relationship(
        back_populates="modelo", cascade="all, delete-orphan",
        order_by="VersionModelo.version",
    )
    borrador: Mapped[BorradorModelo | None] = relationship(
        back_populates="modelo", cascade="all, delete-orphan", uselist=False,
    )


class BorradorModelo(Base):
    """
    El trabajo en curso sobre un modelo, todavia sin publicar.

    Existe porque *guardar* y *publicar* no son lo mismo. Una version es inmutable
    y hay tableros anclados a ella: crear una por cada prueba a medias llena el
    historial de ruido y deja a quien llega despues eligiendo a mano cual de las
    once era la buena. El borrador es el lugar donde se prueba —se guarda las
    veces que haga falta, se descarta entero si no sirvio— y solo al publicar se
    convierte en una version.

    Uno por modelo y no uno por persona. Dos editores sobre el mismo modelo tienen
    que ver el MISMO trabajo en curso: con un borrador por cabeza, el segundo en
    publicar borraria el trabajo del primero sin que ninguno de los dos se
    enterara. `actualizado_por` esta para poder decir de quien es lo que hay antes
    de pisarlo.
    """

    __tablename__ = "borrador_modelo"

    modelo_id: Mapped[int] = mapped_column(
        ForeignKey("modelo.id", ondelete="CASCADE"), primary_key=True)
    yaml: Mapped[str] = mapped_column(Text)
    # De que version se partio. Si mientras tanto alguien publico otra, el
    # borrador esta escrito sobre una base que ya no es la vigente y hay que
    # decirlo antes de publicar, no despues.
    desde_version: Mapped[int] = mapped_column(Integer)
    actualizado_por: Mapped[int | None] = mapped_column(
        ForeignKey("usuario.id"), nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora,
                                                     onupdate=ahora)

    modelo: Mapped[Modelo] = relationship(back_populates="borrador")


class VersionModelo(Base):
    """Instantanea inmutable del YAML del modelo."""

    __tablename__ = "version_modelo"
    __table_args__ = (UniqueConstraint("modelo_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    modelo_id: Mapped[int] = mapped_column(ForeignKey("modelo.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    yaml: Mapped[str] = mapped_column(Text)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    modelo: Mapped[Modelo] = relationship(back_populates="versiones")


class Dashboard(Base):
    __tablename__ = "dashboard"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(160))
    # En que carpeta del estante se guarda. **Solo ordena**: no decide quien ve que
    # —eso es el rol y el publicado— y por eso no va dentro de `definicion`, para
    # que reordenar el estante no le quite la certificacion a nadie.
    carpeta: Mapped[str] = mapped_column(String(120), default="", server_default="")
    # Anclado a una version concreta: cambiar el modelo no lo rompe en silencio.
    version_modelo_id: Mapped[int] = mapped_column(ForeignKey("version_modelo.id"))
    definicion: Mapped[dict] = mapped_column(JSON, default=dict)
    certificado: Mapped[bool] = mapped_column(Boolean, default=False)
    publicado: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora, onupdate=ahora)


class Auditoria(Base):
    """Quien hizo que y cuando. Se escribe siempre, no es opcional."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    email_usuario: Mapped[str | None] = mapped_column(String(255), nullable=True)
    accion: Mapped[str] = mapped_column(String(80), index=True)
    objeto_tipo: Mapped[str | None] = mapped_column(String(60), nullable=True)
    objeto_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    detalle: Mapped[dict] = mapped_column(JSON, default=dict)
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)
