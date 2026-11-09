from taskplanner.core.models import Category, Milestone, ParBadge, Task, TaskStatus, WorkType


def make_task(engine, guess=60, n=2):
    t = Task(title="Build login page", work_type=WorkType.CODING, user_guess_minutes=guess,
             milestones=[Milestone(f"m{i}", guess_minutes=guess / n) for i in range(n)])
    return engine.create_task(t)


def log_work(db, clock, task_id, minutes):
    start = clock()
    db.add_activity(start, start + minutes * 60, "code.exe", "x", Category.PRODUCTIVE, task_id)
    clock.advance(minutes * 60)


def test_create_task_predicts_and_splits_par(engine):
    t = make_task(engine)
    assert t.id and t.par_minutes == 75
    assert sum(m.par_minutes for m in t.milestones) == 75
    assert t.original_par == 75


def test_progress_earns_par_share_not_time(engine, db, clock):
    t = make_task(engine)
    log_work(db, clock, t.id, 200)  # way over par
    engine.set_milestone_progress(t, t.milestones[0], 1.0)
    assert db.earned_between(0, clock() + 1) == 37.5
    assert t.status == TaskStatus.ACTIVE and t.started_at is not None


def test_progress_never_goes_backwards(engine, db, clock):
    t = make_task(engine)
    engine.set_milestone_progress(t, t.milestones[0], 0.5)
    engine.set_milestone_progress(t, t.milestones[0], 0.2)
    assert t.milestones[0].progress == 0.5
    assert db.earned_between(0, clock() + 1) == 0.5 * t.milestones[0].par_minutes


def test_completion_scores_against_par(engine, db, clock):
    events = []
    engine.subscribe(lambda k, p: events.append(k))
    t = make_task(engine)  # par 75
    log_work(db, clock, t.id, 40)
    badge = engine.complete_task(t)
    assert badge == ParBadge.EAGLE  # 40/75 = 53%
    assert t.status == TaskStatus.DONE
    assert "task_completed" in events and "achievement" in events
    assert db.total_xp() > 75
    assert "first_finish" in db.unlocked()


def test_slow_completion_gets_no_speed_bonus(engine, db, clock):
    fast = make_task(engine)
    log_work(db, clock, fast.id, 40)
    engine.complete_task(fast)
    xp_fast = db.total_xp()
    slow = make_task(engine)
    log_work(db, clock, slow.id, 150)
    assert engine.complete_task(slow) == ParBadge.DOUBLE_BOGEY
    xp_slow = db.total_xp() - xp_fast
    assert xp_slow < xp_fast


def test_par_locked_after_start_and_revisions_counted(engine):
    t = make_task(engine)
    engine.start_task(t)
    t.user_guess_minutes = 500
    engine.update_task(t)
    assert t.par_minutes == 75  # not re-predicted once started
    engine.reestimate(t, 120)
    assert t.revisions == 1 and t.original_par == 75


def test_finalize_days_awards_once(engine, db, clock):
    t = make_task(engine)
    engine.commit_plan(engine.today(), [t])
    log_work(db, clock, t.id, 60)
    engine.complete_task(t)
    clock.advance(86400 * 2)
    days = engine.finalize_days()
    assert days and days[0].score > 0
    xp = db.total_xp()
    assert engine.finalize_days() == []
    assert db.total_xp() == xp


def test_auto_source_readings_apply(engine, db, tmp_path):
    doc = tmp_path / "essay.md"
    doc.write_text("hello world")
    t = Task(title="Essay", work_type=WorkType.WRITING, user_guess_minutes=60,
             milestones=[Milestone("Draft", source_type=__import__(
                 "taskplanner.core.models", fromlist=["SourceType"]).SourceType.DOCUMENT,
                 source_config={"path": str(doc), "target_words": 10})])
    t = engine.create_task(t)
    assert t.milestones[0].baseline["words"] == 2
    doc.write_text("hello world " + "word " * 5)
    t = db.get_task(t.id)
    changed = engine.apply_readings(engine.read_sources([t]))
    assert changed == 1
    t = db.get_task(t.id)
    assert t.milestones[0].progress == 0.5
    doc.write_text("hello world " + "word " * 20)
    engine.apply_readings(engine.read_sources([db.get_task(t.id)]))
    assert db.get_task(t.id).status == TaskStatus.DONE


def test_same_source_milestones_run_in_sequence(engine, db, tmp_path):
    import subprocess

    from taskplanner.core.models import SourceType

    repo = tmp_path / "r"
    repo.mkdir()

    def git(*a):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@e.com")
    git("config", "user.name", "t")

    def commit(name):
        (repo / name).write_text(name)
        git("add", ".")
        git("commit", "-qm", name)

    cfg = {"repo": str(repo), "metric": "commits", "target": 1}
    t = engine.create_task(Task(title="x", user_guess_minutes=60, milestones=[
        Milestone("first", 30, source_type=SourceType.GIT, source_config=dict(cfg)),
        Milestone("second", 30, source_type=SourceType.GIT, source_config=dict(cfg))]))
    assert t.milestones[0].baseline and not t.milestones[1].baseline
    commit("a")
    engine.apply_readings(engine.read_sources([db.get_task(t.id)]))
    t = db.get_task(t.id)
    assert t.milestones[0].progress == 1 and t.milestones[1].progress == 0
    assert t.milestones[1].baseline  # second starts counting after the first finished
    commit("b")
    engine.apply_readings(engine.read_sources([db.get_task(t.id)]))
    assert db.get_task(t.id).status == TaskStatus.DONE
