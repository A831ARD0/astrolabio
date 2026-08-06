<#
.SYNOPSIS
    Instala Astrolabio nativo en Windows Server.

.DESCRIPTION
    Para Windows Server 2019, donde no hay contenedores Linux (WSL 2 pide la
    compilacion 19041 o superior y Docker Desktop no se soporta en Windows
    Server). Y es ademas la unica instalacion donde carga el driver ODBC de
    Pervasive, que es de Windows.

    Deja el entorno de Python, compila la interfaz, genera las claves si faltan y
    comprueba que la API arranca. Los servicios se instalan aparte, con -Servicios,
    porque hacen falta permisos de administrador y NSSM.

    Se puede volver a correr: no pisa nada de lo que ya este bien.

.PARAMETER Raiz
    Donde esta clonado el repositorio. Por omision, la carpeta de este guion.

.PARAMETER Servicios
    Ademas, registra los servicios de Windows con NSSM. Pide administrador.

.PARAMETER Comprobar
    Solo revisa los requisitos y sale. No escribe nada.

.PARAMETER DescargarNSSM
    Baja NSSM de nssm.cc a herramientas\ en vez de pedir que se instale a mano.
    Solo tiene efecto junto con -Servicios.

.PARAMETER Puente32
    Instala ademas el puente ODBC de 32 bits: un segundo interprete, de 32 bits,
    con pyodbc y nada mas. Hace falta cuando el driver del origen solo existe de
    32 bits y no se puede cambiar —Pervasive/Actian con TotalDealer es el caso—,
    porque un proceso de 64 bits no puede cargar una libreria de 32.

    Con -Servicios, ademas lo registra como el servicio AstrolabioPuente32.

.PARAMETER RotarClaveCifrado
    Genera una CLAVE_CIFRADO nueva y sale. Para cuando la anterior se haya visto
    —una captura de pantalla, un correo—. Barato antes de que haya conexiones
    guardadas; despues obliga a reescribir sus contrasenas.

.EXAMPLE
    .\instalar-windows.ps1
    .\instalar-windows.ps1 -Servicios
    .\instalar-windows.ps1 -Puente32 -Servicios
    .\instalar-windows.ps1 -RotarClaveCifrado
#>

[CmdletBinding()]
param(
    [string] $Raiz = $PSScriptRoot,
    [switch] $Servicios,
    [switch] $Comprobar,
    [switch] $RotarClaveCifrado,
    [switch] $DescargarNSSM,
    [switch] $Puente32
)

$ErrorActionPreference = 'Stop'

function Paso  { param($t) Write-Host "`n== $t" -ForegroundColor Cyan }
function Bien  { param($t) Write-Host "   OK  $t" -ForegroundColor Green }
function Aviso { param($t) Write-Host "   !   $t" -ForegroundColor Yellow }

<#
Llama a un programa externo y devuelve su salida y su codigo.

Existe por dos trampas de Windows PowerShell 5.1, que es el que trae Windows
Server 2019:

1. Con $ErrorActionPreference = 'Stop', CUALQUIER cosa que un programa externo
   escriba en la salida de error se convierte en un error que aborta el guion
   —el famoso NativeCommandError—. Y pip, npm y py escriben ahi de continuo
   cosas que no son errores. Aqui se baja la preferencia solo mientras dura la
   llamada y se decide por el codigo de salida, que es lo que de verdad dice si
   fue bien.

2. Lo que decide si algo fallo es $LASTEXITCODE, no que haya habido texto en la
   salida de error.
#>
<#
Deja un archivo legible solo por administradores y SYSTEM.

Por SID y no por nombre: en un Windows en espanol la cuenta se llama
'BUILTIN\Administradores', y pedirla por su nombre en ingles falla con "No se
pudieron convertir algunas o todas las referencias de identidad". Los SID
conocidos son iguales en todos los idiomas.
#>
function ProtegerArchivo {
    param([Parameter(Mandatory)] [string] $Ruta)

    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetAccessRuleProtection($true, $false)   # sin herencia de la carpeta
    foreach ($tipo in @([System.Security.Principal.WellKnownSidType]::BuiltinAdministratorsSid,
                        [System.Security.Principal.WellKnownSidType]::LocalSystemSid)) {
        $sid = New-Object System.Security.Principal.SecurityIdentifier($tipo, $null)
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $sid, 'FullControl', 'Allow')))
    }
    Set-Acl -Path $Ruta -AclObject $acl
}

