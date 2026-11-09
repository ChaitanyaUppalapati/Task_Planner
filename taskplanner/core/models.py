"""Domain models."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkType(str, Enum):
    CODING = "coding"
    WRITING = "writing"
    STUDY = "study"
    RESEARCH = "research"
    DESIGN = "design"
    ADMIN = "admin"
    OTHER = "other"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class TaskStatus(str, Enum):
    TODO = "todo"
    ACTIVE = "active"
    DONE = "done"
    ARCHIVED = "archived"


class SourceType(str, Enum):
    MANUAL = "manual"
    GIT = "git"
    DOCUMENT = "document"
    FOLDER = "folder"

    @property
    def label(self) -> str:
        return {
            "manual": "Checklist (manual)",
            "git": "Git repository",
            "document": "Document word count",
            "folder": "Output files in folder",
        }[self.value]


class Category(str, Enum):
    PRODUCTIVE = "productive"
    NEUTRAL = "neutral"
    DISTRACTING = "distracting"
    IDLE = "idle"


class ParBadge(str, Enum):
    EAGLE = "eagle"          # <= 60% of par
    BIRDIE = "birdie"        # <= 85% of par
    PAR = "par"              # <= 110% of par
    BOGEY = "bogey"          # <= 150% of par
    DOUBLE_BOGEY = "double_bogey"
    UNVERIFIED = "unverified"  # too little tracked time to judge

    @property
    def label(self) -> str:
        return {
            "eagle": "Eagle",
            "birdie": "Birdie",
            "par": "Par",
            "bogey": "Bogey",
            "double_bogey": "Double bogey",
            "unverified": "Unverified",
        }[self.value]


PRIORITY_LABELS = {1: "Low", 2: "Medium", 3: "High"}


@dataclass
class Milestone:
    title: str
    guess_minutes: float | None = None
    par_minutes: float = 0.0
    source_type: SourceType = SourceType.MANUAL
    source_config: dict[str, Any] = field(default_factory=dict)
    baseline: dict[str, Any] = field(default_factory=dict)
    progress: float = 0.0
    position: int = 0
    done_at: float | None = None
    evidence: str = ""
    id: int | None = None
    task_id: int | None = None

    @property
    def done(self) -> bool:
        return self.progress >= 1.0

    @property
    def earned_minutes(self) -> float:
        return self.par_minutes * min(1.0, max(0.0, self.progress))


@dataclass
class Task:
    title: str
    description: str = ""
    work_type: WorkType = WorkType.OTHER
    priority: int = 2
    due_date: str | None = None  # ISO date
    tags: list[str] = field(default_factory=list)
    match_apps: list[str] = field(default_factory=list)
    match_keywords: list[str] = field(default_factory=list)
    user_guess_minutes: float | None = None
    ai_guess_minutes: float | None = None
    par_minutes: float = 0.0
    par_low: float = 0.0
    par_high: float = 0.0
    par_basis: str = "default"
    base_minutes: float = 0.0
    original_par: float = 0.0
    revisions: int = 0
    status: TaskStatus = TaskStatus.TODO
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    badge: ParBadge | None = None
    actual_minutes: float = 0.0
    milestones: list[Milestone] = field(default_factory=list)
    id: int | None = None

    @property
    def is_started(self) -> bool:
        return self.started_at is not None

    @property
    def progress(self) -> float:
        total = sum(m.par_minutes for m in self.milestones)
        if total <= 0:
            return 1.0 if self.status == TaskStatus.DONE else 0.0
        return min(1.0, sum(m.earned_minutes for m in self.milestones) / total)

    @property
    def earned_minutes(self) -> float:
        return sum(m.earned_minutes for m in self.milestones)

    @property
    def remaining_par(self) -> float:
        return max(0.0, self.par_minutes - self.earned_minutes)


@dataclass
class ActivitySample:
    """One observation of what the user is doing right now."""

    timestamp: float
    process: str
    title: str
    idle_seconds: float
    locked: bool = False


@dataclass
class Estimate:
    par_minutes: float
    low_minutes: float
    high_minutes: float
    base_minutes: float
    basis: str
    confidence: str  # "low" | "medium" | "high"
    samples: int
    explanation: str


@dataclass
class DayStats:
    date: str
    earned: float = 0.0
    spent: float = 0.0
    distracting: float = 0.0
    planned: float = 0.0
    planned_earned: float = 0.0
    available: float = 0.0
    switches: int = 0
    longest_focus: float = 0.0
    tasks_completed: int = 0
    under_par: int = 0
    throughput_score: float = 0.0
    efficiency_score: float = 0.0
    plan_score: float = 0.0
    focus_score: float = 0.0
    score: float = 0.0

    @property
    def efficiency(self) -> float:
        from taskplanner.core.scoring import efficiency

        return efficiency(self.earned, self.spent)

    @property
    def density(self) -> float:
        return self.planned / self.available if self.available > 0 else 0.0

    @property
    def plan_completion(self) -> float:
        return min(1.0, self.planned_earned / self.planned) if self.planned > 0 else 0.0
