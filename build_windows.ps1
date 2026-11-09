# Local Windows build: produces dist\TaskPlanner\TaskPlanner.exe and (if Inno Setup is installed)
# dist\TaskPlannerSetup-<version>.exe
$ErrorActionPreference = "Stop"
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\pyinstaller packaging\taskplanner.spec --noconfirm
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    $version = (Select-String -Path taskplanner\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
    & $iscc /DAppVersion=$version packaging\installer.iss
    Write-Host "Installer: dist\TaskPlannerSetup-$version.exe"
} else {
    Write-Host "Inno Setup not found - portable app is in dist\TaskPlanner\ (install Inno Setup 6 for an installer)"
}
