"""Color palette and stylesheet for the Minimal Harness desktop shell."""

from PySide6.QtWidgets import QApplication

DOMINANT = "#11302A"
SECONDARY = "#AFB4AD"
ACCENT = "#D6CFBF"
NEUTRAL = "#F8F3EC"

STYLESHEET = f"""
* {{
    font-family: sans-serif;
    font-size: 13px;
}}
QMainWindow, QWidget {{
    background-color: {NEUTRAL};
    color: {DOMINANT};
}}
#PanelCard {{
    background-color: white;
    border: 1px solid {SECONDARY};
    border-radius: 8px;
}}
#Sidebar {{
    background-color: white;
    border: 1px solid {SECONDARY};
    border-radius: 8px;
}}
#Sidebar QListWidget {{
    border: none;
    background: transparent;
}}
#Sidebar QListWidget::item {{
    padding: 6px 8px;
    border-radius: 4px;
}}
#Sidebar QListWidget::item:selected {{
    background-color: {ACCENT};
    color: {DOMINANT};
}}
#PanelCard QTextEdit, #PanelCard QPlainTextEdit, #PanelCard QLineEdit {{
    background-color: {NEUTRAL};
    border: 1px solid {SECONDARY};
}}
QLabel {{
    color: {DOMINANT};
    background: transparent;
}}
QTextEdit {{
    background-color: white;
    border: 1px solid {SECONDARY};
    border-radius: 6px;
    padding: 6px;
    selection-background-color: {ACCENT};
    selection-color: {DOMINANT};
}}
QPlainTextEdit {{
    background-color: white;
    border: 1px solid {SECONDARY};
    border-radius: 6px;
    padding: 6px;
    selection-background-color: {ACCENT};
    selection-color: {DOMINANT};
}}
QPushButton {{
    background-color: {ACCENT};
    color: {DOMINANT};
    border: 1px solid {SECONDARY};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{
    background-color: #c5bda9;
}}
QPushButton:pressed {{
    background-color: #b4ab95;
}}
QPushButton:disabled {{
    background-color: {NEUTRAL};
    color: {SECONDARY};
}}
QInputDialog QLineEdit, QLineEdit {{
    background-color: white;
    border: 1px solid {SECONDARY};
    border-radius: 6px;
    padding: 6px;
    selection-background-color: {ACCENT};
}}
QSplitter::handle {{
    background-color: {SECONDARY};
    width: 2px;
}}
"""


def apply_palette(app: QApplication) -> None:
    """Apply the app-wide color palette.

    Parameters
    ----------
    app : QApplication
        Application receiving the stylesheet.

    Returns
    -------
    None
        The stylesheet is set on the application.
    """
    app.setStyleSheet(STYLESHEET)
