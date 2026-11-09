"""Productivity scoring: output (earned par time) per unit of real time spent.

Definitions
-----------
earned   Minutes of par completed: each milestone earns its share of the task's
         par as its measured progress rises. A 2 h task finished in 4 h earns 2 h.
spent    Active (non-idle) minutes attributed to tasks, plus distracting minutes.
efficiency = earned / spent.

Daily score (0-100):
    throughput  40  earned vs. daily output goal
    efficiency  35  earned / spent, full marks at 125% (beating par)
    plan        15  share of planned work delivered x planning density
    focus       10  distraction share and context-switching
"""

from __future__ import annotations

from dataclasses import asdict

from taskplanner.core.db import Database, day_bounds, local_date
from taskplanner.core.models import Category, DayStats, ParBadge, Task, TaskStatus

W_THROUGHPUT = 40.0
W_EFFICIENCY = 35.0
W_PLAN = 15.0
W_FOCUS = 10.0

EFFICIENCY_FULL_MARKS = 1.25
EFFICIENCY_CAP = 2.0
DENSITY_FULL_MARKS = 0.8
SWITCHES_PER_HOUR_OK = 12
FOCUS_GAP_SECONDS = 120
# A task needs at least this share of its par actually tracked to be judged.
VERIFIED_MIN_SHARE = 0.30


def efficiency(earned: float, spent: float) -> float:
    if spent <= 0:
        return 0.0 if earned <= 0 else EFFICIENCY_CAP
    return min(EFFICIENCY_CAP, earned / spent)


def badge_for(par: float, actual: float) -> ParBadge:
    if par <= 0:
        return ParBadge.UNVERIFIED
    if actual < par * VERIFIED_MIN_SHARE:
        return ParBadge.UNVERIFIED
    r = actual / par
    if r <= 0.60:
        return ParBadge.EAGLE
    if r <= 0.85:
        return ParBadge.BIRDIE
    if r <= 1.10:
        return ParBadge.PAR
    if r <= 1.50:
        return ParBadge.BOGEY
    return ParBadge.DOUBLE_BOGEY


def score_components(stats: DayStats, goal_minutes: float) -> DayStats:
    if stats.earned <= 0 and stats.spent <= 0:
        stats.throughput_score = stats.efficiency_score = 0.0
        stats.plan_score = stats.focus_score = stats.score = 0.0
        return stats

    goal = max(1.0, goal_minutes)
    stats.throughput_score = W_THROUGHPUT * min(1.0, stats.earned / goal)

    eff = efficiency(stats.earned, stats.spent)
    stats.efficiency_score = W_EFFICIENCY * min(1.0, eff / EFFICIENCY_FULL_MARKS)

    if stats.planned > 0:
        density_factor = 0.5 + 0.5 * min(1.0, stats.density / DENSITY_FULL_MARKS)
        stats.plan_score = W_PLAN * stats.plan_completion * density_factor
    else:
        stats.plan_score = 0.0

    if stats.spent > 0 and stats.earned > 0:  # focus without output is worth nothing
        distract_ratio = stats.distracting / stats.spent
        hours = max(stats.spent / 60.0, 0.5)
        excess_switch = max(0.0, stats.switches / hours - SWITCHES_PER_HOUR_OK)
        focus = 1.0 - 2.0 * distract_ratio - excess_switch / 60.0
        stats.focus_score = W_FOCUS * max(0.0, min(1.0, focus))
    else:
        stats.focus_score = 0.0

    stats.score = round(
        stats.throughput_score + stats.efficiency_score + stats.plan_score + stats.focus_score, 1
    )
    return stats


def compute_day(db: Database, day: str, goal_minutes: float, available_minutes: float) -> DayStats:
    start, end = day_bounds(day)
    stats = DayStats(date=day)
    stats.earned = db.earned_between(start, end)

    rows = db.activity_between(start, end)
    spent_s = distract_s = 0.0
    switches = 0
    prev_key: object = None
    run_task: int | None = None
    run_len = 0.0
    run_end = 0.0
    longest = 0.0
    for r in rows:
        s = max(r["start_ts"], start)
        e = min(r["end_ts"], end)
        dur = max(0.0, e - s)
        cat = r["category"]
        if cat == Category.IDLE.value:
            continue
        if cat == Category.DISTRACTING.value:
            distract_s += dur
            spent_s += dur
            key: object = "distract"
        elif r["task_id"] is not None:
            spent_s += dur
            key = r["task_id"]
        else:
            key = None  # neutral, unassigned
        if key is not None:
            if prev_key is not None and key != prev_key:
                switches += 1
            prev_key = key
        # Longest unbroken focus run on a single task.
        if r["task_id"] is not None and cat != Category.DISTRACTING.value:
            if run_task == r["task_id"] and s - run_end <= FOCUS_GAP_SECONDS:
                run_len += dur
            else:
                run_task, run_len = r["task_id"], dur
            run_end = e
            longest = max(longest, run_len)
        elif cat == Category.DISTRACTING.value:
            run_task, run_len = None, 0.0

    stats.spent = spent_s / 60.0
    stats.distracting = distract_s / 60.0
    stats.switches = switches
    stats.longest_focus = longest / 60.0

    plan = db.get_plan(day)
    if plan:
        stats.planned = sum(p["planned_minutes"] for p in plan)
        stats.available = plan[0]["available_minutes"]
        planned_ids = [p["task_id"] for p in plan]
        since = max(start, float(plan[0]["committed_at"] or start))
        stats.planned_earned = min(
            stats.planned, db.earned_between(since, end, planned_ids)
        )
    else:
        stats.available = available_minutes

    done_rows = db.query(
        "SELECT badge FROM tasks WHERE status = ? AND completed_at >= ? AND completed_at < ?",
        (TaskStatus.DONE.value, start, end),
    )
    stats.tasks_completed = len(done_rows)
    stats.under_par = sum(
        1 for r in done_rows if r["badge"] in (ParBadge.EAGLE.value, ParBadge.BIRDIE.value)
    )
    return score_components(stats, goal_minutes)


def stats_to_dict(stats: DayStats) -> dict:
    d = asdict(stats)
    d["efficiency"] = stats.efficiency
    d["density"] = stats.density
    d["plan_completion"] = stats.plan_completion
    return d


def stats_from_dict(d: dict) -> DayStats:
    allowed = DayStats.__dataclass_fields__.keys()
    return DayStats(**{k: v for k, v in d.items() if k in allowed})


def task_efficiency(task: Task) -> float:
    return efficiency(task.earned_minutes, task.actual_minutes)


def today() -> str:
    import time

    return local_date(time.time())
