"""'Update available' dialog: release notes, download with progress, install."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from taskplanner import __version__, updater
from taskplanner.core.settings import save_settings
from taskplanner.ui.controller import Controller
from taskplanner.ui.widgets import label

log = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    def __init__(self, ctl: Controller, info: updater.ReleaseInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctl = ctl
        self.info = info
        self.setWindowTitle("Update available")
        self.setMinimumSize(520, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.addWidget(label(f"Task Planner {info.version} is available", "H1"))
        lay.addWidget(label(f"You have {__version__}. Your tasks, history and XP are kept.",
                            "Muted"))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.notes or "No release notes.")
        lay.addWidget(notes, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        self.status = label("", "Muted", wrap=True)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.skip = QPushButton("Skip this version")
        self.skip.clicked.connect(self._skip)
        self.later = QPushButton("Later")
        self.later.clicked.connect(self.reject)
        self.install = QPushButton("Update now")
        self.install.setObjectName("Primary")
        self.install.setDefault(True)
        self.install.clicked.connect(self._start)
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.later)
        row.addWidget(self.install)
        lay.addLayout(row)
        ctl.download_progress.connect(self._on_progress)

    def _skip(self) -> None:
        self.ctl.settings.skipped_version = self.info.version
        save_settings(self.ctl.db, self.ctl.settings)
        self.reject()

    def _start(self) -> None:
        for b in (self.install, self.later, self.skip):
            b.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText("Downloading…")
        self.ctl.download_update(self.info, self._downloaded, self._failed)

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setValue(int(1000 * done / total))
            self.status.setText(f"Downloading… {done / 1e6:.1f} of {total / 1e6:.1f} MB")
        else:
            self.progress.setRange(0, 0)

    def _failed(self, message: str) -> None:
        log.warning("update download failed: %s", message)
        self.progress.setVisible(False)
        self.status.setText("")
        for b in (self.install, self.later, self.skip):
            b.setEnabled(True)
        QMessageBox.warning(self, "Update failed", message)

    def _downloaded(self, path) -> None:
        self.status.setText("Verified. Installing — Task Planner will restart in a moment…")
        QApplication.processEvents()
        try:
            updater.launch_installer(path)
        except updater.UpdateError as e:
            self._failed(f"{e}\n\nThe installer was downloaded to:\n{path}")
            return
        log.info("launched installer %s; quitting for update", path)
        win = self.parent()
        if win is not None:
            win.really_quit = True  # type: ignore[attr-defined]
        QApplication.quit()

    def done(self, r: int) -> None:
        try:
            self.ctl.download_progress.disconnect(self._on_progress)
        except (RuntimeError, TypeError):
            pass
        super().done(r)


def connect_updates(window, ctl: Controller, tray=None) -> None:
    """Show the dialog when an update is found; report manual check results."""

    def available(info, manual: bool) -> None:
        if getattr(window, "_update_dialog_open", False):
            return
        if not manual and tray is not None and not window.isVisible():
            tray.show_notification("Update available",
                                   f"Task Planner {info.version} is ready. Open the app to "
                                   "update.")
            window._pending_update = info
            return
        window._update_dialog_open = True
        try:
            UpdateDialog(ctl, info, window).exec()
        finally:
            window._update_dialog_open = False

    def none(manual: bool) -> None:
        if manual:
            QMessageBox.information(window, "Up to date",
                                    f"You have the latest version ({__version__}).")

    def failed(message: str, manual: bool) -> None:
        if manual:
            QMessageBox.warning(window, "Update check failed", message)

    ctl.update_available.connect(available)
    ctl.update_none.connect(none)
    ctl.update_failed.connect(failed)
