# Contribuir a Astrolabio

Gracias por mirar el proyecto. Antes de escribir código, dos cosas que ahorran
tiempo: cómo se trabaja aquí, y el acuerdo de licencia.

## Cómo se trabaja aquí

Este proyecto tiene una idea fija: **las cifras tienen que poder comprobarse**. Casi
todas las decisiones raras del código vienen de ahí, y están explicadas en comentarios
donde ocurren. Si algo parece innecesariamente cuidadoso, lo más probable es que haya
una nota diciendo qué se rompió la primera vez.

Reglas concretas:

1. **En español.** Nombres de funciones, variables, mensajes y documentación. El
   código lo mantiene gente que habla español y la mezcla de idiomas cansa.
2. **Un cambio, una prueba.** Si arreglas un fallo, la prueba tiene que fallar sin
   el arreglo. Si no puedes escribirla, dilo en el PR y explica por qué.
3. **Comentarios que expliquen el porqué**, no el qué. `# suma 1` no aporta;
   `# +1 porque el rango es inclusivo y sin esto se pierde el último día` sí.
4. **Nada de dependencias nuevas sin motivo.** Cada una es algo que actualizar y
   auditar durante años. Si la biblioteca estándar lo hace, se usa la estándar.
5. **Ningún mensaje de error que no diga qué hacer.** "Error al cargar" no es un
   mensaje; "no existe la columna 'fecha' en 'ventas'; columnas parecidas:
   fecha_emision" sí.

## Empezar

```bash
git clone https://github.com/a831ard0/astrolabio.git
cd astrolabio/backend
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/python demo/generar_datos.py     # datos ficticios, 8 segundos
./venv/bin/python -m pytest -q              # 296 pruebas
```

El detalle está en el [manual técnico](docs/manual-tecnico.md).

## Antes de abrir un PR

```bash
cd backend  && ./venv/bin/python -m pytest -q && ./venv/bin/pip-audit
cd frontend && npx tsc --noEmit && npx oxlint src && npm run build
```

Las pruebas que hablan con MySQL se saltan solas si no hay base; para correrlas de
verdad: `python demo/cargar_mysql.py`.

En el PR, di **qué se rompía antes** y **cómo lo comprobaste**. Un "arreglado" sin
eso obliga a quien revisa a reconstruir el problema desde cero.

## El acuerdo de contribución (importante)

Astrolabio se publica con doble licencia: AGPL-3.0 para todo el mundo, y una
licencia comercial para quien necesite cerrar el código (ver [COMERCIAL.md](COMERCIAL.md)).

Para que eso siga siendo posible, al enviar un PR **otorgas al mantenedor el derecho
de licenciar tu aportación también bajo otros términos, incluidos los comerciales**,
además de la AGPL. Tú conservas el copyright de lo que escribes.

Por qué se pide: si cada contribución quedara solo bajo AGPL, nadie —ni el
mantenedor— podría ofrecer una licencia comercial del conjunto, porque haría falta
el permiso de cada persona que haya tocado una línea. Es el punto en el que muchos
proyectos con doble licencia se quedan atascados años después.

Basta con incluir esta línea en el mensaje del commit, con tu nombre real:

```
Contribucion-bajo: doble licencia AGPL-3.0 y comercial. Nombre Apellido <correo>
```

Si eso no te parece bien, es una posición legítima y no hace falta discutirla: abre
un issue describiendo el problema y el arreglo, y se implementa por separado.

## Qué se acepta con gusto

- **Conectores nuevos** (PostgreSQL, SQL Server, SQLite, Oracle). El molde está en
  `backend/app/conectores/base.py`. Se pide que vengan con pruebas contra un motor
  real, aunque se salten cuando no esté disponible.
- **Traducciones** de la interfaz.
- **Correcciones de accesibilidad**: contraste, foco, lectores de pantalla.
- **Documentación**: si algo no se entendió a la primera, ese es un fallo del texto.

## Qué probablemente se rechace

- Cambiar el idioma del código a inglés.
- Cambiar SQLite por Postgres "porque escala". Está razonado en
  [docs/adr/0001](docs/adr/0001-sqlite-para-metadatos.md); si el argumento falla,
  el sitio para discutirlo es un issue, no un PR de 4.000 líneas.
- Añadir telemetría, analítica o cualquier llamada a un servidor externo que el
  usuario no haya pedido.
- Funciones sin pruebas que toquen el camino de las cifras.

## Seguridad

Los fallos de seguridad **no** van en un issue público: ver [SECURITY.md](SECURITY.md).
