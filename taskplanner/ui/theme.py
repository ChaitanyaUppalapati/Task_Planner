"""Colours and Qt stylesheet."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    accent: str
    accent2: str
    good: str
    warn: str
    bad: str
    gold: str


DARK = Palette(
    bg="#0f1117", surface="#171a23", surface2="#1f2330", border="#2a2f3d",
    text="#e7e9ee", muted="#8b91a1", accent="#7c5cff", accent2="#22c3ee",
    good="#2ecc71", warn="#f5a623", bad="#ff5c6c", gold="#ffd166",
)
LIGHT = Palette(
    bg="#f4f5f8", surface="#ffffff", surface2="#eef0f5", border="#dde0e8",
    text="#1b1e27", muted="#646b7d", accent="#6246ea", accent2="#0ea5c6",
    good="#1f9d55", warn="#c77c02", bad="#d63649", gold="#b7791f",
)

_current: Palette = DARK


def palette() -> Palette:
    return _current


def set_theme(name: str) -> Palette:
    global _current
    _current = LIGHT if name == "light" else DARK
    return _current


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{ background: {p.bg}; color: {p.text}; font-family: "Segoe UI", "Inter", sans-serif;
              font-size: 10pt; }}
    QMainWindow, QDialog {{ background: {p.bg}; }}
    QToolTip {{ background: {p.surface2}; color: {p.text}; border: 1px solid {p.border};
               padding: 4px; }}
    #Sidebar {{ background: {p.surface}; border-right: 1px solid {p.border}; }}
    #Sidebar QListWidget {{ background: transparent; border: none; outline: none; }}
    #Sidebar QListWidget::item {{ padding: 10px 14px; border-radius: 8px; margin: 2px 8px;
                                  color: {p.muted}; }}
    #Sidebar QListWidget::item:selected {{ background: {p.surface2}; color: {p.text}; }}
    #Sidebar QListWidget::item:hover {{ background: {p.surface2}; }}
    #AppTitle {{ font-size: 13pt; font-weight: 700; padding: 18px 16px 8px 16px;
                background: transparent; }}
    #Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
    #Card QLabel, #Card QWidget {{ background: transparent; }}
    #H1 {{ font-size: 18pt; font-weight: 700; background: transparent; }}
    #H2 {{ font-size: 12pt; font-weight: 600; background: transparent; }}
    #Muted {{ color: {p.muted}; background: transparent; }}
    #Big {{ font-size: 20pt; font-weight: 700; background: transparent; }}
    #Pill {{ background: {p.surface2}; border-radius: 9px; padding: 2px 8px; color: {p.muted}; }}
    QPushButton {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 8px;
                  padding: 7px 14px; color: {p.text}; }}
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:pressed {{ background: {p.border}; }}
    QPushButton:disabled {{ color: {p.muted}; border-color: {p.border}; }}
    QPushButton#Primary {{ background: {p.accent}; border: none; color: white; font-weight: 600; }}
    QPushButton#Primary:hover {{ background: {p.accent2}; }}
    QPushButton#Danger {{ color: {p.bad}; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit,
    QTimeEdit {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 7px;
                 padding: 5px 8px; selection-background-color: {p.accent}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus
    {{ border-color: {p.accent}; }}
    QComboBox QAbstractItemView {{ background: {p.surface2}; border: 1px solid {p.border};
                                   selection-background-color: {p.accent}; }}
    QTableWidget, QTreeWidget, QListWidget {{ background: {p.surface}; border: 1px solid {p.border};
                   border-radius: 10px; gridline-color: {p.border}; alternate-background-color: {p.surface2}; }}
    QHeaderView::section {{ background: {p.surface}; color: {p.muted}; border: none;
                           border-bottom: 1px solid {p.border}; padding: 6px; font-weight: 600; }}
    QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected
    {{ background: {p.accent}; color: white; }}
    QProgressBar {{ background: {p.surface2}; border: none; border-radius: 5px; height: 10px;
                   text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                          stop:0 {p.accent}, stop:1 {p.accent2}); border-radius: 5px; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 30px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; }}
    QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 5px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QCheckBox::indicator, QListView::indicator, QTableView::indicator {{ width: 16px; height: 16px;
        border: 1px solid {p.muted}; border-radius: 4px; background: {p.surface2}; }}
    QCheckBox::indicator:checked, QListView::indicator:checked, QTableView::indicator:checked
    {{ background: {p.accent}; border-color: {p.accent}; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {p.muted};
                   border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {p.text}; border-bottom-color: {p.accent}; }}
    QCheckBox {{ background: transparent; spacing: 8px; }}
    QGroupBox {{ border: 1px solid {p.border}; border-radius: 10px; margin-top: 14px;
                padding: 12px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; }}
    QMenu {{ background: {p.surface}; border: 1px solid {p.border}; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {p.accent}; color: white; }}
    """
