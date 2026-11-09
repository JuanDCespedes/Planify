$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$instance = Join-Path $root 'instance'
$logDirectory = Join-Path $env:TEMP 'Planify\logs'
$ports = @(5000, 8100, 8101, 8102)

if (-not (Test-Path $python)) {
    throw 'No se encontro .venv\Scripts\python.exe. Instala las dependencias desde requirements.txt.'
}

$missingDatabases = @(@('identity.db', 'planning.db', 'notifications.db') | Where-Object {
    -not (Test-Path (Join-Path $instance $_))
})
if ($missingDatabases.Count -gt 0 -and $missingDatabases.Count -lt 3) {
    throw "Solo existen algunas bases de servicios. Revisa instance/ antes de iniciar. Faltan: $($missingDatabases -join ', ')"
}
if ($missingDatabases.Count -eq 3 -and (Test-Path (Join-Path $instance 'planify.db'))) {
    throw "Faltan bases de servicio. Si existe instance\planify.db, ejecuta primero: python migrate_to_microservices.py. Faltan: $($missingDatabases -join ', ')"
}

$listeners = Get-NetTCPConnection -State Listen -LocalPort $ports -ErrorAction SilentlyContinue
if ($listeners) {
    $usedPorts = ($listeners | Select-Object -ExpandProperty LocalPort -Unique) -join ', '
    throw "Puertos ocupados: $usedPorts. Detén esos procesos antes de iniciar Planify."
}

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$token = & $python -c "import secrets; print(secrets.token_urlsafe(48))"
if (-not $token) {
    throw 'No se pudo generar el token interno.'
}

$env:PLANIFY_ENV = 'development'
$env:PLANIFY_DEBUG = 'false'
$env:GOOGLE_REDIRECT_URI = 'http://127.0.0.1:5000/auth/google/callback'
$env:PLANIFY_MICROSERVICES_ENABLED = 'true'
$env:PLANIFY_SERVICE_TOKEN = $token
$env:IDENTITY_SERVICE_URL = 'http://127.0.0.1:8101'
$env:PLANNING_SERVICE_URL = 'http://127.0.0.1:8102'
$env:NOTIFICATION_SERVICE_URL = 'http://127.0.0.1:8100'
$env:IDENTITY_DATABASE_URL = "sqlite:///$($instance.Replace('\', '/'))/identity.db"
$env:PLANNING_DATABASE_URL = "sqlite:///$($instance.Replace('\', '/'))/planning.db"
$env:NOTIFICATION_DATABASE_URL = "sqlite:///$($instance.Replace('\', '/'))/notifications.db"
$env:IDENTITY_PORT = '8101'
$env:PLANNING_PORT = '8102'
$env:DELIVERY_PORT = '8100'
$env:PLANIFY_ENABLE_NOTIFICATION_SCHEDULER = 'true'
$env:PLANIFY_DELIVERY_EMAIL_ENABLED = 'false'
$env:PLANIFY_SMTP_HOST = ''
$env:PLANIFY_SMTP_USERNAME = ''
$env:PLANIFY_SMTP_PASSWORD = ''
$env:PLANIFY_SMTP_FROM = ''
$env:PLANIFY_SMTP_USE_SSL = 'false'
$env:PLANIFY_SMTP_STARTTLS = 'false'
$env:PLANIFY_VAPID_PRIVATE_KEY = ''
$env:PLANIFY_VAPID_PUBLIC_KEY = ''
$env:PLANIFY_VAPID_CLAIMS_EMAIL = ''

$services = @(
    @{ Name = 'identity'; Arguments = '-m identity_service.serve' },
    @{ Name = 'planning'; Arguments = '-m planning_service.serve' },
    @{ Name = 'notifications'; Arguments = '-m notification_service.serve' },
    @{ Name = 'web'; Arguments = 'app.py' }
)
$startedServices = @()

foreach ($service in $services) {
    $stdout = Join-Path $logDirectory "$($service.Name).out.log"
    $stderr = Join-Path $logDirectory "$($service.Name).err.log"
    $process = Start-Process -FilePath $python -ArgumentList $service.Arguments `
        -WorkingDirectory $root -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
    $startedServices += [PSCustomObject]@{
        Service = $service.Name
        ProcessId = $process.Id
        Arguments = $service.Arguments
        Log = $stdout
    }
}

$startedServices | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDirectory 'processes.json') -Encoding UTF8
$startedServices | Select-Object Service, ProcessId, Log
Write-Output 'Planify iniciando en http://127.0.0.1:5000'
Write-Output 'Para detenerlo, ejecuta .\stop-planify.ps1.'
