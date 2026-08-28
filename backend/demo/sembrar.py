"""
Deja Astrolabio listo para mirar: usuario, modelo semántico y un tablero con datos.

Sirve para dos cosas. Para quien acaba de clonar el repositorio, es la diferencia
entre una pantalla vacía —donde no se entiende qué hace el producto— y algo que se
puede tocar en el primer minuto. Y para el proyecto, es de donde salen las capturas
de la documentación, que así **no** llevan datos de nadie.

    python demo/generar_datos.py      # primero los datos
    python demo/sembrar.py            # y esto encima

Es idempotente: si ya está sembrado, no duplica nada.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from sqlalchemy import func, select                                # noqa: E402

from app.db import CrearSesion, motor                              # noqa: E402
from app.esquema import actualizar as actualizar_esquema           # noqa: E402
from app.modelos_db import (                                       # noqa: E402
    AtributoUsuario, Base, Dashboard, Flujo, Modelo, ReglaAviso, Rol,
    Transformacion, Usuario, VersionModelo,
)
from app.seguridad import hashear                                  # noqa: E402

YAML_MODELO = RAIZ / "demo" / "modelo_demo.yaml"

CONTRASENA = "astrolabio-demo-2026"

#: (correo, nombre, rol, atributos)
#:
#: Los tres roles con alguien dentro, porque la seguridad por fila no se entiende
#: leyendo una politica: se entiende entrando como el lector regional y viendo que
#: la misma pantalla muestra menos filas.
USUARIOS = [
    ("admin@example.com", "Administración", Rol.administrador, {}),
    ("editor@example.com", "Área de datos", Rol.editor, {}),
    ("region@example.com", "Dirección Región Sur", Rol.lector, {"region_id": "3"}),
]

TABLERO = {
    "widgets": [
        {"id": "w1", "tipo": "kpi", "titulo": "Venta",
         "posicion": {"x": 0, "y": 0, "ancho": 3, "alto": 4},
         "metricas": ["monto_venta"]},
        {"id": "w2", "tipo": "kpi", "titulo": "Unidades",
         "posicion": {"x": 3, "y": 0, "ancho": 3, "alto": 4},
         "metricas": ["unidades_vendidas"]},
        {"id": "w3", "tipo": "kpi", "titulo": "Utilidad",
         "posicion": {"x": 6, "y": 0, "ancho": 3, "alto": 4},
         "metricas": ["monto_utilidad"]},
        {"id": "w4", "tipo": "barras", "titulo": "Venta por sucursal",
         "posicion": {"x": 0, "y": 4, "ancho": 9, "alto": 9},
         "dimensiones": ["cat_sucursal.sucursal_nombre"],
         "metricas": ["monto_venta"], "limite": 12},
        {"id": "w5", "tipo": "lineas", "titulo": "Venta por año",
         "posicion": {"x": 9, "y": 0, "ancho": 3, "alto": 13},
         "dimensiones": ["dim_calendario.anio"],
         "metricas": ["monto_venta"]},
        {"id": "w6", "tipo": "tabla", "titulo": "Detalle por marca",
         "posicion": {"x": 0, "y": 13, "ancho": 12, "alto": 8},
         "dimensiones": ["cat_marca.marca_nombre"],
         "metricas": ["monto_venta", "unidades_vendidas", "monto_utilidad"]},
    ],
    "selecciones": {},
    # Hay dos caminos de `fact_venta` a `cat_marca` —por la agencia y por el
    # vehículo— y dan cifras distintas, así que el motor se niega a elegir por su
    # cuenta. Aquí se deja elegido "la marca de la agencia", que es lo que
    # significa "venta por marca" para un grupo de concesionarios. Queda guardado
    # en el tablero para que la cifra sea reproducible, no dependiente de quién
    # lo abre.
    "rutas_elegidas": {
        "fact_venta->cat_marca": "fact_venta → cat_sucursal → cat_marca",
    },
}


#: Una transformación de ejemplo: la venta neta por sucursal, sin cancelaciones.
#:
#: Se siembra porque una pantalla de ETL vacía no enseña nada, y porque el conteo
#: de filas por paso —que es lo que más se usa de esa pantalla— solo se ve cuando
#: hay pasos de verdad: 500,000 filas entran, el filtro quita las canceladas, y el
#: agrupado deja 36 sucursales.
TRANSFORMACION = {
    "nombre": "venta_neta_por_sucursal",
    "origenes": [
        {"nombre": "ventas", "tipo": "tabla", "referencia": "fact_venta"},
        {"nombre": "sucursales", "tipo": "tabla", "referencia": "cat_sucursal"},
    ],
    "pasos": [
        # `en` y `traer`, que son los nombres que valida `PasoUnir`. Con
        # `parejas`/`trae` la definicion se guardaba igual —nadie la valida al
        # sembrar— y reventaba al abrirla: la pantalla de Transformar de la
        # demostracion contestaba 422 en vez de ensenar los pasos.
        {"tipo": "unir", "con": "sucursales", "como": "izquierda",
         "en": [["sucursal_id", "sucursal_id"]],
         "traer": ["sucursal_nombre"]},
        {"tipo": "filtrar", "condiciones": [
            {"campo": "es_cancelacion", "op": "=", "valor": False}]},
        {"tipo": "derivar", "nombre": "neto",
         "expresion": "monto_base - monto_impuesto"},
        {"tipo": "agrupar", "por": ["sucursal_nombre"], "agregados": [
            {"nombre": "venta_neta", "funcion": "suma", "campo": "neto"},
            {"nombre": "unidades", "funcion": "suma", "campo": "unidades"},
            {"nombre": "operaciones", "funcion": "cuenta"}]},
        {"tipo": "ordenar", "por": ["venta_neta"], "descendente": True},
    ],
}


def sembrar() -> None:
    actualizar_esquema()
    Base.metadata.create_all(motor)

    with CrearSesion() as s:
        for correo, nombre, rol, atributos in USUARIOS:
            if s.scalar(select(func.count()).select_from(Usuario)
                        .where(Usuario.email == correo)):
                continue
            u = Usuario(email=correo, nombre=nombre,
                        hash_contrasena=hashear(CONTRASENA), rol=rol)
            u.atributos = [AtributoUsuario(clave=k, valor=v)
                           for k, v in atributos.items()]
            s.add(u)
            print(f"  usuario  {correo}  ({rol.value})")

        modelo = s.scalar(select(Modelo).where(Modelo.nombre == "demo_comercial"))
        if modelo is None:
            modelo = Modelo(nombre="demo_comercial",
                            descripcion="Ventas, servicio y refacciones de un "
                                        "grupo automotriz ficticio")
            s.add(modelo)
            s.flush()
            s.add(VersionModelo(modelo_id=modelo.id, version=1,
                                yaml=YAML_MODELO.read_text(encoding="utf-8"),
                                notas="Sembrado por demo/sembrar.py"))
            s.flush()
            print("  modelo   demo_comercial v1")

        version = s.scalar(select(VersionModelo)
                           .where(VersionModelo.modelo_id == modelo.id)
                           .order_by(VersionModelo.version.desc()))

        if not s.scalar(select(func.count()).select_from(Dashboard)
                        .where(Dashboard.nombre == "Ventas del grupo")):
            s.add(Dashboard(nombre="Ventas del grupo",
                            version_modelo_id=version.id, definicion=TABLERO,
                            publicado=True, certificado=True))
            print("  tablero  Ventas del grupo")

        trans = s.scalar(select(Transformacion)
                         .where(Transformacion.nombre == TRANSFORMACION["nombre"]))
        if trans is None:
            trans = Transformacion(nombre=TRANSFORMACION["nombre"],
                                   descripcion="Venta sin cancelaciones, por "
                                               "sucursal",
                                   definicion=TRANSFORMACION)
            s.add(trans)
            s.flush()
            print(f"  ETL      {trans.nombre}")

        if not s.scalar(select(func.count()).select_from(Flujo)):
            # Un flujo de un paso: enseña la pantalla y el historial sin inventar
            # dependencias que en la demo no existen.
            s.add(Flujo(nombre="cada_manana",
                        descripcion="Recalcula la venta por sucursal",
                        pasos=[{"tipo": "transformacion", "id": trans.id,
                                "nombre": trans.nombre}],
                        al_fallar="detener", cron="0 6 * * *",
                        programacion_activa=False))
            print("  flujo    cada_manana (sin programar)")

        if not s.scalar(select(func.count()).select_from(ReglaAviso)):
            # Apagada a proposito: es un ejemplo para ver la pantalla, no un
            # destino real. Encenderla mandaria avisos a una URL que no existe.
            s.add(ReglaAviso(
                nombre="avisar_al_area_de_datos", canal="correo",
                destino="datos@example.com",
                eventos=["carga_fallida", "carga_recuperada",
                         "flujo_fallido", "flujo_recuperado"],
                silencio_minutos=60, activa=False))
            print("  aviso    avisar_al_area_de_datos (en pausa)")

        s.commit()

    print(f"\nListo. Entra con cualquiera de los tres correos y la contraseña:"
          f"\n    {CONTRASENA}\n"
          f"\nPruébalo entrando como region@example.com: es la misma pantalla,"
          f"\ncon las filas que esa persona tiene permitido ver.")


if __name__ == "__main__":
    sembrar()
