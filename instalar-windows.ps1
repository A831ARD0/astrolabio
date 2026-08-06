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

.EXAMPLE
    .\instalar-windows.ps1
    .\instalar-windows.ps1 -Servicios
#>

[CmdletBinding()]
param(
    [string] $Raiz = $PSScriptRoot,
    [switch] $Servicios,
    [switch] $Comprobar
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

$backend  = Join-Path $Raiz 'backend'
$frontend = Join-Path $Raiz 'frontend'
$python   = Join-Path $backend 'venv\Scripts\python.exe'

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
        return
    }
    [Environment]::SetEnvironmentVariable($nombre, $valor, 'Machine')
    Set-Item -Path "Env:$nombre" -Value $valor      # para el resto de esta sesion
    Bien "$nombre generada. $porque"
}

# NUNCA se pisa una clave que ya existe, y CLAVE_CIFRADO es la razon: cambiarla
# deja ilegibles TODAS las contrasenas de las conexiones ya guardadas. No hay
# recuperacion; hay que volver a escribirlas una por una.
FijarSiFalta 'ASTROLABIO_CLAVE_SECRETA' (((Bytes32) | ForEach-Object { $_.ToString('x2') }) -join '') 'Firma los tokens de sesion.'
FijarSiFalta 'ASTROLABIO_CLAVE_CIFRADO' ([Convert]::ToBase64String((Bytes32)).Replace('+','-').Replace('/','_')) 'Cifra las credenciales. GUARDALA con el respaldo.'
FijarSiFalta 'ASTROLABIO_ENTORNO' 'produccion' 'Exige las claves de verdad al arrancar.'

Aviso 'Copia las dos claves a tu gestor de secretos AHORA:'
Write-Host "     ASTROLABIO_CLAVE_CIFRADO = $([Environment]::GetEnvironmentVariable('ASTROLABIO_CLAVE_CIFRADO','Machine'))"
Aviso 'Un respaldo sin esa clave restaura todo menos las contrasenas de las conexiones.'

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

    if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
        throw 'Falta NSSM. Bajalo de https://nssm.cc y ponlo en el PATH.'
    }

    $registros = Join-Path $Raiz 'registros'
    New-Item -ItemType Directory -Force -Path $registros | Out-Null

    # --host 127.0.0.1 a proposito: quien entra de fuera pasa por Caddy, que es
    # el que lleva HTTPS y las cabeceras de seguridad.
    $ordenes = @(
        @('install', 'Astrolabio', $python),
        @('set', 'Astrolabio', 'AppParameters',
          '-m uvicorn app.main:app --host 127.0.0.1 --port 8000'),
        @('set', 'Astrolabio', 'AppDirectory', $backend),
        @('set', 'Astrolabio', 'AppStdout', (Join-Path $registros 'salida.log')),
        @('set', 'Astrolabio', 'AppStderr', (Join-Path $registros 'error.log')),
        @('set', 'Astrolabio', 'Start', 'SERVICE_AUTO_START'),
        @('start', 'Astrolabio')
    )
    foreach ($orden in $ordenes) {
        $r = Correr nssm $orden
        if ($r.Codigo -ne 0) {
            throw "Fallo 'nssm $($orden -join ' ')':`n$($r.Texto)"
        }
    }
    Bien 'Servicio Astrolabio instalado y arrancado'

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
