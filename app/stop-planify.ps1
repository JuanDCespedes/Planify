$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$logDirectory = Join-Path $env:TEMP 'Planify\logs'
$manifest = Join-Path $logDirectory 'processes.json'
$services = @(
    @{ Name = 'identity'; Arguments = '-m identity_service.serve' },
    @{ Name = 'planning'; Arguments = '-m planning_service.serve' },
    @{ Name = 'notifications'; Arguments = '-m notification_service.serve' },
    @{ Name = 'web'; Arguments = 'app.py' }
)
$prefix = '"' + $python + '"'
$processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
})

foreach ($service in $services) {
    $matching = @($processes | Where-Object {
        $_.CommandLine.Substring($prefix.Length).Trim() -eq $service.Arguments
    })
    foreach ($process in $matching) {
        Stop-Process -Id $process.ProcessId -Force
        Write-Output "Detenido $($service.Name) (PID $($process.ProcessId))."
    }
}

if (Test-Path $manifest) {
    Remove-Item -LiteralPath $manifest -Force
}
