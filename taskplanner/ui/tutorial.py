"""Interactive guided tour.

A translucent overlay dims the main window and spotlights one control at a time
with an explanation card. The spotlighted area stays clickable (the overlay is
masked there), so steps like "create your first task" are done for real and the
tour moves on when the user does them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QRegion, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from taskplanner.core.settings import save_settings
from taskplanner.ui.theme import palette
from taskplanner.ui.widgets import label

SETTING_KEY = "tutorial"


@dataclass
class Step:
    title: str
    text: str
    page: int | None = None                       # main-window page to show first
    planner_tab: int | None = None                # 0 = Today, 1 = This week
    target: Callable[[], QWidget | None] | None = None
    advance_on: Callable[[], object] | None = None  # returns a signal; firing it = step done
    action: tuple[str, Callable[[], None]] | None = None
    hint: str = ""
    extras: dict = field(default_factory=dict)


def build_steps(win) -> list[Step]:
    """``win`` is the MainWindow."""
    t, d = win.tasks, win.dashboard
    return [
        Step("Welcome to Task Planner ⚡",
             "This quick tour shows how to <b>finish more work in less time</b>.<br><br>"
             "The app scores <b>output, not hours</b>: every task has a predicted time "
             "(<b>par</b>), progress comes from real evidence (commits, words written, files, "
             "checklists), and you're rewarded for beating par.<br><br>"
             "Use <b>Next</b> / <b>Back</b>, or the arrow keys. <b>Esc</b> exits — you can "
             "restart the tour any time from the sidebar or press <b>F1</b>."),
        Step("1 · Create a task",
             "Click <b>+ New task</b> now (or press Ctrl+N).<br><br>In the editor:<ul>"
             "<li>Give it a specific outcome as the title.</li>"
             "<li>Link <b>where the work lives</b> — a git repo, the document you're writing, "
             "or the folder where outputs appear. That's how progress is detected "
             "automatically.</li>"
             "<li>Click <b>✨ Break down with Claude</b> for milestones and estimates.</li></ul>"
             "The tour continues when you close the editor.",
             page=1, target=lambda: t.new_btn, advance_on=lambda: t.new_btn.clicked,
             hint="Try it: click the highlighted button"),
        Step("2 · Par and pace",
             "Each row shows <b>progress</b> (from milestones), <b>par</b> (predicted focused "
             "time), time <b>spent</b>, and whether you're <b>ahead or behind par</b>.<br><br>"
             "Par learns from your <i>faster</i> past runs, so it tightens as you improve. It "
             "locks once you start; re-estimating is allowed but shrinks the finish bonus.",
             page=1, target=lambda: t.table),
        Step("3 · Say what you're working on",
             "Select a task and click <b>📌 Work on this</b>. Time in non-distracting windows "
             "then counts toward it, and the dashboard shows a live pace meter.<br><br>"
             "Tracking also matches windows automatically by repo/document names and your "
             "keywords, so pinning is optional.",
             page=1, target=lambda: t.actions_bar),
        Step("4 · Plan your day",
             "Tick tasks or press <b>⚡ Auto-fill</b>, then <b>Commit plan for today</b>.<br><br>"
             "A dense plan (85%+ of your available hours) that you actually deliver earns the "
             "<b>Plan Bonus</b> and up to 15 score points. Only work done <i>after</i> "
             "committing counts.",
             page=2, planner_tab=0, target=lambda: win.day_planner.commit_btn.parentWidget(),
             advance_on=lambda: win.day_planner.commit_btn.clicked),
        Step("5 · Commit to the week",
             "On Monday, commit the tasks you'll finish this week against your weekly output "
             "goal. Deliver 90%+ for the <b>weekly bonus</b>. Committed tasks get a ★ and are "
             "planned first each day.",
             page=2, planner_tab=1, target=lambda: win.week_planner.commit_btn.parentWidget(),
             advance_on=lambda: win.week_planner.commit_btn.clicked),
        Step("6 · Your daily score",
             "<b>Throughput</b> (output vs. goal) 40 · <b>Efficiency</b> (output ÷ time) 35 · "
             "<b>Plan</b> delivered 15 · <b>Focus</b> 10.<br><br>A 2 h task done in 4 h earns "
             "only 2 h of output — that's 50% efficiency. Beat par to push it above 100%.",
             page=0, target=lambda: d.score_card),
        Step("7 · Live pace",
             "While you work, this card shows how far ahead or behind par you are. Tick "
             "checklist milestones here (or from the tray icon). Auto-tracked milestones "
             "update themselves from your commits, words and files.",
             page=0, target=lambda: d.current_card),
        Step("8 · Weekly target",
             "Your output against the weekly goal, the pace you need by today, and how much of "
             "your weekly commitment is delivered.",
             page=0, target=lambda: d.week_card),
        Step("9 · Clean up unassigned time",
             "Anything tracked that didn't match a task lands here. Assign it in one click — "
             "and add keywords to the task so it matches automatically next time.",
             page=3, target=lambda: win.insights.inbox_card),
        Step("10 · Levels, badges, streaks",
             "XP comes from output. Finishing under par earns <b>Eagles</b> (≤60% of par) and "
             "<b>Birdies</b> (≤85%) with bigger bonuses. Keep a streak with 85%+ efficiency "
             "and a delivered plan.",
             page=4, target=lambda: win.achievements.level_card),
        Step("11 · Claude and tracking settings",
             "Set your goals and working hours, distracting apps, and private apps that are "
             "never tracked. The AI breakdown uses your local <b>claude</b> CLI — run "
             "<code>claude</code> once in a terminal to sign in with your subscription.",
             page=5, target=lambda: win.settings_page.ai_group),
        Step("You're ready 🚀",
             "Task Planner keeps tracking from the <b>system tray</b> when you close this "
             "window — right-click the tray icon to switch tasks, tick milestones or pause.<br>"
             "<br>Start now: create a task, plan your day, and beat par.",
             page=0,
             action=("Create my first task", lambda: (win.go(1), win.tasks.new_task()))),
    ]


class _Card(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        p = palette()
        self.setObjectName("TourCard")
        self.setStyleSheet(
            f"#TourCard {{ background: {p.surface}; border: 2px solid {p.accent}; "
            f"border-radius: 14px; }} #TourCard QLabel {{ background: transparent; }}")
        self.setFixedWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        self.counter = label("", "Muted")
        self.title = label("", "H2")
        self.title.setWordWrap(True)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.hint = label("", "Muted", wrap=True)
        self.hint.setStyleSheet(f"color: {p.accent2}; font-weight: 600;")
        lay.addWidget(self.counter)
        lay.addWidget(self.title)
        lay.addWidget(self.text)
        lay.addWidget(self.hint)
        row = QHBoxLayout()
        self.skip = QPushButton("Exit tour")
        self.back = QPushButton("Back")
        self.action = QPushButton("")
        self.next = QPushButton("Next")
        self.next.setObjectName("Primary")
        self.action.setObjectName("Primary")
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.back)
        row.addWidget(self.action)
        row.addWidget(self.next)
        lay.addLayout(row)


class TourOverlay(QWidget):
    finished = Signal(bool)  # True = completed, False = exited early

    PAD = 8

    def __init__(self, window, steps: list[Step]):
        super().__init__(window)
        self.win = window
        self.steps = steps
        self.index = 0
        self.hole = QRect()
        self._advance_conn: tuple[object, Callable] | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.card = _Card(self)
        self.card.next.clicked.connect(self.next)
        self.card.back.clicked.connect(self.back)
        self.card.skip.clicked.connect(lambda: self.close_tour(False))
        self.card.action.clicked.connect(self._run_action)
        for key, fn in ((Qt.Key.Key_Right, self.next), (Qt.Key.Key_Left, self.back),
                        (Qt.Key.Key_Escape, lambda: self.close_tour(False))):
            QShortcut(QKeySequence(key), self, activated=fn,
                      context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        window.installEventFilter(self)
        self.setGeometry(window.rect())

    # ----------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.show()
        self.raise_()
        self.setFocus()
        self.show_step(0)

    def close_tour(self, completed: bool) -> None:
        self._disconnect_advance()
        self.win.removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.deleteLater()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.win and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setGeometry(self.win.rect())
            QTimer.singleShot(0, self._layout)
        return False

    # --------------------------------------------------------------- steps
    def next(self) -> None:
        if self.index >= len(self.steps) - 1:
            self.close_tour(True)
        else:
            self.show_step(self.index + 1)

    def back(self) -> None:
        if self.index > 0:
            self.show_step(self.index - 1)

    def show_step(self, i: int) -> None:
        self._disconnect_advance()
        self.index = i
        step = self.steps[i]
        if step.page is not None:
            self.win.go(step.page)
        if step.planner_tab is not None:
            self.win.planner.setCurrentIndex(step.planner_tab)
        c = self.card
        c.counter.setText(f"Step {i + 1} of {len(self.steps)}")
        c.title.setText(step.title)
        c.text.setText(step.text)
        c.hint.setText(step.hint)
        c.hint.setVisible(bool(step.hint))
        c.back.setEnabled(i > 0)
        last = i == len(self.steps) - 1
        c.next.setText("Finish" if last else "Next")
        c.action.setVisible(step.action is not None)
        if step.action:
            c.action.setText(step.action[0])
        if step.advance_on:
            sig = step.advance_on()
            slot = self._advance_from_signal
            sig.connect(slot)
            self._advance_conn = (sig, slot)
        # Let the page switch and layout settle before measuring the target.
        QTimer.singleShot(0, self._layout)
        QTimer.singleShot(60, self._layout)

    def _advance_from_signal(self, *_args) -> None:
        # The target's own handler (e.g. a modal dialog) has finished by now.
        QTimer.singleShot(0, self.next)

    def _disconnect_advance(self) -> None:
        if self._advance_conn:
            sig, slot = self._advance_conn
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
            self._advance_conn = None

    def _run_action(self) -> None:
        step = self.steps[self.index]
        if not step.action:
            return
        fn = step.action[1]
        self.close_tour(True)
        QTimer.singleShot(0, fn)

    # -------------------------------------------------------------- layout
    def _target_rect(self) -> QRect:
        step = self.steps[self.index]
        widget = step.target() if step.target else None
        if widget is None or not widget.isVisible():
            return QRect()
        scroll = widget.parentWidget()
        while scroll is not None and not isinstance(scroll, QScrollArea):
            scroll = scroll.parentWidget()
        if isinstance(scroll, QScrollArea):
            scroll.ensureWidgetVisible(widget, 20, 20)
        top_left = widget.mapTo(self.win, QPoint(0, 0))
        r = QRect(top_left, widget.size()).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)
        return r.intersected(self.rect().adjusted(4, 4, -4, -4))

    def _layout(self) -> None:
        if not self.isVisible():
            return
        self.setGeometry(self.win.rect())
        self.hole = self._target_rect()
        card = self.card
        card.adjustSize()
        cw, ch = card.width(), card.sizeHint().height()
        card.resize(cw, ch)
        W, H = self.width(), self.height()
        margin = 16
        if self.hole.isNull():
            pos = QPoint((W - cw) // 2, (H - ch) // 2)
        else:
            h = self.hole
            candidates = [
                QPoint(h.left(), h.bottom() + margin),                 # below
                QPoint(h.left(), h.top() - ch - margin),               # above
                QPoint(h.right() + margin, h.top()),                   # right
                QPoint(h.left() - cw - margin, h.top()),               # left
            ]
            pos = None
            for c in candidates:
                x = max(margin, min(c.x(), W - cw - margin))
                y = max(margin, min(c.y(), H - ch - margin))
                if not QRect(x, y, cw, ch).intersects(h):
                    pos = QPoint(x, y)
                    break
            if pos is None:
                # Target nearly fills the window: spotlight only its top part and put
                # the card underneath.
                bottom = max(h.top() + 120, H - ch - 2 * margin)
                self.hole = QRect(h.left(), h.top(), h.width(), bottom - h.top())
                pos = QPoint(max(margin, min(h.left(), W - cw - margin)),
                             min(H - ch - margin, self.hole.bottom() + margin))
        card.move(pos)
        card.raise_()
        region = QRegion(self.rect())
        if not self.hole.isNull():
            region = region.subtracted(QRegion(self.hole))
        self.setMask(region)
        self.update()

    def paintEvent(self, _event) -> None:
        p = palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if not self.hole.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self.hole), 10, 10)
            path = path.subtracted(hole)
        qp.fillPath(path, QColor(0, 0, 0, 165))
        if not self.hole.isNull():
            qp.setPen(QPen(QColor(p.accent2), 3))
            qp.drawRoundedRect(QRectF(self.hole).adjusted(1, 1, -1, -1), 10, 10)


# ------------------------------------------------------------- entry points
def tutorial_state(db) -> dict:
    state = db.get_setting(SETTING_KEY, None) or {}
    state.setdefault("completed", False)
    state.setdefault("remind", True)
    return state


def save_state(db, **changes) -> None:
    state = tutorial_state(db)
    state.update(changes)
    db.set_setting(SETTING_KEY, state)


def start_tour(window, ctl) -> TourOverlay | None:
    existing = getattr(window, "_tour", None)
    if existing is not None and existing.isVisible():
        return existing
    window.showNormal()
    window.raise_()
    window.activateWindow()
    overlay = TourOverlay(window, build_steps(window))

    def done(completed: bool) -> None:
        window._tour = None
        if completed:
            save_state(ctl.db, completed=True)
        ctl.settings.onboarded = True
        save_settings(ctl.db, ctl.settings)

    overlay.finished.connect(done)
    window._tour = overlay
    overlay.start()
    return overlay


class WelcomeDialog(QDialog):
    """First-run prompt: take the tour now or later."""

    def __init__(self, parent: QWidget, remind_default: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Welcome to Task Planner")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(12)
        lay.addWidget(label("Welcome to Task Planner ⚡", "H1"))
        body = label("Task Planner rewards <b>finished work per hour</b>, not hours logged. "
                     "A 2-minute interactive tour shows you how to create tasks, plan your "
                     "day and week, and beat par.", wrap=True)
        body.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(body)
        lay.addWidget(label("You can start the tour later from the sidebar (🎓 Tutorial), the "
                            "tray menu, Settings, or by pressing F1.", "Muted", wrap=True))
        self.remind = QCheckBox("Remind me when the app starts")
        self.remind.setChecked(remind_default)
        lay.addWidget(self.remind)
        row = QHBoxLayout()
        later = QPushButton("Maybe later")
        later.clicked.connect(self.reject)
        start = QPushButton("Start the tour")
        start.setObjectName("Primary")
        start.setDefault(True)
        start.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(later)
        row.addWidget(start)
        lay.addLayout(row)


def maybe_prompt(window, ctl, force: bool = False) -> None:
    """Show the welcome prompt on first run (or when reminders are on)."""
    state = tutorial_state(ctl.db)
    if state["completed"] or (not state["remind"] and not force):
        return
    dlg = WelcomeDialog(window, remind_default=state["remind"])
    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    save_state(ctl.db, remind=dlg.remind.isChecked())
    if accepted:
        start_tour(window, ctl)
