"""Weekly targets: an output goal for the week plus a committed set of tasks.

Weeks start on Monday. A week's score (0-100):
    output      50  earned minutes vs. the weekly output goal
    delivery    35  share of committed par delivered after committing
    efficiency  15  earned / spent, full marks at 125%
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from taskplanner.core.db import Database
from taskplanner.core.models import Task, TaskStatus

W_OUTPUT = 50.0
W_DELIVERY = 35.0
W_EFFICIENCY = 15.0
EFFICIENCY_FULL_MARKS = 1.25
EFFICIENCY_CAP = 2.0
WEEK_BONUS_THRESHOLD = 0.9


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_key(d: date) -> str:
    return week_start(d).isoformat()


def week_bounds(week: str) -> tuple[float, float]:
    start = date.fromisoformat(week)
    s = datetime(start.year, start.month, start.day)
    return s.timestamp(), (s + timedelta(days=7)).timestamp()


def week_label(week: str) -> str:
    start = date.fromisoformat(week)
    end = start + timedelta(days=6)
    return f"{start:%d %b} – {end:%d %b}"


def workdays_elapsed(week: str, today: date, work_days: int) -> int:
    """Workdays of this week up to and including today (Mon=1 … capped at work_days)."""
    start = date.fromisoformat(week)
    if today < start:
        return 0
    return min(work_days, (today - start).days + 1)


@dataclass
class WeekStats:
    week: str
    goal: float = 0.0
    earned: float = 0.0
    spent: float = 0.0
    planned: float = 0.0
    planned_earned: float = 0.0
    tasks_planned: int = 0
    tasks_done: int = 0
    work_days: int = 5
    days_elapsed: int = 0
    output_score: float = 0.0
    delivery_score: float = 0.0
    efficiency_score: float = 0.0
    score: float = 0.0

    @property
    def efficiency(self) -> float:
        if self.spent <= 0:
            return 0.0 if self.earned <= 0 else EFFICIENCY_CAP
        return min(EFFICIENCY_CAP, self.earned / self.spent)

    @property
    def delivery(self) -> float:
        return min(1.0, self.planned_earned / self.planned) if self.planned > 0 else 0.0

    @property
    def expected_now(self) -> float:
        """Output you should have by the end of today to be on track."""
        if self.work_days <= 0:
            return self.goal
        return self.goal * self.days_elapsed / self.work_days

    @property
    def pace(self) -> float:
        """Minutes ahead (+) or behind (-) the weekly output target so far."""
        return self.earned - self.expected_now

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(efficiency=self.efficiency, delivery=self.delivery)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> WeekStats:
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in allowed})


def score_week(s: WeekStats) -> WeekStats:
    if s.earned <= 0 and s.spent <= 0:
        s.output_score = s.delivery_score = s.efficiency_score = s.score = 0.0
        return s
    s.output_score = W_OUTPUT * min(1.0, s.earned / max(1.0, s.goal))
    s.delivery_score = W_DELIVERY * s.delivery
    s.efficiency_score = W_EFFICIENCY * min(1.0, s.efficiency / EFFICIENCY_FULL_MARKS)
    s.score = round(s.output_score + s.delivery_score + s.efficiency_score, 1)
    return s


def compute_week(db: Database, week: str, goal: float, work_days: int, today: date,
                 day_stats) -> WeekStats:
    """``day_stats(iso_date) -> DayStats`` supplies per-day earned/spent."""
    s = WeekStats(week=week, goal=goal, work_days=work_days)
    start = date.fromisoformat(week)
    for i in range(7):
        d = start + timedelta(days=i)
        if d > today:
            break
        ds = day_stats(d.isoformat())
        s.earned += ds.earned
        s.spent += ds.spent
    s.days_elapsed = workdays_elapsed(week, today, work_days)

    plan = db.get_week_plan(week)
    if plan:
        ws, we = week_bounds(week)
        since = max(ws, float(plan[0]["committed_at"] or ws))
        ids = [p["task_id"] for p in plan]
        s.planned = sum(p["planned_minutes"] for p in plan)
        s.planned_earned = min(s.planned, db.earned_between(since, we, ids))
        s.tasks_planned = len(ids)
        marks = ", ".join("?" for _ in ids)
        s.tasks_done = int(db.query(
            f"SELECT COUNT(*) AS n FROM tasks WHERE id IN ({marks}) AND status = ? "
            "AND completed_at >= ?", [*ids, TaskStatus.DONE.value, since])[0]["n"])
    return score_week(s)


def week_bonus(s: WeekStats) -> int:
    if s.planned <= 0 or s.delivery < WEEK_BONUS_THRESHOLD:
        return 0
    return int(round(s.planned * 0.25))


def week_capacity(available_per_day: float, work_days: int) -> float:
    return available_per_day * work_days


def committed_task_ids(db: Database, week: str) -> set[int]:
    return {r["task_id"] for r in db.get_week_plan(week)}


def suggest_week(tasks: list[Task], budget: float, today: date) -> list[Task]:
    from taskplanner.core.planner import suggest_plan

    return suggest_plan(tasks, budget, today)
