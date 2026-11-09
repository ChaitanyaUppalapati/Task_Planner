from datetime import date

from taskplanner.core import weekly
from taskplanner.core.models import Category, Milestone, Task, TaskStatus


def test_week_helpers():
    assert weekly.week_key(date(2026, 11, 12)) == "2026-11-09"  # Thu -> Mon
    assert weekly.week_key(date(2026, 11, 9)) == "2026-11-09"
    assert weekly.workdays_elapsed("2026-11-09", date(2026, 11, 11), 5) == 3
    assert weekly.workdays_elapsed("2026-11-09", date(2026, 11, 15), 5) == 5


def test_week_score_and_bonus():
    s = weekly.score_week(weekly.WeekStats("w", goal=1500, earned=1500, spent=1200,
                                           planned=1000, planned_earned=950))
    assert s.output_score == weekly.W_OUTPUT
    assert s.delivery == 0.95
    assert weekly.week_bonus(s) == 250
    missed = weekly.score_week(weekly.WeekStats("w", goal=1500, earned=600, spent=900,
                                                planned=1000, planned_earned=300))
    assert missed.score < s.score and weekly.week_bonus(missed) == 0


def test_pace():
    s = weekly.WeekStats("w", goal=1500, earned=400, work_days=5, days_elapsed=2)
    assert s.expected_now == 600 and s.pace == -200


def _task(engine, title="t"):
    return engine.create_task(Task(title=title, user_guess_minutes=80,
                                   milestones=[Milestone("a", 40), Milestone("b", 40)]))


def test_commit_and_deliver_week(engine, db, clock):
    t1, t2 = _task(engine, "one"), _task(engine, "two")  # par 100 each
    engine.commit_week_plan([t1, t2])
    assert engine.week_commitments() == {t1.id, t2.id}
    db.add_activity(clock(), clock() + 3000, "code.exe", "x", Category.PRODUCTIVE, t1.id)
    clock.advance(3000)
    engine.complete_task(t1)
    ws = engine.week_stats()
    assert ws.tasks_planned == 2 and ws.tasks_done == 1
    assert ws.planned == 200 and ws.planned_earned == 100 and ws.delivery == 0.5


def test_work_before_commit_does_not_count_as_delivered(engine, db, clock):
    t = _task(engine)
    engine.set_milestone_progress(t, t.milestones[0], 1.0)
    clock.advance(60)
    engine.commit_week_plan([db.get_task(t.id)])
    ws = engine.week_stats()
    assert ws.planned == 50 and ws.planned_earned == 0


def test_finalize_week_awards_once(engine, db, clock):
    t = _task(engine)
    engine.commit_week_plan([t])
    db.add_activity(clock(), clock() + 3000, "code.exe", "x", Category.PRODUCTIVE, t.id)
    clock.advance(3000)
    engine.complete_task(t)
    clock.advance(8 * 86400)
    engine.finalize_days()
    weeks = db.finalized_weeks()
    assert weeks and weeks[0][1]["delivery"] == 1.0
    assert db.has_xp_ref(f"weekbonus:{weeks[0][0]}")
    assert "week_delivered" in db.unlocked()
    xp = db.total_xp()
    engine.finalize_days()
    assert db.total_xp() == xp
    assert db.get_task(t.id).status == TaskStatus.DONE


def test_daily_autofill_prefers_weekly_commitments():
    from taskplanner.core.planner import suggest_plan

    a = Task(title="a", priority=3, par_minutes=100, id=1)
    b = Task(title="b", priority=1, par_minutes=100, id=2)
    assert [t.id for t in suggest_plan([a, b], 100, date.today(), frozenset({2}))] == [2]
