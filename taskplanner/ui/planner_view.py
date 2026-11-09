"""Daily planner: pick tasks, see density vs. capacity, commit; evening review."""

from __future__ import annotations

from datetime import date, datetime, timedelta

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

from taskplanner.core import planner
from taskplanner.core.db import day_bounds
from taskplanner.core.models import PRIORITY_LABELS, Task
from taskplanner.ui.controller import Controller
from taskplanner.ui.theme import palette
from taskplanner.ui.widgets import Card, fmt_minutes, label


class PlannerView(QWidget):
    def __init__(self, ctl: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctl = ctl
        self._tasks: dict[int, Task] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        head = QHBoxLayout()
        head.addWidget(label("Plan your day", "H1"))
        head.addStretch(1)
        lay.addLayout(head)
        lay.addWidget(label("Pick what you'll finish today. Par times are packed into your "
                            "available hours. A dense plan you actually deliver earns the "
                            "Plan Bonus and up to 15 score points; unfinished planned work "
                            "costs you.", "Muted", wrap=True))

        body = QHBoxLayout()
        body.setSpacing(14)
        lay.addLayout(body, 1)

        left = Card("Open tasks")
        self.candidates = QListWidget()
        self.candidates.itemChanged.connect(lambda _i: self._update_summary())
        left.body.addWidget(self.candidates, 1)
        lrow = QHBoxLayout()
        auto = QPushButton("⚡ Auto-fill")
        auto.setToolTip("Pack by urgency (overdue, priority, due date) up to your available time")
        auto.clicked.connect(self.autofill)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear)
        lrow.addWidget(auto)
        lrow.addWidget(clear)
        lrow.addStretch(1)
        left.body.addLayout(lrow)
        body.addWidget(left, 3)

        right = QVBoxLayout()
        right.setSpacing(14)
        summary = Card("Plan density")
        arow = QHBoxLayout()
        self.available_label = label("", "Muted")
        self.available_label.setToolTip("Working hours minus breaks. Change them in Settings.")
        arow.addWidget(self.available_label)
        arow.addStretch(1)
        summary.body.addLayout(arow)
        self.density_bar = QProgressBar()
        self.density_bar.setRange(0, 1000)
        self.density_bar.setFixedHeight(14)
        summary.body.addWidget(self.density_bar)
        self.density_label = label("", "H2")
        self.verdict = label("", "Muted", wrap=True)
        summary.body.addWidget(self.density_label)
        summary.body.addWidget(self.verdict)
        self.commit_btn = QPushButton("Commit plan for today")
        self.commit_btn.setObjectName("Primary")
        self.commit_btn.clicked.connect(self.commit)
        summary.body.addWidget(self.commit_btn)
        right.addWidget(summary)

        timeline = Card("Timeline")
        self.timeline = QListWidget()
        timeline.body.addWidget(self.timeline)
        right.addWidget(timeline, 1)

        review = Card("Review: today so far")
        self.review = QListWidget()
        self.review_sum = label("", "Muted", wrap=True)
        review.body.addWidget(self.review_sum)
        review.body.addWidget(self.review)
        right.addWidget(review, 1)
        body.addLayout(right, 4)

        ctl.data_changed.connect(self.refresh)
        self.refresh()

    # ---------------------------------------------------------------- data
    def refresh(self) -> None:
        today = self.ctl.engine.today()
        plan = {r["task_id"]: r for r in self.ctl.db.get_plan(today)}
        checked_before = self._checked_ids() if self.candidates.count() else None
        tasks = self.ctl.db.open_tasks()
        # Tasks planned today that were finished still belong in the plan view.
        for tid in plan:
            if not any(t.id == tid for t in tasks):
                t = self.ctl.db.get_task(tid)
                if t:
                    tasks.append(t)
        self._tasks = {t.id: t for t in tasks}
        self.candidates.blockSignals(True)
        self.candidates.clear()
        for t in sorted(tasks, key=lambda t: planner.urgency_key(t, date.today())):
            due = f" · due {t.due_date}" if t.due_date else ""
            remaining = t.remaining_par if t.remaining_par > 0 else 0
            item = QListWidgetItem(f"{t.title}   —  {fmt_minutes(remaining)} left of par · "
                                   f"{PRIORITY_LABELS.get(t.priority)}{due}")
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            if remaining <= 0:
                item.setText(f"✅ {t.title}   —  finished")
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.candidates.addItem(item)
                continue
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if checked_before is not None:
                state = t.id in checked_before
            else:
                state = t.id in plan
            item.setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
            self.candidates.addItem(item)
        self.candidates.blockSignals(False)
        self._update_summary()
        self._update_review()

    def _checked_ids(self) -> list[int]:
        out = []
        for i in range(self.candidates.count()):
            it = self.candidates.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out

    def _selected_tasks(self) -> list[Task]:
        return [self._tasks[i] for i in self._checked_ids() if i in self._tasks]

    def _available(self) -> float:
        return float(self.ctl.settings.available_minutes)

    def _capacity(self) -> float:
        hist = self.ctl.engine.history_stats(30)[:-1]
        return planner.capacity_from_history(hist, self._available())

    def _update_summary(self) -> None:
        p = palette()
        tasks = self._selected_tasks()
        planned = sum(t.remaining_par for t in tasks)
        available = self._available()
        s = self.ctl.settings
        self.available_label.setText(f"Available today: {fmt_minutes(available)} "
                                     f"({s.work_start}–{s.work_end}, minus "
                                     f"{s.break_minutes} min breaks)")
        a = planner.assess(planned, available, self._capacity())
        self.density_bar.setValue(int(min(1.0, a.density) * 1000))
        color = {"dense": p.good, "light": p.warn, "overloaded": p.bad, "empty": p.muted}[a.verdict]
        self.density_label.setText(f"{a.density:.0%} density · {fmt_minutes(planned)} planned "
                                   f"of {fmt_minutes(available)}")
        self.density_label.setStyleSheet(f"color: {color};")
        self.verdict.setText(a.message + f"\nRealistic capacity from your history: "
                             f"~{fmt_minutes(a.capacity)}.")
        self.timeline.clear()
        start = datetime.combine(date.today(), datetime.strptime(
            self.ctl.settings.work_start, "%H:%M").time()) if ":" in self.ctl.settings.work_start \
            else datetime.now()
        for e in planner.schedule(tasks):
            t0 = start + timedelta(minutes=e.start_minute)
            t1 = t0 + timedelta(minutes=e.minutes)
            self.timeline.addItem(f"{t0:%H:%M} – {t1:%H:%M}   {e.task.title}  "
                                  f"({fmt_minutes(e.minutes)})")
        if not tasks:
            self.timeline.addItem("Tick tasks on the left or use Auto-fill.")

    def _update_review(self) -> None:
        today = self.ctl.engine.today()
        plan = self.ctl.db.get_plan(today)
        self.review.clear()
        stats = self.ctl.engine.today_stats()
        if not plan:
            self.review_sum.setText("No committed plan yet.")
            return
        self.review_sum.setText(
            f"Delivered {fmt_minutes(stats.planned_earned)} of {fmt_minutes(stats.planned)} "
            f"planned ({stats.plan_completion:.0%}) · earned {fmt_minutes(stats.earned)} total "
            f"in {fmt_minutes(stats.spent)} ({stats.efficiency:.0%} efficiency)")
        start, end = day_bounds(today)
        for r in plan:
            t = self.ctl.db.get_task(r["task_id"])
            if t is None:
                continue
            got = self.ctl.db.earned_between(start, end, [t.id])
            mark = "✅" if t.progress >= 1 else "◐" if got > 0 else "○"
            self.review.addItem(f"{mark} {t.title}: {fmt_minutes(got)} / "
                                f"{fmt_minutes(r['planned_minutes'])} delivered")

    # ------------------------------------------------------------- actions
    def autofill(self) -> None:
        open_tasks = [t for t in self._tasks.values() if t.remaining_par > 0]
        chosen = {t.id for t in planner.suggest_plan(open_tasks, self._available(),
                                                     date.today())}
        self.candidates.blockSignals(True)
        for i in range(self.candidates.count()):
            it = self.candidates.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in chosen
                             else Qt.CheckState.Unchecked)
        self.candidates.blockSignals(False)
        self._update_summary()

    def clear(self) -> None:
        self.candidates.blockSignals(True)
        for i in range(self.candidates.count()):
            self.candidates.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.candidates.blockSignals(False)
        self._update_summary()

    def commit(self) -> None:
        tasks = [t for t in self._selected_tasks() if t.remaining_par > 0]
        today = self.ctl.engine.today()
        existing = self.ctl.db.get_plan(today)
        if existing and QMessageBox.question(
                self, "Replace plan",
                "Replace today's committed plan? Only output earned after re-committing "
                "counts as delivered.") != QMessageBox.StandardButton.Yes:
            return
        self.ctl.engine.commit_plan(today, tasks)
        self.ctl.invalidate()
        if tasks and self.ctl.pinned_task_id is None:
            self.ctl.set_pinned(tasks[0].id)
