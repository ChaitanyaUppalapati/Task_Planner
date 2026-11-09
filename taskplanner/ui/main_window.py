"""Main window with sidebar navigation."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from taskplanner import APP_NAME, __version__
from taskplanner.ui import theme
from taskplanner.ui.achievements_view import AchievementsView
from taskplanner.ui.controller import Controller
from taskplanner.ui.dashboard import Dashboard
from taskplanner.ui.insights_view import InsightsView
from taskplanner.ui.planner_view import PlannerView
from taskplanner.ui.settings_view import SettingsView
from taskplanner.ui.tasks_view import TasksView
from taskplanner.ui.week_view import WeekPlannerView
from taskplanner.ui.widgets import label

PAGES = ["🏠  Dashboard", "✅  Tasks", "🗓️  Planner", "📊  Insights", "🏆  Achievements",
         "⚙️  Settings"]


class MainWindow(QMainWindow):
    def __init__(self, ctl: Controller):
        super().__init__()
        self.ctl = ctl
        self.really_quit = False
        self.tray = None
        self._tray_hint_shown = False
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 860)
        self.setMinimumSize(QSize(1000, 680))

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(210)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 12)
        sl.addWidget(label("⚡ Task Planner", "AppTitle"))
        self.nav = QListWidget()
        self.nav.addItems(PAGES)
        sl.addWidget(self.nav, 1)
        self.side_level = label("", "Muted", wrap=True)
        self.side_level.setContentsMargins(16, 0, 16, 0)
        sl.addWidget(self.side_level)
        ver = label(f"v{__version__}", "Muted")
        ver.setContentsMargins(16, 4, 16, 0)
        sl.addWidget(ver)
        root.addWidget(side)

        self.stack = QStackedWidget()
        self.dashboard = Dashboard(ctl)
        self.tasks = TasksView(ctl)
        self.planner = QTabWidget()
        self.day_planner = PlannerView(ctl)
        self.week_planner = WeekPlannerView(ctl)
        self.planner.addTab(self.day_planner, "Today")
        self.planner.addTab(self.week_planner, "This week")
        self.insights = InsightsView(ctl)
        self.achievements = AchievementsView(ctl)
        self.settings_page = SettingsView(ctl, on_theme_change=self.apply_theme)
        for w in (self.dashboard, self.tasks, self.planner, self.insights, self.achievements,
                  self.settings_page):
            self.stack.addWidget(w)
        root.addWidget(self.stack, 1)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        ctl.data_changed.connect(self._refresh_side)
        self._refresh_side()

    def apply_theme(self, name: str) -> None:
        p = theme.set_theme(name)
        QApplication.instance().setStyleSheet(theme.stylesheet(p))
        for w in self.findChildren(QWidget):
            w.update()
        self.ctl.data_changed.emit()

    def _refresh_side(self) -> None:
        info = self.ctl.engine.level()
        streak = self.ctl.engine.streak().current
        self.side_level.setText(f"Lv {info.level} {info.title}\n{info.xp:,} XP · 🔥 {streak}")

    def go(self, page: int) -> None:
        self.nav.setCurrentRow(page)

    def closeEvent(self, event) -> None:
        if self.really_quit or self.tray is None or not self.tray.isVisible():
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray.showMessage(APP_NAME, "Still tracking in the tray. Right-click the icon "
                                  "to quit.", self.tray.icon(), 4000)

    def keyPressEvent(self, e) -> None:
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and e.key() == Qt.Key.Key_N:
            self.go(1)
            self.tasks.new_task()
            return
        super().keyPressEvent(e)

    def confirm_quit(self) -> bool:
        return QMessageBox.question(self, "Quit", "Quit and stop tracking?") \
            == QMessageBox.StandardButton.Yes
