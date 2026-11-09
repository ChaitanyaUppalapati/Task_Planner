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
