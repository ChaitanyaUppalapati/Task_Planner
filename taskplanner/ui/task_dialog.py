"""Create / edit a task: milestones, evidence sources, par prediction, AI breakdown."""

from __future__ import annotations

import copy
from datetime import date

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from taskplanner.core.models import PRIORITY_LABELS, Milestone, SourceType, Task, WorkType
from taskplanner.ui.controller import Controller
from taskplanner.ui.widgets import fmt_minutes, label

EVIDENCE = [
    ("manual", "Checklist (tick manually)", SourceType.MANUAL, None),
    ("git_commits", "Git: new commits", SourceType.GIT, "commits"),
    ("git_lines", "Git: lines changed", SourceType.GIT, "lines"),
    ("git_message", "Git: commit message contains", SourceType.GIT, "message"),
    ("document_words", "Document: new words", SourceType.DOCUMENT, None),
    ("folder_files", "Folder: new output files", SourceType.FOLDER, None),
]
EVIDENCE_BY_KEY = {e[0]: e for e in EVIDENCE}
COL_TITLE, COL_GUESS, COL_EVIDENCE, COL_TARGET, COL_PATTERN, COL_STATUS = range(6)


def evidence_key(m: Milestone) -> str:
    if m.source_type == SourceType.GIT:
        return {"commits": "git_commits", "lines": "git_lines", "message": "git_message"}.get(
            m.source_config.get("metric", "commits"), "git_commits")
    if m.source_type == SourceType.DOCUMENT:
        return "document_words"
    if m.source_type == SourceType.FOLDER:
        return "folder_files"
    return "manual"


def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


class PathField(QWidget):
    def __init__(self, placeholder: str, folder: bool, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)
        self.folder = folder

    def _browse(self) -> None:
        if self.folder:
            path = QFileDialog.getExistingDirectory(self, "Choose folder", self.edit.text())
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose document", self.edit.text(),
                "Documents (*.docx *.pptx *.odt *.md *.txt *.tex *.rst *.html);;All files (*)")
        if path:
            self.edit.setText(path)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, t: str) -> None:
        self.edit.setText(t or "")


