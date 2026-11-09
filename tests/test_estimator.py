from taskplanner.core import estimator
from taskplanner.core.models import Milestone, ParBadge, Task, TaskStatus, WorkType

NOW = 1_760_000_000.0


def done_task(title, base, actual, wt=WorkType.CODING, basis="user"):
    return Task(title=title, work_type=wt, status=TaskStatus.DONE, base_minutes=base,
                actual_minutes=actual, par_basis=basis, completed_at=NOW - 86400,
                badge=ParBadge.PAR)


def test_cold_start_user_guess_applies_planning_fallacy():
    t = Task(title="Write report", user_guess_minutes=60, work_type=WorkType.WRITING)
    est = estimator.predict(t, [], now=NOW)
    assert est.basis == "user"
    assert est.par_minutes == 75  # 60 * 1.25
    assert est.low_minutes <= est.par_minutes <= est.high_minutes
    assert est.confidence == "low"


def test_default_scales_with_milestones():
    t1 = Task(title="x", work_type=WorkType.CODING, milestones=[Milestone("a")])
    t3 = Task(title="x", work_type=WorkType.CODING, milestones=[Milestone(str(i)) for i in range(3)])
    assert estimator.predict(t3, [], NOW).par_minutes > estimator.predict(t1, [], NOW).par_minutes


def test_history_uses_fast_runs_not_average():
    # User consistently takes 1.0x-2.0x their guess; par should sit low in that range.
    tasks = [done_task(f"api endpoint {i}", 60, 60 * r) for i, r in
             enumerate([1.0, 1.1, 1.2, 1.5, 1.8, 2.0, 1.3, 1.4, 1.6, 1.9])]
    hist = estimator.history_from_tasks(tasks)
    t = Task(title="api endpoint new", user_guess_minutes=60, work_type=WorkType.CODING)
    est = estimator.predict(t, hist, now=NOW)
    mean_ratio = sum(h.ratio for h in hist) / len(hist)
    assert est.par_minutes < 60 * mean_ratio
    assert est.par_minutes > 60
    assert est.confidence in ("medium", "high")


def test_being_slow_does_not_inflate_par_much():
    fast = [done_task(f"t{i}", 60, 60) for i in range(6)]
    slow_outlier = fast + [done_task("t-slow", 60, 600)]
    t = Task(title="t new", user_guess_minutes=60, work_type=WorkType.CODING)
    p1 = estimator.predict(t, estimator.history_from_tasks(fast), NOW).par_minutes
    p2 = estimator.predict(t, estimator.history_from_tasks(slow_outlier), NOW).par_minutes
    assert p2 - p1 <= 5


def test_unverified_tasks_excluded_from_history():
    t = done_task("x", 60, 10)
    t.badge = ParBadge.UNVERIFIED
    assert estimator.history_from_tasks([t]) == []


def test_distribute_par_by_guess_weights():
    t = Task(title="x", milestones=[Milestone("a", guess_minutes=30), Milestone("b", guess_minutes=90)])
    t.par_minutes = 100
    estimator.distribute_par(t)
    assert [m.par_minutes for m in t.milestones] == [25, 75]


def test_weighted_quantile():
    assert estimator.weighted_quantile([1, 2, 3], [1, 1, 1], 0.5) == 2
    assert estimator.weighted_quantile([5], [1], 0.1) == 5
