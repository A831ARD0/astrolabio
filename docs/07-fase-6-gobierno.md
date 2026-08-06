# Fase 6 — Gobierno

Estado: **completa** en el backend y con interfaz. 216 pruebas pasando, 37 de ellas
nuevas de esta fase.

Es la fase que permite que Astrolabio salga de una sola máquina. El motor de seguridad
por fila existe y está probado desde la Fase 0, pero hasta ahora las políticas solo
se escribían editando el YAML del modelo a mano: en la práctica no se le podía dar
acceso a nadie más.

---

## 1. El problema que ordena la fase: quien escribe la política no la puede probar

Las políticas **no** aplican a un administrador. Es la definición del rol, y es
correcto. Pero tiene una consecuencia incómoda: la persona que escribe una política
es exactamente la que no puede comprobarla mirando sus propias consultas.

Sin herramienta, la única forma de verificar una política es publicarla, pedirle a
alguien que entre y que te cuente lo que ve. Es decir: arriesgar primero y verificar
después.

De ahí sale la pieza central de la fase, el **simulador**.

---

## 2. El simulador: qué vería esta persona

Se elige a alguien —o un rol con atributos escritos a mano, para probar antes de dar
de alta a nadie— y responde tres cosas:

**Los predicados resueltos**, con el valor que tomó cada atributo:

```
rls_region_norte   cat_sucursal    "region_id" = ?    donde ? = 3
```

**Cuántas filas ve de cuántas hay**, con la proporción dibujada:

```
cat_sucursal        1 de 40 filas    ▏
                    muestra: Ekos Río Blanco
```

**La comparación de una consulta, con y sin políticas**, lado a lado:

| Lo que vería (1 fila) | Sin políticas (36 filas) |
|---|---|
| Ekos Río Blanco — 3,481,205 | las 36 sucursales — 439,970 |

La comparación es el producto, no un adorno. «Ve 1 fila» no dice nada; **«ve 1 de
40» dice si la política está filtrando o si no está haciendo nada**. Cuando una
política deja pasar todas las filas, el simulador lo dice con esas palabras: *«Deja
pasar todas las filas: tal como está, esta política no restringe nada.»* Ese es el
fallo silencioso que un simulador tiene que atrapar — una política presente y
decorativa es peor que ninguna, porque parece que hay protección.

### Se simula por el mismo camino que se ejecuta

La consulta simulada pasa por `ejecutar_consulta` con un contexto fabricado. No hay
una versión «de prueba» del compilador ni una ruta que se salte la capa de
políticas. Si la simulación pasara por otro lado, comprobaría otra cosa — que es
justo el defecto que un simulador no puede tener.

El «sin políticas» tampoco es un atajo: es un contexto de administrador. Atraviesa
la capa y resuelve a cero predicados, igual que cualquier consulta de administrador.

### Falla cerrado también al simular

Si a la persona le falta el atributo que la política necesita, el simulador **no
cuenta nada** y muestra el mismo error que esa persona recibiría:

> No vería nada. La política 'rls_region_norte' necesita el atributo ['region_id']
> del usuario 'incompleto@…', que no está definido. No se entregan datos sin la
> regla aplicada.

Y agrega lo que hace falta saber: *«Es lo correcto: sin el atributo, entregar los
datos sin filtrar sería peor. Pero esta persona verá un error, no un tablero vacío:
dale el atributo que le falta.»*

### Un administrador simulando a otro queda en auditoría

Un administrador mirando los datos como otra persona es precisamente el tipo de
acceso por el que existe un registro. Se audita con el `como` completo.

---

## 3. Las políticas se validan sobre el árbol sintáctico

El predicado se escribe a mano y es SQL de verdad. Es el único lugar de Astrolabio
donde un desplegable no alcanza: una política real dice cosas como
`region_id = {{ usuario.region_id }} AND NOT es_confidencial`.

