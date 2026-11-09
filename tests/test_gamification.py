from taskplanner.core import gamification as g
from taskplanner.core.models import DayStats, ParBadge


def test_levels_monotonic_and_consistent():
    assert g.level_for_xp(0) == 1
    assert g.level_for_xp(149) == 1
    assert g.level_for_xp(150) == 2
    for xp in range(0, 50000, 137):
        lvl = g.level_for_xp(xp)
        assert g.xp_for_level(lvl) <= xp < g.xp_for_level(lvl + 1)


def test_completion_bonus_rewards_speed_and_penalises_revisions():
    eagle = g.completion_bonus(60, ParBadge.EAGLE, 0)
    bogey = g.completion_bonus(60, ParBadge.BOGEY, 0)
    revised = g.completion_bonus(60, ParBadge.EAGLE, 2)
    assert eagle > revised > bogey


def test_plan_bonus_requires_delivery():
    done = DayStats("d", planned=300, planned_earned=290, available=420)
    missed = DayStats("d", planned=300, planned_earned=100, available=420)
    assert g.plan_bonus(done) > 0
    assert g.plan_bonus(missed) == 0


def test_streak_counts_qualified_and_skips_weekend_rest():
    # 2025-10-06 is a Monday.
    days = {
        "2025-10-02": {"qualified": True, "earned": 300, "spent": 300},  # Thu
        "2025-10-03": {"qualified": True, "earned": 300, "spent": 300},  # Fri
        # Sat/Sun absent -> rest
        "2025-10-06": {"qualified": True, "earned": 300, "spent": 300},  # Mon
    }
    assert g.compute_streak(days, "2025-10-06").current == 3


def test_streak_breaks_on_missed_weekday():
    days = {
        "2025-10-01": {"qualified": True, "earned": 300, "spent": 300},
        "2025-10-02": {"qualified": False, "earned": 50, "spent": 300, "final": True},
        "2025-10-03": {"qualified": True, "earned": 300, "spent": 300},
    }
    s = g.compute_streak(days, "2025-10-03")
    assert s.current == 1 and s.best == 1


def test_today_in_progress_does_not_break_streak():
    days = {"2025-10-01": {"qualified": True, "earned": 1, "spent": 1},
            "2025-10-02": {"qualified": False, "earned": 0, "spent": 10}}
    assert g.compute_streak(days, "2025-10-02").current == 1


def test_achievement_keys_unique():
    keys = [a.key for a in g.ACHIEVEMENTS]
    assert len(keys) == len(set(keys))
