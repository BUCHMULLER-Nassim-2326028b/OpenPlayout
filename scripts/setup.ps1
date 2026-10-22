param([string]$Python = "", [switch]$SkipWeb, [switch]$SkipCasparCG)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not $Python) {
        $projectPython = Join-Path $projectRoot '.tools\python'
        if (Test-Path -LiteralPath $projectPython) {
            $found = Get-ChildItem -LiteralPath $projectPython -Filter python.exe -Recurse | Select-Object -First 1
            if ($found) { $Python = $found.FullName }
        }
        if (-not $Python) { $Python = 'python' }
    }
    & $Python -c "import sys; assert sys.version_info >= (3, 12), 'Python 3.12+ is required. Pass -Python with the executable path'"
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12+ or pass its path with -Python.' }
    & $Python -m venv .venv312
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    & .\.venv312\Scripts\python.exe -m pip install -e 'backend[test]'
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    if (-not $SkipCasparCG) { & (Join-Path $PSScriptRoot 'install-casparcg.ps1') }
    if (-not $SkipWeb) {
        Push-Location apps\web
        try {
            npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
            npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        } finally { Pop-Location }
    }
    Write-Host 'Setup complete. Run .\scripts\start.ps1'
    Write-Host 'CasparCG and bundled FFprobe start locally with OpenPlayout; see README.md.'
} finally { Pop-Location }
