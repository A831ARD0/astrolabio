# Fase 0 — Cimientos

Estado: **completa**. 33 pruebas automatizadas pasando.

Esta fase no agrega funciones visibles. Construye la base sobre la que se apoyan
las demás: persistencia, identidad, y el gancho de seguridad por fila. Se hace
primero porque agregar cualquiera de estas tres cosas después significa reescribir
lo que ya se construyó.

---

## 1. Qué quedó construido

| Componente | Archivo | Qué hace |
|---|---|---|
| Configuración | `app/config.py` | Todo por variables de entorno. Falla al arrancar si en producción siguen las claves por defecto |
| Metadatos | `app/db.py`, `app/modelos_db.py` | SQLite en WAL vía SQLAlchemy. Ver [ADR 0001](adr/0001-sqlite-para-metadatos.md) |
| Seguridad | `app/seguridad.py` | argon2 para contraseñas, JWT para sesión, Fernet para credenciales de conexiones |
| **Capa de políticas** | `app/politicas.py` | Seguridad por fila. El gancho que justifica hacer esta fase primero |
| Motor analítico | `app/analitico.py` | Único camino para ejecutar consultas. No hay vía alterna que se salte las políticas |
| Auditoría | `app/auditoria.py` | Quién hizo qué y cuándo |
| API | `app/rutas/` | Autenticación, usuarios, modelo semántico, consultas, estados asociativos |
| Despliegue | `Dockerfile`, `docker-compose.yml`, `Caddyfile` | Dos servicios: API y Caddy |

---

## 2. La capa de políticas — por qué está en la Fase 0

La interfaz de seguridad por fila llegó en la Fase 6
([07](07-fase-6-gobierno.md)). El **mecanismo** se construyó ahora, y no es por
adelantarse: es porque retrofitear seguridad por fila significa auditar cada
camino de consulta buscando el que se la salte.

Tres decisiones concretas:

### El join se fuerza

El caso que rompe implementaciones ingenuas: si una política protege
`cat_sucursal` y el usuario pide el **total sin desglosar por sucursal**, el CTE
no uniría esa tabla — y el filtro no se aplicaría. El lector regional vería el
total del grupo entero.

El compilador añade la entidad protegida a las entidades a alcanzar, aunque no
aparezca en el desglose pedido. Hay una prueba dedicada a esto
(`test_el_total_tambien_esta_filtrado`).

### Falla cerrado

Si la política necesita `usuario.region_id` y el usuario no lo tiene definido, la
consulta **falla con 403**. No devuelve todo, no devuelve nada: no entrega datos
sin la regla aplicada.

### Los estados asociativos también se filtran

La existencia misma de una sucursal es información. Si un lector regional no
puede ver Puebla, Puebla no debe aparecer ni como valor "excluido" en un panel de
filtros. Probado en `test_estados_asociativos_tambien_filtrados`.

### Frontera contra inyección

Solo se admite la sustitución `{{ usuario.<clave> }}`, validada por expresión
regular, y el valor **siempre** se liga como parámetro. Cualquier otra plantilla
se rechaza. Lo mismo aplica a los filtros del usuario: nada se interpola en el
texto del SQL.

---

## 3. Versionado inmutable del modelo

Guardar un modelo **no sobreescribe**: crea una `VersionModelo` nueva. Los
dashboards se anclan a una versión concreta.

Consecuencia práctica: editar el modelo no puede cambiar en silencio las cifras
de un dashboard ya publicado y firmado. Durante la migración desde Qlik, cuando
se esté conciliando número por número, esto es lo que permite decir "este
dashboard usa la versión 7 del modelo" y que eso signifique algo exacto.

---

## 4. Lo que las pruebas demuestran

33 pruebas, 2.4 segundos. Con un solo mantenedor y sin revisión de código, las
pruebas no son opcionales: son el único mecanismo que avisa cuando un cambio
rompe algo.

**Autenticación y roles** (`test_auth.py`)
- Un correo inexistente y una contraseña mala dan el **mismo** mensaje: no se
  puede averiguar cuáles correos existen
- Lector no lista usuarios; editor no crea usuarios
- Contraseña de menos de 10 caracteres se rechaza

**Seguridad por fila** (`test_seguridad_por_fila.py`) — el corazón de la fase
- Administrador ve 36 sucursales con venta; el lector regional ve exactamente 1
- El **total sin desglose** también queda filtrado
- Falla cerrado si falta el atributo del usuario
- Los estados asociativos van filtrados
- El SQL generado no se expone al rol lector
- Un valor de filtro con `' OR 1=1 --` devuelve 0 filas, no todas

**Modelo semántico vía API** (`test_modelos.py`)
- El diagnóstico reporta 4 problemas, todos reales
- La ambigüedad de ruta devuelve 422 con las dos opciones, no un número adivinado
- El fan trap no infla: 4,826 unidades, no 526,300
- Una versión nueva no sobreescribe la anterior

---

## 5. Cómo correrlo

```bash
cd backend && ./venv/bin/python3 -m pytest tests/ -q
```

```bash
cd backend && ./venv/bin/uvicorn app.main:app --reload
```

En el **primer arranque** se crea el usuario administrador y su contraseña
temporal se escribe en el log. No se vuelve a mostrar.

Con Docker:

```bash
docker compose up --build
```

Antes de producción, generar las dos claves:

```bash
openssl rand -hex 32
```

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 6. Deuda consciente de esta fase

Cosas que decidí dejar para después, con su razón:

| Pendiente | Por qué se dejó |
|---|---|
| ~~Alembic no se usa aún~~ | **Resuelto en la Fase 2.** El disparador se cumplió tal cual: el primer cambio de esquema sobre una base con datos rompió el arranque. Ver [ADR 0002](adr/0002-alembic-para-el-esquema.md) |
| `@app.on_event` está deprecado | Funciona; migrar a `lifespan` es cosmético. Anotado para no olvidarlo |
| No hay límite de intentos de ingreso | Es una app interna sin exposición pública. Si algún día se publica, hace falta |
| No hay rotación de tokens | El token dura 8 horas y no hay refresh. Para uso interno es aceptable |
| El SQL se compila en cada consulta | No hay caché. A este volumen no hace falta (8–34 ms); si crece, es el primer lugar donde mirar |

---

## 7. Siguiente: Fase 1 — Datos de verdad

Lo primero que necesito para arrancarla: **un usuario de solo lectura a MariaDB
`BASE_MYSQL`**. La imagen de Docker ya lleva `unixodbc` instalado para
que el conector universal de la Fase 1 no requiera cambiarla.
