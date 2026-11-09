"""Weekly targets: commit this week's tasks against the weekly output goal."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from taskplanner.core import planner, weekly
from taskplanner.core.models import PRIORITY_LABELS, Task
from taskplanner.ui.controller import Controller
from taskplanner.ui.theme import palette
from taskplanner.ui.widgets import Card, ComponentBar, fmt_minutes, label


def _bar() -> QProgressBar:
    b = QProgressBar()
    b.setRange(0, 1000)
    b.setFixedHeight(12)
    return b


class WeekPlannerView(QWidget):
    def __init__(self, ctl: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctl = ctl
        self._tasks: dict[int, Task] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.addWidget(label("Plan your week", "H1"))
        self.header = label("", "H2")
        lay.addWidget(self.header)
        lay.addWidget(label("Commit the tasks you'll finish this week. Delivering 90%+ of the "
                            "commitment earns the weekly bonus (¼ XP per committed minute); "
                            "only output earned after committing counts.", "Muted", wrap=True))
        body = QHBoxLayout()
        body.setSpacing(14)
        lay.addLayout(body, 1)

        left = Card("Open tasks")
        self.candidates = QListWidget()
        self.candidates.itemChanged.connect(lambda _i: self._update_summary())
        left.body.addWidget(self.candidates, 1)
        row = QHBoxLayout()
        auto = QPushButton("⚡ Auto-fill to weekly goal")
        auto.clicked.connect(self.autofill)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        row.addWidget(auto)
        row.addWidget(clear)
        row.addStretch(1)
        left.body.addLayout(row)
        body.addWidget(left, 3)

        right = QVBoxLayout()
        right.setSpacing(14)
        target = Card("Weekly target")
        target.body.addWidget(label("Output", "Muted"))
        self.output_bar = _bar()
        target.body.addWidget(self.output_bar)
        self.output_label = label("", "H2")
        self.pace_label = label("", "Muted", wrap=True)
        target.body.addWidget(self.output_label)
        target.body.addWidget(self.pace_label)
        target.body.addSpacing(6)
        target.body.addWidget(label("Commitment delivered", "Muted"))
        self.delivery_bar = _bar()
        target.body.addWidget(self.delivery_bar)
        self.delivery_label = label("", "H2")
        target.body.addWidget(self.delivery_label)
        target.body.addSpacing(6)
        self.c_output = ComponentBar("Output", weekly.W_OUTPUT)
        self.c_delivery = ComponentBar("Delivery", weekly.W_DELIVERY)
        self.c_eff = ComponentBar("Efficiency", weekly.W_EFFICIENCY)
        for c in (self.c_output, self.c_delivery, self.c_eff):
            target.body.addWidget(c)
        self.score_label = label("", "H2")
        target.body.addWidget(self.score_label)
        right.addWidget(target)

        commit = Card("New commitment")
        self.selection_label = label("", "H2")
        self.selection_hint = label("", "Muted", wrap=True)
        self.commit_btn = QPushButton("Commit tasks for this week")
        self.commit_btn.setObjectName("Primary")
        self.commit_btn.clicked.connect(self.commit)
        commit.body.addWidget(self.selection_label)
        commit.body.addWidget(self.selection_hint)
        commit.body.addWidget(self.commit_btn)
        right.addWidget(commit)
        right.addStretch(1)
        body.addLayout(right, 4)

        ctl.data_changed.connect(self._maybe_refresh)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()

    def _maybe_refresh(self) -> None:
        if self.isVisible():
            self.refresh()

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        eng = self.ctl.engine
        week = eng.this_week()
        committed = {r["task_id"]: r for r in self.ctl.db.get_week_plan(week)}
        checked_before = self._checked_ids() if self.candidates.count() else None
        tasks = self.ctl.db.open_tasks()
        for tid in committed:
            if not any(t.id == tid for t in tasks):
                t = self.ctl.db.get_task(tid)
                if t:
                    tasks.append(t)
        self._tasks = {t.id: t for t in tasks}
        self.candidates.blockSignals(True)
        self.candidates.clear()
        for t in sorted(tasks, key=lambda t: planner.urgency_key(t, date.today())):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            if t.remaining_par <= 0:
                item.setText(f"✅ {t.title}   —  finished")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            else:
                due = f" · due {t.due_date}" if t.due_date else ""
                item.setText(f"{t.title}   —  {fmt_minutes(t.remaining_par)} left · "
                             f"{PRIORITY_LABELS.get(t.priority)}{due}")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                state = (t.id in checked_before) if checked_before is not None \
                    else (t.id in committed)
                item.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
            self.candidates.addItem(item)
        self.candidates.blockSignals(False)
        self._update_progress()
        self._update_summary()

    def _checked_ids(self) -> list[int]:
        out = []
        for i in range(self.candidates.count()):
            it = self.candidates.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable \
                    and it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out

    def _update_progress(self) -> None:
        p = palette()
        s = self.ctl.engine.week_stats()
        self.header.setText(f"This week · {weekly.week_label(s.week)} · "
                            f"workday {s.days_elapsed} of {s.work_days}")
        self.output_bar.setValue(int(min(1.0, s.earned / max(1.0, s.goal)) * 1000))
        self.output_label.setText(f"{fmt_minutes(s.earned)} of {fmt_minutes(s.goal)} earned")
        ahead = s.pace >= 0
        self.pace_label.setText(
            f"{'▲ Ahead of' if ahead else '▼ Behind'} weekly pace by "
            f"{fmt_minutes(abs(s.pace))} (on track = {fmt_minutes(s.expected_now)} by end of "
            f"today) · {s.efficiency:.0%} efficiency")
        self.pace_label.setStyleSheet(f"color: {p.good if ahead else p.bad};")
        if s.planned > 0:
            self.delivery_bar.setValue(int(s.delivery * 1000))
            self.delivery_label.setText(
                f"{s.tasks_done}/{s.tasks_planned} tasks · {fmt_minutes(s.planned_earned)} of "
                f"{fmt_minutes(s.planned)} ({s.delivery:.0%})")
        else:
            self.delivery_bar.setValue(0)
            self.delivery_label.setText("No weekly commitment yet")
        self.c_output.set(s.output_score)
        self.c_delivery.set(s.delivery_score)
        self.c_eff.set(s.efficiency_score)
        bonus = weekly.week_bonus(s)
        self.score_label.setText(f"Weekly score {s.score:.0f}"
                                 + (f" · bonus +{bonus} XP unlocked" if bonus else ""))

    def _update_summary(self) -> None:
        p = palette()
        selected = [self._tasks[i] for i in self._checked_ids() if i in self._tasks]
        planned = sum(t.remaining_par for t in selected)
        s = self.ctl.engine.week_stats()
        remaining_goal = max(0.0, s.goal - s.earned)
        days_left = max(1, s.work_days - s.days_elapsed + 1)
        capacity = self.ctl.settings.available_minutes * days_left
        self.selection_label.setText(f"{len(selected)} tasks · {fmt_minutes(planned)} of par")
        if not selected:
            hint, color = "Pick the tasks you'll finish this week.", p.muted
        elif planned > capacity * 1.05:
            hint, color = (f"More than the {fmt_minutes(capacity)} of working time left this "
                           "week. Unfinished commitments lower your weekly score."), p.bad
        elif planned < remaining_goal * 0.8:
            hint, color = (f"Covers {planned / max(1, remaining_goal):.0%} of the "
                           f"{fmt_minutes(remaining_goal)} still needed for the weekly goal. "
                           "Commit more to aim for the full target."), p.warn
        else:
            hint, color = (f"Covers the remaining weekly goal "
                           f"({fmt_minutes(remaining_goal)}). Deliver 90%+ for the bonus."), p.good
        self.selection_hint.setText(hint)
        self.selection_hint.setStyleSheet(f"color: {color};")

    # ------------------------------------------------------------- actions
    def autofill(self) -> None:
        s = self.ctl.engine.week_stats()
        budget = max(0.0, s.goal - s.earned)
        open_tasks = [t for t in self._tasks.values() if t.remaining_par > 0]
        chosen = {t.id for t in planner.suggest_plan(open_tasks, budget, date.today())}
        self._set_checked(chosen)

    def clear(self) -> None:
        self._set_checked(set())

    def _set_checked(self, ids: set[int]) -> None:
        self.candidates.blockSignals(True)
        for i in range(self.candidates.count()):
            it = self.candidates.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole)
                                 in ids else Qt.CheckState.Unchecked)
        self.candidates.blockSignals(False)
        self._update_summary()

    def commit(self) -> None:
        selected = [self._tasks[i] for i in self._checked_ids() if i in self._tasks]
        if not selected:
            QMessageBox.information(self, "Weekly plan", "Tick at least one task.")
            return
        if self.ctl.db.get_week_plan(self.ctl.engine.this_week()) and QMessageBox.question(
                self, "Replace weekly commitment",
                "Replace this week's commitment? Only output earned after re-committing "
                "counts as delivered.") != QMessageBox.StandardButton.Yes:
            return
        self.ctl.engine.commit_week_plan(selected)
        self.ctl.invalidate()