A cambio, se valida en el servidor (`semantic/politica.py`) y se rechaza:

| Predicado | Por qué se rechaza |
|---|---|
| `region_id = (SELECT 1)` | una subconsulta dentro de una política puede leer cualquier tabla |
| `region_id = 1; DROP TABLE …` | dos sentencias |
| `region_id = {{ tabla.otra }}` | solo se admite `{{ usuario.clave }}` |
| `region_id` | no es una condición |
| `estado = {{ usuario.region_id }}` | `estado` no es campo de esa entidad |

Se valida con SQLGlot sobre el árbol y no con una lista de palabras prohibidas, por
lo mismo que en las transformaciones: buscar «SELECT» en el texto se esquiva con
comentarios o con comillas raras.

La comprobación de columnas merece su propia nota: **una columna mal escrita dentro
de una política no rompe esa política, rompe toda consulta de la gente a la que
aplica**. Vale como error al guardar, no como sorpresa a las 8 de la mañana.

### La marca de sustitución vive en un solo sitio

`{{ usuario.x }}` es la frontera contra inyección. La expresión regular que la
reconoce está escrita **una vez**, en `semantic/politica.py`, y `app/politicas.py`
la importa. Dos copias de una frontera de seguridad se separan tarde o temprano, y
la que se olvida es la que se usa.

### Avisos que no bloquean

Hay políticas raras que son legítimas, y convertir toda rareza en error obliga a la
gente a rodear la herramienta. Son avisos:

- La política no usa ningún atributo del usuario, así que filtra igual para todos.
- La política no limita roles, así que aplica a todos menos a administrador.

---

## 4. La cobertura: quién se queda sin ver nada

El cruce que evita el 403 sorpresa. Al abrir las políticas, se cruza cada una contra
los usuarios activos:

> **1 persona se quedaría sin ver nada:** `incompleto@…` — le falta region_id
>
> No es que vean datos de más: reciben un error. Ponles el atributo en Usuarios.

Sin este cruce, el descubrimiento llega por teléfono.

---

## 5. Guardar una política crea una versión del modelo

No es edición en sitio, y es deliberado: **«quién podía ver qué, y desde cuándo» es
la pregunta de después de un incidente**, y solo se puede contestar si cada cambio
dejó su versión. Los tableros anclados a la versión anterior no cambian.

La auditoría del cambio guarda el **antes** y el después. Sin el «antes» no se puede
saber qué se quitó.

Se edita el mapa crudo del YAML, no los objetos del motor, por la misma razón que en
la Fase 2: lo que el motor ignora tiene que sobrevivir al guardado. Hay una prueba
que guarda políticas y después comprueba que las entidades siguen ahí.

---

## 6. Usuarios: el rol dice qué puede hacer, los atributos qué puede ver

Los atributos se editan junto al rol y no en otra pantalla, porque son la mitad de
una política: `region_id = {{ usuario.region_id }}` no hace nada si la persona no
tiene `region_id`.

Decisiones que tomó esta parte:

- **El correo no se cambia.** Es la identidad con la que está escrito todo el
  registro de auditoría; renombrarlo dejaría el historial apuntando a alguien que ya
  no se llama así. Si hace falta otro correo, es otra cuenta.
- **Los atributos se reemplazan, no se mezclan.** Con una mezcla no habría forma de
  quitar uno.
- **Las claves tienen que ser identificadores** (`region_id`, no `Estado ID`): van a
  parar dentro de un predicado.
- **No se borran usuarios, se desactivan.** La auditoría los referencia.
- **Nadie puede dejar el sistema sin administradores activos.** Un administrador que
  se quita el rol a sí mismo por descuido deja Astrolabio sin nadie que pueda
  administrarlo: haría falta editar la base a mano. Es un error de un clic y sin
  vuelta atrás, así que se bloquea con un 409 que explica qué hacer.
