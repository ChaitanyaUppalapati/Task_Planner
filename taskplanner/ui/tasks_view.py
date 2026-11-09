"""Task list with actions."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from taskplanner.core.models import PRIORITY_LABELS, Task, TaskStatus
from taskplanner.ui.controller import Controller
from taskplanner.ui.task_dialog import TaskDialog
from taskplanner.ui.theme import palette
from taskplanner.ui.widgets import badge_color, fmt_minutes, label

COLUMNS = ["Task", "Type", "Priority", "Due", "Progress", "Par", "Spent", "Pace / result"]


class _NumItem(QTableWidgetItem):
    def __init__(self, text: str, value: float):
        super().__init__(text)
        self.value = value

    def __lt__(self, other) -> bool:
        if isinstance(other, _NumItem):
            return self.value < other.value
        return super().__lt__(other)


class TasksView(QWidget):
    def __init__(self, ctl: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctl = ctl
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 24)
        head = QHBoxLayout()
        head.addWidget(label("Tasks", "H1"))
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self.refresh)
        self.filter = QComboBox()
        for text, val in (("Open", "open"), ("Done", "done"), ("Archived", "archived"),
                          ("All", "all")):
            self.filter.addItem(text, val)
        self.filter.currentIndexChanged.connect(self.refresh)
        new = QPushButton("+ New task")
        new.setObjectName("Primary")
        new.clicked.connect(self.new_task)
        head.addWidget(self.search)
        head.addWidget(self.filter)
        head.addWidget(new)
        lay.addLayout(head)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(COLUMNS)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda _i: self.edit_task())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        lay.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.b_edit = QPushButton("Edit")
        self.b_edit.clicked.connect(self.edit_task)
        self.b_pin = QPushButton("📌 Work on this")
        self.b_pin.clicked.connect(self.pin_task)
        self.b_done = QPushButton("✓ Mark done")
        self.b_done.clicked.connect(self.complete_task)
        self.b_reopen = QPushButton("Reopen")
        self.b_reopen.clicked.connect(self.reopen_task)
        self.b_archive = QPushButton("Archive")
        self.b_archive.clicked.connect(self.archive_task)
        self.b_delete = QPushButton("Delete")
        self.b_delete.setObjectName("Danger")
        self.b_delete.clicked.connect(self.delete_task)
        for b in (self.b_edit, self.b_pin, self.b_done, self.b_reopen, self.b_archive):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.b_delete)
        lay.addLayout(actions)
        self.hint = label("", "Muted", wrap=True)
        lay.addWidget(self.hint)

        ctl.data_changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------- data
    def _tasks(self) -> list[Task]:
        f = self.filter.currentData()
        db = self.ctl.db
        if f == "open":
            tasks = db.open_tasks()
        elif f == "done":
            tasks = sorted(db.list_tasks([TaskStatus.DONE]),
                           key=lambda t: t.completed_at or 0, reverse=True)
        elif f == "archived":
            tasks = db.list_tasks([TaskStatus.ARCHIVED])
        else:
            tasks = db.list_tasks()
        q = self.search.text().strip().lower()
        if q:
            tasks = [t for t in tasks if q in t.title.lower() or any(q in g.lower() for g in t.tags)]
        return tasks

    def refresh(self) -> None:
        p = palette()
        selected = self.selected_id()
        tasks = self._tasks()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(tasks))
        today = date.today()
        for r, t in enumerate(tasks):
            spent = self.ctl.engine.refresh_actual(t) if t.status != TaskStatus.DONE \
                else t.actual_minutes
            title = QTableWidgetItem(("📌 " if t.id == self.ctl.pinned_task_id else "") + t.title)
            title.setData(Qt.ItemDataRole.UserRole, t.id)
            title.setToolTip(t.description or t.title)
            self.table.setItem(r, 0, title)
            self.table.setItem(r, 1, QTableWidgetItem(t.work_type.label))
            self.table.setItem(r, 2, _NumItem(PRIORITY_LABELS.get(t.priority, "?"), t.priority))
            due = QTableWidgetItem(t.due_date or "")
            if t.due_date and t.status != TaskStatus.DONE:
                try:
                    if date.fromisoformat(t.due_date) < today:
                        due.setForeground(QColor(p.bad))
                except ValueError:
                    pass
            self.table.setItem(r, 3, due)
            done_ms = sum(1 for m in t.milestones if m.progress >= 1)
            self.table.setItem(r, 4, _NumItem(
                f"{t.progress:.0%}  ({done_ms}/{len(t.milestones)})", t.progress))
            self.table.setItem(r, 5, _NumItem(fmt_minutes(t.par_minutes), t.par_minutes))
            self.table.setItem(r, 6, _NumItem(fmt_minutes(spent), spent))
            if t.status == TaskStatus.DONE and t.badge:
                par = t.original_par or t.par_minutes
                res = QTableWidgetItem(f"{t.badge.label} ({t.actual_minutes / par:.0%} of par)"
                                       if par else t.badge.label)
                res.setForeground(QColor(badge_color(t.badge)))
            elif t.is_started:
                pace = t.earned_minutes - spent
                res = QTableWidgetItem(("▲ ahead " if pace >= 0 else "▼ behind ")
                                       + fmt_minutes(abs(pace)))
                res.setForeground(QColor(p.good if pace >= 0 else p.bad))
            else:
                res = QTableWidgetItem("not started")
                res.setForeground(QColor(p.muted))
            self.table.setItem(r, 7, res)
        self.table.setSortingEnabled(True)
        if selected is not None:
            for r in range(self.table.rowCount()):
                if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == selected:
                    self.table.selectRow(r)
                    break
        self.hint.setText("Par is the predicted focused time. Progress comes from milestones "
                          "(commits, words, output files or checklist), never from time spent.")
        self._update_buttons()

    def selected_id(self) -> int | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def selected_task(self) -> Task | None:
        tid = self.selected_id()
        return self.ctl.db.get_task(tid) if tid is not None else None

    def _update_buttons(self) -> None:
        t = self.selected_task()
        is_open = t is not None and t.status in (TaskStatus.TODO, TaskStatus.ACTIVE)
        self.b_edit.setEnabled(t is not None)
        self.b_pin.setEnabled(is_open)
        self.b_done.setEnabled(is_open)
        self.b_reopen.setEnabled(t is not None and not is_open)
        self.b_archive.setEnabled(t is not None and t.status != TaskStatus.ARCHIVED)
        self.b_delete.setEnabled(t is not None)

    # ---------------------------------------------------------- actions
    def new_task(self) -> None:
        dlg = TaskDialog(self.ctl, None, self)
        if dlg.exec():
            self.ctl.engine.create_task(dlg.result_task)
            self.ctl.invalidate()

    def edit_task(self) -> None:
        t = self.selected_task()
        if t is None:
            return
        dlg = TaskDialog(self.ctl, t, self)
        if dlg.exec():
            updated = dlg.result_task
            fresh = self.ctl.db.get_task(t.id)  # pick up re-estimates made inside the dialog
            if fresh:
                updated.par_minutes = fresh.par_minutes
                updated.revisions = fresh.revisions
            self.ctl.engine.update_task(updated)
            self.ctl.invalidate()

    def pin_task(self) -> None:
        t = self.selected_task()
        if t:
            self.ctl.set_pinned(t.id)

    def complete_task(self) -> None:
        t = self.selected_task()
        if t is None:
            return
        open_ms = [m for m in t.milestones if m.progress < 1]
        if len(open_ms) > 0 and QMessageBox.question(
                self, "Mark done",
                f"{len(open_ms)} milestone(s) are not detected as done yet. Mark the whole "
                "task done anyway?") != QMessageBox.StandardButton.Yes:
            return
        self.ctl.engine.complete_task(t)
        self.ctl.invalidate()

    def reopen_task(self) -> None:
        t = self.selected_task()
        if t:
            self.ctl.engine.reopen_task(t)
            self.ctl.invalidate()

    def archive_task(self) -> None:
        t = self.selected_task()
        if t:
            if t.id == self.ctl.pinned_task_id:
                self.ctl.set_pinned(None)
            self.ctl.engine.archive_task(t)
            self.ctl.invalidate()

    def delete_task(self) -> None:
        t = self.selected_task()
        if t is None:
            return
        if QMessageBox.question(self, "Delete task",
                                f"Delete “{t.title}” and its progress history? XP already "
                                "earned is kept.") != QMessageBox.StandardButton.Yes:
            return
        if t.id == self.ctl.pinned_task_id:
            self.ctl.set_pinned(None)
        self.ctl.engine.delete_task(t)
        self.ctl.invalidate()
