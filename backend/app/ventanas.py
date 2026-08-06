"""
Ventanas moviles de recarga: "trae siempre el mes actual y el anterior".

El problema que resuelven: una carga incremental por clave (`id > 60026`) trae lo
NUEVO, pero no vuelve a mirar lo que cambio. En un sistema de ventas, una venta de
hace tres semanas se corrige —cambia el importe, se cancela, se reasigna la
sucursal— y su `id` no cambia, asi que la carga incremental no la vuelve a leer y
el Parquet se queda con la version vieja. La cifra sigue pareciendo un numero.

Una ventana movil dice "reemplaza siempre estas particiones", y el rango se
resuelve **en el momento de correr**, no al guardarlo. Guardar el rango calculado
seria un error silencioso: el dataset que se configuro en enero seguiria recargando
enero para siempre.

Dos decisiones:

- **Se calcula con la zona horaria del dataset.** "Ayer" a las 00:30 en un servidor
  en UTC es hoy en Monterrey. Una carga que corre de madrugada y usa la fecha del
  servidor recarga el dia equivocado, y el que falta no lo recarga nadie.

- **Siempre en meses completos, aunque la ventana sea de dias.** El Parquet esta
  partido por anio/mes, y la unidad minima que se puede reemplazar es un mes. Pedir
  "ayer" reemplaza el mes de ayer entero. Se dice en la descripcion en vez de dar a
  entender una precision que no hay.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

#: Ventanas fijas: clave -> (etiqueta, cuantos dias hacia atras contando hoy).
#: La cuenta se hace en dias y luego se redondea a meses completos.
FIJAS: dict[str, tuple[str, int]] = {
    "dia_anterior": ("Solo el día anterior", 1),
    "ultimos_7_dias": ("Los últimos 7 días", 7),
    "ultimos_30_dias": ("Los últimos 30 días", 30),
}

#: Ventanas por calendario, que no se pueden expresar en dias fijos.
CALENDARIO: dict[str, str] = {
    "mes_actual": "El mes en curso",
    "mes_actual_y_anterior": "El mes en curso y el anterior",
    "anio_actual": "Lo que va del año",
    "ultimos_2_anios": "Los últimos 2 años (este y el anterior)",
}

#: Parametrizada: 'ultimos_dias:45'.
_PARAM = re.compile(r"^ultimos_dias:(\d{1,4})$")


class VentanaInvalida(ValueError):
    """La clave de ventana no existe o esta mal escrita."""


def claves() -> list[dict]:
    """Catalogo para la interfaz, en el orden en que tiene sentido leerlo."""
    salida = [{"clave": k, "etiqueta": e} for k, (e, _) in FIJAS.items()]
    salida += [{"clave": k, "etiqueta": e} for k, e in CALENDARIO.items()]
    salida.append({"clave": "ultimos_dias:N",
                   "etiqueta": "Los últimos N días (se escribe el número)"})
    return salida


def _hoy(zona: str) -> date:
    try:
        return datetime.now(ZoneInfo(zona)).date()
    except Exception:
        # Una zona mal escrita no debe impedir una carga: se avisa al guardar.
        return datetime.now(ZoneInfo("UTC")).date()


def _primero_del_mes(d: date, meses_atras: int = 0) -> date:
    anio, mes = d.year, d.month - meses_atras
    while mes <= 0:
        anio, mes = anio - 1, mes + 12
    return date(anio, mes, 1)


def resolver(clave: str, zona: str = "America/Mexico_City",
             hoy: date | None = None) -> tuple[str, str]:
    """
    Rango (desde, hasta) en AAAA-MM-DD, ambos inclusive, para recargar hoy.

    `hoy` se puede fijar para probar: una funcion que lee el reloj por dentro no
    se puede verificar, y aqui equivocarse de un dia significa un mes de datos que
    no se recarga.
    """
    dia = hoy or _hoy(zona)

    if clave in FIJAS:
        dias = FIJAS[clave][1]
        return (dia - timedelta(days=dias)).isoformat(), dia.isoformat()

    if m := _PARAM.match(clave):
        dias = int(m.group(1))
        if dias < 1:
            raise VentanaInvalida("La ventana en dias tiene que ser de al menos 1.")
        return (dia - timedelta(days=dias)).isoformat(), dia.isoformat()

    if clave == "mes_actual":
        return _primero_del_mes(dia).isoformat(), dia.isoformat()
    if clave == "mes_actual_y_anterior":
        return _primero_del_mes(dia, 1).isoformat(), dia.isoformat()
    if clave == "anio_actual":
        return date(dia.year, 1, 1).isoformat(), dia.isoformat()
    if clave == "ultimos_2_anios":
        return date(dia.year - 1, 1, 1).isoformat(), dia.isoformat()

    raise VentanaInvalida(
        f"Ventana desconocida: '{clave}'. Validas: "
        + ", ".join([*FIJAS, *CALENDARIO, "ultimos_dias:N"])
    )


def describir(clave: str, zona: str = "America/Mexico_City",
              hoy: date | None = None) -> str:
    """
    Que va a recargar, en palabras y con las fechas de hoy.

    Se muestra al configurarla: "los ultimos 30 dias" suena inofensivo hasta que se
    ve que son cuatro particiones y que la de hace un mes se reescribe entera.
    """
    desde, hasta = resolver(clave, zona, hoy)
    etiqueta = (FIJAS.get(clave, (None,))[0] or CALENDARIO.get(clave))
    if etiqueta is None and (m := _PARAM.match(clave)):
        etiqueta = f"Los últimos {m.group(1)} días"
    return f"{etiqueta or clave}: del {desde} al {hasta}"