- **Cambiar la propia contraseña pide la actual**, aunque el token ya pruebe quién
  eres: una sesión abierta en una máquina ajena no debe poder quedarse con la
  cuenta.
- Un administrador **restablece** sin conocer la anterior. La anterior no se puede
  consultar: solo se guarda su hash (argon2).

---

## 7. Un bug real que encontró esta fase

**Los intentos de ingreso fallidos no se estaban guardando.**

El código los registraba y lanzaba el 401 acto seguido. Pero la dependencia de
sesión hace `rollback` cuando la ruta falla, así que el registro se deshacía con
ella. Es decir: lo primero que se mira cuando se sospecha de algo —los intentos
fallidos— no existía en ninguna parte, y nada lo delataba, porque el código que lo
escribía estaba ahí a la vista.

Lo encontró una prueba que cuenta los ingresos fallidos del resumen. Se arregla con
un `commit()` antes de lanzar la excepción, y el mismo arreglo hacía falta en el
cambio de contraseña fallido.

Segundo hallazgo, más pequeño: reemplazar los atributos de un usuario reventaba
contra `UNIQUE(usuario_id, clave)` cuando se reasignaba el mismo atributo con otro
valor, porque en un solo flush SQLAlchemy inserta antes de borrar. El borrado va
ahora con su propio flush.

---

## 8. La auditoría solo se lee

No hay ruta para editarla ni para borrarla, y no es un olvido: **un registro que se
puede limpiar no sirve para lo único que hace.** Hay una prueba que comprueba que no
existe ni un DELETE ni un PUT.

Se pagina en el servidor. Esta tabla crece con **cada consulta que hace cualquiera**:
en unas semanas son cientos de miles de filas, y traerlas todas para filtrar en el
cliente deja de funcionar sin avisar.

El visor filtra por acción, persona y ventana de tiempo, resume cada evento en una
línea legible y abre el JSON completo al hacer clic. Los ingresos fallidos se cuentan
aparte y se avisan arriba: perdidos entre 50,000 consultas no se ven.

Se colorean las acciones que conviene distinguir de un golpe: los fallos de
credenciales en rojo, la simulación y la exportación en ámbar (son las dos formas en
que un dato sale de la herramienta o se mira desde otros ojos).

---

## 9. Lo que falta

- **Aviso automático cuando algo se sale de lo normal** — muchos ingresos fallidos
  seguidos, una exportación enorme fuera de horario. Hoy hay que mirar. Se junta con
  el pendiente de avisar cuando falla un flujo: los dos necesitan la misma pieza de
  notificación.
- **Políticas sobre métricas, no solo sobre filas** — «este rol ve unidades pero no
  importes». El compilador ya podría, la definición no lo expresa.
- **Grupos** — hoy los atributos se ponen persona por persona. Con 40 sucursales y
  varios regionales, un grupo «Dirección Norte» con sus atributos ahorraría trabajo
  y errores.
- **Autenticación contra el directorio de la empresa** (LDAP/Entra). Mientras no
  esté, las contraseñas viven aquí.
- **Retención de la auditoría.** No se borra nada todavía; cuando la tabla pese, hará
  falta archivar en vez de borrar.
- **Ver la auditoría de un tablero desde el tablero**, no solo desde Gobierno.

---

## 10. Cómo usarlo

1. **Gobierno → Usuarios**: crea a la persona, dale rol `lector` y sus atributos
   (`region_id = 3`).
2. **Gobierno → Seguridad por fila**: elige el modelo, agrega la política sobre la
   entidad que corresponda, escribe la condición y marca los roles. Guarda: es una
   versión nueva del modelo.
3. **Comprobarlo**, en la misma pantalla: elige a esa persona y mira cuántas filas de
   cuántas ve, y la consulta con y sin políticas.
4. **Gobierno → Auditoría** para ver qué pasó después.

El orden importa: el paso 3 no es opcional. Es el único momento en que una política
deja de ser una intención y se convierte en un número verificado.
