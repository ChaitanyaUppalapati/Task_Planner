# Third-party notices

Task Planner is proprietary software (see `LICENSE`). It bundles the following
third-party components, which remain under their own licenses.

| Component | License | Source |
|---|---|---|
| Qt for Python (PySide6 / Shiboken6) | GNU LGPL v3 | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| Qt 6 libraries | GNU LGPL v3 | https://code.qt.io/ |
| Python runtime | Python Software Foundation License | https://www.python.org/ |
| PyInstaller bootloader | GPL v2 with bootloader exception | https://github.com/pyinstaller/pyinstaller |

## LGPL notice for Qt / PySide6
The Qt and PySide6 libraries are dynamically linked and shipped as separate files
inside the installation folder (`_internal\PySide6\`). You may replace them with
your own compatible build of the same libraries. The full LGPL v3 text is at
https://www.gnu.org/licenses/lgpl-3.0.html, and the corresponding source code is
available from the links above.

The Claude Code CLI is not bundled; the app runs the copy you installed yourself,
under Anthropic's own terms.