class TaskDialog(QDialog):
    def __init__(self, ctl: Controller, task: Task | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctl = ctl
        self.original = task
        self.task = copy.deepcopy(task) if task else Task(title="")
        self.locked = self.task.is_started
        self._ai_pending = False
        self.setWindowTitle("Edit task" if task else "New task")
        self.resize(900, 760)

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit(self.task.title)
        self.title.setPlaceholderText("What needs to get done? Be specific about the outcome.")
        form.addRow("Title", self.title)
        self.desc = QPlainTextEdit(self.task.description)
        self.desc.setPlaceholderText("Details, definition of done, constraints (also sent to "
                                     "Claude for the breakdown).")
        self.desc.setFixedHeight(70)
        form.addRow("Description", self.desc)

        row = QHBoxLayout()
        self.work_type = QComboBox()
        for w in WorkType:
            self.work_type.addItem(w.label, w.value)
        self.work_type.setCurrentIndex(self.work_type.findData(self.task.work_type.value))
        self.priority = QComboBox()
        for k, v in PRIORITY_LABELS.items():
            self.priority.addItem(v, k)
        self.priority.setCurrentIndex(self.priority.findData(self.task.priority))
        self.has_due = QCheckBox("Due")
        self.due = QDateEdit()
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("yyyy-MM-dd")
        if self.task.due_date:
            self.has_due.setChecked(True)
            self.due.setDate(QDate.fromString(self.task.due_date, "yyyy-MM-dd"))
        else:
            self.due.setDate(QDate.currentDate())
        self.due.setEnabled(self.has_due.isChecked())
        self.has_due.toggled.connect(self.due.setEnabled)
        self.guess = QSpinBox()
        self.guess.setRange(0, 100000)
        self.guess.setSuffix(" min")
        self.guess.setSpecialValueText("no guess")
        self.guess.setValue(int(self.task.user_guess_minutes or 0))
        self.guess.setToolTip("Your own rough estimate. The app calibrates it against your history.")
        for w, text in ((self.work_type, "Type"), (self.priority, "Priority"),
                        (self.guess, "Your guess")):
            row.addWidget(label(text, "Muted"))
            row.addWidget(w)
        row.addWidget(self.has_due)
        row.addWidget(self.due)
        row.addStretch(1)
        form.addRow("", row)
        self.tags = QLineEdit(", ".join(self.task.tags))
        self.tags.setPlaceholderText("comma separated, e.g. thesis, client-x")
        form.addRow("Tags", self.tags)
        lay.addLayout(form)

        links = QGroupBox("Where the work lives (enables automatic progress)")
        lf = QFormLayout(links)
        tl = self.task.links or {}
        self.repo = PathField("Git repository folder", folder=True)
        self.repo.setText(tl.get("repo", ""))
        self.document = PathField("Document you're writing (.docx, .md, .tex, …)", folder=False)
        self.document.setText(tl.get("document", ""))
        frow = QHBoxLayout()
        self.folder = PathField("Folder where outputs appear", folder=True)
        self.folder.setText(tl.get("folder", ""))
        self.folder_pattern = QLineEdit(tl.get("folder_pattern", "*"))
        self.folder_pattern.setFixedWidth(110)
        self.folder_pattern.setToolTip("File pattern, e.g. *.pdf")
        frow.addWidget(self.folder, 1)
        frow.addWidget(self.folder_pattern)
        lf.addRow("Repository", self.repo)
        lf.addRow("Document", self.document)
        lf.addRow("Output folder", frow)
        self.apps = QLineEdit(", ".join(self.task.match_apps))
        self.apps.setPlaceholderText("optional: only count time in these apps, e.g. code.exe, winword.exe")
        self.keywords = QLineEdit(", ".join(self.task.match_keywords))
        self.keywords.setPlaceholderText("window-title keywords, e.g. thesis, jira-123 "
                                         "(file/repo names are added automatically)")
        lf.addRow("Window keywords", self.keywords)
        lf.addRow("Apps", self.apps)
        lay.addWidget(links)

        ms = QGroupBox("Milestones — progress is measured by these, not by time")
        ml = QVBoxLayout(ms)
        tools = QHBoxLayout()
        self.ai_btn = QPushButton("✨ Break down with Claude")
        self.ai_btn.setObjectName("Primary")
        self.ai_btn.setToolTip("Uses your local Claude Code CLI (your Claude subscription).")
        self.ai_btn.clicked.connect(self._ai)
        self.ai_btn.setVisible(ctl.settings.ai_enabled)
        add = QPushButton("+ Milestone")
        add.clicked.connect(lambda: self._add_row(Milestone(title="")))
        rem = QPushButton("Remove")
        rem.clicked.connect(self._remove_row)
        up = QPushButton("↑")
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("↓")
        down.clicked.connect(lambda: self._move(1))
        for b in (self.ai_btn, add, rem, up, down):
            tools.addWidget(b)
        tools.addStretch(1)
        ml.addLayout(tools)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Milestone", "Guess (min)", "Evidence of progress", "Target", "Pattern", "Status"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for c, w in ((COL_GUESS, 90), (COL_EVIDENCE, 210), (COL_TARGET, 70), (COL_PATTERN, 100),
                     (COL_STATUS, 90)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.itemChanged.connect(lambda _i: self._schedule_predict())
        ml.addWidget(self.table)
        lay.addWidget(ms, 1)

        par_row = QHBoxLayout()
        self.par_label = label("", "H2")
        self.par_detail = label("", "Muted", wrap=True)
        par_col = QVBoxLayout()
        par_col.addWidget(self.par_label)
        par_col.addWidget(self.par_detail)
        par_row.addLayout(par_col, 1)
        self.reest_btn = QPushButton("Re-estimate par…")
        self.reest_btn.setVisible(self.locked)
        self.reest_btn.clicked.connect(self._reestimate)
        par_row.addWidget(self.reest_btn)
        lay.addLayout(par_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        for m in self.task.milestones:
            self._add_row(m)
        if not self.task.milestones:
            self._add_row(Milestone(title=""))

        self._predict_timer = QTimer(self)
        self._predict_timer.setSingleShot(True)
        self._predict_timer.timeout.connect(self._predict)
        for w in (self.title.textChanged, self.guess.valueChanged, self.tags.textChanged,
                  self.work_type.currentIndexChanged):
            w.connect(self._schedule_predict)
        ctl.ai_finished.connect(self._ai_done)
        ctl.ai_failed.connect(self._ai_failed)
        self._predict()

    # ---------------------------------------------------------------- table
    def _add_row(self, m: Milestone) -> None:
        self.table.blockSignals(True)
        r = self.table.rowCount()
        self.table.insertRow(r)
        title = QTableWidgetItem(m.title)
        title.setData(Qt.ItemDataRole.UserRole, m.id)
        self.table.setItem(r, COL_TITLE, title)
        self.table.setItem(r, COL_GUESS, QTableWidgetItem(
            f"{m.guess_minutes:.0f}" if m.guess_minutes else ""))
        combo = QComboBox()
        for key, text, _st, _metric in EVIDENCE:
            combo.addItem(text, key)
        combo.setCurrentIndex(combo.findData(evidence_key(m)))
        combo.currentIndexChanged.connect(lambda _i, c=combo: self._evidence_changed(c))
        self.table.setCellWidget(r, COL_EVIDENCE, combo)
        cfg = m.source_config or {}
        target = cfg.get("target") or cfg.get("target_words") or cfg.get("count") or ""
        self.table.setItem(r, COL_TARGET, QTableWidgetItem(f"{float(target):.0f}" if target else ""))
        self.table.setItem(r, COL_PATTERN, QTableWidgetItem(cfg.get("pattern", "")))
        status = QTableWidgetItem("✓ done" if m.progress >= 1 else f"{m.progress:.0%}"
                                  if m.progress else "")
        status.setFlags(Qt.ItemFlag.ItemIsEnabled)
        status.setToolTip(m.evidence)
        self.table.setItem(r, COL_STATUS, status)
        self.table.blockSignals(False)
        self._evidence_changed(combo, set_defaults=False)

    def _row_of(self, combo: QComboBox) -> int:
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, COL_EVIDENCE) is combo:
                return r
        return -1

    def _evidence_changed(self, combo: QComboBox, set_defaults: bool = True) -> None:
        r = self._row_of(combo)
        if r < 0:
            return
        key = combo.currentData()
        defaults = {"git_commits": "1", "git_lines": "100", "document_words": "500",
                    "folder_files": "1"}
        tgt = self.table.item(r, COL_TARGET)
        if set_defaults and tgt is not None:
            tgt.setText(defaults.get(key, ""))
        pat = self.table.item(r, COL_PATTERN)
        if set_defaults and pat is not None and key == "folder_files" and not pat.text():
            pat.setText(self.folder_pattern.text() or "*")

    def _remove_row(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._schedule_predict()

    def _move(self, delta: int) -> None:
        r = self.table.currentRow()
        target = r + delta
        if r < 0 or target < 0 or target >= self.table.rowCount():
            return
        rows = self._read_rows()
        rows[r], rows[target] = rows[target], rows[r]
        self.table.setRowCount(0)
        for m in rows:
            self._add_row(m)
        self.table.selectRow(target)

    def _links(self) -> dict[str, str]:
        out = {"repo": self.repo.text(), "document": self.document.text(),
               "folder": self.folder.text(), "folder_pattern": self.folder_pattern.text() or "*"}
        return {k: v for k, v in out.items() if v}

    def _read_rows(self) -> list[Milestone]:
        existing = {m.id: m for m in self.task.milestones if m.id is not None}
        links = self._links()
        out = []
        for r in range(self.table.rowCount()):
            title_item = self.table.item(r, COL_TITLE)
            title = title_item.text().strip() if title_item else ""
            mid = title_item.data(Qt.ItemDataRole.UserRole) if title_item else None
            try:
                guess = float(self.table.item(r, COL_GUESS).text() or 0) or None
            except (ValueError, AttributeError):
                guess = None
            key = self.table.cellWidget(r, COL_EVIDENCE).currentData()
            _k, _t, st, metric = EVIDENCE_BY_KEY[key]
            try:
                target = float(self.table.item(r, COL_TARGET).text() or 0)
            except (ValueError, AttributeError):
                target = 0.0
            pattern = (self.table.item(r, COL_PATTERN).text() or "").strip()
            cfg: dict = {}
            if st == SourceType.GIT:
                cfg = {"repo": links.get("repo", ""), "metric": metric,
                       "target": target or (100 if metric == "lines" else 1)}
                if metric == "message":
                    cfg["pattern"] = pattern
            elif st == SourceType.DOCUMENT:
                cfg = {"path": links.get("document", ""), "target_words": target or 500}
            elif st == SourceType.FOLDER:
                cfg = {"path": links.get("folder", ""), "pattern": pattern or
                       links.get("folder_pattern", "*"), "count": int(target or 1)}
            m = copy.deepcopy(existing[mid]) if mid in existing else Milestone(title=title)
            m.id = mid if mid in existing else None
            m.title = title
            m.guess_minutes = guess
            if m.source_type != st or m.source_config != cfg:
                m.baseline = {}  # re-capture when the evidence changes
                m.evidence = ""
            m.source_type, m.source_config = st, cfg
            out.append(m)
        return out

    # ------------------------------------------------------------- predict
    def _collect(self) -> Task:
        t = copy.deepcopy(self.task)
        t.title = self.title.text().strip()
        t.description = self.desc.toPlainText().strip()
        t.work_type = WorkType(self.work_type.currentData())
        t.priority = int(self.priority.currentData())
        t.due_date = self.due.date().toString("yyyy-MM-dd") if self.has_due.isChecked() else None
        t.tags = _csv(self.tags.text())
        t.match_apps = [a.lower() for a in _csv(self.apps.text())]
        t.match_keywords = [k.lower() for k in _csv(self.keywords.text())]
        t.user_guess_minutes = float(self.guess.value()) or None
        t.links = self._links()
        t.milestones = [m for m in self._read_rows() if m.title]
        return t

    def _schedule_predict(self) -> None:
        self._predict_timer.start(250)

    def _predict(self) -> None:
        if self.locked:
            t = self.task
            self.par_label.setText(f"Par {fmt_minutes(t.par_minutes)} (locked since you started)")
            orig = t.original_par or t.par_minutes
            rev = f" · revised {t.revisions}×, finish bonus ×{0.8 ** t.revisions:.2f}" \
                if t.revisions else ""
            self.par_detail.setText(f"Original par {fmt_minutes(orig)}{rev}. Re-estimating is "
                                    "allowed but reduces the finish bonus.")
            return
        t = self._collect()
        est = self.ctl.engine.predict(t)
        self.par_label.setText(f"Predicted par: {fmt_minutes(est.par_minutes)}   "
                               f"(likely {fmt_minutes(est.low_minutes)} – "
                               f"{fmt_minutes(est.high_minutes)})")
        self.par_detail.setText(f"Confidence {est.confidence}. {est.explanation}")

    def _reestimate(self) -> None:
        val, ok = QInputDialog.getInt(
            self, "Re-estimate par",
            "New par in minutes.\nThis is logged and multiplies the finish bonus by 0.8.",
            int(self.task.par_minutes), 5, 100000, 5)
        if ok and self.original is not None:
            self.ctl.engine.reestimate(self.original, val)
            self.task.par_minutes = self.original.par_minutes
            self.task.revisions = self.original.revisions
            self._predict()

    # ------------------------------------------------------------------ ai
    def _ai(self) -> None:
        t = self._collect()
        if not t.title:
            QMessageBox.information(self, "Claude", "Give the task a title first.")
            return
        has_rows = any(m.title for m in t.milestones)
        if has_rows and QMessageBox.question(
                self, "Replace milestones?",
                "Replace the current milestones with Claude's breakdown?") \
                != QMessageBox.StandardButton.Yes:
            return
        self._ai_pending = True
        self._ai_task = t
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("Claude is thinking…")
        self.ctl.ai_breakdown(t)

    def _ai_done(self, task: Task, breakdown) -> None:
        if not self._ai_pending or task is not getattr(self, "_ai_task", None):
            return
        self._ai_pending = False
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("✨ Break down with Claude")
        keep = [m for m in self.task.milestones if m.progress > 0]
        self.table.setRowCount(0)
        for m in keep + breakdown.milestones:
            self._add_row(m)
        self.task.ai_guess_minutes = breakdown.total_minutes
        self.work_type.setCurrentIndex(self.work_type.findData(breakdown.work_type.value))
        kws = _csv(self.keywords.text())
        for k in breakdown.match_keywords:
            if k not in kws:
                kws.append(k)
        self.keywords.setText(", ".join(kws))
        if breakdown.notes:
            self.par_detail.setText(breakdown.notes)
        self._predict()

    def _ai_failed(self, message: str) -> None:
        if not self._ai_pending:
            return
        self._ai_pending = False
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("✨ Break down with Claude")
        QMessageBox.warning(self, "Claude breakdown failed", message)

    # --------------------------------------------------------------- accept
    def _accept(self) -> None:
        t = self._collect()
        if not t.title:
            QMessageBox.warning(self, "Missing title", "Give the task a title.")
            return
        for m in t.milestones:
            st = m.source_type
            if st == SourceType.GIT and not t.links.get("repo"):
                return self._need("a Git repository", m)
            if st == SourceType.DOCUMENT and not t.links.get("document"):
                return self._need("a document", m)
            if st == SourceType.FOLDER and not t.links.get("folder"):
                return self._need("an output folder", m)
            if st == SourceType.GIT and m.source_config.get("metric") == "message" \
                    and not m.source_config.get("pattern"):
                QMessageBox.warning(self, "Missing pattern",
                                    f"“{m.title}” needs the commit-message text to look for.")
                return
        if t.due_date:
            try:
                date.fromisoformat(t.due_date)
            except ValueError:
                t.due_date = None
        self.result_task = t
        self.accept()

    def _need(self, what: str, m: Milestone) -> None:
        QMessageBox.warning(self, "Link needed",
                            f"“{m.title}” measures progress from {what}. Set it under "
                            "'Where the work lives', or choose Checklist.")

    def done(self, r: int) -> None:  # disconnect so a closed dialog doesn't react
        try:
            self.ctl.ai_finished.disconnect(self._ai_done)
            self.ctl.ai_failed.disconnect(self._ai_failed)
        except (RuntimeError, TypeError):
            pass
        super().done(r)