function Correr {
    param(
        [Parameter(Mandatory)] [string]   $Programa,
        [Parameter(Mandatory)] [string[]] $Argumentos
    )
    $antes = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $salida = & $Programa @Argumentos 2>&1
        return [pscustomobject]@{
            Codigo = $LASTEXITCODE
            Texto  = ($salida | ForEach-Object { "$_" }) -join "`n"
        }
    } finally { $ErrorActionPreference = $antes }
}

<#
Deja un proceso como servicio de Windows con NSSM, y lo vuelve a dejar igual si
ya existia.

Existe porque hay dos servicios —la API y el puente de 32 bits— y el segundo
llego despues. Duplicar estas quince lineas es como uno de los dos se queda sin
el `Start` automatico y nadie se entera hasta el siguiente reinicio del servidor.
#>
function InstalarServicio {
    param(
        [Parameter(Mandatory)] [string]   $Nssm,
        [Parameter(Mandatory)] [string]   $Nombre,
        [Parameter(Mandatory)] [string]   $Programa,
        [Parameter(Mandatory)] [string]   $Parametros,
        [Parameter(Mandatory)] [string]   $Directorio,
        [Parameter(Mandatory)] [string]   $Registros
    )
    $yaExiste = Get-Service -Name $Nombre -ErrorAction SilentlyContinue
    if ($yaExiste) {
        Bien "El servicio $Nombre ya existia: se detiene y se vuelve a configurar"
        if ($yaExiste.Status -ne 'Stopped') {
            Stop-Service -Name $Nombre -Force
            (Get-Service $Nombre).WaitForStatus('Stopped', '00:00:30')
        }
    } else {
        $r = Correr $Nssm @('install', $Nombre, $Programa)
        if ($r.Codigo -ne 0) { throw "Fallo 'nssm install $Nombre':`n$($r.Texto)" }
    }

    $ordenes = @(
        @('set', $Nombre, 'Application', $Programa),
        @('set', $Nombre, 'AppParameters', $Parametros),
        @('set', $Nombre, 'AppDirectory', $Directorio),
        @('set', $Nombre, 'AppStdout', (Join-Path $Registros "$Nombre-salida.log")),
        @('set', $Nombre, 'AppStderr', (Join-Path $Registros "$Nombre-error.log")),
        @('set', $Nombre, 'Start', 'SERVICE_AUTO_START'),
        @('start', $Nombre)
    )
    foreach ($orden in $ordenes) {
        $r = Correr $Nssm $orden
        if ($r.Codigo -ne 0) { throw "Fallo 'nssm $($orden -join ' ')':`n$($r.Texto)" }
    }
}

$backend  = Join-Path $Raiz 'backend'
$frontend = Join-Path $Raiz 'frontend'
$python   = Join-Path $backend 'venv\Scripts\python.exe'
# El interprete de 32 bits del puente. Vive aparte a proposito: es OTRO Python,
# con OTRO pyodbc, y mezclarlos en el mismo venv no es posible.
$python32 = Join-Path $backend 'venv32\Scripts\python.exe'
$tokenPuente = Join-Path $backend 'datos\puente.token'

# --------------------------------------------------------------------------- #
# Rotar la clave de cifrado
# --------------------------------------------------------------------------- #
#
# Se hace y se sale: no tiene nada que ver con instalar. Sirve para el caso en
# que la clave se haya visto —una captura, un correo, un chat—, y solo es barato
# ANTES de que haya conexiones guardadas: las contrasenas ya guardadas estan
# cifradas con la vieja y quedan ilegibles.

