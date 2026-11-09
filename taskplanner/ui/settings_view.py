"""Settings page."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from taskplanner.ai.claude_cli import find_claude
from taskplanner.core.settings import Settings
from taskplanner.paths import data_dir
from taskplanner.ui.controller import Controller
from taskplanner.ui.widgets import label


def _lines(text: str) -> list[str]:
    out = []
    for part in text.replace(",", "\n").splitlines():
        part = part.strip().lower()
        if part:
            out.append(part)
    return out


class SettingsView(QScrollArea):
    def __init__(self, ctl: Controller, on_theme_change=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctl = ctl
        self.on_theme_change = on_theme_change
        self.setWidgetResizable(True)
        root = QWidget()
        self.setWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)
        lay.addWidget(label("Settings", "H1"))
        s = ctl.settings

        goals = QGroupBox("Goals & working hours")
        f = QFormLayout(goals)
        self.goal = QSpinBox()
        self.goal.setRange(30, 960)
        self.goal.setSingleStep(15)
        self.goal.setSuffix(" min earned / day")
        self.goal.setValue(s.daily_goal_minutes)
        self.start = QTimeEdit(QTime.fromString(s.work_start, "HH:mm"))
        self.start.setDisplayFormat("HH:mm")
        self.end = QTimeEdit(QTime.fromString(s.work_end, "HH:mm"))
        self.end.setDisplayFormat("HH:mm")
        self.breaks = QSpinBox()
        self.breaks.setRange(0, 480)
        self.breaks.setSuffix(" min")
        self.breaks.setValue(s.break_minutes)
        f.addRow("Daily output goal", self.goal)
        f.addRow("Work starts", self.start)
        f.addRow("Work ends", self.end)
        f.addRow("Breaks", self.breaks)
        lay.addWidget(goals)

        tr = QGroupBox("Tracking")
        f = QFormLayout(tr)
        self.tracking = QCheckBox("Track active window and idle time")
        self.tracking.setChecked(s.tracking_enabled)
        self.idle = QSpinBox()
        self.idle.setRange(30, 1800)
        self.idle.setSuffix(" s without input = idle")
        self.idle.setValue(s.idle_threshold_seconds)
        self.interval = QSpinBox()
        self.interval.setRange(1, 60)
        self.interval.setSuffix(" s")
        self.interval.setValue(s.sample_interval_seconds)
        self.progress_every = QSpinBox()
        self.progress_every.setRange(15, 3600)
        self.progress_every.setSuffix(" s")
        self.progress_every.setValue(s.progress_check_seconds)
        self.nudge = QSpinBox()
        self.nudge.setRange(1, 60)
        self.nudge.setSuffix(" min of distraction")
        self.nudge.setValue(s.drift_nudge_minutes)
        self.retention = QSpinBox()
        self.retention.setRange(0, 3650)
        self.retention.setSpecialValueText("forever")
        self.retention.setSuffix(" days")
        self.retention.setValue(s.activity_retention_days)
        f.addRow(self.tracking)
        f.addRow("Idle threshold", self.idle)
        f.addRow("Sample every", self.interval)
        f.addRow("Check progress sources every", self.progress_every)
        f.addRow("Nudge after", self.nudge)
        f.addRow("Keep raw window history", self.retention)
        lay.addWidget(tr)

        cats = QGroupBox("App categories (one per line or comma separated)")
        cl = QHBoxLayout(cats)
        self.productive = QPlainTextEdit("\n".join(s.productive_apps))
        self.distracting_apps = QPlainTextEdit("\n".join(s.distracting_apps))
        self.distracting_kw = QPlainTextEdit("\n".join(s.distracting_keywords))
        self.excluded = QPlainTextEdit("\n".join(s.excluded_apps))
        for title, w in (("Productive apps", self.productive),
                         ("Distracting apps", self.distracting_apps),
                         ("Distracting title keywords", self.distracting_kw),
                         ("Never track (private)", self.excluded)):
            col = QVBoxLayout()
            col.addWidget(label(title, "Muted"))
            w.setMinimumHeight(160)
            col.addWidget(w)
            cl.addLayout(col)
        lay.addWidget(cats)

        ai = QGroupBox("AI breakdown (Claude Code CLI)")
        f = QFormLayout(ai)
        self.ai_enabled = QCheckBox("Enable ✨ Break down with Claude")
        self.ai_enabled.setChecked(s.ai_enabled)
        self.claude_path = QLineEdit(s.claude_path)
        self.claude_path.setPlaceholderText("auto-detect `claude` on PATH")
        self.claude_model = QLineEdit(s.claude_model)
        self.claude_model.setPlaceholderText("CLI default (e.g. sonnet, opus)")
        self.ai_timeout = QSpinBox()
        self.ai_timeout.setRange(30, 900)
        self.ai_timeout.setSuffix(" s")
        self.ai_timeout.setValue(s.ai_timeout_seconds)
        self.claude_status = label("", "Muted", wrap=True)
        test = QPushButton("Detect CLI")
        test.clicked.connect(self._detect)
        f.addRow(self.ai_enabled)
        f.addRow("claude executable", self.claude_path)
        f.addRow("Model", self.claude_model)
        f.addRow("Timeout", self.ai_timeout)
        row = QHBoxLayout()
        row.addWidget(test)
        row.addWidget(self.claude_status, 1)
        f.addRow(row)
        f.addRow(label("Runs `claude -p` locally with tools disabled, so it uses the account "
                       "you're logged into (your Claude subscription). Run `claude` once in a "
                       "terminal to log in.", "Muted", wrap=True))
        lay.addWidget(ai)

        app = QGroupBox("App")
        f = QFormLayout(app)
        self.autostart = QCheckBox("Start with Windows (minimised to tray)")
        self.autostart.setChecked(s.start_with_windows)
        self.autostart.setEnabled(sys.platform == "win32")
        self.notifications = QCheckBox("Show notifications (level-ups, badges, drift nudges)")
        self.notifications.setChecked(s.notifications_enabled)
        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.setCurrentIndex(self.theme.findData(s.theme))
        f.addRow(self.autostart)
        f.addRow(self.notifications)
        f.addRow("Theme", self.theme)
        lay.addWidget(app)

        data = QGroupBox("Data")
        dl = QHBoxLayout(data)
        exp_json = QPushButton("Export everything (JSON)")
        exp_json.clicked.connect(self._export_json)
        exp_csv = QPushButton("Export daily scores (CSV)")
        exp_csv.clicked.connect(self._export_csv)
        dl.addWidget(exp_json)
        dl.addWidget(exp_csv)
        dl.addStretch(1)
        dl.addWidget(label(f"Stored locally in {data_dir()}", "Muted"))
        lay.addWidget(data)

        save = QPushButton("Save settings")
        save.setObjectName("Primary")
        save.clicked.connect(self.save)
        brow = QHBoxLayout()
        brow.addStretch(1)
        brow.addWidget(save)
        lay.addLayout(brow)
        lay.addStretch(1)
        self._detect()

    def _detect(self) -> None:
        found = find_claude(self.claude_path.text().strip())
        self.claude_status.setText(f"✓ Found: {found}" if found else
                                   "✗ Not found. Install Claude Code and make sure `claude` is on "
                                   "PATH, or enter its full path.")

    def save(self) -> None:
        s: Settings = self.ctl.settings
        s.daily_goal_minutes = self.goal.value()
        s.work_start = self.start.time().toString("HH:mm")
        s.work_end = self.end.time().toString("HH:mm")
        s.break_minutes = self.breaks.value()
        s.tracking_enabled = self.tracking.isChecked()
        s.idle_threshold_seconds = self.idle.value()
        s.sample_interval_seconds = self.interval.value()
        s.progress_check_seconds = self.progress_every.value()
        s.drift_nudge_minutes = self.nudge.value()
        s.activity_retention_days = self.retention.value()
        s.productive_apps = _lines(self.productive.toPlainText())
        s.distracting_apps = _lines(self.distracting_apps.toPlainText())
        s.distracting_keywords = _lines(self.distracting_kw.toPlainText())
        s.excluded_apps = _lines(self.excluded.toPlainText())
        s.ai_enabled = self.ai_enabled.isChecked()
        s.claude_path = self.claude_path.text().strip()
        s.claude_model = self.claude_model.text().strip()
        s.ai_timeout_seconds = self.ai_timeout.value()
        s.start_with_windows = self.autostart.isChecked()
        s.notifications_enabled = self.notifications.isChecked()
        theme_changed = s.theme != self.theme.currentData()
        s.theme = self.theme.currentData()
        if s.available_minutes <= 0:
            QMessageBox.warning(self, "Working hours", "Working hours minus breaks must be "
                                "more than zero.")
            return
        self.ctl.save_settings()
        if theme_changed and self.on_theme_change:
            self.on_theme_change(s.theme)
        QMessageBox.information(self, "Settings", "Saved.")

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", str(Path.home() / f"taskplanner-{datetime.now():%Y%m%d}.json"),
            "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.ctl.db.export_all(), fh, indent=1, default=str)

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", str(Path.home() / f"taskplanner-days-{datetime.now():%Y%m%d}.csv"),
            "CSV (*.csv)")
        if not path:
            return
        days = sorted(self.ctl.engine.all_day_data().items())
        cols = ["date", "score", "earned", "spent", "efficiency", "distracting", "planned",
                "planned_earned", "plan_completion", "density", "tasks_completed", "qualified"]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for d, data in days:
                w.writerow([d] + [data.get(c, "") for c in cols[1:]])
