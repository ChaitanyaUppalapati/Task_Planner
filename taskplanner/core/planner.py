"""Daily planning: pack tasks into available time and judge plan density."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from taskplanner.core.estimator import weighted_quantile
from taskplanner.core.models import DayStats, Task

TARGET_DENSITY = 0.85
LOW_DENSITY = 0.6


@dataclass
class PlanEntry:
    task: Task
    minutes: float
    start_minute: float  # minutes after work start


@dataclass
class PlanAssessment:
    planned: float
    available: float
    capacity: float          # realistic output you have delivered on good days
    density: float
    verdict: str             # "light" | "dense" | "overloaded" | "empty"
    message: str


def urgency_key(task: Task, today: date, weekly_ids: frozenset[int] = frozenset()) -> tuple:
    due_days = 9999
    if task.due_date:
        try:
            due_days = (date.fromisoformat(task.due_date) - today).days
        except ValueError:
            pass
    overdue = due_days < 0
    return (not overdue, task.id not in weekly_ids, -task.priority, due_days, -task.progress,
            task.remaining_par)


def suggest_plan(tasks: Sequence[Task], available: float, today: date,
                 weekly_ids: frozenset[int] = frozenset()) -> list[Task]:
    """Greedy pack by urgency (overdue, this week's commitments, priority, due date)."""
    candidates = sorted((t for t in tasks if t.remaining_par > 0),
                        key=lambda t: urgency_key(t, today, weekly_ids))
    chosen: list[Task] = []
    total = 0.0
    budget = available
    for t in candidates:
        if total + t.remaining_par <= budget:
            chosen.append(t)
            total += t.remaining_par
    return chosen


def schedule(tasks: Sequence[Task]) -> list[PlanEntry]:
    entries = []
    cursor = 0.0
    for t in tasks:
        entries.append(PlanEntry(task=t, minutes=t.remaining_par, start_minute=cursor))
        cursor += t.remaining_par
    return entries


def capacity_from_history(history: Sequence[DayStats], available: float) -> float:
    """Output you can realistically deliver: 75th percentile of real work days."""
    days = [d.earned for d in history if d.spent >= 60]
    if len(days) < 3:
        return available * 0.9
    return weighted_quantile(days, [1.0] * len(days), 0.75)


def assess(planned: float, available: float, capacity: float) -> PlanAssessment:
    density = planned / available if available > 0 else 0.0
    if planned <= 0:
        verdict = "empty"
        msg = "No plan yet. A dense plan you deliver earns the Plan Bonus."
    elif planned > max(capacity, available) * 1.1 or planned > available * 1.05:
        verdict = "overloaded"
        msg = (f"{planned:.0f} min planned vs. ~{min(capacity, available):.0f} min you can "
               "realistically deliver. Unfinished planned work lowers your plan score.")
    elif density < LOW_DENSITY:
        verdict = "light"
        msg = (f"Only {density:.0%} of your available time is planned. "
               f"Aim for {TARGET_DENSITY:.0%}+ to maximise the Plan Bonus.")
    else:
        verdict = "dense"
        msg = f"{density:.0%} density - a strong plan. Deliver 90%+ of it for the Plan Bonus."
    return PlanAssessment(planned, available, capacity, density, verdict, msg)