if ($RotarClaveCifrado) {
    Paso 'Rotar ASTROLABIO_CLAVE_CIFRADO'

    $hayBase = Test-Path (Join-Path $backend 'datos\astrolabio.db')
    if ($hayBase) {
        Aviso 'Ya hay una base de metadatos. Si tiene conexiones guardadas, sus'
        Aviso 'contrasenas quedaran ilegibles y habra que reescribirlas a mano'
        Aviso 'desde Conexiones -> Editar. Los datasets y tableros no se tocan.'
        $respuesta = Read-Host 'Escribe ROTAR para continuar'
        if ($respuesta -ne 'ROTAR') { Write-Host 'Cancelado.'; exit 0 }
    }

    $b = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    $nueva = [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_')

    [Environment]::SetEnvironmentVariable('ASTROLABIO_CLAVE_CIFRADO', $nueva, 'Machine')
    Bien 'Clave rotada.'

    $destino = Join-Path $Raiz 'CLAVES-GENERADAS.txt'
    "ASTROLABIO_CLAVE_CIFRADO = $nueva" | Set-Content -Path $destino -Encoding UTF8
    ProtegerArchivo $destino
    Aviso "La nueva quedo en $destino. Guardala y borra el archivo."
    Aviso 'Reinicia el servicio: Restart-Service Astrolabio'
    exit 0
}

# --------------------------------------------------------------------------- #
# Requisitos
# --------------------------------------------------------------------------- #

Paso 'Requisitos'

if ($Raiz -match '[^\x20-\x7E]') {
    throw "La ruta '$Raiz' tiene caracteres raros. Usa algo como C:\astrolabio."
}

$ayudaPython = @'
Falta Python 3.12.

  Bajalo de https://www.python.org/downloads/windows/ — el instalador
  "Windows installer (64-bit)". En el instalador marca las dos casillas:

    [x] Add python.exe to PATH
    [x] Install for all users        <- hace falta para correrlo como servicio

  TIENE QUE SER DE 64 BITS. Con Python de 32 bits, DuckDB se queda en unos
  3 GB de memoria y una consulta sobre millones de filas se muere; y ademas
  cargaria los drivers ODBC de 32 bits, que es justo de lo que hay que salir.

  Despues, `py -0` tiene que listar 3.12.
'@

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { throw $ayudaPython }

# Comillas: el codigo de Python va entre comillas DOBLES y por dentro solo lleva
# comillas simples. Al reves —simples fuera, dobles dentro— PowerShell se come
# las dobles al pasarselas al programa y Python recibe algo que no compila.
$r = Correr py @('-3.12', '-c', "import sys; print('%d.%d' % sys.version_info[:2])")
if ($r.Codigo -ne 0) { throw $ayudaPython }
$version = $r.Texto.Trim()

$r = Correr py @('-3.12', '-c', "import struct; print(struct.calcsize('P') * 8)")
if ($r.Codigo -ne 0 -or $r.Texto.Trim() -ne '64') {
    throw "Python $version no es de 64 bits (dice: $($r.Texto.Trim())).`n$ayudaPython"
}
Bien "Python $version de 64 bits"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'Falta Node. Instala Node 20 o superior desde nodejs.org.'
}
$r = Correr node @('--version')
if ($r.Codigo -ne 0) { throw 'Node esta en el PATH pero no responde.' }
Bien "Node $($r.Texto.Trim())"

# Windows trae su propio administrador de ODBC, asi que pyodbc funciona sin
# instalar nada. Lo que no trae son los drivers de cada origen.
$odbc = "$env:SystemRoot\System32\odbcad32.exe"
if (Test-Path $odbc) { Bien 'Administrador ODBC de 64 bits presente' }

$ayudaPython32 = @'
Falta Python 3.12 de 32 bits, que es lo que necesita el puente.

  Bajalo de https://www.python.org/downloads/windows/ — esta vez el instalador
  "Windows installer (32-bit)". Se instala AL LADO del de 64 bits, no lo
  reemplaza: Windows los mantiene aparte y `py` sabe cual es cual.

  En el instalador marca "Install for all users". NO marques "Add python.exe to
  PATH": el de 64 bits ya esta ahi y el que gane el PATH seria cuestion de azar.

  Despues, `py -0` tiene que listar tanto 3.12 como 3.12-32.
'@

if ($Puente32) {
    # El sufijo -32 es como el lanzador de Python distingue las dos instalaciones.
    $r = Correr py @('-3.12-32', '-c', "import struct; print(struct.calcsize('P') * 8)")
    if ($r.Codigo -ne 0) { throw $ayudaPython32 }
    if ($r.Texto.Trim() -ne '32') {
        throw ("'py -3.12-32' contesto $($r.Texto.Trim()) bits, no 32. " +
               "Sin un interprete de 32 bits el puente no sirve de nada, " +
               "porque lo unico que aporta es poder cargar ese driver.`n$ayudaPython32")
    }
    Bien 'Python 3.12 de 32 bits presente'

    $odbc32 = "$env:SystemRoot\SysWOW64\odbcad32.exe"
    # El nombre despista: el de System32 es el de 64 bits y el de SysWOW64 el de
    # 32. Es asi desde Windows XP de 64 bits y no va a cambiar.
    if (Test-Path $odbc32) { Bien 'Administrador ODBC de 32 bits presente' }
}

