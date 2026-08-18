# Diseño técnico — Modelo semántico

Estado: **validado con prototipo funcional** contra 11.6M filas de datos sintéticos
con la forma real de un grupo automotriz. Ver `backend/semantic/engine.py` y
`backend/datos/`.

El modelo semántico es la pieza central de Astrolabio: define una sola vez qué
tablas existen, cómo se relacionan y cómo se calculan las métricas. El ETL, los
dashboards y el módulo Explorar **leen todos de aquí**. Es la capa más difícil de
cambiar después, y por eso se diseña y se prueba primero.

---

## 1. Principios

1. **Nunca adivinar.** Si una petición admite más de una interpretación válida, el
   motor falla y pide decidir. Un número plausible pero equivocado es peor que un
   error: el error se ve, el número malo se firma. Es la regla que protege las
   cifras financieras durante la migración desde Qlik.

2. **El modelo es texto.** Se guarda en Postgres pero su forma canónica es YAML:
   diffable, revisable en git, exportable. La UI lo genera; el usuario no lo
   escribe. Sin encierro en una base de datos propietaria.

3. **Salida de escape en cada nivel.** Toda entidad puede ser una tabla física o
   SQL arbitrario. Toda métrica puede ser una expresión SQL libre. Toda política
   puede ser un predicado SQL. Nada del origen queda inalcanzable.

4. **Independiente del motor.** Las expresiones se manipulan como árbol
   sintáctico con SQLGlot, no como cadenas. Cambiar DuckDB por ClickHouse es
   cambiar un dialecto, no reescribir el modelo.

5. **Multi-sucursal de origen.** La realidad de un origen real son ~40 bases, una por
   sucursal, con esquemas que varían entre ellas. El modelo asume eso desde el
   inicio en vez de tratarlo como caso excepcional.

---

## 2. Entidades del modelo

| Objeto | Qué es |
|---|---|
| `Conexion` | Origen físico (ODBC, MariaDB, archivo). Credenciales cifradas |
| `TablaFisica` | Tabla o consulta en un origen. Esquema, particionado, última carga |
| `Entidad` | Tabla lógica. Apunta a una `TablaFisica` **o a SQL arbitrario**. Tipo: `hecho` o `dimension` |
| `Campo` | Columna. Rol: `clave`, `clave_externa`, `dimension`, `medida_base`. Marca `pii` |
| `Relacion` | Arista entre entidades: cardinalidad, dirección de filtro, activa/inactiva |
| `Metrica` | Expresión agregada reutilizable, anclada a una entidad. Se define una vez |
| `Jerarquia` | Lista ordenada de campos para drill-down |
| `Politica` | Regla de seguridad por fila: entidad + predicado + roles |
| `Perspectiva` | Subconjunto del modelo visible para un grupo (no mostrar 70 hechos a todos) |
| `VersionModelo` | Instantánea inmutable. Los dashboards se anclan a una versión |

El `tipo` de entidad (`hecho` vs `dimension`) no es decorativo: **determina las
reglas de recorrido del grafo**, como se ve abajo.

---

## 3. Resolución de rutas — las dos reglas

El grafo del modelo se recorre con reglas distintas según para qué. Esto no es un
detalle de implementación; es la decisión central del diseño, y ambas reglas
salieron de probar contra datos reales.

### Regla A — Para agregar: los hechos son terminales, no puentes

Que `cat_sucursal` y `dim_calendario` se toquen "a través de" `fact_venta` no es
una ruta: es la definición de un esquema en estrella. Permitir esos saltos
generaba **25 alarmas de ambigüedad, casi todas falsas**. Con la regla aplicada
quedan **4 problemas, todos reales**.

### Regla B — Para agregar: cada salto va de "muchos" a "uno"

Ir de `cat_marca` a `dim_vehiculo` (uno → muchos) expande filas en vez de
agruparlas. La ruta existe en el grafo pero el número que produce no significa
nada. Sin esta regla, "objetivo de unidades por modelo de vehículo" compilaba y
devolvía basura; con ella, avisa que la métrica no se puede desglosar por esa
dimensión.

### Y la contraparte: para estados asociativos, ambas reglas se invierten

Un hecho **sí** es el puente — así es como una selección de `Modelo` alcanza a
`Estado`. Y la ambigüedad de rutas **no es un error, es una unión**: un valor es
alcanzable si lo es por cualquier camino.

| | Agregación | Estados asociativos |
|---|---|---|
| Atravesar un hecho | prohibido | **es el mecanismo** |
| Dirección del salto | solo muchos → uno | cualquiera |
| Varias rutas | **error**, hay que elegir | unión de resultados |

### Diagnóstico del modelo

Se corre al guardar el modelo, antes de construir cualquier dashboard. Detecta:

- **Tabla huérfana** — sin ninguna relación, queda aislada del análisis
- **Ruta ambigua hecho → dimensión** — la única ambigüedad que puede afectar una
  consulta real, porque toda métrica nace en un hecho
- **Relación muchos-a-muchos** — advertencia de posible duplicación al agregar

Lo que en Qlik se descubre como *clave sintética* o como un número raro en un
gráfico, aquí se reporta con nombre, ruta y explicación antes de que llegue a un
dashboard.

---

## 4. Compilación a prueba de fan trap

El problema: `fact_presupuesto` vive a grano *sucursal × mes*; `fact_venta` a
grano *línea de factura*. Un motor que une ambas tablas y luego suma, infla el
objetivo por el número de facturas del mes.

**Medido en el prototipo:** objetivo de Aurex Valle Alto = 4,826 unidades. El
enfoque ingenuo devuelve **526,300 — inflado 109 veces.**

