# Build TaskPill for Windows: icon -> PyInstaller folder -> Inno Setup installer.
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# Output: dist\TaskPill\ (the app folder), dist\TaskPill-Setup-<version>.exe and
#         dist\TaskPill-<version>-portable.zip
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$version = & $python -c "import sys; sys.path.insert(0, 'src'); import taskpill; print(taskpill.__version__)"
Write-Host "Building TaskPill $version"

& $python packaging\make_icon.py packaging\taskpill.ico
if ($LASTEXITCODE -ne 0) { throw "icon failed" }

& $python -m PyInstaller --noconfirm --clean --log-level WARN packaging\taskpill.spec --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }

& $iscc /Q "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

# The portable .zip: the same app folder plus portable.txt (which also tells the
# app it's portable, so updates open the download page instead of an installer).
& $python packaging\make_portable.py $version
if ($LASTEXITCODE -ne 0) { throw "portable zip failed" }
$zip = "dist\TaskPill-$version-portable.zip"

Write-Host "Done: dist\TaskPill-Setup-$version.exe and $zip"
