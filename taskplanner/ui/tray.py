"""System tray icon with live score and quick actions."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from taskplanner import APP_NAME
from taskplanner.core.models import SourceType
from taskplanner.ui.controller import Controller
from taskplanner.ui.widgets import fmt_signed_minutes


def score_icon(score: float | None, paused: bool = False) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    if paused:
        color = QColor("#8b91a1")
    elif score is None:
        color = QColor("#7c5cff")
    elif score >= 75:
        color = QColor("#2ecc71")
    elif score >= 50:
        color = QColor("#22c3ee")
    elif score >= 25:
        color = QColor("#f5a623")
    else:
        color = QColor("#ff5c6c")
    qp.setBrush(color)
    qp.setPen(Qt.PenStyle.NoPen)
    qp.drawRoundedRect(QRectF(2, 2, 60, 60), 14, 14)
    qp.setPen(QColor("white"))
    f = QFont("Segoe UI")
    f.setBold(True)
    f.setPixelSize(34 if score is not None and score < 100 else 26)
    qp.setFont(f)
    text = "II" if paused else ("TP" if score is None else f"{score:.0f}")
    qp.drawText(QRectF(0, 0, 64, 64), Qt.AlignmentFlag.AlignCenter, text)
    qp.end()
    return QIcon(pm)


class Tray(QSystemTrayIcon):
    def __init__(self, ctl: Controller, window: QWidget):
        super().__init__(score_icon(None), window)
        self.ctl = ctl
        self.window = window
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        ctl.data_changed.connect(self.refresh)
        ctl.tracking_state.connect(lambda _e: self.refresh())
        ctl.notify.connect(self.show_notification)
        self.refresh()

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def show_notification(self, title: str, message: str) -> None:
        if self.ctl.settings.notifications_enabled and self.supportsMessages():
            self.showMessage(title, message, self.icon(), 6000)

    def refresh(self) -> None:
        stats = self.ctl.engine.today_stats()
        paused = not self.ctl.settings.tracking_enabled
        self.setIcon(score_icon(stats.score, paused))
        pinned = self.ctl.pinned_task()
        tip = f"{APP_NAME} — score {stats.score:.0f} · earned {stats.earned:.0f} min · " \
              f"{stats.efficiency:.0%} efficiency"
        if pinned:
            pace = pinned.earned_minutes - self.ctl.engine.refresh_actual(pinned)
            tip += f"\n{pinned.title}: {pinned.progress:.0%} · {fmt_signed_minutes(pace)} vs par"
        self.setToolTip(tip)

        self.menu.clear()
        self.menu.addAction("Open Task Planner", self.show_window)
        self.menu.addSeparator()
        work = self.menu.addMenu("Work on…")
        none = work.addAction("— Nothing pinned —")
        none.triggered.connect(lambda: self.ctl.set_pinned(None))
        for t in self.ctl.open_tasks()[:15]:
            a = QAction(("● " if t.id == self.ctl.pinned_task_id else "") + t.title, work)
            a.triggered.connect(lambda _=False, tid=t.id: self.ctl.set_pinned(tid))
            work.addAction(a)
        if pinned:
            ms = self.menu.addMenu(f"Tick milestone ({pinned.title[:24]})")
            any_manual = False
            for m in pinned.milestones:
                if m.progress < 1 and m.source_type == SourceType.MANUAL:
                    any_manual = True
                    a = QAction(f"✓ {m.title}", ms)
                    a.triggered.connect(lambda _=False, mid=m.id: self._tick(mid))
                    ms.addAction(a)
            if not any_manual:
                ms.addAction("(auto-tracked milestones only)").setEnabled(False)
        self.menu.addSeparator()
        toggle = self.menu.addAction("Resume tracking" if paused else "Pause tracking")
        toggle.triggered.connect(lambda: self.ctl.set_tracking(paused))
        self.menu.addSeparator()
        self.menu.addAction("Quit", self._quit)

    def _tick(self, milestone_id: int) -> None:
        pinned = self.ctl.pinned_task()
        if pinned is None:
            return
        task = self.ctl.db.get_task(pinned.id)
        m = next((x for x in task.milestones if x.id == milestone_id), None)
        if m:
            self.ctl.engine.set_milestone_progress(task, m, 1.0, "manual")
            self.ctl.invalidate()

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        self.window.really_quit = True  # type: ignore[attr-defined]
        QApplication.quit()
