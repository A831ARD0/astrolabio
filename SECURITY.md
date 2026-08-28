# Seguridad

## Reportar un fallo

**No abras un issue público.** Hay dos vías privadas, y las dos llegan:

1. **Aviso privado de GitHub** — la pestaña *Security* del repositorio,
   «Report a vulnerability». Es la preferida: queda hilo, historial y un
   identificador, y permite publicar el aviso cuando haya arreglo.
2. **Correo** a **abelardo.wr.garcia@gmail.com**, si prefieres no pasar por
   GitHub.

Cuenta qué hiciste, qué esperabas y qué pasó. Si puedes, incluye la petición
exacta.

Respuesta en un plazo razonable (esto lo mantiene una persona, no un equipo). Se
publicará el arreglo y se te dará crédito, salvo que prefieras que no.

## Qué versiones reciben arreglos

Solo **la última publicada**. Es lo honesto con un mantenedor único: sostener
ramas viejas es una promesa que no se podría cumplir, y una promesa de seguridad
que no se cumple es peor que no haberla hecho.

| Versión | Arreglos |
|---|---|
| 0.1.x | Sí |
| Anteriores | No — actualiza |

Mientras la serie sea `0.x`, una versión menor puede traer cambios que rompan
compatibilidad. Están en el [registro de cambios](CHANGELOG.md), y lo que haya
que hacer al actualizar, en el [manual técnico](docs/manual-tecnico.md).

## Qué protege Astrolabio, y qué no

Está pensado para correr **dentro de la red de una organización**, detrás de HTTPS,
con usuarios que la organización conoce. No está pensado para exponerse a internet
abierto ni para servir a varios clientes que no confían entre sí.

Lo que sí hace:

| | Cómo |
|---|---|
| Contraseñas | Argon2 (`passlib`). Nunca en claro, nunca reversibles |
| Sesión | JWT firmado, caduca a las 8 horas |
| Fuerza bruta | 8 intentos fallidos por cuenta y la cuenta se frena 15 minutos, incluso con la contraseña correcta |
| Credenciales de conexiones | Cifradas con Fernet. La API **nunca** las devuelve, ni enmascaradas de forma reversible |
| Seguridad por fila | Todas las consultas pasan por la capa de políticas; no hay una vía "sin políticas" |
| Inyección de SQL | Los valores van como parámetros; los identificadores se validan contra una lista blanca; las expresiones se revisan sobre el árbol de SQLGlot, no sobre el texto |
| Base analítica | Se abre en **solo lectura** para consultar |
| Archivos | El conector de archivos no puede salir de su carpeta (`..` y rutas absolutas se rechazan) |
| Auditoría | Quién hizo qué y cuándo, sin ruta para borrarla |
| Webhooks de avisos | Se rechazan las direcciones internas y **siempre** las de enlace local (`169.254.0.0/16`, donde las nubes publican credenciales) |

Lo que **no** hace, y conviene saberlo:

- **No cifra los Parquet en disco.** Quien tenga acceso al sistema de archivos del
  servidor lee los datos. Se protege con permisos del sistema operativo y con
  cifrado de disco.
- **No tiene doble factor.** Si hace falta, va delante un proveedor de identidad.
- **No limita las peticiones por IP** más allá del freno de ingreso por cuenta.
- **El freno de ingreso vive en memoria del proceso.** Con varios trabajadores, el
  límite efectivo se multiplica por su número. Está explicado en
  `backend/app/intentos.py`.
- **Un editor puede hacer que el servidor se conecte a donde diga** (una conexión
  nueva, un webhook). Es inherente a una herramienta que conecta a orígenes
  arbitrarios; por eso crear conexiones es de editor en adelante, y por eso los
  webhooks a la red interna están apagados por defecto.

## Antes de poner esto en producción

Está en el [manual técnico](docs/manual-tecnico.md), pero lo esencial:

```bash
ASTROLABIO_ENTORNO=produccion
ASTROLABIO_CLAVE_SECRETA=$(openssl rand -hex 32)
ASTROLABIO_CLAVE_CIFRADO=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

Con `ASTROLABIO_ENTORNO=produccion` **el arranque falla** si esas claves faltan o
siguen en el valor de ejemplo. Es a propósito: un sistema que arranca con la clave
de ejemplo es un sistema donde cualquiera puede firmarse un token de administrador.

Además: HTTPS delante, un usuario **de solo lectura** en cada origen de datos, y
respaldo del archivo de metadatos.

## Dependencias

Se revisan con `pip-audit` (backend) y `npm audit` (frontend), y las versiones están
fijas. Estado a la última revisión:

- Backend: **sin vulnerabilidades conocidas**.
- Frontend: queda un aviso alto en `react-router` (GHSA-qwww-vcr4-c8h2, *RSC Mode
  CSRF Bypass*). **No aplica aquí**: afecta al modo React Server Components y a las
  Server Actions, y esta interfaz es una SPA de navegador sin nada de eso. La
  versión "corregida" que propone `npm audit` es anterior y arrastra catorce avisos
  peores, así que se mantiene la última y se documenta. Se cambiará en cuanto haya
  una versión con el arreglo hacia adelante.
