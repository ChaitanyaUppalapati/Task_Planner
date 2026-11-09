from taskplanner.core.models import ActivitySample, Category, Milestone, SourceType, Task
from taskplanner.tracking.matcher import classify
from taskplanner.tracking.recorder import ActivityRecorder


def S(t, process, title, idle=0.0, locked=False):
    return ActivitySample(t, process, title, idle, locked)


def tasks():
    return [
        Task(id=1, title="Thesis", match_keywords=["thesis"]),
        Task(id=2, title="App", match_apps=["code.exe"], milestones=[
            Milestone("x", source_type=SourceType.GIT, source_config={"repo": "/src/task_planner"})]),
        Task(id=3, title="Video edit", match_keywords=["youtube studio"]),
    ]


def test_keyword_and_implicit_repo_match(settings):
    assert classify(S(0, "winword.exe", "Thesis.docx - Word"), tasks(), settings).task_id == 1
    r = classify(S(0, "code.exe", "engine.py - task_planner - VS Code"), tasks(), settings)
    assert r.task_id == 2 and r.category == Category.PRODUCTIVE
    # app restricted: same title in a different app doesn't match task 2
    assert classify(S(0, "notepad.exe", "task_planner notes"), tasks(), settings).task_id is None


def test_distraction_and_task_override(settings):
    assert classify(S(0, "chrome.exe", "Funny cats - YouTube"), tasks(), settings).category == Category.DISTRACTING
    r = classify(S(0, "chrome.exe", "Channel content - YouTube Studio"), tasks(), settings)
    assert r.task_id == 3


def test_pinned_absorbs_unmatched_but_not_distractions(settings):
    r = classify(S(0, "explorer.exe", "Downloads"), tasks(), settings, pinned_task_id=1)
    assert r.task_id == 1
    r = classify(S(0, "chrome.exe", "reddit - home"), tasks(), settings, pinned_task_id=1)
    assert r.category == Category.DISTRACTING and r.task_id is None


def test_idle_locked_excluded(settings):
    assert classify(S(0, "code.exe", "x", idle=999), tasks(), settings).category == Category.IDLE
    assert classify(S(0, "", "", locked=True), tasks(), settings).category == Category.IDLE
    settings.excluded_apps = ["keepass.exe"]
    assert classify(S(0, "keepass.exe", "db"), tasks(), settings).excluded


def test_recorder_merges_and_trims_idle(db, settings):
    t = db.save_task(Task(title="Thesis", match_keywords=["thesis"]))
    rec = ActivityRecorder(db, settings)
    ts = [t]
    for i in range(0, 60, 5):
        rec.record(S(1000 + i, "winword.exe", "thesis.docx"), ts, None)
    rows = db.activity_between(0, 10**10)
    assert len(rows) == 1 and rows[0]["end_ts"] - rows[0]["start_ts"] == 55
    for i in range(60, 305, 5):
        rec.record(S(1000 + i, "winword.exe", "thesis.docx", idle=max(0, i - 100)), ts, None)
    # Idle threshold (180s) crossed at t=1280; input stopped at t=1100 -> trimmed back.
    rows = db.activity_between(0, 10**10)
    assert rows[0]["end_ts"] == 1100
    assert rows[-1]["category"] == "idle"


def test_recorder_drift(db, settings):
    db.save_task(Task(title="t"))
    rec = ActivityRecorder(db, settings)
    rec.record(S(0, "chrome.exe", "YouTube"), [], 1)
    r = rec.record(S(120, "chrome.exe", "YouTube"), [], 1)
    assert r.drift_seconds == 120
    assert rec.record(S(125, "code.exe", "x"), [], 1).drift_seconds == 0
