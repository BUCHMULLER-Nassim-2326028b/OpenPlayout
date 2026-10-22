$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    $backendPython = Join-Path $projectRoot '.venv312\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $backendPython)) { $backendPython = Join-Path $projectRoot '.tools\backend-venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $backendPython)) { throw 'Run scripts/setup.ps1 first.' }
    $testRuns = Join-Path $projectRoot '.tools\test-runs'
    New-Item -ItemType Directory -Path $testRuns -Force | Out-Null
    $testTemp = Join-Path $testRuns ([guid]::NewGuid().ToString('N'))
    & $backendPython -m pytest backend\tests -q --basetemp $testTemp -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed.' }
    Push-Location apps\web
    try {
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
} finally { Pop-Location }
