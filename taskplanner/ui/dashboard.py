"""Dashboard: today's score, level, streak, current task pace and plan."""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from taskplanner.core import gamification, scoring
from taskplanner.core.models import Category, SourceType
from taskplanner.ui.controller import Controller
from taskplanner.ui.theme import palette
from taskplanner.ui.widgets import (
    Card,
    ComponentBar,
    ScoreRing,
    StatTile,
    fmt_minutes,
    fmt_signed_minutes,
    label,
)


class Dashboard(QScrollArea):
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
        self.greeting = label("", "H1")
        self.status_pill = label("", "Pill")
        head.addWidget(self.greeting)
        head.addStretch(1)
        head.addWidget(self.status_pill)
        lay.addLayout(head)

        top = QGridLayout()
        top.setSpacing(14)
        lay.addLayout(top)

        # Score card
        score_card = Card("Today's productivity score")
        row = QHBoxLayout()
        self.ring = ScoreRing(150)
        row.addWidget(self.ring)
        comps = QVBoxLayout()
        self.c_throughput = ComponentBar("Throughput", scoring.W_THROUGHPUT)
        self.c_eff = ComponentBar("Efficiency", scoring.W_EFFICIENCY)
        self.c_plan = ComponentBar("Plan", scoring.W_PLAN)
        self.c_focus = ComponentBar("Focus", scoring.W_FOCUS)
        for c in (self.c_throughput, self.c_eff, self.c_plan, self.c_focus):
            comps.addWidget(c)
        self.score_hint = label("", "Muted", wrap=True)
        comps.addWidget(self.score_hint)
        row.addLayout(comps, 1)
        score_card.body.addLayout(row)
        score_card.body.addStretch(1)
        top.addWidget(score_card, 0, 0)

        # Level card
        lvl_card = Card()
        self.level_title = label("", "H2")
        self.level_sub = label("", "Muted")
        self.xp_bar = QProgressBar()
        self.xp_bar.setRange(0, 1000)
        self.xp_bar.setFixedHeight(12)
        self.streak = label("", "Big")
        self.streak_sub = label("", "Muted", wrap=True)
        lvl_card.body.addWidget(self.level_title)
        lvl_card.body.addWidget(self.xp_bar)
        lvl_card.body.addWidget(self.level_sub)
        lvl_card.body.addSpacing(6)
        lvl_card.body.addWidget(self.streak)
        lvl_card.body.addWidget(self.streak_sub)
        lvl_card.body.addStretch(1)
        top.addWidget(lvl_card, 0, 1)

        # Current task card
        cur = Card("Working on")
        self.pin_combo = QComboBox()
        self.pin_combo.setToolTip("Pin the task you're working on. Unmatched, non-distracting "
                                  "activity is credited to it.")
        self.pin_combo.activated.connect(self._pin_changed)
        cur.body.addWidget(self.pin_combo)
        self.cur_progress = QProgressBar()
        self.cur_progress.setRange(0, 1000)
        self.cur_progress.setFixedHeight(12)
        cur.body.addWidget(self.cur_progress)
        self.cur_detail = label("", "Muted", wrap=True)
        self.pace = label("", "H2")
        cur.body.addWidget(self.cur_detail)
        cur.body.addWidget(self.pace)
        self.milestone_box = QVBoxLayout()
        cur.body.addLayout(self.milestone_box)
        btns = QHBoxLayout()
        self.done_btn = QPushButton("Mark task done")
        self.done_btn.setObjectName("Primary")
        self.done_btn.clicked.connect(self._complete_pinned)
        btns.addWidget(self.done_btn)
        btns.addStretch(1)
        cur.body.addLayout(btns)
        cur.body.addStretch(1)
        top.addWidget(cur, 0, 2)
        top.setColumnStretch(0, 5)
        top.setColumnStretch(1, 3)
        top.setColumnStretch(2, 4)

        tiles = QHBoxLayout()
        tiles.setSpacing(14)
        self.t_earned = StatTile("Earned (output)")
        self.t_spent = StatTile("Spent (active time)")
        self.t_eff = StatTile("Efficiency")
        self.t_plan = StatTile("Plan delivered")
        for t in (self.t_earned, self.t_spent, self.t_eff, self.t_plan):
            tiles.addWidget(t)
        lay.addLayout(tiles)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        plan_card = Card("Today's plan")
        self.plan_list = QListWidget()
        self.plan_list.setMinimumHeight(220)
        plan_card.body.addWidget(self.plan_list)
        bottom.addWidget(plan_card, 3)
        week_card = Card("This week")
        self.week_bar = QProgressBar()
        self.week_bar.setRange(0, 1000)
        self.week_bar.setFixedHeight(12)
        self.week_output = label("", "H2")
        self.week_pace = label("", "Muted", wrap=True)
        self.week_commit_bar = QProgressBar()
        self.week_commit_bar.setRange(0, 1000)
        self.week_commit_bar.setFixedHeight(12)
        self.week_commit = label("", "Muted", wrap=True)
        self.week_score = label("", "H2")
        week_card.body.addWidget(label("Output vs. weekly goal", "Muted"))
        week_card.body.addWidget(self.week_bar)
        week_card.body.addWidget(self.week_output)
        week_card.body.addWidget(self.week_pace)
        week_card.body.addSpacing(6)
        week_card.body.addWidget(label("Weekly commitment", "Muted"))
        week_card.body.addWidget(self.week_commit_bar)
        week_card.body.addWidget(self.week_commit)
        week_card.body.addWidget(self.week_score)
        week_card.body.addStretch(1)
        bottom.addWidget(week_card, 2)
        feed_card = Card("Recent XP")
        self.feed = QListWidget()
        self.feed.setMinimumHeight(220)
        feed_card.body.addWidget(self.feed)
        bottom.addWidget(feed_card, 2)
        lay.addLayout(bottom)

        ctl.data_changed.connect(self.refresh)
        ctl.tick.connect(self.refresh_live)
        self._last_full = 0.0
        self.refresh()

    # ------------------------------------------------------------- refresh
    def refresh(self) -> None:
        self._last_full = time.time()
        ctl = self.ctl
        eng = ctl.engine
        p = palette()
        hour = datetime.now().hour
        part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        self.greeting.setText(f"Good {part}")

        stats = eng.today_stats()
        goal = ctl.settings.daily_goal_minutes
        self.ring.set_value(stats.score, "score today")
        self.c_throughput.set(stats.throughput_score,
                              f"{stats.earned:.0f} of {goal} goal minutes earned")
        self.c_eff.set(stats.efficiency_score,
                       f"{stats.efficiency:.0%} efficiency (full marks at "
                       f"{scoring.EFFICIENCY_FULL_MARKS:.0%})")
        self.c_plan.set(stats.plan_score, f"{stats.plan_completion:.0%} of plan delivered, "
                                          f"{stats.density:.0%} density")
        self.c_focus.set(stats.focus_score, f"{stats.distracting:.0f} min distracted, "
                                            f"{stats.switches} switches")
        self.score_hint.setText(self._hint(stats))

        info = eng.level()
        self.level_title.setText(f"Level {info.level} · {info.title}")
        self.xp_bar.setValue(int(info.progress * 1000))
        self.level_sub.setText(f"{info.xp - info.level_floor} / "
                               f"{info.next_level_xp - info.level_floor} XP to level "
                               f"{info.level + 1}")
        streak = eng.streak()
        self.streak.setText(f"🔥 {streak.current}-day streak")
        q = gamification.day_qualifies(stats, goal)
        today_txt = "Today qualifies ✓" if q else (
            f"Today: reach {gamification.STREAK_MIN_EFFICIENCY:.0%} efficiency and deliver "
            f"{gamification.STREAK_MIN_PLAN_COMPLETION:.0%} of your plan")
        self.streak_sub.setText(f"Best {streak.best} · ❄ {streak.freezes} freeze(s)\n{today_txt}")

        eff_color = p.good if stats.efficiency >= 1 else p.warn if stats.efficiency >= 0.7 else p.bad
        self.t_earned.set(fmt_minutes(stats.earned), f"goal {fmt_minutes(goal)}")
        self.t_spent.set(fmt_minutes(stats.spent), f"{fmt_minutes(stats.distracting)} distracted")
        self.t_eff.set(f"{stats.efficiency:.0%}" if stats.spent else "—",
                       "earned ÷ spent", eff_color if stats.spent else None)
        self.t_plan.set(f"{stats.plan_completion:.0%}" if stats.planned else "No plan",
                        f"{fmt_minutes(stats.planned_earned)} of {fmt_minutes(stats.planned)}"
                        if stats.planned else "Plan your day to earn the Plan Bonus")

        self._fill_pin_combo()
        self._fill_plan()
        self._fill_feed()
        self._fill_week()
        self.refresh_live()

    def refresh_live(self) -> None:
        if time.time() - self._last_full > 30:
            self.refresh()
            return
        ctl = self.ctl
        p = palette()
        cat = ctl.current_category
        if not ctl.settings.tracking_enabled:
            self.status_pill.setText("⏸ Tracking paused")
        elif cat == Category.DISTRACTING:
            self.status_pill.setText("● Distracted")
            self.status_pill.setStyleSheet(f"color: {p.bad};")
        elif cat == Category.IDLE:
            self.status_pill.setText("○ Idle")
            self.status_pill.setStyleSheet("")
        else:
            t = next((x for x in ctl.open_tasks() if x.id == ctl.current_task_id), None)
            self.status_pill.setText(f"● Tracking: {t.title}" if t else "● Active (unassigned)")
            self.status_pill.setStyleSheet(f"color: {p.good};" if t else "")

        task = ctl.pinned_task()
        self.done_btn.setEnabled(task is not None)
        if task is None:
            self.cur_progress.setValue(0)
            self.cur_detail.setText("Pin a task to get a live pace meter. Tracking still "
                                    "matches windows to tasks by their keywords/apps.")
            self.pace.setText("")
            self._ms_sig = None
            while self.milestone_box.count():
                w = self.milestone_box.takeAt(0).widget()
                if w:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
            return
        actual = ctl.engine.refresh_actual(task)
        self.cur_progress.setValue(int(task.progress * 1000))
        self.cur_detail.setText(
            f"{task.progress:.0%} done · {fmt_minutes(actual)} spent · par "
            f"{fmt_minutes(task.par_minutes)}")
        pace = task.earned_minutes - actual
        self.pace.setText(("▲ Ahead of par " if pace >= 0 else "▼ Behind par ")
                          + fmt_signed_minutes(pace))
        self.pace.setStyleSheet(f"color: {p.good if pace >= 0 else p.bad};")
        self._fill_milestones(task)

    def _fill_milestones(self, task) -> None:
        sig = (task.id, tuple((m.id, round(m.progress, 3), m.evidence) for m in task.milestones))
        if sig == getattr(self, "_ms_sig", None):
            return
        self._ms_sig = sig
        while self.milestone_box.count():
            w = self.milestone_box.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for m in task.milestones:
            if m.progress >= 1:
                continue
            if m.source_type == SourceType.MANUAL:
                b = QPushButton(f"✓  {m.title}")
                b.setToolTip(f"Mark milestone done (+{m.par_minutes:.0f} min earned)")
                b.clicked.connect(lambda _=False, mid=m.id: self._tick_milestone(mid))
                self.milestone_box.addWidget(b)
            else:
                lbl = label(f"⟳ {m.title}: {m.progress:.0%} — {m.evidence}", "Muted", wrap=True)
                self.milestone_box.addWidget(lbl)
            if self.milestone_box.count() >= 4:
                break

    def _hint(self, stats) -> str:
        if stats.spent == 0 and stats.earned == 0:
            return "No work tracked yet today. Plan your day, then start on the first task."
        if stats.planned == 0:
            return "Tip: plan your day — the Plan component is worth 15 points."
        if stats.efficiency < 0.8:
            return "You're spending more time than par. Close distractions and finish milestones."
        if stats.earned < self.ctl.settings.daily_goal_minutes:
            left = self.ctl.settings.daily_goal_minutes - stats.earned
            return f"{fmt_minutes(left)} of output left to hit today's goal."
        return "Goal reached. Every extra milestone now is pure bonus."

    def _fill_pin_combo(self) -> None:
        tasks = self.ctl.open_tasks()
        self.pin_combo.blockSignals(True)
        self.pin_combo.clear()
        self.pin_combo.addItem("— No pinned task —", None)
        for t in tasks:
            self.pin_combo.addItem(f"{t.title}  ({t.progress:.0%})", t.id)
        idx = self.pin_combo.findData(self.ctl.pinned_task_id)
        self.pin_combo.setCurrentIndex(max(0, idx))
        self.pin_combo.blockSignals(False)

    def _fill_plan(self) -> None:
        self.plan_list.clear()
        plan = self.ctl.db.get_plan(self.ctl.engine.today())
        if not plan:
            item = QListWidgetItem("No plan for today. Open the Planner to build one.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.plan_list.addItem(item)
            return
        for row in plan:
            t = self.ctl.db.get_task(row["task_id"])
            if t is None:
                continue
            mark = "✅" if t.progress >= 1 else "▶" if t.id == self.ctl.pinned_task_id else "○"
            badge = f" · {t.badge.label}" if t.badge else ""
            item = QListWidgetItem(f"{mark}  {t.title} — {t.progress:.0%} · planned "
                                   f"{fmt_minutes(row['planned_minutes'])}{badge}")
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            self.plan_list.addItem(item)

    def _fill_week(self) -> None:
        p = palette()
        s = self.ctl.engine.week_stats()
        self.week_bar.setValue(int(min(1.0, s.earned / max(1.0, s.goal)) * 1000))
        self.week_output.setText(f"{fmt_minutes(s.earned)} / {fmt_minutes(s.goal)}")
        ahead = s.pace >= 0
        self.week_pace.setText(f"{'▲ ahead of' if ahead else '▼ behind'} pace by "
                               f"{fmt_minutes(abs(s.pace))} · day {s.days_elapsed}/{s.work_days}")
        self.week_pace.setStyleSheet(f"color: {p.good if ahead else p.bad};")
        if s.planned > 0:
            self.week_commit_bar.setValue(int(s.delivery * 1000))
            self.week_commit.setText(f"{s.tasks_done}/{s.tasks_planned} tasks done · "
                                     f"{s.delivery:.0%} of committed par delivered")
        else:
            self.week_commit_bar.setValue(0)
            self.week_commit.setText("Nothing committed. Planner → This week.")
        self.week_score.setText(f"Weekly score {s.score:.0f}")

    def _fill_feed(self) -> None:
        self.feed.clear()
        for r in self.ctl.db.recent_xp(25):
            when = datetime.fromtimestamp(r["ts"]).strftime("%a %H:%M")
            sign = "+" if r["amount"] >= 0 else ""
            self.feed.addItem(f"{sign}{r['amount']} XP  ·  {r['reason']}  ·  {when}")
        if self.feed.count() == 0:
            self.feed.addItem("Finish milestones to earn XP.")

    # ------------------------------------------------------------- actions
    def _pin_changed(self, _index: int) -> None:
        self.ctl.set_pinned(self.pin_combo.currentData())

    def _tick_milestone(self, milestone_id: int) -> None:
        task = self.ctl.pinned_task()
        if task is None:
            return
        task = self.ctl.db.get_task(task.id)
        m = next((x for x in task.milestones if x.id == milestone_id), None)
        if m:
            self.ctl.engine.set_milestone_progress(task, m, 1.0, "manual")
            self.ctl.invalidate()

    def _complete_pinned(self) -> None:
        task = self.ctl.pinned_task()
        if task is None:
            return
        task = self.ctl.db.get_task(task.id)
        self.ctl.engine.complete_task(task)
        self.ctl.invalidate()