La solución: **una métrica, un CTE, su propio grano.** Cada métrica se agrega
contra las dimensiones pedidas *antes* de tocar cualquier otra tabla de hechos;
después se unen por las llaves de dimensión sobre una espina dorsal.

```sql
WITH m0 AS (                                    -- venta, a grano factura
  SELECT s.sucursal_nombre, SUM(v.unidades) AS unidades_vendidas
  FROM fact_venta v JOIN cat_sucursal s USING (sucursal_id)
  GROUP BY 1
),
m1 AS (                                         -- objetivo, a grano sucursal×mes
  SELECT s.sucursal_nombre, SUM(p.objetivo_unidades) AS objetivo_unidades
  FROM fact_presupuesto p JOIN cat_sucursal s USING (sucursal_id)
  GROUP BY 1
),
espina AS (                                     -- todas las combinaciones
  SELECT sucursal_nombre FROM m0
  UNION
  SELECT sucursal_nombre FROM m1
)
SELECT e.sucursal_nombre, m0.unidades_vendidas, m1.objetivo_unidades
FROM espina e
LEFT JOIN m0 ON e.sucursal_nombre IS NOT DISTINCT FROM m0.sucursal_nombre
LEFT JOIN m1 ON e.sucursal_nombre IS NOT DISTINCT FROM m1.sucursal_nombre
```

La espina dorsal importa: sin ella se pierde un mes con objetivo pero sin venta,
o al contrario. `IS NOT DISTINCT FROM` en vez de `=` para que los nulos casen.

Resultado medido: coincide con la verdad de campo en las 40 sucursales.

---

## 5. Estados asociativos

Cuatro estados, como Qlik:

| Estado | Significado | Color |
|---|---|---|
`seleccionado` | Elegido explícitamente | verde |
`posible` | Sobrevive a las selecciones de **otros** campos | blanco |
`alternativo` | Sería posible, pero hay una selección en su propio campo que no lo incluye | gris claro |
`excluido` | No sobrevive a las selecciones de otros campos | gris |

La distinción `alternativo` vs `excluido` es la que hace que seleccionar la región
"Norte" no borre visualmente las otras tres — siguen disponibles para ampliar la
selección. Es un detalle que separa una implementación real de una imitación.

Cálculo: para el campo objetivo, se propagan las selecciones de los demás campos
por el grafo (atravesando hechos, uniendo rutas) y se clasifican los valores
distintos.

**Límite honesto:** Qlik mantiene un índice asociativo en memoria y pinta el
estado de *todos* los campos del modelo en cada clic. Sobre SQL eso no se
sostiene a escala. La estrategia es calcular solo los campos visibles en paneles
de filtro, con caché por firma de selección. Medido: 6 ms para un campo sobre
11.6M filas — suficiente para paneles, no para el modelo entero.

---

## 6. Seguridad por fila

Las políticas viven en el modelo, no en los dashboards. El compilador inyecta el
predicado en **cada CTE de métrica** que toque la entidad protegida, con los
valores del usuario ligados como parámetros.

```yaml
politicas:
  - nombre: rls_region
    entidad: cat_sucursal
    predicado: "region_id = {{ usuario.region_id }}"
    aplica_a_roles: [lector_regional]
```

Consecuencia de diseño: **el gancho de políticas se implementa en la Fase 0**,
aunque la UI llegue en la Fase 6. Toda consulta pasa por la capa de políticas
desde el primer día, aunque al principio la política sea "permitir todo".
Agregar seguridad por fila después es reescribir el compilador.

---

## 7. Versionado

Cada guardado produce una `VersionModelo` inmutable. Los dashboards se anclan a
una versión; cambiar el modelo no rompe en silencio lo que ya está publicado. Al
publicar una versión nueva, el sistema reporta qué dashboards se verían afectados
y por qué, antes de aplicar.

---

## 8. Qué queda validado y qué queda abierto

**Validado con prototipo y datos de forma real (11.6M filas):**

| | |
|---|---|
| Detección de tabla huérfana | ✓ |
| Detección de ruta ambigua, sin falsas alarmas | ✓ 4 de 4 reales |
| Negativa a elegir ruta en silencio | ✓ |
| Aviso de métrica no desglosable | ✓ |
| Fan trap evitado, cuadra en 40/40 sucursales | ✓ |
| Cancelaciones netean correctamente | ✓ |
| 4 estados asociativos, incluido `alternativo` | ✓ |
| Unión sobre rutas para estados asociativos | ✓ |
| Desempeño: consultas 8–34 ms, asociativo 6 ms | ✓ |

**Abierto, a resolver antes de conectar orígenes reales:**

- **Unión de las ~40 bases por sucursal.** El prototipo asume una tabla ya
  unificada. Falta decidir entre unificar en la ingesta (más simple, recomendado)
  o una entidad por sucursal con unión lógica (más flexible, más complejo).
- **Esquema variable entre sucursales.** El Qlik actual lo resuelve con
  introspección en tiempo de ejecución (`FieldNumber(...)`). Necesita un
  equivalente: probablemente esquema declarado con campos opcionales.
- **Métricas no aditivas** (razones, promedios ponderados, distintos). El
  esquema de "un CTE por métrica" funciona para sumas; las razones necesitan
  calcularse *después* de la unión, no dentro del CTE.
- **Análisis de conjuntos temporal** (mismo mes año anterior, acumulado del año).
  Es el equivalente del *set analysis* de Qlik y merece su propio diseño.
- **Caché.** Qué se cachea, con qué clave, y cómo se invalida al recargar datos.
