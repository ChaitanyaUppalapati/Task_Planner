"""Badge gallery, level ladder and par-badge counts."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from taskplanner.core import gamification
from taskplanner.core.models import ParBadge, TaskStatus
from taskplanner.ui.controller import Controller
from taskplanner.ui.theme import palette
from taskplanner.ui.widgets import Card, StatTile, badge_color, label


class AchievementsView(QScrollArea):
    def __init__(self, ctl: Controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctl = ctl
        self.setWidgetResizable(True)
        root = QWidget()
        self.setWidget(root)
        self.lay = QVBoxLayout(root)
        self.lay.setContentsMargins(24, 20, 24, 24)
        self.lay.setSpacing(14)
        self.lay.addWidget(label("Achievements", "H1"))

        self.level_card = lvl = Card()
        self.level_label = label("", "H2")
        self.xp_bar = QProgressBar()
        self.xp_bar.setRange(0, 1000)
        self.level_sub = label("", "Muted", wrap=True)
        lvl.body.addWidget(self.level_label)
        lvl.body.addWidget(self.xp_bar)
        lvl.body.addWidget(self.level_sub)
        self.lay.addWidget(lvl)

        self.badge_row = QHBoxLayout()
        self.badge_tiles: dict[ParBadge, StatTile] = {}
        for b in (ParBadge.EAGLE, ParBadge.BIRDIE, ParBadge.PAR, ParBadge.BOGEY,
                  ParBadge.DOUBLE_BOGEY):
            tile = StatTile(b.label)
            self.badge_tiles[b] = tile
            self.badge_row.addWidget(tile)
        self.lay.addLayout(self.badge_row)
        self.lay.addWidget(label("Eagle ≤ 60% of par · Birdie ≤ 85% · Par ≤ 110% · Bogey ≤ 150%. "
                                 "Faster finishes earn bigger bonuses.", "Muted", wrap=True))

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(12)
        self.lay.addWidget(self.grid_host)
        self.lay.addStretch(1)
        ctl.data_changed.connect(self._maybe_refresh)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.refresh()

    def _maybe_refresh(self) -> None:
        if self.isVisible():
            self.refresh()

    def refresh(self) -> None:
        p = palette()
        info = self.ctl.engine.level()
        self.level_label.setText(f"Level {info.level} · {info.title} · {info.xp:,} XP")
        self.xp_bar.setValue(int(info.progress * 1000))
        nxt = next((t for lv, t in gamification.TITLES if lv > info.level), None)
        nxt_lv = next((lv for lv, _ in gamification.TITLES if lv > info.level), None)
        self.level_sub.setText(
            f"{info.next_level_xp - info.xp:,} XP to level {info.level + 1}"
            + (f" · “{nxt}” at level {nxt_lv}" if nxt else ""))

        counts: dict[str, int] = {}
        for t in self.ctl.db.list_tasks([TaskStatus.DONE]):
            if t.badge:
                counts[t.badge.value] = counts.get(t.badge.value, 0) + 1
        for b, tile in self.badge_tiles.items():
            tile.set(str(counts.get(b.value, 0)), "", badge_color(b))

        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        unlocked = self.ctl.db.unlocked()
        cols = 3
        ordered = sorted(gamification.ACHIEVEMENTS, key=lambda a: (a.key not in unlocked,))
        for i, a in enumerate(ordered):
            got = a.key in unlocked
            card = Card()
            title = label(f"{a.icon}  {a.name}", "H2")
            if not got:
                title.setStyleSheet(f"color: {p.muted};")
            card.body.addWidget(title)
            card.body.addWidget(label(a.description, "Muted", wrap=True))
            when = (f"Unlocked {datetime.fromtimestamp(unlocked[a.key]):%d %b %Y}" if got
                    else "Locked · +50 XP")
            w = label(when, "Muted")
            if got:
                w.setStyleSheet(f"color: {p.good};")
            card.body.addWidget(w)
            self.grid.addWidget(card, i // cols, i % cols)
