"""Render every page offscreen against a seeded database."""
import time

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from taskplanner.core.models import ActivitySample, Category, Milestone, Task  # noqa: E402
from taskplanner.tracking.sampler import ScriptedSampler  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_all_pages_render(qapp, db, settings):
    from taskplanner.ui.controller import Controller
    from taskplanner.ui.main_window import MainWindow
    from taskplanner.ui.task_dialog import TaskDialog

    now = time.time()
    settings.onboarded = True
    sampler = ScriptedSampler([ActivitySample(now, "code.exe", "proj - VS Code", 0)])
    ctl = Controller(db, settings, sampler=sampler)
    t = ctl.engine.create_task(Task(title="proj work", match_keywords=["proj"],
                                    user_guess_minutes=60,
                                    milestones=[Milestone("a", 30), Milestone("b", 30)]))
    ctl.engine.commit_plan(ctl.engine.today(), [t])
    db.add_activity(now - 600, now - 10, "code.exe", "proj", Category.PRODUCTIVE, t.id)
    ctl.set_pinned(t.id)
    w = MainWindow(ctl)
    w.show()
    ctl.sample_once()
    assert ctl.current_task_id == t.id
    for i in range(6):
        w.go(i)
        qapp.processEvents()
        assert not w.grab().isNull()
    w.dashboard._tick_milestone(t.milestones[0].id)
    assert db.get_task(t.id).progress == pytest.approx(0.5)
    d = TaskDialog(ctl, db.get_task(t.id), w)
    d.show()
    qapp.processEvents()
    collected = d._collect()
    assert collected.title == "proj work" and len(collected.milestones) == 2
    d.reject()
    w.apply_theme("light")
    w.really_quit = True
    w.close()
    ctl.stop()


def test_week_planner_commit(qapp, db, settings):
    from taskplanner.ui.controller import Controller
    from taskplanner.ui.main_window import MainWindow

    settings.onboarded = True
    ctl = Controller(db, settings, sampler=ScriptedSampler([]))
    t = ctl.engine.create_task(Task(title="weekly thing", user_guess_minutes=60))
    w = MainWindow(ctl)
    w.show()
    w.go(2)
    w.planner.setCurrentIndex(1)
    qapp.processEvents()
    wp = w.week_planner
    wp.autofill()
    assert wp._checked_ids() == [t.id]
    wp.commit()
    assert ctl.engine.week_commitments() == {t.id}
    assert ctl.engine.week_stats().planned == t.par_minutes
    w.really_quit = True
    w.close()
    ctl.stop()


def test_ai_breakdown_result_reaches_dialog(qapp, db, settings, monkeypatch):
    """Regression: the worker was garbage-collected and its result silently dropped."""
    import gc
    import time as _time

    from PySide6.QtWidgets import QMessageBox

    from taskplanner.ai import claude_cli
    from taskplanner.core.models import WorkType
    from taskplanner.ui.controller import Controller
    from taskplanner.ui.task_dialog import TaskDialog

    def fake(*_a, **_k):
        _time.sleep(0.3)
        return claude_cli.Breakdown(WorkType.CODING, 60, [Milestone("AI one", 30),
                                                          Milestone("AI two", 30)])

    monkeypatch.setattr(claude_cli, "run_breakdown", fake)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    ctl = Controller(db, settings, sampler=ScriptedSampler([]))
    for _ in range(3):
        d = TaskDialog(ctl, None)
        d.title.setText("Essay")
        d.ai_btn.click()
        gc.collect()
        deadline = _time.time() + 5
        while d._ai_pending and _time.time() < deadline:
            qapp.processEvents()
            _time.sleep(0.02)
        assert not d._ai_pending
        assert [d.table.item(r, 0).text() for r in range(d.table.rowCount())] == ["AI one", "AI two"]
        d.reject()
    ctl.stop()
