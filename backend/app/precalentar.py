"""
Precalentar la caché de consultas cuando termina una recarga.

La caché (`app.cache_consultas`) hace instantánea la segunda vez que alguien pide
algo. Pero cada recarga de datos la invalida, y las recargas son de madrugada: la
primera persona de la mañana pagaba la espera completa de cada tablero.

Aquí se repiten, después de cada recarga, **las consultas que la gente de verdad
hace**, no una reconstrucción de los tableros. Así no hay que imitar lo que arma
el navegador (filtros por omisión, tablas dinámicas, selecciones guardadas): se
repite lo mismo que se pidió, con el mismo usuario, y la entrada que queda es
justo la que va a buscar la siguiente petición.

Decisiones:

- **Se registra lo que se usa**, con cuántas veces y cuándo por última vez, en un
  archivo junto a los datos. Sobrevive a los reinicios, que es cuando más falta
  hace. Se repiten primero las más usadas, hasta `precalentar_max`, y se olvidan
  las que nadie ha pedido en `precalentar_dias`.
- **Se espera a que los datos dejen de cambiar.** Durante un flujo, cada paso
  reescribe una tabla; calentar a medias sería trabajo tirado. Se calienta cuando
  pasan `precalentar_espera_seg` sin recargas y no hay trabajos en la cola. Si
  llega una recarga a media tanda, la tanda se corta y se vuelve a esperar.
- **De una en una**, en un hilo aparte: el motor ya usa todos los núcleos en cada
  consulta, y calentar no puede quitarle el servidor a quien está trabajando.
- **Con el usuario que la hizo**, y sus permisos de ahora. Si los permisos
  cambiaron, el SQL sale distinto y simplemente se calienta lo que esa persona va
  a ver hoy.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_candado = threading.Lock()
_registro: dict[str, dict] | None = None
_ultimo_cambio = 0.0          # time.monotonic() de la última recarga
_pendiente = False
_hilo: threading.Thread | None = None
_ultima_tanda: dict = {}


def _archivo() -> Path:
    from app.config import config

    return Path(config().ruta_duckdb).parent / "consultas_frecuentes.json"


def _cargar() -> dict[str, dict]:
    global _registro
    if _registro is None:
        try:
            _registro = json.loads(_archivo().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _registro = {}
    return _registro


def _guardar() -> None:
    try:
        ruta = _archivo()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(_registro, ensure_ascii=False, default=str),
                            encoding="utf-8")
        temporal.replace(ruta)
    except OSError:
        log.warning("No se pudo guardar el registro de consultas frecuentes",
                    exc_info=True)


def registrar_uso(tipo: str, modelo_id: int, version: int | None, cuerpo: dict,
                  usuario_id: int | None) -> None:
    """Anota que se hizo esta consulta. `tipo`: 'consulta' o 'asociativo'."""
    from app.cache_consultas import clave
    from app.config import config

    if not config().precalentar or usuario_id is None:
        return
    k = clave(tipo, modelo_id, version, cuerpo, usuario_id)
    ahora = datetime.now(timezone.utc).isoformat()
    with _candado:
        reg = _cargar()
        e = reg.get(k)
        if e is None:
            reg[k] = e = {"tipo": tipo, "modelo_id": modelo_id, "version": version,
                          "cuerpo": cuerpo, "usuario_id": usuario_id, "veces": 0}
        e["veces"] += 1
        e["ultima"] = ahora
        _podar(reg)
        # Guardar en cada uso sería escribir el archivo cuarenta veces por tablero:
        # se guarda cada tanto y al calentar.
        if e["veces"] == 1 or e["veces"] % 20 == 0:
            _guardar()


def _podar(reg: dict) -> None:
    from app.config import config

    limite = datetime.now(timezone.utc) - timedelta(days=config().precalentar_dias)
    for k in [k for k, e in reg.items()
              if datetime.fromisoformat(e["ultima"]) < limite]:
        del reg[k]
    tope = config().precalentar_max * 2
    if len(reg) > tope:
        for k, _ in sorted(reg.items(), key=lambda x: (x[1]["veces"], x[1]["ultima"])
                           )[:len(reg) - tope]:
            del reg[k]


def pedir() -> None:
    """Hubo una recarga: hay que calentar cuando los datos dejen de cambiar."""
    from app.config import config

    global _ultimo_cambio, _pendiente
    if not config().precalentar:
        return
    with _candado:
        _ultimo_cambio = time.monotonic()
        _pendiente = True
    _arrancar()


def _arrancar() -> None:
    global _hilo
    with _candado:
        if _hilo is not None and _hilo.is_alive():
            return
        _hilo = threading.Thread(target=_vigilar, name="precalentar", daemon=True)
        _hilo.start()


def _hay_trabajos() -> bool:
    from app import trabajos

    return trabajos.hay_algo_corriendo() is not None


def _vigilar() -> None:
    from app.config import config

    global _pendiente
    while True:
        with _candado:
            if not _pendiente:
                return
            quieto = time.monotonic() - _ultimo_cambio
        if quieto < config().precalentar_espera_seg or _hay_trabajos():
            time.sleep(min(30, max(1, config().precalentar_espera_seg / 10)))
            continue
        with _candado:
            _pendiente = False
            inicio_tanda = _ultimo_cambio
        try:
            tanda(cortar_si_cambia=inicio_tanda)
        except Exception:          # noqa: BLE001 - un hilo que muere no avisa
            log.exception("Fallo al precalentar la caché de consultas")


def tanda(cortar_si_cambia: float | None = None, maximo: int | None = None) -> dict:
    """
    Repite las consultas más usadas que no estén ya en la caché.

    Devuelve cuántas se calentaron, cuántas ya estaban, cuántas fallaron y cuánto
    tardó. Se corta si llegan datos nuevos a media tanda.
    """
    from app.config import config

    global _ultima_tanda
    t0 = time.perf_counter()
    with _candado:
        reg = _cargar()
        orden = sorted(reg.items(), key=lambda x: (-x[1]["veces"], x[1]["ultima"]))
        orden = orden[:maximo or config().precalentar_max]
    hechas = ya = fallidas = 0
    cortada = False
    for _, e in orden:
        if cortar_si_cambia is not None and _ultimo_cambio != cortar_si_cambia:
            cortada = True
            break
        try:
            if _repetir(e):
                hechas += 1
            else:
                ya += 1
        except Exception:          # noqa: BLE001 - una consulta rota no para las demás
            fallidas += 1
            log.debug("No se pudo precalentar %s", e, exc_info=True)
    with _candado:
        _guardar()
    _ultima_tanda = {
        "cuando": datetime.now(timezone.utc).isoformat(),
        "calentadas": hechas, "ya_estaban": ya, "fallidas": fallidas,
        "segundos": round(time.perf_counter() - t0, 1), "cortada": cortada,
    }
    log.info("Precalentado: %s", _ultima_tanda)
    return _ultima_tanda


def _repetir(e: dict) -> bool:
    """Hace la consulta del registro. True si hubo que calcularla."""
    from app.analitico import ejecutar_consulta, estados_asociativos
    from app.cache_consultas import cache
    from app.db import CrearSesion
    from app.gobierno import contexto_de
    from app.modelos_db import Usuario, VersionModelo
    from app.rutas.modelos import _cargar_semantico
    from semantic.engine import Consulta
    from sqlalchemy import select

    with CrearSesion() as sesion:
        usuario = sesion.get(Usuario, e["usuario_id"])
        if usuario is None or not getattr(usuario, "activo", True):
            return False
        q = select(VersionModelo).where(VersionModelo.modelo_id == e["modelo_id"])
        q = (q.where(VersionModelo.version == e["version"]) if e.get("version")
             else q.order_by(VersionModelo.version.desc()).limit(1))
        v = sesion.scalar(q)
        if v is None:
            return False
        ctx = contexto_de(usuario)
        yaml_texto = v.yaml
    m = _cargar_semantico(yaml_texto)
    antes = cache().aciertos
    c = e["cuerpo"]
    if e["tipo"] == "consulta":
        ejecutar_consulta(m, Consulta(**c), ctx)
    else:
        estados_asociativos(m, c["entidad"], c["campo"], c.get("selecciones") or {},
                            ctx, c.get("ordenar_por"))
    return cache().aciertos == antes


def estado() -> dict:
    with _candado:
        reg = _cargar()
        return {"registradas": len(reg), "pendiente": _pendiente,
                "ultima_tanda": _ultima_tanda or None}