if ($Comprobar) { Write-Host "`nSolo comprobacion. No se escribio nada."; exit 0 }

# --------------------------------------------------------------------------- #
# Entorno de Python
# --------------------------------------------------------------------------- #

Paso 'Entorno de Python'

if (-not (Test-Path $python)) {
    $r = Correr py @('-3.12', '-m', 'venv', (Join-Path $backend 'venv'))
    if ($r.Codigo -ne 0) { throw "No se pudo crear el venv:`n$($r.Texto)" }
    Bien 'venv creado'
} else {
    Bien 'venv ya estaba'
}

$r = Correr $python @('-m', 'pip', 'install', '--upgrade', 'pip', '--quiet')
if ($r.Codigo -ne 0) { throw "Fallo actualizar pip:`n$($r.Texto)" }

Write-Host '   ... instalando dependencias (tarda un par de minutos)'
$r = Correr $python @('-m', 'pip', 'install', '-r',
                      (Join-Path $backend 'requirements.txt'), '--quiet')
if ($r.Codigo -ne 0) { throw "Fallo la instalacion de dependencias:`n$($r.Texto)" }
Bien 'Dependencias instaladas'

# --------------------------------------------------------------------------- #
# El puente ODBC de 32 bits
# --------------------------------------------------------------------------- #

if ($Puente32) {
    Paso 'Puente ODBC de 32 bits'

    if (-not (Test-Path $python32)) {
        $r = Correr py @('-3.12-32', '-m', 'venv', (Join-Path $backend 'venv32'))
        if ($r.Codigo -ne 0) { throw "No se pudo crear el venv de 32 bits:`n$($r.Texto)" }
        Bien 'venv32 creado'
    } else {
        Bien 'venv32 ya estaba'
    }

    # Solo pyodbc. Ni pyarrow ni duckdb: no tienen ruedas de 32 bits, y el puente
    # no las necesita porque no toca ni Arrow ni Parquet — de eso se encarga el
    # proceso de 64 bits con las filas ya recibidas.
    $r = Correr $python32 @('-m', 'pip', 'install', '--upgrade', 'pip', '--quiet')
    if ($r.Codigo -ne 0) { throw "Fallo actualizar pip en venv32:`n$($r.Texto)" }
    $r = Correr $python32 @('-m', 'pip', 'install', 'pyodbc==5.3.0', '--quiet')
    if ($r.Codigo -ne 0) { throw "Fallo instalar pyodbc de 32 bits:`n$($r.Texto)" }
    Bien 'pyodbc de 32 bits instalado'

    # Lo que de verdad decide si esto valio la pena: que desde 32 bits se vea el
    # driver que desde 64 no se veia. Se dice ahora y no cuando falle una carga.
    $r = Correr $python32 @('-c', "import pyodbc; print('|'.join(sorted(pyodbc.drivers())))")
    if ($r.Codigo -eq 0) {
        $vistos = $r.Texto.Trim()
        if ($vistos) {
            Bien "Drivers de 32 bits que ve el puente: $($vistos -replace '\|', ', ')"
        } else {
            Aviso 'El puente no ve ningun driver de 32 bits. Revisa que el cliente'
            Aviso 'del origen este instalado y que sus DSN esten en SysWOW64\odbcad32.exe.'
        }
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $tokenPuente) | Out-Null
    if (Test-Path $tokenPuente) {
        Bien 'El token del puente ya estaba (no se toca)'
    } else {
        # Es lo unico que separa a ese proceso de cualquiera que hable con su
        # puerto. Se genera aqui y lo leen los dos servicios del mismo archivo:
        # asi no pasa por la linea de comandos, que es visible en el Administrador
        # de tareas, ni por una variable de entorno.
        $b = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
        [Convert]::ToBase64String($b).Replace('+','-').Replace('/','_').TrimEnd('=') |
            Set-Content -Path $tokenPuente -Encoding ASCII -NoNewline
        ProtegerArchivo $tokenPuente
        Bien "Token del puente generado en $tokenPuente"
    }
}

