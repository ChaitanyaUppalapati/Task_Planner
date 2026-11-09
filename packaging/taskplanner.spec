# PyInstaller spec - build with:  pyinstaller packaging/taskplanner.spec --noconfirm
import os

import re

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Embed Windows file metadata (publisher, product, copyright). Executables with no
# version resource look more suspicious to antivirus heuristics.
with open(os.path.join(ROOT, "taskplanner", "__init__.py"), encoding="utf-8") as fh:
    _src = fh.read()
VERSION = re.search(r'__version__ = "([^"]+)"', _src).group(1)
_nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])

from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
    VSVersionInfo,
)

VERSION_INFO = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_nums, prodvers=_nums, mask=0x3F, flags=0x0, OS=0x40004,
                      fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Chaitanya Uppalapati"),
            StringStruct("FileDescription", "Task Planner - productivity tracker"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "TaskPlanner"),
            StringStruct("LegalCopyright", "Copyright (c) 2026 Chaitanya Uppalapati. All rights reserved."),
            StringStruct("OriginalFilename", "TaskPlanner.exe"),
            StringStruct("ProductName", "Task Planner"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

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
    version=VERSION_INFO,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TaskPlanner")
