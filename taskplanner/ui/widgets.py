"""Reusable custom-painted widgets."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from taskplanner.core.models import ParBadge
from taskplanner.ui.theme import palette


def fmt_minutes(minutes: float) -> str:
    minutes = max(0.0, minutes)
    if minutes < 1:
        return "0m"
    h, m = divmod(int(round(minutes)), 60)
    if h and m:
        return f"{h}h {m:02d}m"
    return f"{h}h" if h else f"{m}m"


def fmt_signed_minutes(minutes: float) -> str:
    sign = "+" if minutes >= 0 else "−"
    return sign + fmt_minutes(abs(minutes))


def badge_color(badge: ParBadge | None) -> str:
    p = palette()
    return {
        ParBadge.EAGLE: p.gold,
        ParBadge.BIRDIE: p.good,
        ParBadge.PAR: p.accent2,
        ParBadge.BOGEY: p.warn,
        ParBadge.DOUBLE_BOGEY: p.bad,
        ParBadge.UNVERIFIED: p.muted,
    }.get(badge, p.muted) if badge else p.muted


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    if obj:
        lbl.setObjectName(obj)
    lbl.setWordWrap(wrap)
    return lbl


class Card(QFrame):
    def __init__(self, title: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(8)
        if title:
            self.body.addWidget(label(title, "H2"))


class ScoreRing(QWidget):
    """Circular 0-100 gauge."""

    def __init__(self, size: int = 170, parent: QWidget | None = None):
        super().__init__(parent)
        self._value = 0.0
        self._caption = "score"
        self._size = size
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def set_value(self, value: float, caption: str = "score") -> None:
        self._value = max(0.0, min(100.0, value))
        self._caption = caption
        self.update()

    def paintEvent(self, _event) -> None:
        p = palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        pen_w = side * 0.09
        rect = QRectF((self.width() - side) / 2 + pen_w / 2, (self.height() - side) / 2 + pen_w / 2,
                      side - pen_w, side - pen_w)
        track = QPen(QColor(p.surface2), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        qp.setPen(track)
        qp.drawArc(rect, 0, 360 * 16)
        if self._value >= 75:
            color = p.good
        elif self._value >= 50:
            color = p.accent2
        elif self._value >= 25:
            color = p.warn
        else:
            color = p.bad
        qp.setPen(QPen(QColor(color), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        qp.drawArc(rect, 90 * 16, int(-360 * 16 * self._value / 100))
        qp.setPen(QColor(p.text))
        f = QFont(self.font())
        f.setPointSizeF(side * 0.17)
        f.setBold(True)
        qp.setFont(f)
        qp.drawText(rect.adjusted(0, -side * 0.08, 0, -side * 0.08), Qt.AlignmentFlag.AlignCenter,
                    f"{self._value:.0f}")
        f.setPointSizeF(side * 0.065)
        f.setBold(False)
        qp.setFont(f)
        qp.setPen(QColor(p.muted))
        qp.drawText(rect.adjusted(0, side * 0.2, 0, side * 0.2), Qt.AlignmentFlag.AlignCenter,
                    self._caption)


class StatTile(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)
        self.title = label(title, "Muted")
        self.value = label("—", "Big")
        self.sub = label("", "Muted")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.value.setStyleSheet(f"color: {color};" if color else "")


class ComponentBar(QWidget):
    """Label + bar + "x / max" for a score component."""

    def __init__(self, name: str, maximum: float, parent: QWidget | None = None):
        super().__init__(parent)
        self.maximum = maximum
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.name = label(name)
        self.name.setFixedWidth(90)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(10)
        self.value = label("0", "Muted")
        self.value.setFixedWidth(60)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.name)
        lay.addWidget(self.bar, 1)
        lay.addWidget(self.value)

    def set(self, value: float, tooltip: str = "") -> None:
        self.bar.setValue(int(1000 * value / self.maximum) if self.maximum else 0)
        self.value.setText(f"{value:.0f} / {self.maximum:.0f}")
        self.setToolTip(tooltip)


class BarChart(QWidget):
    """Simple vertical bar chart with optional second series drawn as a line."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.labels: list[str] = []
        self.values: list[float] = []
        self.line: list[float] | None = None
        self.max_value: float | None = None
        self.fmt = lambda v: f"{v:.0f}"
        self.reference: float | None = None
        self.setMinimumHeight(180)

    def set_data(self, labels: Sequence[str], values: Sequence[float],
                 line: Sequence[float] | None = None, max_value: float | None = None,
                 reference: float | None = None, fmt=None) -> None:
        self.labels, self.values = list(labels), list(values)
        self.line = list(line) if line is not None else None
        self.max_value = max_value
        self.reference = reference
        if fmt:
            self.fmt = fmt
        self.update()

    def paintEvent(self, _event) -> None:
        p = palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        left, right, top, bottom = 8, 8, 18, 22
        if not self.values:
            qp.setPen(QColor(p.muted))
            qp.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data yet")
            return
        vmax = self.max_value or max([*self.values, *(self.line or []), self.reference or 0, 1])
        n = len(self.values)
        slot = (w - left - right) / n
        bar_w = max(3.0, slot * 0.62)
        plot_h = h - top - bottom
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        qp.setFont(f)
        if self.reference:
            y = top + plot_h * (1 - min(1.0, self.reference / vmax))
            qp.setPen(QPen(QColor(p.muted), 1, Qt.PenStyle.DashLine))
            qp.drawLine(left, int(y), w - right, int(y))
        for i, v in enumerate(self.values):
            x = left + i * slot + (slot - bar_w) / 2
            bh = plot_h * min(1.0, v / vmax) if vmax else 0
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QColor(p.accent))
            qp.drawRoundedRect(QRectF(x, top + plot_h - bh, bar_w, bh), 3, 3)
            step = max(1, n // 10)
            if (n - 1 - i) % step == 0:
                qp.setPen(QColor(p.muted))
                qp.drawText(QRectF(left + i * slot - 10, h - bottom + 4, slot + 20, 16),
                            Qt.AlignmentFlag.AlignHCenter, self.labels[i])
        if self.line:
            qp.setPen(QPen(QColor(p.accent2), 2))
            pts = []
            for i, v in enumerate(self.line):
                x = left + i * slot + slot / 2
                y = top + plot_h * (1 - min(1.0, v / vmax))
                pts.append((x, y))
            for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
                qp.drawLine(int(x0), int(y0), int(x1), int(y1))
        qp.setPen(QColor(p.muted))
        qp.drawText(QRectF(left, 0, w, top), Qt.AlignmentFlag.AlignLeft, self.fmt(vmax))


class HBarList(QWidget):
    """Horizontal labelled bars (e.g. time per app)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.items: list[tuple[str, float, str]] = []
        self.setMinimumHeight(60)

    def set_items(self, items: Sequence[tuple[str, float, str]]) -> None:
        self.items = list(items)
        self.setMinimumHeight(max(60, 26 * len(self.items) + 8))
        self.update()

    def paintEvent(self, _event) -> None:
        p = palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.items:
            qp.setPen(QColor(p.muted))
            qp.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data yet")
            return
        vmax = max(v for _, v, _ in self.items) or 1
        label_w = min(200, self.width() * 0.35)
        val_w = 70
        for i, (name, v, color) in enumerate(self.items):
            y = 4 + i * 26
            qp.setPen(QColor(p.text))
            qp.drawText(QRectF(0, y, label_w - 8, 20),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        qp.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight,
                                                    int(label_w - 8)))
            bw = (self.width() - label_w - val_w) * v / vmax
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QColor(color or p.accent))
            qp.drawRoundedRect(QRectF(label_w, y + 4, max(2.0, bw), 12), 4, 4)
            qp.setPen(QColor(p.muted))
            qp.drawText(QRectF(self.width() - val_w, y, val_w, 20),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                        fmt_minutes(v))
