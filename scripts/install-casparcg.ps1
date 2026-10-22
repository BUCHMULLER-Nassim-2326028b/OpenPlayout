param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$version = '2.5.1'
$expectedHash = 'C0756F53F49908FBA94F17A43B83D45FD275201E24AB1676530D7BB26832EFC6'
$downloadUrl = 'https://github.com/CasparCG/server/releases/download/v2.5.1-stable/casparcg-server-v2.5.1-windows.zip'
$runtimeRoot = Join-Path $projectRoot ".tools\casparcg\$version"
$archive = Join-Path $projectRoot ".tools\downloads\casparcg-server-v$version-windows.zip"
$manifestPath = Join-Path $runtimeRoot 'openplayout-install.json'
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.sha256 -eq $expectedHash -and (Test-Path -LiteralPath (Join-Path $runtimeRoot 'casparcg.exe')) -and (Test-Path -LiteralPath (Join-Path $runtimeRoot 'ffprobe.exe'))) {
        Write-Host "CasparCG $version is already installed locally."
        return
    }
    throw 'The existing runtime has an invalid manifest. Select a clean version directory before reinstalling.'
}
New-Item -ItemType Directory -Path (Split-Path $archive -Parent) -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
    Write-Host "Downloading official CasparCG $version Windows runtime (approximately 296 MB)..."
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archive -UseBasicParsing
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) {
    throw "CasparCG archive checksum mismatch. The archive was not extracted. Remove the failed download and retry: $archive"
}
if (Test-Path -LiteralPath $runtimeRoot) {
    throw "Refusing to overwrite a partial or custom runtime: $runtimeRoot"
}
Write-Host 'Extracting CasparCG and its bundled FFmpeg/FFprobe tools...'
New-Item -ItemType Directory -Path $runtimeRoot | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $runtimeRoot
foreach ($name in @('casparcg.exe', 'ffprobe.exe', 'ffmpeg.exe', 'LICENSE')) {
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeRoot $name))) { throw "Official archive is missing $name" }
}
@{
    version = $version
    url = $downloadUrl
    sha256 = $expectedHash
    source = 'https://github.com/CasparCG/server/tree/v2.5.1-stable'
    installed_at = [DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Host "CasparCG $version installed: $runtimeRoot"
