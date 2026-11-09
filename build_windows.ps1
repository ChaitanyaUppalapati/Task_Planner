# Local Windows build: produces dist\TaskPlanner\TaskPlanner.exe and (if Inno Setup is installed)
# dist\TaskPlannerSetup-<version>.exe
$ErrorActionPreference = "Stop"
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
# Compile a unique PyInstaller bootloader (needs Visual Studio Build Tools); the shared
# prebuilt one is a frequent antivirus false positive. Falls back to the prebuilt one.
$env:PYINSTALLER_COMPILE_BOOTLOADER = "1"
.\.venv\Scripts\pip install --force-reinstall --no-deps --no-binary pyinstaller pyinstaller==6.22.2
if ($LASTEXITCODE -ne 0) { .\.venv\Scripts\pip install --force-reinstall --no-deps pyinstaller==6.22.2 }
.\.venv\Scripts\pyinstaller packaging\taskplanner.spec --noconfirm
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    $version = (Select-String -Path taskplanner\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
    & $iscc /DAppVersion=$version packaging\installer.iss
    Write-Host "Installer: dist\TaskPlannerSetup-$version.exe"
} else {
    Write-Host "Inno Setup not found - portable app is in dist\TaskPlanner\ (install Inno Setup 6 for an installer)"
}
