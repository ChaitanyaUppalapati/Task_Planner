"""Par-time prediction.

Predicts how long a task *should* take (its "par") from the user's own history.

Approach (deliberately transparent, works from the first task):

1. A *base* estimate comes from the best available guess: the user's own guess,
   else the AI breakdown's estimate, else a per-work-type default scaled by the
   number of milestones.
2. For each finished, verified task in history we know ``ratio = actual / base``.
   Similar tasks (same work type, same basis, shared title/tag words, recent)
   are weighted more heavily.
3. Par uses a *low* weighted quantile (40th percentile) of those ratios, so par
   reflects the user's faster runs, not their average. Being slow does not make
   future pars longer; getting faster makes them tighter.
4. With little history the ratio is shrunk toward a prior (planning-fallacy
   correction for human guesses).
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass

from taskplanner.core.models import Estimate, Task, TaskStatus, WorkType

TYPE_DEFAULT_MINUTES: dict[WorkType, float] = {
    WorkType.CODING: 90,
    WorkType.WRITING: 60,
    WorkType.STUDY: 60,
    WorkType.RESEARCH: 60,
    WorkType.DESIGN: 75,
    WorkType.ADMIN: 25,
    WorkType.OTHER: 45,
}

PRIOR_RATIO = {"user": 1.25, "ai": 1.1, "default": 1.0}
PAR_QUANTILE = 0.40
LOW_QUANTILE = 0.20
HIGH_QUANTILE = 0.80
SHRINK_K = 3.0
RECENCY_HALF_LIFE_DAYS = 90.0
MIN_PAR = 5.0

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with", "my", "fix", "do"}


@dataclass
class HistoryPoint:
    work_type: WorkType
    basis: str
    base_minutes: float
    actual_minutes: float
    tokens: frozenset[str]
    completed_at: float

    @property
    def ratio(self) -> float:
        return self.actual_minutes / self.base_minutes


def tokens(text: str, tags: Sequence[str] = ()) -> frozenset[str]:
    words = {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1}
    words.update(t.lower().strip() for t in tags if t.strip())
    return frozenset(words)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def weighted_quantile(values: Sequence[float], weights: Sequence[float], q: float) -> float:
    pairs = sorted(zip(values, weights, strict=True))
    total = sum(w for _, w in pairs)
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    # Midpoint interpolation over the cumulative weight distribution.
    cum = 0.0
    points = []
    for v, w in pairs:
        points.append(((cum + w / 2) / total, v))
        cum += w
    if q <= points[0][0]:
        return points[0][1]
    if q >= points[-1][0]:
        return points[-1][1]
    for (p0, v0), (p1, v1) in zip(points, points[1:], strict=False):
        if p0 <= q <= p1:
            t = 0.0 if p1 == p0 else (q - p0) / (p1 - p0)
            return v0 + t * (v1 - v0)
    return points[-1][1]


def base_estimate(task: Task) -> tuple[float, str]:
    if task.user_guess_minutes and task.user_guess_minutes > 0:
        return float(task.user_guess_minutes), "user"
    guesses = [m.guess_minutes for m in task.milestones if m.guess_minutes]
    if task.ai_guess_minutes and task.ai_guess_minutes > 0:
        return float(task.ai_guess_minutes), "ai"
    if guesses:
        return float(sum(guesses)), "user"
    n = max(1, len(task.milestones))
    return TYPE_DEFAULT_MINUTES[task.work_type] * n**0.8, "default"


def history_from_tasks(tasks: Sequence[Task]) -> list[HistoryPoint]:
    points = []
    for t in tasks:
        if t.status != TaskStatus.DONE or t.base_minutes <= 0 or t.actual_minutes <= 0:
            continue
        if t.badge is not None and t.badge.value == "unverified":
            continue
        points.append(
            HistoryPoint(
                work_type=t.work_type,
                basis=t.par_basis,
                base_minutes=t.base_minutes,
                actual_minutes=t.actual_minutes,
                tokens=tokens(t.title, t.tags),
                completed_at=t.completed_at or t.created_at,
            )
        )
    return points


def _round5(x: float) -> float:
    return max(MIN_PAR, 5.0 * round(x / 5.0))


def predict(task: Task, history: Sequence[HistoryPoint], now: float | None = None) -> Estimate:
    now = now or time.time()
    base, basis = base_estimate(task)
    prior = PRIOR_RATIO[basis]
    task_tokens = tokens(task.title, task.tags)

    ratios: list[float] = []
    weights: list[float] = []
    for h in history:
        w = 1.0 if h.basis == basis else 0.35
        w *= 1.5 if h.work_type == task.work_type else 0.5
        w *= 1.0 + 3.0 * jaccard(task_tokens, h.tokens)
        age_days = max(0.0, (now - h.completed_at) / 86400.0)
        w *= 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        # Clamp absurd outliers (e.g. a task left open for a week).
        ratios.append(min(max(h.ratio, 0.2), 5.0))
        weights.append(w)

    if ratios and sum(weights) > 0:
        n_eff = sum(weights) ** 2 / sum(w * w for w in weights)
        # n_eff counts samples; also scale by how relevant they are on average.
        relevance = min(1.0, sum(weights) / len(weights) / 1.5)
        strength = n_eff * relevance
        blend = strength / (strength + SHRINK_K)
        q_par = weighted_quantile(ratios, weights, PAR_QUANTILE)
        q_low = weighted_quantile(ratios, weights, LOW_QUANTILE)
        q_high = weighted_quantile(ratios, weights, HIGH_QUANTILE)
    else:
        n_eff, blend = 0.0, 0.0
        q_par = q_low = q_high = prior

    ratio = blend * q_par + (1 - blend) * prior
    low_ratio = blend * q_low + (1 - blend) * prior * 0.75
    high_ratio = blend * q_high + (1 - blend) * prior * 1.5

    par = _round5(base * ratio)
    low = min(par, _round5(base * low_ratio))
    high = max(par, _round5(base * high_ratio))

    if n_eff >= 8 and blend > 0.6:
        confidence = "high"
    elif n_eff >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    basis_text = {"user": "your guess", "ai": "the AI breakdown", "default": "the work-type default"}
    if ratios:
        explanation = (
            f"Base {base:.0f} min from {basis_text[basis]}, scaled by {ratio:.2f}x "
            f"(your faster runs on {len(ratios)} similar finished task(s), "
            f"{blend:.0%} weight on history)."
        )
    else:
        explanation = (
            f"Base {base:.0f} min from {basis_text[basis]}, scaled by {ratio:.2f}x. "
            "Par will personalise as you finish tasks."
        )
    return Estimate(
        par_minutes=par,
        low_minutes=low,
        high_minutes=high,
        base_minutes=base,
        basis=basis,
        confidence=confidence,
        samples=len(ratios),
        explanation=explanation,
    )


def apply_estimate(task: Task, est: Estimate) -> None:
    """Write a prediction onto a task and split par across its milestones."""
    task.par_minutes = est.par_minutes
    task.par_low = est.low_minutes
    task.par_high = est.high_minutes
    task.base_minutes = est.base_minutes
    task.par_basis = est.basis
    if not task.is_started:
        task.original_par = est.par_minutes
    distribute_par(task)


def distribute_par(task: Task) -> None:
    if not task.milestones:
        return
    weights = [m.guess_minutes if m.guess_minutes and m.guess_minutes > 0 else None
               for m in task.milestones]
    known = [w for w in weights if w is not None]
    fill = (sum(known) / len(known)) if known else 1.0
    weights = [w if w is not None else fill for w in weights]
    total = sum(weights)
    for m, w in zip(task.milestones, weights, strict=True):
        m.par_minutes = round(task.par_minutes * w / total, 2)


def efficiency_ratio(par: float, actual: float) -> float:
    if actual <= 0:
        return math.inf
    return par / actual
