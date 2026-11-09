"""Classify activity samples and attribute them to tasks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from taskplanner.core.models import ActivitySample, Category, SourceType, Task
from taskplanner.core.settings import Settings


@dataclass
class MatchResult:
    category: Category
    task_id: int | None
    excluded: bool = False


def _norm(items: Sequence[str]) -> list[str]:
    return [i.strip().lower() for i in items if i and i.strip()]


def implicit_keywords(task: Task) -> list[str]:
    """Window-title keywords implied by a task's progress sources."""
    words: list[str] = []
    links = task.links or {}
    for key in ("repo", "folder"):
        if links.get(key):
            words.append(Path(links[key]).name.lower())
    if links.get("document"):
        doc = Path(links["document"])
        words += [doc.name.lower(), doc.stem.lower()]
    for m in task.milestones:
        cfg = m.source_config or {}
        path = cfg.get("path") or cfg.get("repo")
        if not path:
            continue
        p = Path(path)
        if m.source_type == SourceType.DOCUMENT:
            words.append(p.name.lower())
            words.append(p.stem.lower())
        elif m.source_type in (SourceType.GIT, SourceType.FOLDER):
            words.append(p.name.lower())
    return [w for w in dict.fromkeys(words) if len(w) >= 3]


def task_match_score(sample: ActivitySample, task: Task) -> int:
    title = sample.title.lower()
    process = sample.process.lower()
    apps = _norm(task.match_apps)
    keywords = _norm(task.match_keywords) + implicit_keywords(task)
    if apps and process not in apps:
        return 0
    if keywords:
        hits = sum(1 for k in keywords if k in title)
        if hits == 0:
            return 0
        return 10 * hits + (5 if apps else 0)
    return 3 if apps else 0


def classify(
    sample: ActivitySample,
    tasks: Sequence[Task],
    settings: Settings,
    pinned_task_id: int | None = None,
    idle_threshold: float | None = None,
) -> MatchResult:
    process = sample.process.lower()
    title = sample.title.lower()
    threshold = idle_threshold if idle_threshold is not None else settings.idle_threshold_seconds

    if process and process in _norm(settings.excluded_apps):
        return MatchResult(Category.NEUTRAL, None, excluded=True)
    if sample.locked or sample.idle_seconds >= threshold or (not process and not title):
        return MatchResult(Category.IDLE, None)

    best: Task | None = None
    best_score = 0
    for t in tasks:
        s = task_match_score(sample, t)
        if s == 0:
            continue
        if t.id == pinned_task_id:
            s += 1  # tie-breaker
        if s > best_score or (s == best_score and best and t.priority > best.priority):
            best, best_score = t, s
    if best is not None:
        return MatchResult(Category.PRODUCTIVE, best.id)

    distracting = process in _norm(settings.distracting_apps) or any(
        k in title for k in _norm(settings.distracting_keywords)
    )
    if distracting:
        return MatchResult(Category.DISTRACTING, None)

    if pinned_task_id is not None:
        return MatchResult(Category.PRODUCTIVE, pinned_task_id)
    if process in _norm(settings.productive_apps):
        return MatchResult(Category.PRODUCTIVE, None)
    return MatchResult(Category.NEUTRAL, None)
