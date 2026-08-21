"""
Dashboards.

Dos decisiones de fondo:

1. **Un dashboard esta anclado a una version concreta del modelo.** No al modelo
   "actual". Si alguien cambia la definicion de una metrica, lo publicado sigue
   diciendo lo que decia; el cambio se adopta al mover el ancla a proposito. Sin
   esto, una cifra certificada puede cambiar sola de un dia para otro.

2. **La definicion se guarda como JSON y no se interpreta aqui.** El backend
   valida la estructura minima (que cada widget diga que metricas y dimensiones
   pide) y nada mas. Los datos NO salen de esta capa: cada widget consulta por
   `/api/modelos/{id}/consultar`, que es el unico camino y el que aplica la
   seguridad por fila. Si un dashboard pudiera traer datos por su cuenta, seria un
   agujero en las politicas.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app import informe_pdf
from app.auditoria import registrar
from app.exportar import nombre_archivo
from app.dependencias import SesionDep, UsuarioDep, exigir_rol
from app.modelos_db import Dashboard, Rol, Usuario, VersionModelo, iso

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])

TIPOS_WIDGET = ("kpi", "barras", "barras_horizontales", "lineas", "area",
                "pastel", "tabla", "tabla_dinamica", "filtro", "texto")

# Topes de la rejilla. 24 columnas porque 12 no alcanzan para una fila de mas de
# cuatro cosas, y mas de 24 da cajas de dos centimetros que nadie puede leer.
COLUMNAS_MAX = 24
FILAS_MAX = 60


# --------------------------------------------------------------------------- #
# Esquemas
# --------------------------------------------------------------------------- #

class Posicion(BaseModel):
    """
    Rejilla de `columnas` columnas (las de la hoja); la fila mide lo que mida
    `alto`. Los topes de aqui son el maximo absoluto: que la caja quepa en SU
    hoja lo revisa `_revisar_widgets`, que es quien sabe cuantas columnas tiene.
    """
    x: int = Field(ge=0, le=COLUMNAS_MAX - 1)
    y: int = Field(ge=0)
    ancho: int = Field(ge=1, le=COLUMNAS_MAX)
    alto: int = Field(ge=1, le=FILAS_MAX)


class Lienzo(BaseModel):
    """
    El tamano del espacio de trabajo de una hoja.

    `pantalla` reparte el alto visible entre `filas`: la hoja entera se ve sin
    desplazar, como una hoja de Qlik. `libre` deja la fila con una altura fija y
    la pagina se desplaza; es para un informe largo que se lee de arriba abajo.

    El modo por omision es `pantalla` porque una hoja que no se ve completa
    esconde widgets, y un widget que nadie ve es una cifra que nadie revisa.
    """
    model_config = ConfigDict(extra="allow")

    modo: Literal["pantalla", "libre"] = "pantalla"
    columnas: int = Field(default=12, ge=4, le=COLUMNAS_MAX)
    filas: int = Field(default=12, ge=2, le=FILAS_MAX)


class Hoja(BaseModel):
    """
    Una hoja del tablero. Los widgets NO van dentro: cada widget dice a que hoja
    pertenece. Asi un tablero de antes de las hojas se sigue leyendo tal cual
    (todos sus widgets caen en la primera), y los ids siguen siendo unicos en
    todo el tablero, con lo que mover un widget de hoja es cambiar un campo.
    """
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=40)
    nombre: str = ""
    lienzo: Lienzo = Lienzo()


class Widget(BaseModel):
    # extra="allow": opciones propias de cada tipo de widget (colores, formato,
    # orden) sin tener que tocar el backend cada vez que se agrega una.
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=40)
    tipo: Literal[TIPOS_WIDGET]              # type: ignore[valid-type]
    titulo: str = ""
    posicion: Posicion
    # "" = la primera hoja. Lo que hace que lo de antes siga funcionando.
    hoja: str = ""
    dimensiones: list[str] = []              # "entidad.campo"
    metricas: list[str] = []
    filtros: list[dict[str, Any]] = []       # propios de este widget
    rutas_elegidas: dict[str, str] = {}
    limite: int = Field(default=1000, ge=1, le=50_000)


class DefinicionDashboard(BaseModel):
    model_config = ConfigDict(extra="allow")

    widgets: list[Widget] = []
    # Vacio = una sola hoja implicita con el lienzo por omision.
    hojas: list[Hoja] = []
    # Selecciones con las que abre el tablero: {"entidad.campo": [valores]}
    selecciones: dict[str, list[Any]] = {}


class CrearDashboard(BaseModel):
    nombre: str = Field(min_length=1, max_length=160)
    carpeta: str = Field(default="", max_length=120)
    modelo_id: int
    version: int | None = None               # None = la vigente al crearlo
    definicion: DefinicionDashboard = DefinicionDashboard()


class ActualizarDashboard(BaseModel):
    nombre: str | None = None
    carpeta: str | None = Field(default=None, max_length=120)
    definicion: DefinicionDashboard | None = None


class DashboardSalida(BaseModel):
    id: int
    nombre: str
    carpeta: str
    modelo_id: int
    modelo_nombre: str
    version_modelo: int
    version_vigente_del_modelo: int
    definicion: dict
    publicado: bool
    certificado: bool
    actualizado_en: str


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def _version(sesion: SesionDep, modelo_id: int, version: int | None) -> VersionModelo:
    consulta = select(VersionModelo).where(VersionModelo.modelo_id == modelo_id)
    if version is None:
        consulta = consulta.order_by(VersionModelo.version.desc())
    else:
        consulta = consulta.where(VersionModelo.version == version)
    v = sesion.scalar(consulta.limit(1))
    if v is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"El modelo {modelo_id} no tiene "
            + (f"la version {version}" if version else "ninguna version guardada"))
    return v


def _salida(sesion: SesionDep, d: Dashboard) -> DashboardSalida:
    v = sesion.get(VersionModelo, d.version_modelo_id)
    assert v is not None                    # hay clave externa; no puede faltar
    vigente = sesion.scalar(
        select(func.max(VersionModelo.version))
        .where(VersionModelo.modelo_id == v.modelo_id))
    return DashboardSalida(
        id=d.id, nombre=d.nombre, carpeta=d.carpeta, modelo_id=v.modelo_id,
        modelo_nombre=v.modelo.nombre, version_modelo=v.version,
        version_vigente_del_modelo=int(vigente or v.version),
        definicion=d.definicion, publicado=d.publicado,
        certificado=d.certificado,
        actualizado_en=iso(d.actualizado_en),
    )


def _obtener(sesion: SesionDep, dashboard_id: int) -> Dashboard:
    d = sesion.get(Dashboard, dashboard_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard no encontrado")
    return d


def _revisar_widgets(definicion: DefinicionDashboard) -> None:
    """
    Lo minimo que hace falta para que un tablero se pueda dibujar. No valida
    contra el modelo: eso lo hace la consulta, que es quien sabe.
    """
    ids = [w.id for w in definicion.widgets]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": [f"ids de widget repetidos: "
                                         f"{', '.join(sorted(repetidos))}"]})
    errores = []

    ids_hoja = [h.id for h in definicion.hojas]
    repes_hoja = {i for i in ids_hoja if ids_hoja.count(i) > 1}
    if repes_hoja:
        errores.append(f"ids de hoja repetidos: {', '.join(sorted(repes_hoja))}")
    # Sin hojas declaradas hay una implicita de 12 columnas: la de siempre.
    columnas = {h.id: h.lienzo.columnas for h in definicion.hojas}
    primera = ids_hoja[0] if ids_hoja else ""

    for w in definicion.widgets:
        hoja = w.hoja or primera
        if hoja and hoja not in columnas:
            errores.append(f"El widget '{w.titulo or w.id}' apunta a la hoja "
                           f"'{hoja}', que no existe en este tablero.")
            continue
        cols = columnas.get(hoja, 12)
        if w.posicion.x + w.posicion.ancho > cols:
            errores.append(
                f"El widget '{w.titulo or w.id}' se sale de la hoja: empieza en "
                f"la columna {w.posicion.x} y mide {w.posicion.ancho}, y la hoja "
                f"tiene {cols} columnas.")

    for w in definicion.widgets:
        if w.tipo in ("kpi", "barras", "barras_horizontales", "lineas", "area",
                      "pastel") and not w.metricas:
            errores.append(f"El widget '{w.titulo or w.id}' ({w.tipo}) necesita "
                           f"al menos una metrica.")
        if w.tipo in ("barras", "barras_horizontales", "lineas", "area",
                      "pastel") and not w.dimensiones:
            errores.append(f"El widget '{w.titulo or w.id}' ({w.tipo}) necesita "
                           f"una dimension por la que desglosar.")
        # Un panel de filtros lleva los campos que quepan: colapsados son una barra
        # de desplegables (Año, Mes, Sucursal en fila) y abiertos son listas que se
        # reparten el alto. Lo unico que no tiene sentido es un panel sin campos.
        if w.tipo == "filtro" and not w.dimensiones:
            errores.append(f"El filtro '{w.titulo or w.id}' no apunta a ningun "
                           f"campo.")
        if w.tipo == "tabla" and not (w.dimensiones or w.metricas):
            errores.append(f"La tabla '{w.titulo or w.id}' esta vacia.")

        # Una tabla dinamica cruza dos desgloses: uno en las filas y otro que se
        # abre en columnas. Con uno solo no hay nada que cruzar, y lo que se queria
        # era una tabla normal.
        if w.tipo == "tabla_dinamica":
            if not w.metricas:
                errores.append(f"La tabla dinamica '{w.titulo or w.id}' necesita al "
                               f"menos una metrica.")
            if len(w.dimensiones) < 2:
                errores.append(f"La tabla dinamica '{w.titulo or w.id}' necesita dos "
                               f"desgloses: uno para las filas y otro que se abra en "
                               f"columnas.")
            pivote = getattr(w, "pivote", None)
            if pivote is not None and pivote not in w.dimensiones:
                errores.append(f"La tabla dinamica '{w.titulo or w.id}' abre en "
                               f"columnas '{pivote}', que no es uno de sus desgloses.")
            # Las metricas que van FUERA de las columnas —una foto no se repite
            # debajo de cada mes— no pueden ser todas: sin ninguna dentro no hay
            # matriz que abrir, y guardarlo asi deja un widget que solo sabe
            # explicarse en pantalla.
            fuera = getattr(w, "fuera_del_pivote", None) or []
            if isinstance(fuera, list):
                sobran = [m for m in fuera if m not in w.metricas]
                if sobran:
                    errores.append(
                        f"La tabla dinamica '{w.titulo or w.id}' deja fuera de las "
                        f"columnas a {', '.join(sobran)}, que no son metricas suyas.")
                if w.metricas and not [m for m in w.metricas if m not in fuera]:
                    errores.append(
                        f"La tabla dinamica '{w.titulo or w.id}' deja fuera de las "
                        f"columnas a todas sus metricas, asi que no queda ninguna que "
                        f"abrir. Deja al menos una dentro.")

        # Un orden que apunta a un desglose que el widget no tiene no ordena nada,
        # y una lista mal ordenada no se distingue de una lista sin ordenar. Suele
        # pasar al quitar el campo y dejar su ajuste detras.
        orden_por = getattr(w, "orden_por", None)
        if isinstance(orden_por, dict):
            for campo in orden_por:
                if campo not in w.dimensiones:
                    errores.append(
                        f"El widget '{w.titulo or w.id}' dice ordenar "
                        f"'{campo}', que no es uno de sus desgloses.")

        # Un semaforo que compara contra una columna que no esta en el widget no
        # pinta nada, y no pintar es indistinguible de "va bien".
        semaforos = getattr(w, "semaforos", None)
        if isinstance(semaforos, dict):
            for columna, sem in semaforos.items():
                if not isinstance(sem, dict):
                    continue
                if columna not in w.metricas:
                    errores.append(
                        f"El widget '{w.titulo or w.id}' tiene un semaforo en "
                        f"'{columna}', que no es una de sus metricas.")
                if sem.get("comparar") != "metrica":
                    continue
                contra = sem.get("metrica")
                if contra not in w.metricas:
                    errores.append(
                        f"El semaforo de '{columna}' en '{w.titulo or w.id}' compara "
                        f"contra '{contra}', que no es una metrica de este widget.")
    if errores:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            {"errores": errores})


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

@router.get("", response_model=list[DashboardSalida])
def listar(sesion: SesionDep, usuario: UsuarioDep, solo_publicados: bool = False):
    # Por carpeta y luego por nombre: el estante sale ya ordenado, y quien monta la
    # pantalla no tiene que reordenar cuarenta tableros en el navegador.
    consulta = select(Dashboard).order_by(Dashboard.carpeta, Dashboard.nombre)
    # Un lector solo ve lo publicado: un borrador a medias no es una cifra que
    # nadie deba usar para decidir.
    if solo_publicados or usuario.rol == Rol.lector:
        consulta = consulta.where(Dashboard.publicado.is_(True))
    return [_salida(sesion, d) for d in sesion.scalars(consulta)]


@router.get("/{dashboard_id}", response_model=DashboardSalida)
def obtener(dashboard_id: int, sesion: SesionDep, usuario: UsuarioDep):
    d = _obtener(sesion, dashboard_id)
    if not d.publicado and usuario.rol == Rol.lector:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard no encontrado")
    return _salida(sesion, d)


@router.post("", response_model=DashboardSalida, status_code=201)
def crear(cuerpo: CrearDashboard, sesion: SesionDep,
          actor: Usuario = Depends(exigir_rol(Rol.editor))):
    _revisar_widgets(cuerpo.definicion)
    v = _version(sesion, cuerpo.modelo_id, cuerpo.version)

    d = Dashboard(nombre=cuerpo.nombre, carpeta=cuerpo.carpeta.strip(),
                  version_modelo_id=v.id,
                  definicion=cuerpo.definicion.model_dump(mode="json"),
                  creado_por=actor.id)
    sesion.add(d)
    sesion.flush()
    registrar(sesion, accion="dashboard_creado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dashboard", objeto_id=d.id,
              detalle={"nombre": d.nombre, "modelo": v.modelo.nombre,
                       "version_modelo": v.version})
    return _salida(sesion, d)


@router.put("/{dashboard_id}", response_model=DashboardSalida)
def actualizar(dashboard_id: int, cuerpo: ActualizarDashboard, sesion: SesionDep,
               actor: Usuario = Depends(exigir_rol(Rol.editor))):
    d = _obtener(sesion, dashboard_id)
    if cuerpo.definicion is not None:
        _revisar_widgets(cuerpo.definicion)
        d.definicion = cuerpo.definicion.model_dump(mode="json")
    if cuerpo.nombre is not None:
        d.nombre = cuerpo.nombre
    if cuerpo.carpeta is not None:
        d.carpeta = cuerpo.carpeta.strip()

    # Cambiar la DEFINICION de un tablero certificado le quita el sello: la
    # certificacion dice "estas cifras se revisaron", y lo que se reviso ya no es
    # esto.
    #
    # Cambiarle el nombre o la carpeta, no. Ninguna de las dos toca una cifra, y si
    # lo hicieran habria que descertificar el estante entero cada vez que alguien lo
    # ordena — con lo que el sello dejaria de significar nada porque nadie podria
    # mantenerlo puesto.
    perdio_sello = False
    if d.certificado and cuerpo.definicion is not None:
        d.certificado = False
        perdio_sello = True

    registrar(sesion, accion="dashboard_actualizado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dashboard", objeto_id=d.id,
              detalle={"widgets": len(d.definicion.get("widgets", [])),
                       "carpeta": d.carpeta,
                       "perdio_certificacion": perdio_sello})
    return _salida(sesion, d)


class PeticionInforme(BaseModel):
    """
    Lo que hace falta para dibujar el informe de una hoja.

    `selecciones` son los filtros que tiene puestos quien lo pide, y van en el cuerpo y
    no en la URL: cuarenta sucursales elegidas no caben decentemente en una direccion,
    y una direccion con los filtros dentro acaba en los registros del servidor web.
    """

    hoja: str | None = None
    formato: Literal["pdf", "png"] = "pdf"
    selecciones: dict[str, list[Any]] = Field(default_factory=dict)


@router.post("/{dashboard_id}/informe")
def informe(dashboard_id: int, sesion: SesionDep, usuario: UsuarioDep,
            cuerpo: PeticionInforme | None = None):
    """
    La hoja como archivo, generada en el servidor.

    Existe porque el camino del navegador no llega: `window.print()` obliga a pasar
    por el dialogo de impresion —ninguna pagina web puede elegir el destino, y eso no
    se rodea— y ademas Safari ignora el tamaño de pagina que pide el documento, asi
    que la hoja de una sola pagina salia en tamaño Carta y cortada.

    El archivo se genera con el token de QUIEN LO PIDE, asi que las politicas de
    seguridad por fila se aplican igual que en pantalla.
    """
    c = cuerpo or PeticionInforme()
    hoja, formato = c.hoja, c.formato
    d = _obtener(sesion, dashboard_id)
    if not d.publicado and usuario.rol == Rol.lector:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard no encontrado")

    try:
        datos = informe_pdf.generar(
            dashboard_id, hoja=hoja, correo=usuario.email, rol=usuario.rol.value,
            imagen=(formato == "png"), selecciones=c.selecciones or None,
        )
    except (informe_pdf.SinNavegador, informe_pdf.FaltaDireccion) as e:
        # 501 y no 500: no es un fallo, es una pieza que no esta instalada, y el
        # mensaje dice como instalarla.
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, str(e))
    except informe_pdf.InformeFallido as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e))

    registrar(sesion, accion="informe", usuario_id=usuario.id, email=usuario.email,
              objeto_tipo="dashboard", objeto_id=dashboard_id,
              detalle={"hoja": hoja, "formato": formato, "bytes": len(datos),
                       "filtros": len(c.selecciones)})
    sesion.commit()

    # El mismo saneado que la exportacion: una cabecera HTTP se codifica en latin-1
    # y el guion largo del nombre de un tablero —«Comercial — venta»— no cabe ahi.
    nombre = nombre_archivo(f"{d.nombre}{f' {hoja}' if hoja else ''}", formato)
    return Response(
        content=datos,
        media_type="application/pdf" if formato == "pdf" else "image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


@router.post("/{dashboard_id}/publicar", response_model=DashboardSalida)
def publicar(dashboard_id: int, sesion: SesionDep, publicado: bool = True,
             actor: Usuario = Depends(exigir_rol(Rol.editor))):
    d = _obtener(sesion, dashboard_id)
    d.publicado = publicado
    registrar(sesion, accion="dashboard_publicado" if publicado else "dashboard_retirado",
              usuario_id=actor.id, email=actor.email, objeto_tipo="dashboard",
              objeto_id=d.id, detalle={"nombre": d.nombre})
    return _salida(sesion, d)


@router.post("/{dashboard_id}/certificar", response_model=DashboardSalida)
def certificar(dashboard_id: int, sesion: SesionDep, certificado: bool = True,
               actor: Usuario = Depends(exigir_rol(Rol.administrador))):
    """
    Certificar es decir "estas cifras se revisaron y se puede decidir con ellas".
    Solo un administrador, y se pierde al editar.
    """
    d = _obtener(sesion, dashboard_id)
    if certificado and not d.publicado:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "No se puede certificar un tablero sin publicar")
    d.certificado = certificado
    registrar(sesion, accion="dashboard_certificado" if certificado
              else "dashboard_descertificado",
              usuario_id=actor.id, email=actor.email, objeto_tipo="dashboard",
              objeto_id=d.id, detalle={"nombre": d.nombre})
    return _salida(sesion, d)


@router.post("/{dashboard_id}/mover-a-version", response_model=DashboardSalida)
def mover_a_version(dashboard_id: int, sesion: SesionDep, version: int,
                    actor: Usuario = Depends(exigir_rol(Rol.editor))):
    """
    Adopta otra version del modelo. Es un acto explicito a proposito: al cambiar
    el ancla, las cifras del tablero pueden cambiar.
    """
    d = _obtener(sesion, dashboard_id)
    actual = sesion.get(VersionModelo, d.version_modelo_id)
    assert actual is not None
    nueva = _version(sesion, actual.modelo_id, version)
    d.version_modelo_id = nueva.id
    d.certificado = False               # el sello era de las cifras anteriores
    registrar(sesion, accion="dashboard_movido_de_version", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dashboard", objeto_id=d.id,
              detalle={"de": actual.version, "a": nueva.version})
    return _salida(sesion, d)


@router.delete("/{dashboard_id}", status_code=204)
def borrar(dashboard_id: int, sesion: SesionDep,
           actor: Usuario = Depends(exigir_rol(Rol.editor))):
    d = _obtener(sesion, dashboard_id)
    nombre = d.nombre
    sesion.delete(d)
    registrar(sesion, accion="dashboard_borrado", usuario_id=actor.id,
              email=actor.email, objeto_tipo="dashboard", objeto_id=dashboard_id,
              detalle={"nombre": nombre})
