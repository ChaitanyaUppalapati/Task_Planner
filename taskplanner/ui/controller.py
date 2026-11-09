"""Qt glue: timers, background workers and signals around the pure engine."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from taskplanner.ai import claude_cli
from taskplanner.core.db import Database
from taskplanner.core.engine import Engine
from taskplanner.core.models import Category, Task, TaskStatus
from taskplanner.core.settings import Settings, save_settings
from taskplanner.tracking.recorder import ActivityRecorder
from taskplanner.tracking.sampler import Sampler, default_sampler

log = logging.getLogger(__name__)


class _WorkerSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Worker(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as e:  # noqa: BLE001
            log.exception("background job failed")
            self.signals.failed.emit(str(e))
        else:
            self.signals.done.emit(result)


class Controller(QObject):
    data_changed = Signal()                  # anything that affects displayed numbers
    tick = Signal()                          # every sample (live pace display)
    notify = Signal(str, str)                # title, message
    tracking_state = Signal(bool)
    ai_finished = Signal(object, object)     # task, Breakdown
    ai_failed = Signal(str)

    def __init__(self, db: Database, settings: Settings, sampler: Sampler | None = None,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.engine = Engine(db, settings)
        self.recorder = ActivityRecorder(db, settings)
        self.sampler = sampler or default_sampler()
        self.pool = QThreadPool.globalInstance()
        self._tasks_cache: list[Task] = []
        self._cache_dirty = True
        self._last_nudge = 0.0
        self._over_par_warned: set[int] = set()
        self._progress_running = False
        self.current_category = Category.IDLE
        self.current_task_id: int | None = None
        self.pinned_task_id: int | None = db.get_setting("pinned_task_id")

        self.engine.subscribe(self._on_engine_event)

        self.sample_timer = QTimer(self)
        self.sample_timer.timeout.connect(self.sample_once)
        self.progress_timer = QTimer(self)
        self.progress_timer.timeout.connect(self.check_progress)
        self.day_timer = QTimer(self)
        self.day_timer.timeout.connect(self.roll_days)

    # ----------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.roll_days()
        self.apply_settings()
        self.day_timer.start(60_000)
        QTimer.singleShot(1500, self.check_progress)
        retention = self.settings.activity_retention_days
        if retention > 0:
            self.db.purge_activity_before(time.time() - retention * 86400)

    def apply_settings(self) -> None:
        self.sample_timer.start(max(1, self.settings.sample_interval_seconds) * 1000)
        self.progress_timer.start(max(15, self.settings.progress_check_seconds) * 1000)
        self.recorder.paused = not self.settings.tracking_enabled
        self.tracking_state.emit(self.settings.tracking_enabled)
        if sys.platform == "win32":
            from taskplanner.ui import autostart

            try:
                autostart.set_enabled(self.settings.start_with_windows)
            except OSError:
                log.exception("could not update autostart")

    def save_settings(self) -> None:
        save_settings(self.db, self.settings)
        self.apply_settings()
        self.invalidate()

    def stop(self) -> None:
        self.sample_timer.stop()
        self.progress_timer.stop()
        self.day_timer.stop()
        self.pool.waitForDone(3000)

    # --------------------------------------------------------------- tasks
    def invalidate(self) -> None:
        self._cache_dirty = True
        self.data_changed.emit()

    def open_tasks(self) -> list[Task]:
        if self._cache_dirty:
            self._tasks_cache = self.db.open_tasks()
            self._cache_dirty = False
        return self._tasks_cache

    def pinned_task(self) -> Task | None:
        if self.pinned_task_id is None:
            return None
        t = next((t for t in self.open_tasks() if t.id == self.pinned_task_id), None)
        if t is None:
            self.set_pinned(None)
        return t

    def set_pinned(self, task_id: int | None) -> None:
        self.pinned_task_id = task_id
        self.db.set_setting("pinned_task_id", task_id)
        if task_id is not None:
            t = self.db.get_task(task_id)
            if t and not t.is_started:
                self.engine.start_task(t)
        self.invalidate()

    def set_tracking(self, enabled: bool) -> None:
        self.settings.tracking_enabled = enabled
        save_settings(self.db, self.settings)
        self.recorder.paused = not enabled
        self.tracking_state.emit(enabled)

    # ------------------------------------------------------------ sampling
    def sample_once(self) -> None:
        try:
            sample = self.sampler.sample()
        except Exception:  # noqa: BLE001
            log.exception("sampling failed")
            return
        tasks = self.open_tasks()
        result = self.recorder.record(sample, tasks, self.pinned_task_id)
        self.current_category = result.match.category
        self.current_task_id = result.match.task_id

        task_id = result.match.task_id
        if task_id is not None:
            t = next((x for x in tasks if x.id == task_id), None)
            if t is not None and not t.is_started:
                self.engine.start_task(t)
                self._cache_dirty = True
            if t is not None:
                self._maybe_warn_over_par(t)

        drift_limit = self.settings.drift_nudge_minutes * 60
        if (result.drift_seconds >= drift_limit and self.pinned_task_id is not None
                and time.time() - self._last_nudge > drift_limit):
            self._last_nudge = time.time()
            pinned = self.pinned_task()
            name = pinned.title if pinned else "your task"
            self.notify.emit("Drifting off par",
                             f"{result.drift_seconds / 60:.0f} min on distractions. "
                             f"Back to “{name}”?")
        self.tick.emit()

    def _maybe_warn_over_par(self, task: Task) -> None:
        if task.id in self._over_par_warned or task.par_minutes <= 0:
            return
        actual = self.engine.refresh_actual(task)
        if actual > task.par_minutes and task.progress < 1.0:
            self._over_par_warned.add(task.id)
            self.notify.emit("Over par",
                             f"“{task.title}” passed its {task.par_minutes:.0f} min par at "
                             f"{task.progress:.0%} done. Finish strong or split it up.")

    # ------------------------------------------------------------ progress
    def check_progress(self) -> None:
        if self._progress_running:
            return
        tasks = [t for t in self.db.open_tasks()
                 if any(m.source_type.value != "manual" and m.progress < 1 for m in t.milestones)]
        if not tasks:
            return
        self._progress_running = True
        worker = _Worker(lambda: Engine.read_sources(tasks))
        worker.signals.done.connect(self._apply_readings)
        worker.signals.failed.connect(lambda _e: setattr(self, "_progress_running", False))
        self.pool.start(worker)

    def _apply_readings(self, readings) -> None:
        self._progress_running = False
        try:
            changed = self.engine.apply_readings(readings)
        except Exception:  # noqa: BLE001
            log.exception("applying readings failed")
            return
        self.invalidate() if changed else self.data_changed.emit()

    # ----------------------------------------------------------------- days
    def roll_days(self) -> None:
        try:
            finalized = self.engine.finalize_days()
        except Exception:  # noqa: BLE001
            log.exception("finalizing days failed")
            return
        if finalized:
            last = finalized[-1]
            self.notify.emit("Day closed",
                             f"{last.date}: score {last.score:.0f}, earned "
                             f"{last.earned:.0f} min at {last.efficiency:.0%} efficiency.")
            self.invalidate()

    # ------------------------------------------------------------------ ai
    def ai_breakdown(self, task: Task) -> None:
        s = self.settings
        worker = _Worker(lambda: claude_cli.run_breakdown(
            task, s.claude_path, s.claude_model, s.ai_timeout_seconds))
        worker.signals.done.connect(lambda b: self._ai_done(task, b))
        worker.signals.failed.connect(self.ai_failed.emit)
        self.pool.start(worker)

    def _ai_done(self, task: Task, breakdown) -> None:
        self.db.set_setting("ai_used", True)
        self.ai_finished.emit(task, breakdown)

    # -------------------------------------------------------------- events
    def _on_engine_event(self, kind: str, payload: dict[str, Any]) -> None:
        if kind in ("task_changed", "task_completed", "progress", "plan_changed"):
            self._cache_dirty = True
        if kind == "task_completed":
            if payload.get("task_id") == self.pinned_task_id:
                self.pinned_task_id = None
                self.db.set_setting("pinned_task_id", None)
            badge = payload["badge"]
            self.notify.emit(
                f"{badge.label}! Task finished",
                f"“{payload['title']}” in {payload['actual']:.0f} min vs par "
                f"{payload['par']:.0f}. +{payload['xp']} XP",
            )
        elif kind == "milestone_done":
            self.notify.emit("Milestone done", payload["title"])
        elif kind == "level_up":
            self.notify.emit("Level up!", f"Level {payload['level']} — {payload['title']}")
        elif kind == "achievement":
            self.notify.emit(f"{payload['icon']} Achievement unlocked",
                             f"{payload['name']}: {payload['description']}")
        if kind != "xp":
            self.data_changed.emit()

    # -------------------------------------------------------------- helpers
    def task_status_text(self, task: Task) -> str:
        if task.status == TaskStatus.DONE:
            return task.badge.label if task.badge else "Done"
        return "In progress" if task.is_started else "To do"
