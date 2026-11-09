"""XP, levels, streaks and achievements."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from taskplanner.core.models import DayStats, ParBadge

# ------------------------------------------------------------------- levels
LEVEL_XP_STEP = 75  # cumulative XP for level n = 75 * n * (n - 1)

TITLES = [
    (1, "Novice"),
    (3, "Apprentice"),
    (6, "Journeyman"),
    (10, "Specialist"),
    (15, "Expert"),
    (20, "Master"),
    (30, "Grandmaster"),
    (40, "Legend"),
]


def xp_for_level(level: int) -> int:
    return LEVEL_XP_STEP * level * (level - 1)


def level_for_xp(xp: int) -> int:
    xp = max(0, xp)
    # Solve 75 n (n-1) <= xp for the largest integer n.
    n = int((1 + math.sqrt(1 + 4 * xp / LEVEL_XP_STEP)) / 2)
    while xp_for_level(n + 1) <= xp:
        n += 1
    while n > 1 and xp_for_level(n) > xp:
        n -= 1
    return max(1, n)


def title_for_level(level: int) -> str:
    title = TITLES[0][1]
    for threshold, name in TITLES:
        if level >= threshold:
            title = name
    return title


@dataclass
class LevelInfo:
    level: int
    title: str
    xp: int
    level_floor: int
    next_level_xp: int

    @property
    def progress(self) -> float:
        span = self.next_level_xp - self.level_floor
        return 0.0 if span <= 0 else (self.xp - self.level_floor) / span


def level_info(xp: int) -> LevelInfo:
    lvl = level_for_xp(xp)
    return LevelInfo(lvl, title_for_level(lvl), xp, xp_for_level(lvl), xp_for_level(lvl + 1))


# ----------------------------------------------------------------------- xp
BADGE_BONUS = {
    ParBadge.EAGLE: 1.0,
    ParBadge.BIRDIE: 0.5,
    ParBadge.PAR: 0.25,
    ParBadge.BOGEY: 0.0,
    ParBadge.DOUBLE_BOGEY: 0.0,
    ParBadge.UNVERIFIED: 0.0,
}
COMPLETION_FLAT_XP = 10
REVISION_PENALTY = 0.8
PLAN_BONUS_THRESHOLD = 0.9


def completion_bonus(par: float, badge: ParBadge, revisions: int) -> int:
    bonus = par * BADGE_BONUS[badge] * (REVISION_PENALTY**revisions)
    return int(round(COMPLETION_FLAT_XP + bonus))


def plan_bonus(stats: DayStats) -> int:
    if stats.planned <= 0 or stats.plan_completion < PLAN_BONUS_THRESHOLD:
        return 0
    return int(round(stats.planned * min(1.0, stats.density) * 0.5))


def streak_bonus(streak: int) -> int:
    return min(100, 10 * streak)


# ------------------------------------------------------------------ streaks
STREAK_MIN_EFFICIENCY = 0.85
STREAK_MIN_PLAN_COMPLETION = 0.8
FREEZE_EVERY = 7
MAX_FREEZES = 2


def day_qualifies(stats: DayStats, goal_minutes: float) -> bool:
    if stats.earned <= 0:
        return False
    if stats.efficiency < STREAK_MIN_EFFICIENCY:
        return False
    if stats.planned > 0:
        return stats.plan_completion >= STREAK_MIN_PLAN_COMPLETION
    return stats.earned >= 0.5 * goal_minutes


@dataclass
class StreakInfo:
    current: int = 0
    best: int = 0
    freezes: int = 0


def compute_streak(days: dict[str, dict], until: str) -> StreakInfo:
    """Walk every calendar day from the first recorded one up to ``until``.

    ``days`` maps ISO date -> stored day data (with "qualified", "earned",
    "spent" keys). Weekend days without any activity are rest days and neither
    extend nor break the streak. Other missed days consume a freeze if one is
    available, otherwise reset the streak.
    """
    info = StreakInfo()
    if not days:
        return info
    cur = date.fromisoformat(min(days))
    end = date.fromisoformat(until)
    run_since_freeze = 0
    while cur <= end:
        key = cur.isoformat()
        d = days.get(key)
        active = bool(d) and (d.get("earned", 0) > 0 or d.get("spent", 0) > 0)
        if d and d.get("qualified"):
            info.current += 1
            run_since_freeze += 1
            if run_since_freeze >= FREEZE_EVERY:
                run_since_freeze = 0
                info.freezes = min(MAX_FREEZES, info.freezes + 1)
        elif not active and cur.weekday() >= 5:
            pass  # weekend rest day
        elif key == until and not (d and d.get("final")):
            pass  # today, still in progress: doesn't break the streak yet
        elif info.freezes > 0 and info.current > 0:
            info.freezes -= 1
        else:
            info.current = 0
            run_since_freeze = 0
        info.best = max(info.best, info.current)
        cur += timedelta(days=1)
    return info


# ------------------------------------------------------------- achievements
@dataclass
class AchievementContext:
    tasks_completed: int = 0
    badge_counts: dict[str, int] = field(default_factory=dict)
    sniper_count: int = 0           # tasks finished within +/-10% of par
    days: list[DayStats] = field(default_factory=list)  # finalized + today, chronological
    streak: int = 0
    level: int = 1
    plan_days: int = 0
    ai_used: bool = False
    goal_minutes: float = 300
    best_earned_before: float = 0.0  # best earned day before the latest day


@dataclass(frozen=True)
class Achievement:
    key: str
    name: str
    description: str
    icon: str
    check: Callable[[AchievementContext], bool]


def _last(ctx: AchievementContext) -> DayStats | None:
    return ctx.days[-1] if ctx.days else None


def _week_efficiency(ctx: AchievementContext) -> float:
    window = [d for d in ctx.days[-7:] if d.spent > 0]
    if len(window) < 5:
        return 0.0
    earned = sum(d.earned for d in window)
    spent = sum(d.spent for d in window)
    return earned / spent if spent > 0 else 0.0


ACHIEVEMENTS: list[Achievement] = [
    Achievement("first_finish", "First Finish", "Complete your first task.", "🏁",
                lambda c: c.tasks_completed >= 1),
    Achievement("birdie", "Birdie", "Finish a task in 85% of par or less.", "🐦",
                lambda c: c.badge_counts.get("birdie", 0) + c.badge_counts.get("eagle", 0) >= 1),
    Achievement("eagle", "Eagle Eye", "Finish a task in 60% of par or less.", "🦅",
                lambda c: c.badge_counts.get("eagle", 0) >= 1),
    Achievement("flock", "Flock", "Finish 10 tasks under par.", "🪶",
                lambda c: c.badge_counts.get("birdie", 0) + c.badge_counts.get("eagle", 0) >= 10),
    Achievement("sniper", "Sniper", "Finish 5 tasks within ±10% of par.", "🎯",
                lambda c: c.sniper_count >= 5),
    Achievement("speedrunner", "Speedrunner", "Finish 3 tasks under par in one day.", "⚡",
                lambda c: any(d.under_par >= 3 for d in c.days)),
    Achievement("clean_sheet", "Clean Sheet",
                "Deliver your whole plan on a day planned at 60%+ density.", "🧹",
                lambda c: any(d.planned > 0 and d.plan_completion >= 0.999 and d.density >= 0.6
                              for d in c.days)),
    Achievement("dense_planner", "Dense Planner",
                "Deliver 90%+ of a plan with 85%+ density.", "📐",
                lambda c: any(d.planned > 0 and d.plan_completion >= 0.9 and d.density >= 0.85
                              for d in c.days)),
    Achievement("planner_pro", "Planner Pro", "Plan your day 10 times.", "🗓️",
                lambda c: c.plan_days >= 10),
    Achievement("goal_day", "Full Output", "Earn your daily output goal in one day.", "🎯",
                lambda c: any(d.earned >= c.goal_minutes for d in c.days)),
    Achievement("overdrive", "Overdrive", "Earn 8 hours of par in one day.", "🚀",
                lambda c: any(d.earned >= 480 for d in c.days)),
    Achievement("efficient_day", "Lean Machine", "A 2h+ day at 125%+ efficiency.", "⚙️",
                lambda c: any(d.spent >= 120 and d.efficiency >= 1.25 for d in c.days)),
    Achievement("efficient_week", "Lean Week", "Average 100%+ efficiency over a week.", "📈",
                lambda c: _week_efficiency(c) >= 1.0),
    Achievement("deep_work", "Deep Work", "90 minutes unbroken on one task.", "🌊",
                lambda c: any(d.longest_focus >= 90 for d in c.days)),
    Achievement("zero_distraction", "Zero Distraction",
                "A 2h+ work day with no distracting time.", "🧘",
                lambda c: any(d.spent >= 120 and d.distracting < 0.5 for d in c.days)),
    Achievement("record", "Record Breaker", "Beat your best earned day.", "🏆",
                lambda c: bool(_last(c)) and c.best_earned_before > 0
                and _last(c).earned > c.best_earned_before),  # type: ignore[union-attr]
    Achievement("score_90", "A-Grade", "Score 90+ in a day.", "🅰️",
                lambda c: any(d.score >= 90 for d in c.days)),
    Achievement("streak_3", "On a Roll", "3-day streak.", "🔥", lambda c: c.streak >= 3),
    Achievement("streak_7", "Week Warrior", "7-day streak.", "🔥", lambda c: c.streak >= 7),
    Achievement("streak_30", "Unstoppable", "30-day streak.", "☄️", lambda c: c.streak >= 30),
    Achievement("tasks_25", "Closer", "Complete 25 tasks.", "📦", lambda c: c.tasks_completed >= 25),
    Achievement("tasks_100", "Centurion", "Complete 100 tasks.", "💯",
                lambda c: c.tasks_completed >= 100),
    Achievement("ai_assist", "Co-pilot", "Break a task down with Claude.", "🤖",
                lambda c: c.ai_used),
    Achievement("level_10", "Specialist", "Reach level 10.", "⭐", lambda c: c.level >= 10),
    Achievement("level_20", "Master", "Reach level 20.", "🌟", lambda c: c.level >= 20),
]

ACHIEVEMENTS_BY_KEY = {a.key: a for a in ACHIEVEMENTS}


def newly_unlocked(ctx: AchievementContext, already: set[str]) -> list[Achievement]:
    return [a for a in ACHIEVEMENTS if a.key not in already and a.check(ctx)]
