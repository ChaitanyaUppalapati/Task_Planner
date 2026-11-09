"""Turns a stream of samples into merged activity segments in the database."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from taskplanner.core.db import Database
from taskplanner.core.models import ActivitySample, Category, Task
from taskplanner.core.settings import Settings
from taskplanner.tracking.matcher import MatchResult, classify


@dataclass
class _Segment:
    id: int
    start: float
    end: float
    process: str
    title: str
    category: Category
    task_id: int | None


@dataclass
class RecordResult:
    match: MatchResult
    drift_seconds: float  # continuous distracting time so far


class ActivityRecorder:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self._current: _Segment | None = None
        self._drift_start: float | None = None
        self.paused = False

    @property
    def max_gap(self) -> float:
        return max(15.0, self.settings.sample_interval_seconds * 3.0)

    def record(
        self, sample: ActivitySample, tasks: Sequence[Task], pinned_task_id: int | None
    ) -> RecordResult:
        if self.paused:
            self._close()
            return RecordResult(MatchResult(Category.IDLE, None), 0.0)

        match = classify(sample, tasks, self.settings, pinned_task_id)
        now = sample.timestamp
        if match.excluded:
            self._close()
            self._drift_start = None
            return RecordResult(match, 0.0)

        if match.category == Category.IDLE and self._current is not None \
                and self._current.category != Category.IDLE and not sample.locked:
            # The user went idle `idle_seconds` ago; don't credit that tail.
            idle_began = now - sample.idle_seconds
            if idle_began > self._current.start and idle_began < self._current.end:
                self._current.end = idle_began
                self.db.extend_activity(self._current.id, idle_began)

        title = sample.title[:300]
        cur = self._current
        same = (
            cur is not None
            and cur.category == match.category
            and cur.task_id == match.task_id
            and cur.process == sample.process
            and (cur.title == title or match.category == Category.IDLE)
            and now - cur.end <= self.max_gap
        )
        if same and cur is not None:
            cur.end = now
            self.db.extend_activity(cur.id, now)
        else:
            start = now
            if cur is not None and now - cur.end <= self.max_gap:
                start = cur.end  # contiguous: the new segment begins where the last ended
            try:
                seg_id = self.db.add_activity(start, now, sample.process, title,
                                              match.category, match.task_id)
            except sqlite3.IntegrityError:
                # Task was deleted between matching and writing.
                match = MatchResult(match.category, None)
                seg_id = self.db.add_activity(start, now, sample.process, title,
                                              match.category, None)
            self._current = _Segment(seg_id, start, now, sample.process, title,
                                     match.category, match.task_id)

        if match.category == Category.DISTRACTING:
            if self._drift_start is None:
                self._drift_start = now
            drift = now - self._drift_start
        else:
            self._drift_start = None
            drift = 0.0
        return RecordResult(match, drift)

    def _close(self) -> None:
        self._current = None