# --------------------------------------------------------------------------- #
# La interfaz
# --------------------------------------------------------------------------- #

Paso 'Interfaz'

Push-Location $frontend
try {
    Write-Host '   ... npm ci (tarda un par de minutos)'
    $r = Correr npm @('ci')
    if ($r.Codigo -ne 0) { throw "Fallo 'npm ci':`n$($r.Texto)" }

    $r = Correr npm @('run', 'build')
    if ($r.Codigo -ne 0) { throw "Fallo la compilacion de la interfaz:`n$($r.Texto)" }
} finally { Pop-Location }

if (-not (Test-Path (Join-Path $frontend 'dist\index.html'))) {
    throw "La compilacion dijo que fue bien pero no hay $frontend\dist\index.html."
}
Bien "Compilada en $frontend\dist"

# --------------------------------------------------------------------------- #
# Las claves
# --------------------------------------------------------------------------- #

Paso 'Claves'

function Bytes32 {
    $b = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return $b
}

function FijarSiFalta {
    param($nombre, $valor, $porque)

    $actual = [Environment]::GetEnvironmentVariable($nombre, 'Machine')
    if ($actual) {
        Bien "$nombre ya estaba (no se toca)"
        return $false
    }
    [Environment]::SetEnvironmentVariable($nombre, $valor, 'Machine')
    Set-Item -Path "Env:$nombre" -Value $valor      # para el resto de esta sesion
    Bien "$nombre generada. $porque"
    return $true
}

# NUNCA se pisa una clave que ya existe, y CLAVE_CIFRADO es la razon: cambiarla
# deja ilegibles TODAS las contrasenas de las conexiones ya guardadas. No hay
# recuperacion; hay que volver a escribirlas una por una.
$generadas = @()
if (FijarSiFalta 'ASTROLABIO_CLAVE_SECRETA' (((Bytes32) | ForEach-Object { $_.ToString('x2') }) -join '') 'Firma los tokens de sesion.') {
    $generadas += 'ASTROLABIO_CLAVE_SECRETA'
}
if (FijarSiFalta 'ASTROLABIO_CLAVE_CIFRADO' ([Convert]::ToBase64String((Bytes32)).Replace('+','-').Replace('/','_')) 'Cifra las credenciales. GUARDALA con el respaldo.') {
    $generadas += 'ASTROLABIO_CLAVE_CIFRADO'
}
FijarSiFalta 'ASTROLABIO_ENTORNO' 'produccion' 'Exige las claves de verdad al arrancar.' | Out-Null

# El archivo se escribe SOLO si se genero alguna clave en esta corrida. Antes se
# escribia siempre que no existiera, con lo que volver a correr el guion
# resucitaba un archivo de secretos que ya se habia guardado y borrado.
$archivoClaves = Join-Path $Raiz 'CLAVES-GENERADAS.txt'

if ($generadas.Count -gt 0) {
    # La clave NO se imprime en pantalla: la consola queda en el historial, en
    # las capturas y en el texto que uno pega para pedir ayuda.
    $lineas = @(
        'Claves de Astrolabio generadas por instalar-windows.ps1.',
        '',
        'Guardalas en el gestor de secretos y BORRA este archivo.',
        'Sin CLAVE_CIFRADO, un respaldo restaura todo menos las contrasenas de',
        'las conexiones, y no hay forma de recuperarlas.',
        ''
    )
    foreach ($clave in $generadas) {
        $lineas += "$clave = $([Environment]::GetEnvironmentVariable($clave,'Machine'))"
    }
    $lineas | Set-Content -Path $archivoClaves -Encoding UTF8

    ProtegerArchivo $archivoClaves

    Aviso "Las claves quedaron en: $archivoClaves"
    Aviso 'Copialas al gestor de secretos y BORRA ese archivo. No se imprimen'
    Aviso 'en pantalla a proposito: la consola acaba en capturas y en correos.'
}

# --------------------------------------------------------------------------- #
# Que arranca de verdad
# --------------------------------------------------------------------------- #

Paso 'Prueba de arranque'

$datos = Join-Path $backend 'datos'
New-Item -ItemType Directory -Force -Path $datos | Out-Null

