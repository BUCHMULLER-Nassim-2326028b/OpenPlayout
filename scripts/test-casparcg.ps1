# Requires OpenPlayout/CasparCG to be running. Shows synthetic clips on layer 9900.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
$savedVariables = @{}
foreach ($name in @('OPENPLAYOUT_TEST_CASPAR', 'OPENPLAYOUT_TEST_PLAYBACK', 'OPENPLAYOUT_TEST_CLIP_A', 'OPENPLAYOUT_TEST_CLIP_B')) {
    $savedVariables[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $backendPython = Join-Path $projectRoot '.venv312\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $backendPython)) { $backendPython = Join-Path $projectRoot '.tools\backend-venv\Scripts\python.exe' }
    $encoder = Join-Path $projectRoot '.tools\casparcg\2.5.1\ffmpeg.exe'
    $sampleRoot = Join-Path $projectRoot ('.tools\casparcg-test-media\' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $sampleRoot -Force | Out-Null
    $first = Join-Path $sampleRoot 'test-red.mp4'
    $second = Join-Path $sampleRoot 'test-blue.mp4'
    & $encoder -v error -nostdin -n -f lavfi -i 'color=c=red:s=320x180:r=25' -t 3 -c:v mpeg4 $first
    if ($LASTEXITCODE -ne 0) { throw 'Could not generate the red synthetic sample.' }
    & $encoder -v error -nostdin -n -f lavfi -i 'color=c=blue:s=320x180:r=25' -t 3 -c:v mpeg4 $second
    if ($LASTEXITCODE -ne 0) { throw 'Could not generate the blue synthetic sample.' }
    $env:OPENPLAYOUT_TEST_CASPAR = '1'
    $env:OPENPLAYOUT_TEST_PLAYBACK = '1'
    $env:OPENPLAYOUT_TEST_CLIP_A = $first
    $env:OPENPLAYOUT_TEST_CLIP_B = $second
    & $backendPython -m pytest backend\tests\test_caspar_integration.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Live CasparCG integration test failed.' }
} finally {
    foreach ($entry in $savedVariables.GetEnumerator()) { [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process') }
    Pop-Location
}
