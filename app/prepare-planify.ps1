$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
$envPath = Join-Path $root '.env'
$examplePath = Join-Path $root '.env.example'

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Python 3.10+ is required. Install Python for Windows, then run this script again.'
}

if (-not (Test-Path $venvPython)) {
    Write-Output 'Creating the project virtual environment...'
    & py -3 -m venv (Join-Path $root '.venv')
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create .venv.'
    }
}

$versionText = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$version = [version]$versionText
if ($version -lt [version]'3.10') {
    throw "Python 3.10 or later is required; found $versionText."
}

Write-Output 'Installing requirements...'
& $venvPython -m pip install -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) {
    throw 'Dependency installation failed. Check the network connection and requirements.txt.'
}

if (-not (Test-Path $envPath)) {
    Copy-Item -LiteralPath $examplePath -Destination $envPath
    $content = [System.IO.File]::ReadAllText($envPath)
    if ($content.Contains('replace-with-a-random-secret-before-starting')) {
        $secret = & $venvPython -c "import secrets; print(secrets.token_urlsafe(48))"
        $content = $content.Replace('replace-with-a-random-secret-before-starting', $secret)
        $encoding = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($envPath, $content, $encoding)
    }
    Write-Output 'Created a private local .env from .env.example.'
} else {
    Write-Output 'Existing .env found; it was left unchanged.'
}

Write-Output 'Preparation complete. Start the presentation with:'
Write-Output 'powershell -ExecutionPolicy Bypass -File start-planify.ps1'
Write-Output 'Google OAuth is optional; email/password registration works without OAuth credentials.'