# La salida se guarda en archivos: la ventana va oculta, asi que sin esto un
# arranque fallido no deja ni rastro y el guion solo sabria decir "no respondio".
$bitacora = Join-Path $env:TEMP 'astrolabio-arranque.log'
$errores  = Join-Path $env:TEMP 'astrolabio-arranque-error.log'

$proceso = Start-Process -FilePath $python `
    -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' `
    -WorkingDirectory $backend -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $bitacora -RedirectStandardError $errores

try {
    $salud = $null
    foreach ($intento in 1..30) {
        Start-Sleep -Seconds 1

        # Si el proceso ya murio, esperar los 30 segundos no aporta nada.
        if ($proceso.HasExited) { break }

        try {
            $salud = Invoke-RestMethod 'http://127.0.0.1:8000/api/salud' -TimeoutSec 2
            if ($salud.estado -eq 'ok') { break }
        } catch { $salud = $null }
    }

    if (-not $salud) {
        $detalle = @()
        foreach ($archivo in @($errores, $bitacora)) {
            if ((Test-Path $archivo) -and (Get-Item $archivo).Length -gt 0) {
                $detalle += "--- $archivo"
                $detalle += (Get-Content $archivo -Tail 25)
            }
        }
        if (-not $detalle) { $detalle = @('(la API no dejo ningun mensaje)') }
        throw ("La API no arranco.`n" + ($detalle -join "`n"))
    }
    Bien "Responde: version $($salud.version), entorno $($salud.entorno)"
} finally {
    if (-not $proceso.HasExited) { Stop-Process -Id $proceso.Id -Force }
}

# --------------------------------------------------------------------------- #
# Servicios
# --------------------------------------------------------------------------- #

