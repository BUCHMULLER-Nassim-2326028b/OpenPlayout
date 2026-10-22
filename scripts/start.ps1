param([switch]$Dev, [switch]$NoCasparCG)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$previousAutostart = [Environment]::GetEnvironmentVariable('OPENPLAYOUT_CASPAR_AUTOSTART', 'Process')
Push-Location $projectRoot
try {
    $backendPython = Join-Path $projectRoot '.venv312\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $backendPython)) {
        $backendPython = Join-Path $projectRoot '.tools\backend-venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $backendPython)) { throw 'Run .\scripts\setup.ps1 first.' }
    if (-not $Dev -and -not (Test-Path -LiteralPath 'apps\web\dist\index.html')) { throw 'Build the frontend first: cd apps\web; npm.cmd run build' }
    if ($NoCasparCG) { $env:OPENPLAYOUT_CASPAR_AUTOSTART = 'false' }
    # Use the backend's settings parser so .env, custom data directories and
    # explicit external-server mode behave identically in the launcher and API.
    $needsBundle = & $backendPython -c "from app.config import Settings; s=Settings(); print('yes' if s.caspar_autostart and not (s.caspar_server_dir / 'casparcg.exe').is_file() else 'no')"
    if ($LASTEXITCODE -ne 0) { throw 'Could not read runtime configuration.' }
    if ($needsBundle -eq 'yes') { & (Join-Path $PSScriptRoot 'install-casparcg.ps1') }
    Write-Host 'OpenPlayout: http://127.0.0.1:8000'
    Write-Host 'After startup, read data/api-token to unlock the interface. Stop with Ctrl+C.'
    if ($Dev) {
        Write-Host 'In another terminal: cd apps\web; npm.cmd run dev'
        & $backendPython -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload --reload-dir backend
    } else {
        & $backendPython -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
    }
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE" }
} finally {
    [Environment]::SetEnvironmentVariable('OPENPLAYOUT_CASPAR_AUTOSTART', $previousAutostart, 'Process')
    Pop-Location
}
