$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$envPath = Join-Path $root '.env'
$examplePath = Join-Path $root '.env.example'

if (Test-Path -LiteralPath $envPath) {
    Write-Output 'Existing .env found; it was left unchanged.'
    exit 0
}

if (-not (Test-Path -LiteralPath $examplePath)) {
    throw 'Could not find .env.example.'
}

function New-RandomToken {
    $bytes = New-Object byte[] 48
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$content = [System.IO.File]::ReadAllText($examplePath)
$secretPlaceholder = 'replace-with-a-random-secret-before-starting'
if (-not $content.Contains($secretPlaceholder)) {
    throw 'The secret-key placeholder is missing from .env.example.'
}
$content = $content.Replace($secretPlaceholder, (New-RandomToken))
$serviceTokenPattern = '(?m)^PLANIFY_SERVICE_TOKEN=.*$'
if (-not [regex]::IsMatch($content, $serviceTokenPattern)) {
    throw 'PLANIFY_SERVICE_TOKEN is missing from .env.example.'
}
$content = [regex]::Replace(
    $content,
    $serviceTokenPattern,
    ('PLANIFY_SERVICE_TOKEN=' + (New-RandomToken)),
    1
)

$encoding = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($envPath, $content, $encoding)
Write-Output 'Created a private local .env with random application and service keys.'
Write-Output 'Add Google OAuth credentials locally if Google sign-in is required.'