if ($Servicios) {
    Paso 'Servicios de Windows'

    $admin = ([Security.Principal.WindowsPrincipal] `
              [Security.Principal.WindowsIdentity]::GetCurrent()
             ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $admin) { throw 'Para -Servicios hace falta PowerShell como administrador.' }

    # NSSM es lo que convierte un proceso normal en un servicio de Windows que
    # arranca solo y se levanta si se cae. `sc.exe` no sirve: espera un programa
    # escrito como servicio, y uvicorn no lo es.
    # .Source: la ruta del .exe. Sin eso seria un objeto de PowerShell, y lo que
    # hace falta para invocarlo es una ruta.
    $enPath = Get-Command nssm -ErrorAction SilentlyContinue
    $nssm = if ($enPath) { $enPath.Source } else { $null }

    # Si ya se bajo antes con -DescargarNSSM, esta aqui aunque no este en el PATH.
    if (-not $nssm) {
        $local = Join-Path $Raiz 'herramientas\nssm.exe'
        if (Test-Path $local) { $nssm = $local }
    }

    if (-not $nssm -and $DescargarNSSM) {
        Paso 'Bajando NSSM'
        $carpeta = Join-Path $Raiz 'herramientas'
        New-Item -ItemType Directory -Force -Path $carpeta | Out-Null
        $zip = Join-Path $env:TEMP 'nssm.zip'

        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' `
                          -OutFile $zip -UseBasicParsing

        # Se enseña la huella para que se pueda comparar con la de nssm.cc. No se
        # comprueba contra un valor escrito aqui: una huella copiada a mano en un
        # guion da una seguridad que no es real.
        Aviso "SHA256 de lo descargado: $((Get-FileHash $zip -Algorithm SHA256).Hash)"

        $temporal = Join-Path $env:TEMP 'nssm-extraido'
        Remove-Item $temporal -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive -Path $zip -DestinationPath $temporal -Force

        $encontrado = Get-ChildItem $temporal -Recurse -Filter 'nssm.exe' |
                      Where-Object { $_.FullName -match 'win64' } |
                      Select-Object -First 1
        if (-not $encontrado) { throw 'El zip de NSSM no traia win64\nssm.exe.' }

        Copy-Item $encontrado.FullName (Join-Path $carpeta 'nssm.exe') -Force
        Remove-Item $zip, $temporal -Recurse -Force -ErrorAction SilentlyContinue
        $nssm = Join-Path $carpeta 'nssm.exe'
        Bien "NSSM en $nssm"
    }

    if (-not $nssm) {
        throw @"
Falta NSSM, que es lo que convierte la API en un servicio de Windows.

  Dejame bajarlo:

      .\instalar-windows.ps1 -Servicios -DescargarNSSM

  O hazlo a mano: baja https://nssm.cc/release/nssm-2.24.zip, descomprimelo, y
  copia el nssm.exe de la carpeta win64 (no el de win32) a
  $Raiz\herramientas\nssm.exe
"@
    }

    $registros = Join-Path $Raiz 'registros'
    New-Item -ItemType Directory -Force -Path $registros | Out-Null

    # El puente PRIMERO: si la API arranca antes, la primera carga que use una
    # conexion de 32 bits se encuentra el puente caido.
    if ($Puente32) {
        InstalarServicio -Nssm $nssm -Nombre 'AstrolabioPuente32' `
            -Programa $python32 `
            -Parametros "-m puente32.servidor --puerto 8001 --token-archivo `"$tokenPuente`"" `
            -Directorio $backend -Registros $registros
        Bien 'Servicio AstrolabioPuente32 instalado'
    }

    # --host 127.0.0.1 a proposito: quien entra de fuera pasa por Caddy, que es
    # el que lleva HTTPS y las cabeceras de seguridad.
    InstalarServicio -Nssm $nssm -Nombre 'Astrolabio' -Programa $python `
        -Parametros '-m uvicorn app.main:app --host 127.0.0.1 --port 8000' `
        -Directorio $backend -Registros $registros

    # Que diga que arranco no basta: un servicio que se cae al segundo tambien
    # "arranca". Se comprueba que responde de verdad.
    $vivo = $false
    foreach ($intento in 1..20) {
        Start-Sleep -Seconds 1
        try {
            if ((Invoke-RestMethod 'http://127.0.0.1:8000/api/salud' -TimeoutSec 2).estado -eq 'ok') {
                $vivo = $true; break
            }
        } catch { }
    }
    if (-not $vivo) {
        throw ("El servicio se instalo pero no responde. Mira " +
               (Join-Path $registros 'Astrolabio-error.log'))
    }
    Bien 'Servicio Astrolabio arrancado y respondiendo'

    if ($Puente32) {
        # El puente no tiene salud sin token, asi que se comprueba desde el mismo
        # Python que lo va a usar de verdad. Que el servicio este 'Running' no
        # dice nada: puede estar arriba y rechazando el token.
        # En una sola linea y con comillas simples por dentro: una cadena con
        # saltos de linea pasada a un programa externo es la otra forma de la
        # trampa de comillas de PowerShell 5.1. Y la ruta va explicita porque
        # este guion no corre desde backend\, asi que un '.' no serviria.
        $prueba = ("import sys; sys.path.insert(0, r'$backend'); " +
                   "from app.conectores import puente; " +
                   "from app.conectores.odbc import _ajustes_del_puente as a; " +
                   "u, t = a(); s = puente.salud(u, t); " +
                   "print('%d|%s' % (s['bits'], ','.join(s['drivers'])))")
        $r = Correr $python @('-c', $prueba)
        if ($r.Codigo -ne 0) {
            throw ("El puente no contesta desde Astrolabio:`n$($r.Texto)`nMira " +
                   (Join-Path $registros 'AstrolabioPuente32-error.log'))
        }
        $bits, $drivers = $r.Texto.Trim().Split('|')
        if ($bits -ne '32') {
            Aviso "El puente contesta pero es de $bits bits, no de 32. Revisa que"
            Aviso 'el servicio apunte a backend\venv32, no a backend\venv.'
        }
        Bien "Puente de $bits bits respondiendo. Drivers: $(if ($drivers) { $drivers } else { '(ninguno)' })"
    }

    Aviso 'Falta Caddy delante. Ver el manual tecnico, seccion de Windows.'
    Aviso 'Y ponlo a correr con una cuenta de servicio sin privilegios:'
    Write-Host '     nssm set Astrolabio ObjectName <dominio\cuenta> <clave>'
}

# --------------------------------------------------------------------------- #

Write-Host "`nListo." -ForegroundColor Green
if (-not $Servicios) {
    Write-Host 'Para dejarlo como servicio: .\instalar-windows.ps1 -Servicios (como administrador).'
}
Write-Host 'Lo que falta esta en docs\manual-tecnico.md, seccion 4.'
