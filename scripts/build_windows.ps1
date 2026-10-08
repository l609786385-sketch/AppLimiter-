param([switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
if ($env:OS -ne 'Windows_NT') { throw 'This build script requires Windows 10/11.' }
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 (64-bit) from python.org first.' }
}
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not $SkipInstall) {
    & $PythonExe -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
# Always perform fresh Windows tests; never rely on a stale success stamp.
& $PythonExe scripts\verify_windows.py
if ($LASTEXITCODE -ne 0) { throw 'Native Windows tests failed or were skipped. EXE build aborted.' }
& $PythonExe -m PyInstaller --noconfirm --clean AppLimiter.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
# Exercise the frozen worker using an isolated DB and a disposable test EXE.
& $PythonExe scripts\verify_windows.py --exe dist\AppLimiter\AppLimiter.exe
if ($LASTEXITCODE -ne 0) { throw 'Packaged EXE verification failed. Do not distribute this build.' }
Copy-Item 'README.md' 'dist\AppLimiter\README.md'
Copy-Item '.windows-package-verification.json' 'dist\AppLimiter\Windows-verification.json'
$ReleaseZip = Join-Path $ProjectRoot 'dist\AppLimiter-Windows-x64.zip'
if (Test-Path $ReleaseZip) { Remove-Item $ReleaseZip }
Compress-Archive -Path 'dist\AppLimiter' -DestinationPath $ReleaseZip
Write-Host "Verified Windows artifact: $ReleaseZip"
Write-Host 'Complete the manual Windows checklist in README before releasing to other users.'
