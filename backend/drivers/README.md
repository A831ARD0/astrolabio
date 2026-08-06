# Drivers ODBC licenciados

Esta carpeta está vacía a propósito, y su contenido está en `.gitignore`.

## Para qué es

Algunos orígenes necesitan un driver ODBC que **no se puede descargar**: sale del
instalador licenciado del fabricante. El caso que motivó esto es **Actian Zen /
Pervasive PSQL**, sobre el que corren muchos sistemas de gestión antiguos.

Si dejas aquí el paquete del cliente de Linux, la construcción de la imagen lo
instala y lo registra sola. Si no dejas nada, la imagen se construye igual y sin
ese driver — los demás conectores funcionan sin enterarse.

## Qué dejar aquí

El **cliente** de Actian Zen para **Linux**, de **64 bits**. Un `.deb` o el
`.tar.gz`, tal como viene del portal de Actian:

```
backend/drivers/Zen-Client-linux-x86_64-16.xx.deb
```

Y reconstruir:

```bash
docker compose build api && docker compose up -d
```

Tres formas de equivocarse, y las tres se parecen mucho al paquete correcto:

| No sirve | Por qué |
|---|---|
| El cliente de **Windows** | Un contenedor es Linux; una DLL no se carga ahí |
| El cliente de **32 bits** | Un proceso de 64 bits no puede cargar un driver de 32 |
| El **servidor** (Zen Server / Enterprise) | Astrolabio es cliente: se conecta a un motor que ya existe |

## Comprobar que quedó

```bash
docker compose exec api python -c "import pyodbc; print(pyodbc.drivers())"
```

Tiene que salir `Actian Zen ODBC Interface` en la lista. Ese mismo nombre es el
que la pantalla de conexiones preselecciona sola al elegir el origen Pervasive.

Si la lista sale sin él pero la construcción no dio error, es que la carpeta
estaba vacía cuando se construyó la imagen: `docker compose build --no-cache api`.

## Y la licencia

El cliente de Actian es software licenciado de un tercero. **No se puede
redistribuir**, y por eso esta carpeta está en `.gitignore`: un binario licenciado
en un repositorio público con licencia AGPL es un problema legal, no un descuido
de configuración.
