"""Application entry point."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys

from taskplanner import APP_ID, APP_NAME, __version__
from taskplanner.paths import db_path, log_path, resource_path


def setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(log_path(), maxBytes=1_000_000, backupCount=3,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not getattr(sys, "frozen", False):
        root.addHandler(logging.StreamHandler())


def main(argv: list[str] | None = None) -> int:
    # Windowed (console-less) builds have no stdout/stderr; give argparse somewhere to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
    parser = argparse.ArgumentParser(prog="taskplanner", description=APP_NAME)
    parser.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    setup_logging()
    log = logging.getLogger("taskplanner")
    log.info("starting %s %s", APP_NAME, __version__)

    if sys.platform == "win32":
        import ctypes

        try:  # own taskbar identity (not python.exe) and crisp DPI scaling
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.App")
        except (AttributeError, OSError):
            pass

    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    from taskplanner.core.db import Database
    from taskplanner.core.settings import load_settings
    from taskplanner.ui import theme
    from taskplanner.ui.controller import Controller
    from taskplanner.ui.main_window import MainWindow
    from taskplanner.ui.tray import Tray, score_icon

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    # Single instance: if already running, ask it to show itself and exit.
    server_name = f"{APP_ID}-single-instance"
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)

    def excepthook(exc_type, exc, tb):
        log.critical("unhandled exception", exc_info=(exc_type, exc, tb))
        try:
            QMessageBox.critical(None, APP_NAME, f"Unexpected error: {exc}\n\nDetails were "
                                 f"written to {log_path()}")
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = excepthook

    db = Database(db_path())
    settings = load_settings(db)
    app.setStyleSheet(theme.stylesheet(theme.set_theme(settings.theme)))
    icon_file = resource_path("assets/icon.png")
    if icon_file.is_file():
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(str(icon_file)))
    else:
        app.setWindowIcon(score_icon(None))

    ctl = Controller(db, settings)
    window = MainWindow(ctl)
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = Tray(ctl, window)
        window.tray = tray
        tray.show()

    def on_connection():
        sock = server.nextPendingConnection()
        if sock:
            sock.readyRead.connect(lambda: (window.showNormal(), window.raise_(),
                                            window.activateWindow()))

    server.newConnection.connect(on_connection)

    ctl.start()
    if not (args.minimized and window.tray):
        window.show()
    if not settings.onboarded:
        from taskplanner.ui.onboarding import show_onboarding

        show_onboarding(window, ctl)

    def shutdown():
        ctl.stop()
        db.close()
        log.info("stopped")

    app.aboutToQuit.connect(shutdown)
    return app.exec()
