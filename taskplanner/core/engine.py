"""Application service layer: task lifecycle, progress, XP and day finalization.

Pure Python (no Qt) so it can be unit tested. The UI subscribes to events.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from taskplanner.core import estimator, gamification, scoring
from taskplanner.core.db import Database, day_bounds, local_date
from taskplanner.core.models import (
    DayStats,
    Estimate,
    Milestone,
    ParBadge,
    SourceType,
    Task,
    TaskStatus,
)
from taskplanner.core.settings import Settings
from taskplanner.progress import sources

log = logging.getLogger(__name__)

Listener = Callable[[str, dict[str, Any]], None]


@dataclass
class SourceReading:
    task_id: int
    milestone_id: int
    progress: float | None
    evidence: str
    error: str | None = None


class Engine:
    def __init__(self, db: Database, settings: Settings, clock: Callable[[], float] = time.time):
        self.db = db
        self.settings = settings
        self.clock = clock
        self._listeners: list[Listener] = []

    # ------------------------------------------------------------- events
    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def emit(self, kind: str, **payload: Any) -> None:
        for fn in list(self._listeners):
            try:
                fn(kind, payload)
            except Exception:  # pragma: no cover - listener bugs must not break the engine
                log.exception("listener failed for %s", kind)

    # --------------------------------------------------------- estimation
    def history(self) -> list[estimator.HistoryPoint]:
        return estimator.history_from_tasks(self.db.list_tasks([TaskStatus.DONE]))

    def predict(self, task: Task) -> Estimate:
        return estimator.predict(task, self.history(), now=self.clock())

    # ------------------------------------------------------ task lifecycle
    def create_task(self, task: Task) -> Task:
        est = self.predict(task)
        estimator.apply_estimate(task, est)
        task.original_par = task.par_minutes
        if not task.milestones:
            task.milestones = [Milestone(title="Done", guess_minutes=task.par_minutes)]
            estimator.distribute_par(task)
        self._capture_baselines(task)
        self.db.save_task(task)
        self.emit("task_changed", task_id=task.id)
        return task

    def update_task(self, task: Task) -> Task:
        """Save edits. Par is re-predicted only until the task is started."""
        if not task.milestones:
            task.milestones = [Milestone(title="Done", guess_minutes=task.par_minutes or None)]
        if not task.is_started:
            est = self.predict(task)
            estimator.apply_estimate(task, est)
            task.original_par = task.par_minutes
        else:
            # Locked par: new milestones get a share carved from remaining guesses
            # but the task total stays fixed.
            estimator.distribute_par(task)
        self._capture_baselines(task)
        self.db.save_task(task)
        self.emit("task_changed", task_id=task.id)
        return task

    def reestimate(self, task: Task, new_par: float) -> Task:
        """Change par after starting. Allowed, but logged and it shrinks the finish bonus."""
        new_par = max(estimator.MIN_PAR, float(new_par))
        if task.is_started and abs(new_par - task.par_minutes) >= 1:
            task.revisions += 1
        task.par_minutes = new_par
        if not task.is_started:
            task.original_par = new_par
        estimator.distribute_par(task)
        self.db.save_task(task)
        self.emit("task_changed", task_id=task.id)
        return task

    def start_task(self, task: Task) -> Task:
        if task.started_at is None:
            task.started_at = self.clock()
            if task.original_par <= 0:
                task.original_par = task.par_minutes
        if task.status == TaskStatus.TODO:
            task.status = TaskStatus.ACTIVE
        self._capture_baselines(task)
        self.db.save_task(task)
        self.emit("task_changed", task_id=task.id)
        return task

    def archive_task(self, task: Task) -> None:
        task.status = TaskStatus.ARCHIVED
        self.db.save_task(task)
        self.emit("task_changed", task_id=task.id)

    def delete_task(self, task: Task) -> None:
        if task.id is not None:
            self.db.delete_task(task.id)
        self.emit("task_changed", task_id=task.id)

    @staticmethod
    def _source_key(m: Milestone) -> tuple | None:
        """Milestones sharing a key measure the same evidence and run in sequence.

        Commit-message milestones look for their own text, so they are independent.
        """
        cfg = m.source_config or {}
        if m.source_type == SourceType.MANUAL:
            return None
        if m.source_type == SourceType.GIT:
            if cfg.get("metric") == "message":
                return None
            return ("git", cfg.get("repo"))
        if m.source_type == SourceType.DOCUMENT:
            return ("doc", cfg.get("path"))
        return ("folder", cfg.get("path"), cfg.get("pattern"))

    def _capture_baselines(self, task: Task) -> list[Milestone]:
        """Give the next eligible auto-milestone of each source its starting point.

        Without sequencing, two "1 new commit" milestones on one repo would both
        complete on the first commit. Later milestones wait (no baseline) until the
        earlier one on the same source is done, then start counting from there.
        """
        changed = []
        active_keys: set[tuple] = set()
        for m in task.milestones:
            if m.source_type == SourceType.MANUAL or m.progress >= 1.0:
                continue
            key = self._source_key(m)
            if key is not None:
                if key in active_keys:
                    continue  # an earlier milestone on this source is still running
                active_keys.add(key)
            if m.baseline:
                continue
            try:
                m.baseline = sources.capture_baseline(m)
                m.evidence = "measuring from now"
            except sources.SourceError as e:
                m.evidence = f"⚠ {e}"
            changed.append(m)
        return changed

    # ------------------------------------------------------------ progress
    def set_milestone_progress(
        self, task: Task, milestone: Milestone, progress: float, source: str = "manual",
        evidence: str | None = None,
    ) -> None:
        """Record measured progress. Progress never goes backwards."""
        progress = max(0.0, min(1.0, progress))
        if evidence is not None:
            milestone.evidence = evidence
        if progress <= milestone.progress + 1e-6:
            if evidence is not None and milestone.id is not None:
                self.db.save_milestone(milestone)
            return
        if task.started_at is None:
            self.start_task(task)
        delta = progress - milestone.progress
        earned = milestone.par_minutes * delta
        milestone.progress = progress
        now = self.clock()
        if progress >= 1.0 and milestone.done_at is None:
            milestone.done_at = now
        self.db.save_milestone(milestone)
        self.db.add_progress_event(task.id, milestone.id, delta, earned, source, ts=now)
        self._award_fractional(earned, f"Progress: {task.title}")
        self.emit("progress", task_id=task.id, milestone_id=milestone.id, earned=earned)
        if milestone.done_at == now:
            self.emit("milestone_done", task_id=task.id, title=milestone.title)
            for m in self._capture_baselines(task):
                if m.id is not None:
                    self.db.save_milestone(m)
        if all(m.progress >= 1.0 for m in task.milestones) and task.status != TaskStatus.DONE:
            self.complete_task(task)

    def complete_task(self, task: Task) -> ParBadge:
        """Mark a task done (closing any open milestones) and score it against par."""
        if task.status == TaskStatus.DONE and task.badge is not None:
            return task.badge
        task.status = TaskStatus.DONE  # set first so the recursive check above is a no-op
        for m in task.milestones:
            if m.progress < 1.0:
                self.set_milestone_progress(task, m, 1.0, source="manual")
        now = self.clock()
        if task.started_at is None:
            task.started_at = now
        task.completed_at = now
        task.actual_minutes = self.db.task_minutes(task.id) if task.id else 0.0
        par = task.original_par or task.par_minutes
        task.badge = scoring.badge_for(par, task.actual_minutes)
        self.db.save_task(task)
        bonus = gamification.completion_bonus(par, task.badge, task.revisions)
        self._award(bonus, f"Finished {task.title} ({task.badge.label})", ref=f"task:{task.id}")
        self.emit("task_completed", task_id=task.id, badge=task.badge, title=task.title,
                  par=par, actual=task.actual_minutes, xp=bonus)
        self.check_achievements()
        return task.badge

    def reopen_task(self, task: Task) -> None:
        task.status = TaskStatus.ACTIVE
        task.completed_at = None
        task.badge = None
        self.db.save_task(task)
        self.emit("task_changed", task_id=task.id)

    def refresh_actual(self, task: Task) -> float:
        if task.id is not None:
            task.actual_minutes = self.db.task_minutes(task.id)
        return task.actual_minutes

    # --------------------------------------------- automatic progress sources
    @staticmethod
    def read_sources(tasks: Sequence[Task]) -> list[SourceReading]:
        """Evaluate auto-progress milestones. Thread-safe: touches no database."""
        out = []
        for t in tasks:
            if t.status not in (TaskStatus.TODO, TaskStatus.ACTIVE):
                continue
            for m in t.milestones:
                if m.source_type == SourceType.MANUAL or m.progress >= 1.0 or m.id is None:
                    continue
                if not m.baseline:
                    continue
                try:
                    r = sources.read_progress(m)
                except sources.SourceError as e:
                    out.append(SourceReading(t.id, m.id, None, "", str(e)))
                    continue
                except Exception as e:  # noqa: BLE001 - never let a bad file crash tracking
                    out.append(SourceReading(t.id, m.id, None, "", f"{type(e).__name__}: {e}"))
                    continue
                if r is not None:
                    out.append(SourceReading(t.id, m.id, r.progress, r.evidence))
        return out

    def apply_readings(self, readings: Sequence[SourceReading]) -> int:
        changed = 0
        cache: dict[int, Task] = {}
        for r in readings:
            task = cache.get(r.task_id) or self.db.get_task(r.task_id)
            if task is None:
                continue
            cache[r.task_id] = task
            m = next((x for x in task.milestones if x.id == r.milestone_id), None)
            if m is None:
                continue
            if r.error:
                m.evidence = f"⚠ {r.error}"
                self.db.save_milestone(m)
                continue
            before = m.progress
            self.set_milestone_progress(task, m, r.progress or 0.0, source=m.source_type.value,
                                        evidence=r.evidence)
            if m.progress > before:
                changed += 1
        return changed

    # ------------------------------------------------------------------- xp
    def _award(self, amount: int, reason: str, ref: str | None = None) -> None:
        if amount == 0:
            return
        before = gamification.level_for_xp(self.db.total_xp())
        self.db.add_xp(amount, reason, ref, ts=self.clock())
        total = self.db.total_xp()
        after = gamification.level_for_xp(total)
        self.emit("xp", amount=amount, reason=reason, total=total)
        if after > before:
            self.emit("level_up", level=after, title=gamification.title_for_level(after))

    def _award_fractional(self, earned_minutes: float, reason: str) -> None:
        carry = float(self.db.get_setting("xp_carry", 0.0)) + earned_minutes
        whole = int(carry)
        self.db.set_setting("xp_carry", carry - whole)
        self._award(whole, reason)

    def level(self) -> gamification.LevelInfo:
        return gamification.level_info(self.db.total_xp())

    # ----------------------------------------------------------------- days
    def today(self) -> str:
        return local_date(self.clock())

    def day_stats(self, day: str) -> DayStats:
        return scoring.compute_day(self.db, day, self.settings.daily_goal_minutes,
                                   self.settings.available_minutes)

    def today_stats(self) -> DayStats:
        return self.day_stats(self.today())

    def finalize_days(self) -> list[DayStats]:
        """Finalize every day before today that hasn't been scored yet."""
        today = date.fromisoformat(self.today())
        first_ts = self.db.first_activity_ts()
        finalized = {d for d, _ in self.db.finalized_days()}
        if first_ts is None:
            return []
        cur = date.fromisoformat(local_date(first_ts))
        last_final = self.db.get_setting("last_finalized")
        if last_final:
            cur = max(cur, date.fromisoformat(last_final) + timedelta(days=1))
        done: list[DayStats] = []
        while cur < today:
            key = cur.isoformat()
            if key not in finalized:
                done.append(self._finalize(key))
            cur += timedelta(days=1)
        if done:
            self.db.set_setting("last_finalized", done[-1].date)
            self.check_achievements()
        return done

    def _finalize(self, day: str) -> DayStats:
        stats = self.day_stats(day)
        goal = self.settings.daily_goal_minutes
        qualified = gamification.day_qualifies(stats, goal)
        data = scoring.stats_to_dict(stats)
        data.update(qualified=qualified, final=True)
        self.db.save_day(day, data, finalized=True)
        _, day_end = day_bounds(day)
        ts = day_end - 1
        if stats.score > 0 and not self.db.has_xp_ref(f"day:{day}"):
            self.db.add_xp(int(round(stats.score)), f"Daily score {day}", f"day:{day}", ts=ts)
        pb = gamification.plan_bonus(stats)
        if pb and not self.db.has_xp_ref(f"plan:{day}"):
            self.db.add_xp(pb, f"Plan bonus {day}", f"plan:{day}", ts=ts)
        if qualified:
            streak = self.streak(until=day).current
            if not self.db.has_xp_ref(f"streak:{day}"):
                self.db.add_xp(gamification.streak_bonus(streak), f"Streak day {streak}",
                               f"streak:{day}", ts=ts)
        self.emit("day_finalized", day=day, score=stats.score, qualified=qualified)
        return stats

    def all_day_data(self) -> dict[str, dict]:
        return {d: data for d, data in self.db.finalized_days()}

    def streak(self, until: str | None = None) -> gamification.StreakInfo:
        until = until or self.today()
        days = self.all_day_data()
        if until == self.today():
            stats = self.today_stats()
            data = scoring.stats_to_dict(stats)
            data["qualified"] = gamification.day_qualifies(stats, self.settings.daily_goal_minutes)
            days[until] = data
        return gamification.compute_streak(days, until)

    def history_stats(self, days: int = 30) -> list[DayStats]:
        today = date.fromisoformat(self.today())
        stored = self.all_day_data()
        out = []
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            if d == today.isoformat():
                out.append(self.today_stats())
            elif d in stored:
                out.append(scoring.stats_from_dict(stored[d]))
            else:
                out.append(DayStats(date=d))
        return out

    # --------------------------------------------------------- achievements
    def achievement_context(self) -> gamification.AchievementContext:
        done = self.db.list_tasks([TaskStatus.DONE])
        badge_counts: dict[str, int] = {}
        sniper = 0
        for t in done:
            if t.badge:
                badge_counts[t.badge.value] = badge_counts.get(t.badge.value, 0) + 1
            par = t.original_par or t.par_minutes
            if t.badge not in (None, ParBadge.UNVERIFIED) and par > 0 \
                    and abs(t.actual_minutes - par) <= 0.1 * par:
                sniper += 1
        stored = self.db.finalized_days()
        stored.sort()
        days = [scoring.stats_from_dict(d) for _, d in stored]
        today_stats = self.today_stats()
        if today_stats.spent > 0 or today_stats.earned > 0:
            days.append(today_stats)
        best_before = max((d.earned for d in days[:-1]), default=0.0)
        return gamification.AchievementContext(
            tasks_completed=len(done),
            badge_counts=badge_counts,
            sniper_count=sniper,
            days=days,
            streak=self.streak().current,
            level=self.level().level,
            plan_days=len(self.db.plan_days()),
            ai_used=bool(self.db.get_setting("ai_used", False)),
            goal_minutes=self.settings.daily_goal_minutes,
            best_earned_before=best_before,
        )

    def check_achievements(self) -> list[gamification.Achievement]:
        ctx = self.achievement_context()
        new = gamification.newly_unlocked(ctx, set(self.db.unlocked()))
        for a in new:
            if self.db.unlock(a.key, ts=self.clock()):
                self._award(50, f"Achievement: {a.name}", ref=f"ach:{a.key}")
                self.emit("achievement", key=a.key, name=a.name, icon=a.icon,
                          description=a.description)
        return new

    # ----------------------------------------------------------------- plan
    def commit_plan(self, day: str, tasks: Sequence[Task]) -> None:
        entries = [(t.id, t.remaining_par) for t in tasks
                   if t.id is not None and t.remaining_par > 0]
        self.db.set_plan(day, entries, self.settings.available_minutes, committed_at=self.clock())
        self.emit("plan_changed", day=day)
        self.check_achievements()
