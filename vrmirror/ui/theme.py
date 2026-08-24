"""A dark theme, because a bright chrome around a video feed is distracting."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#16181d"
BG_RAISED = "#1e2128"
BG_SUNKEN = "#101216"
BORDER = "#2b2f39"
TEXT = "#e6e8ee"
TEXT_DIM = "#9aa1b1"
ACCENT = "#4c8dff"
ACCENT_DIM = "#2f5fb0"
DANGER = "#e5484d"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-size: 13px;
}}
QMainWindow::separator {{ background: {BORDER}; width: 1px; height: 1px; }}

QToolBar {{
    background: {BG_RAISED};
    border-bottom: 1px solid {BORDER};
    padding: 4px 6px;
    spacing: 4px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 5px 10px;
    color: {TEXT};
}}
QToolButton:hover {{ background: #262a33; border-color: {BORDER}; }}
QToolButton:pressed {{ background: {ACCENT_DIM}; }}
QToolButton:checked {{ background: {ACCENT_DIM}; border-color: {ACCENT}; }}
QToolButton:disabled {{ color: #5d6470; }}

QPushButton {{
    background: #272b34;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover {{ background: #30353f; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QPushButton:disabled {{ color: #5d6470; background: #1c1f26; }}
QPushButton#primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #0b0d11; font-weight: 600; }}
QPushButton#primary:hover {{ background: #649dff; }}
QPushButton#primary:disabled {{ background: #2a3240; color: #6b7382; border-color: {BORDER}; }}

QListWidget {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{ padding: 7px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {ACCENT_DIM}; color: #ffffff; }}
QListWidget::item:hover {{ background: #232732; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG_SUNKEN};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {BG_RAISED};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT_DIM};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

QLabel#hint {{ color: {TEXT_DIM}; font-size: 11px; }}
QLabel#status {{ color: {TEXT_DIM}; }}
QLabel#statusBad {{ color: {DANGER}; }}

QStatusBar {{ background: {BG_RAISED}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QStatusBar::item {{ border: none; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #383d49; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QSplitter::handle {{ background: {BORDER}; width: 1px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG_SUNKEN};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QToolTip {{ background: {BG_RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(BG_SUNKEN))
    palette.setColor(QPalette.AlternateBase, QColor(BG_RAISED))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(BG_RAISED))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#0b0d11"))
    palette.setColor(QPalette.ToolTipBase, QColor(BG_RAISED))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    app.setPalette(palette)

    app.setStyleSheet(STYLESHEET)
