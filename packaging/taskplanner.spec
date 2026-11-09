# PyInstaller spec - build with:  pyinstaller packaging/taskplanner.spec --noconfirm
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "packaging", "launcher.pyw")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "assets", "icon.png"), "assets"),
           (os.path.join(ROOT, "assets", "icon.ico"), "assets")],
    hiddenimports=["PySide6.QtNetwork"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia",
              "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TaskPlanner",
    console=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TaskPlanner")
