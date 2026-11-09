"""First-run explanation of how scoring works."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from taskplanner.core.settings import save_settings
from taskplanner.ui.widgets import label

TEXT = """
<h2>Welcome to Task Planner ⚡</h2>
<p>This app rewards <b>finished work per hour</b> — not hours logged.</p>
<ul>
<li><b>Par</b> — every task gets a predicted focused time. It learns from your
<i>faster</i> past runs, so it tightens as you improve.</li>
<li><b>Progress is measured by output</b> — milestones complete from git commits / lines
changed, words written in a document, output files appearing in a folder, or a checklist tick.</li>
<li><b>Earned time</b> — each finished milestone earns its share of par. A 2&nbsp;h task done in
4&nbsp;h earns 2&nbsp;h. <b>Efficiency = earned ÷ time spent.</b></li>
<li><b>Plan your day</b> — a dense plan that you deliver earns the Plan Bonus and up to 15
score points.</li>
<li><b>Beat par</b> for Eagles and Birdies, bigger XP, streaks and achievements.</li>
</ul>
<p>Tracking runs in the tray: it reads the active window title and idle time, matches them to
your tasks' keywords, repos and documents, and never leaves your laptop.</p>
<p><b>Start:</b> create a task (Ctrl+N), link where the work lives, click
<i>✨ Break down with Claude</i>, then plan your day.</p>
"""


def show_onboarding(parent: QWidget, ctl) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Welcome")
    dlg.resize(620, 520)
    lay = QVBoxLayout(dlg)
    text = label(TEXT, wrap=True)
    lay.addWidget(text, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Let's go")
    buttons.accepted.connect(dlg.accept)
    lay.addWidget(buttons)
    dlg.exec()
    ctl.settings.onboarded = True
    save_settings(ctl.db, ctl.settings)
