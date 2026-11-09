"""
Caché de resultados de consultas, válida mientras no cambien los datos.

Un tablero de cuarenta widgets hace cuarenta consultas cada vez que alguien lo
abre, y casi siempre son las mismas que hizo la persona anterior: mismos campos,
mismos filtros, los mismos datos. Mientras no se recargue nada, la respuesta es la
misma, así que se guarda.

Tres reglas:

- **La clave es el SQL ya compilado, con sus parámetros.** Ahí van las métricas,
  los filtros y también las políticas de seguridad del usuario —el compilador las
  escribe dentro del WHERE—, así que dos personas con permisos distintos nunca
  comparten una entrada. No hace falta acordarse de meter nada más en la clave:
  si algo cambia la respuesta, cambia el SQL.
- **Se invalida por los datos, no por el reloj.** Cada entrada guarda el sello de
  las tablas que leyó (ver `analitico.invalidar_vistas`, que lo sube quien escribe
  Parquet). Si alguna se recargó desde entonces, la entrada ya no vale. Sin
  caducidad por tiempo: un dato que no cambió no se vuelve viejo.
- **Tiene tope de memoria.** Al llenarse sale lo que hace más tiempo que nadie
  pide. `ASTROLABIO_CACHE_MB=0` la apaga.

Vive en la memoria del proceso: un reinicio la vacía. Para que la primera apertura
después de una recarga no espere, ver `app.precalentar`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from collections import OrderedDict
from typing import Any, Iterable


def clave(*partes: Any) -> str:
    """Huella estable de lo que define una respuesta."""
    texto = json.dumps(partes, default=str, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def sellos_de(tablas: Iterable[str]) -> tuple:
    """
    El estado de los datos de esas tablas: cambia cuando alguna se recarga.

    Lleva también la fecha del archivo del motor analítico. Las tablas que viven
    dentro de él no pasan por `invalidar_vistas` —las escribe otro proceso, con el
    motor abierto aquí en solo lectura—, y sin esto un cambio ahí no se vería.
    """
    from app.analitico import sello

    return ((("__motor__", _fecha_motor()),)
            + tuple((t, sello(t)) for t in sorted(set(tablas))))


def _fecha_motor() -> int:
    from app.config import config

    try:
        return os.stat(config().ruta_duckdb).st_mtime_ns
    except OSError:
        return 0


def _tamano(valor: Any) -> int:
    try:
        return len(json.dumps(valor, default=str))
    except Exception:              # noqa: BLE001 - es una estimación
        return 10_000


class CacheResultados:
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        self._datos: OrderedDict[str, tuple[tuple, Any, int]] = OrderedDict()
        self._bytes = 0
        self._candado = threading.Lock()
        self.aciertos = 0
        self.fallos = 0

    @property
    def activa(self) -> bool:
        return self.max_bytes > 0

    def obtener(self, k: str, sellos: tuple) -> Any | None:
        """Una copia de lo guardado, o None si no hay o ya no vale."""
        if not self.activa:
            return None
        with self._candado:
            entrada = self._datos.get(k)
            if entrada is None or entrada[0] != sellos:
                if entrada is not None:
                    self._quitar(k)
                self.fallos += 1
                return None
            self._datos.move_to_end(k)
            self.aciertos += 1
            valor = entrada[1]
        # Copia: quien la recibe puede tocar las filas (quitar una columna interna,
        # formatear) y no debe estropear lo guardado para el siguiente.
        return copy.deepcopy(valor)

    def vigente(self, k: str, sellos: tuple) -> bool:
        """Si hay una entrada que vale, sin contarla como uso."""
        with self._candado:
            entrada = self._datos.get(k)
            return entrada is not None and entrada[0] == sellos

    def guardar(self, k: str, sellos: tuple, valor: Any) -> None:
        if not self.activa:
            return
        tam = _tamano(valor)
        if tam > self.max_bytes // 4:
            return                 # una sola respuesta no puede echar a todas las demás
        guardado = copy.deepcopy(valor)
        with self._candado:
            if k in self._datos:
                self._quitar(k)
            self._datos[k] = (sellos, guardado, tam)
            self._bytes += tam
            while self._bytes > self.max_bytes and self._datos:
                self._quitar(next(iter(self._datos)))

    def _quitar(self, k: str) -> None:
        _, _, tam = self._datos.pop(k)
        self._bytes -= tam

    def limpiar(self) -> int:
        with self._candado:
            n = len(self._datos)
            self._datos.clear()
            self._bytes = 0
            return n

    def estado(self) -> dict:
        with self._candado:
            total = self.aciertos + self.fallos
            return {
                "activa": self.activa,
                "entradas": len(self._datos),
                "mb": round(self._bytes / 1024 / 1024, 2),
                "max_mb": round(self.max_bytes / 1024 / 1024, 2),
                "aciertos": self.aciertos,
                "fallos": self.fallos,
                "tasa_aciertos": round(self.aciertos / total, 3) if total else None,
            }


_cache: CacheResultados | None = None
_candado_global = threading.Lock()


def cache() -> CacheResultados:
    global _cache
    if _cache is None:
        with _candado_global:
            if _cache is None:
                from app.config import config

                _cache = CacheResultados(max(0, config().cache_mb) * 1024 * 1024)
    return _cache
