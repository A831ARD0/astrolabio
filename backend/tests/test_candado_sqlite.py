"""
Traer datos no puede dejar la aplicacion sin escribir.

SQLite admite un escritor a la vez. Una carga empieza apuntando su ejecucion en
el historial, y con eso abre una transaccion de escritura; si esa transaccion se
queda abierta durante la ingesta —minutos en una tabla grande por el puente de
32 bits— cualquier otra escritura espera el `busy_timeout` y despues falla con
«database is locked». Eso se veia como un «Error 500» al intentar crear un flujo
mientras corria una extraccion.

La prueba no mide tiempos ni provoca el bloqueo a proposito: comprueba lo que lo
evita, que es que el candado ya no este tomado mientras se traen los datos. Se
mira desde dentro de la ingesta, que es el unico momento en que importa.
"""

from __future__ import annotations

from app.conectores import archivos


def test_durante_la_ingesta_otro_puede_escribir(cliente, cab_admin,
                                                conexion_archivos_etl,
                                                monkeypatch):
    from app.db import CrearSesion
    from app.modelos_db import CargaEjecucion, EstadoCarga

    visto: dict = {}
    original = archivos.ConectorArchivos.ingestar

    def espiado(self, p, ruta_destino):
        # Estamos en mitad de la carga. Otra sesion —como la del navegador
        # creando un flujo— tiene que poder leer Y escribir.
        with CrearSesion() as otra:
            fila = otra.query(CargaEjecucion).order_by(
                CargaEjecucion.id.desc()).first()
            visto["estado"] = fila.estado if fila else None
            fila.detalle = {**(fila.detalle or {}), "tocado_desde_fuera": True}
            otra.commit()
            visto["escribio"] = True
        return original(self, p, ruta_destino)

    monkeypatch.setattr(archivos.ConectorArchivos, "ingestar", espiado)

    r = cliente.post(f"/api/conexiones/datasets/{conexion_archivos_etl}/cargar",
                     headers=cab_admin)
    assert r.status_code == 200, r.text

    # Que la ejecucion ya estuviera confirmada como 'corriendo' es justo lo que
    # suelta el candado: antes ni siquiera existia para nadie mas.
    assert visto.get("estado") == EstadoCarga.corriendo
    assert visto.get("escribio") is True


def test_se_puede_crear_un_flujo_mientras_carga(cliente, cab_admin,
                                                conexion_archivos_etl,
                                                monkeypatch):
    """El caso tal cual lo conto quien lo sufrio: crear un flujo sin poder."""
    original = archivos.ConectorArchivos.ingestar
    respuesta: dict = {}

    def espiado(self, p, ruta_destino):
        r = cliente.post("/api/flujos", headers=cab_admin, json={
            "nombre": "creado_mientras_cargaba",
            "pasos": [{"tipo": "carga", "id": conexion_archivos_etl}]})
        respuesta["codigo"] = r.status_code
        respuesta["texto"] = r.text
        return original(self, p, ruta_destino)

    monkeypatch.setattr(archivos.ConectorArchivos, "ingestar", espiado)
    cliente.post(f"/api/conexiones/datasets/{conexion_archivos_etl}/cargar",
                 headers=cab_admin)

    assert respuesta.get("codigo") in (201, 409), respuesta.get("texto")
