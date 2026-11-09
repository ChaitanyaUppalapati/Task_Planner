from taskplanner.core import scoring
from taskplanner.core.models import Category, DayStats, ParBadge


def test_efficiency_is_output_over_time():
    assert scoring.efficiency(120, 240) == 0.5   # 2h task done in 4h
    assert round(scoring.efficiency(120, 90), 2) == 1.33
    assert scoring.efficiency(100, 1) == scoring.EFFICIENCY_CAP


def test_badges():
    assert scoring.badge_for(100, 50) == ParBadge.EAGLE
    assert scoring.badge_for(100, 80) == ParBadge.BIRDIE
    assert scoring.badge_for(100, 105) == ParBadge.PAR
    assert scoring.badge_for(100, 140) == ParBadge.BOGEY
    assert scoring.badge_for(100, 200) == ParBadge.DOUBLE_BOGEY
    assert scoring.badge_for(100, 10) == ParBadge.UNVERIFIED


def test_slow_day_scores_lower_than_fast_day():
    slow = scoring.score_components(DayStats("d", earned=120, spent=240), 300)
    fast = scoring.score_components(DayStats("d", earned=120, spent=100), 300)
    assert fast.score > slow.score
    assert fast.throughput_score == slow.throughput_score


def test_dense_delivered_plan_beats_tiny_plan():
    tiny = scoring.score_components(
        DayStats("d", earned=60, spent=60, planned=60, planned_earned=60, available=420), 300)
    dense = scoring.score_components(
        DayStats("d", earned=360, spent=360, planned=360, planned_earned=360, available=420), 300)
    assert dense.plan_score > tiny.plan_score
    assert dense.plan_score == scoring.W_PLAN


def test_overplanning_is_penalised():
    over = scoring.score_components(
        DayStats("d", earned=200, spent=200, planned=800, planned_earned=200, available=420), 300)
    assert over.plan_score < scoring.W_PLAN / 2


def test_empty_day_is_zero():
    assert scoring.score_components(DayStats("d"), 300).score == 0


def test_compute_day_from_db(db):
    from taskplanner.core.db import day_bounds
    from taskplanner.core.models import Task

    start, _ = day_bounds("2025-10-01")
    t = db.save_task(Task(title="x", par_minutes=60))
    db.add_activity(start + 3600, start + 3600 + 1800, "code.exe", "x", Category.PRODUCTIVE, t.id)
    db.add_activity(start + 5400, start + 5400 + 600, "chrome.exe", "YouTube", Category.DISTRACTING, None)
    db.add_activity(start + 6000, start + 6000 + 1200, "code.exe", "x", Category.PRODUCTIVE, t.id)
    db.add_activity(start + 7200, start + 7200 + 999, "", "", Category.IDLE, None)
    db.add_progress_event(t.id, None, 1.0, 60, "manual", ts=start + 7000)
    s = scoring.compute_day(db, "2025-10-01", 300, 420)
    assert s.spent == 60  # 30 + 10 distracting + 20
    assert s.distracting == 10
    assert s.earned == 60
    assert s.switches == 2
    assert s.longest_focus == 30
    assert 0 < s.score <= 100
