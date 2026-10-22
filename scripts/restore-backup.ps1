param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [switch]$ConfirmStopped
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $ConfirmStopped) { throw 'Stop OpenPlayout, then pass -ConfirmStopped to restore its database. The existing database will be retained.' }
$backupPath = (Resolve-Path -LiteralPath $Archive).Path
$pythonPath = Join-Path $projectRoot '.tools\backend-venv\Scripts\python.exe'
& $pythonPath (Join-Path $PSScriptRoot 'restore_backup.py') $backupPath --data-dir (Join-Path $projectRoot 'data') --confirm-stopped
if ($LASTEXITCODE -ne 0) { throw 'Backup restoration failed; read the error above.' }
