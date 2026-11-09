"""Trends, par accuracy, time breakdown and the unassigned-time inbox."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from taskplanner.core.db import day_bounds
from taskplanner.core.models import Category, TaskStatus
from taskplanner.ui.controller import Controller
from taskplanner.ui.theme import palette
from taskplanner.ui.widgets import (
    BarChart,
    Card,
    HBarList,
    StatTile,
    badge_color,
    fmt_minutes,
    label,
)


class InsightsView(QScrollArea):
    def __init__(self, ctl: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctl = ctl
        self.setWidgetResizable(True)
        root = QWidget()
        self.setWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(24, 20, 24, 24)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(label("Insights", "H1"))
        head.addStretch(1)
        self.range = QComboBox()
        self.range.addItem("Last 14 days", 14)
        self.range.addItem("Last 30 days", 30)
        self.range.addItem("Last 90 days", 90)
        self.range.setCurrentIndex(1)
        self.range.currentIndexChanged.connect(self.refresh)
        head.addWidget(self.range)
        lay.addLayout(head)

        tiles = QHBoxLayout()
        self.t_week = StatTile("This week: earned")
        self.t_week_eff = StatTile("This week: efficiency")
        self.t_best = StatTile("Personal best day")
        self.t_par = StatTile("Par accuracy")
        for t in (self.t_week, self.t_week_eff, self.t_best, self.t_par):
            tiles.addWidget(t)
        lay.addLayout(tiles)

        grid = QGridLayout()
        grid.setSpacing(14)
        c1 = Card("Output earned per day (dashed line = goal)")
        self.earned_chart = BarChart()
        c1.body.addWidget(self.earned_chart)
        c2 = Card("Daily score (line = efficiency × 50)")
        self.score_chart = BarChart()
        c2.body.addWidget(self.score_chart)
        grid.addWidget(c1, 0, 0)
        grid.addWidget(c2, 0, 1)
        c6 = Card("Weekly output, last 8 weeks (dashed = weekly goal, line = commitment delivered)")
        self.week_chart = BarChart()
        c6.body.addWidget(self.week_chart)
        grid.addWidget(c6, 1, 0, 1, 2)
        lay.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(14)
        c3 = Card("Recent finishes vs. par")
        self.finishes = QTableWidget(0, 4)
        self.finishes.setHorizontalHeaderLabels(["Task", "Par", "Actual", "Result"])
        self.finishes.verticalHeader().setVisible(False)
        self.finishes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.finishes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.finishes.setMinimumHeight(240)
        c3.body.addWidget(self.finishes)
        row.addWidget(c3, 1)
        c4 = Card("Today: where the time went")
        self.by_app = HBarList()
        c4.body.addWidget(self.by_app)
        c4.body.addStretch(1)
        row.addWidget(c4, 1)
        lay.addLayout(row)

        self.inbox_card = c5 = Card("Unassigned time today — assign it to the right task")
        c5.body.addWidget(label("Active time that didn't match any task. Assigning it makes "
                                "your efficiency honest and teaches the predictor. Add "
                                "keywords to the task so it matches automatically next time.",
                                "Muted", wrap=True))
        self.inbox = QTableWidget(0, 3)
        self.inbox.setHorizontalHeaderLabels(["App", "Window", "Time"])
        self.inbox.verticalHeader().setVisible(False)
        self.inbox.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.inbox.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.inbox.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.inbox.setMinimumHeight(220)
        c5.body.addWidget(self.inbox)
        arow = QHBoxLayout()
        self.assign_to = QComboBox()
        assign = QPushButton("Assign selected")
        assign.clicked.connect(self.assign)
        arow.addWidget(label("Assign to", "Muted"))
        arow.addWidget(self.assign_to, 1)
        arow.addWidget(assign)
        c5.body.addLayout(arow)
        lay.addWidget(c5)

        ctl.data_changed.connect(self._maybe_refresh)
        self._dirty = True

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()

    def _maybe_refresh(self) -> None:
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        p = palette()
        days = int(self.range.currentData())
        eng = self.ctl.engine
        hist = eng.history_stats(days)
        labels = [date.fromisoformat(d.date).strftime("%d %b") for d in hist]
        self.earned_chart.set_data(labels, [d.earned for d in hist],
                                   reference=self.ctl.settings.daily_goal_minutes,
                                   fmt=lambda v: fmt_minutes(v))
        self.score_chart.set_data(labels, [d.score for d in hist],
                                  line=[min(100, d.efficiency * 50) for d in hist], max_value=100)

        weeks = eng.week_history(8)
        wmax = max([self.ctl.settings.weekly_goal_minutes, *(w.earned for w in weeks)])
        self.week_chart.set_data(
            [date.fromisoformat(w.week).strftime("%d %b") for w in weeks],
            [w.earned for w in weeks],
            line=[w.delivery * wmax for w in weeks], max_value=wmax,
            reference=self.ctl.settings.weekly_goal_minutes, fmt=lambda v: fmt_minutes(v))

        week = hist[-7:]
        prev = hist[-14:-7]
        w_e, w_s = sum(d.earned for d in week), sum(d.spent for d in week)
        p_e, p_s = sum(d.earned for d in prev), sum(d.spent for d in prev)
        delta = w_e - p_e
        self.t_week.set(fmt_minutes(w_e), f"{'+' if delta >= 0 else '−'}{fmt_minutes(abs(delta))} "
                        "vs. previous 7 days")
        w_eff = w_e / w_s if w_s else 0
        p_eff = p_e / p_s if p_s else 0
        self.t_week_eff.set(f"{w_eff:.0%}" if w_s else "—",
                            f"previous 7 days {p_eff:.0%}" if p_s else "earned ÷ spent",
                            p.good if w_eff >= 1 else p.warn if w_s else None)
        all_days = [(d, data) for d, data in eng.all_day_data().items()
                    if data.get("earned", 0) > 0]
        today_stats = hist[-1]
        if today_stats.earned > 0:
            all_days.append((today_stats.date, {"earned": today_stats.earned,
                                                "score": today_stats.score}))
        if all_days:
            best_day, best = max(all_days, key=lambda kv: kv[1].get("earned", 0))
            self.t_best.set(fmt_minutes(best.get("earned", 0)),
                            f"{best_day} · score {best.get('score', 0):.0f}")
        else:
            self.t_best.set("—", "finish your first day")

        done = sorted(self.ctl.db.list_tasks([TaskStatus.DONE]),
                      key=lambda t: t.completed_at or 0, reverse=True)
        verified = [t for t in done if t.badge and t.badge.value != "unverified"]
        if verified:
            ratios = [t.actual_minutes / (t.original_par or t.par_minutes) for t in verified[:20]
                      if (t.original_par or t.par_minutes) > 0]
            avg = sum(ratios) / len(ratios) if ratios else 0
            within = sum(1 for r in ratios if 0.8 <= r <= 1.2)
            self.t_par.set(f"{avg:.0%} of par", f"{within}/{len(ratios)} within ±20% "
                           "(last 20)", p.good if avg <= 1 else p.warn)
        else:
            self.t_par.set("—", "no finished tasks yet")
        self.finishes.setRowCount(min(25, len(done)))
        for r, t in enumerate(done[:25]):
            par = t.original_par or t.par_minutes
            self.finishes.setItem(r, 0, QTableWidgetItem(t.title))
            self.finishes.setItem(r, 1, QTableWidgetItem(fmt_minutes(par)))
            self.finishes.setItem(r, 2, QTableWidgetItem(fmt_minutes(t.actual_minutes)))
            res = QTableWidgetItem(t.badge.label if t.badge else "")
            res.setForeground(QColor(badge_color(t.badge)))
            self.finishes.setItem(r, 3, res)

        self._fill_today()

    def _fill_today(self) -> None:
        p = palette()
        start, end = day_bounds(self.ctl.engine.today())
        rows = self.ctl.db.activity_between(start, end)
        tasks = {t.id: t.title for t in self.ctl.db.list_tasks()}
        per: dict[tuple[str, str], float] = defaultdict(float)
        inbox: dict[tuple[str, str], list] = defaultdict(lambda: [0.0, []])
        for r in rows:
            dur = (min(r["end_ts"], end) - max(r["start_ts"], start)) / 60.0
            cat = r["category"]
            if cat == Category.IDLE.value or dur <= 0:
                continue
            if r["task_id"] is not None:
                key = (f"📌 {tasks.get(r['task_id'], 'task')}", p.good)
            elif cat == Category.DISTRACTING.value:
                key = (f"⚠ {r['process'] or 'unknown'}", p.bad)
            else:
                key = (r["process"] or "unknown", p.muted)
                k = (r["process"], r["title"][:120])
                inbox[k][0] += dur
                inbox[k][1].append(r["id"])
            per[key] += dur
        items = sorted(((name, v, color) for (name, color), v in per.items()),
                       key=lambda x: -x[1])[:12]
        self.by_app.set_items(items)

        entries = sorted(inbox.items(), key=lambda kv: -kv[1][0])
        entries = [e for e in entries if e[1][0] >= 0.5][:100]
        self.inbox.setRowCount(len(entries))
        for r, ((proc, title), (mins, ids)) in enumerate(entries):
            a = QTableWidgetItem(proc)
            a.setData(Qt.ItemDataRole.UserRole, ids)
            self.inbox.setItem(r, 0, a)
            self.inbox.setItem(r, 1, QTableWidgetItem(title))
            self.inbox.setItem(r, 2, QTableWidgetItem(fmt_minutes(mins)))
        current = self.assign_to.currentData()
        self.assign_to.clear()
        for t in self.ctl.db.open_tasks():
            self.assign_to.addItem(t.title, t.id)
        idx = self.assign_to.findData(current)
        if idx >= 0:
            self.assign_to.setCurrentIndex(idx)

    def assign(self) -> None:
        task_id = self.assign_to.currentData()
        if task_id is None:
            return
        ids: list[int] = []
        for idx in self.inbox.selectionModel().selectedRows():
            ids.extend(self.inbox.item(idx.row(), 0).data(Qt.ItemDataRole.UserRole) or [])
        if not ids:
            return
        self.ctl.db.execute(
            f"UPDATE activity SET category = 'productive' WHERE id IN "
            f"({', '.join('?' for _ in ids)})", ids)
        self.ctl.db.reassign_activity(ids, task_id)
        t = self.ctl.db.get_task(task_id)
        if t and not t.is_started:
            self.ctl.engine.start_task(t)
        self.ctl.invalidate()
