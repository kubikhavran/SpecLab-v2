"""A restrained, shared visual system for the native laboratory workspace."""

STYLESHEET = """
QWidget { color: #24343c; font-family: 'Avenir Next', 'Segoe UI', sans-serif; font-size: 12px; }
QMainWindow, QWidget#workspace { background: #f5f7f7; }
QFrame#header { background: white; border-bottom: 1px solid #e1e8e8; }
QFrame#library, QFrame#inspector { background: #fafbfb; }
QWidget#panelContents { background: #fafbfb; }
QLabel#brand { font-size: 23px; font-weight: 700; color: #146b68; }
QLabel#section { font-size: 15px; font-weight: 600; }
QLabel#muted { color: #697d84; font-size: 11px; }
QLabel#plotTitle { font-size: 18px; font-weight: 600; }
QPushButton, QToolButton { background: white; border: 1px solid #dce4e5; border-radius: 6px; padding: 7px 10px; }
QPushButton:hover, QToolButton:hover { background: #edf4f3; border-color: #b8cecc; }
QPushButton:pressed { background: #dceae8; }
QPushButton:disabled { color: #9faeb2; border-color: #e5ebec; background: #f7f9f9; }
QPushButton#primary { color: white; background: #14756f; border-color: #14756f; font-weight: 600; }
QPushButton#primary:hover { background: #0e625e; }
QPushButton#primary:disabled { background: #b5cac7; border-color: #b5cac7; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {
 background: white; border: 1px solid #dce4e5; border-radius: 5px; padding: 6px; selection-background-color: #14756f;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border-color: #14756f; }
QComboBox::drop-down { border: none; width: 22px; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { padding: 10px 8px; border-radius: 5px; margin: 2px 0; }
QListWidget::item:selected { color: #115c59; background: #e1efed; }
QListWidget::item:hover:!selected { background: #edf2f3; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { color: #6d7f86; background: transparent; padding: 10px 12px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #126862; border-bottom: 2px solid #14756f; font-weight: 600; }
QTabBar::tab:hover { background: #eef4f3; }
QGroupBox { border: none; border-top: 1px solid #dfe7e7; margin-top: 16px; padding-top: 15px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 0; padding: 0 4px 0 0; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }
QScrollBar::handle:vertical { background: #c7d5d6; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #e4ebec; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QTableWidget { background: white; alternate-background-color: #f7fafa; border: none; gridline-color: #edf1f2; }
QHeaderView::section { background: #f3f7f7; color: #657b81; border: none; padding: 7px; font-weight: 600; }
QStatusBar { background: #edf3f3; color: #5e747a; border-top: 1px solid #dce7e7; }
QCheckBox { spacing: 7px; padding: 3px 0; }
QSlider::groove:horizontal { height: 4px; background: #dce7e7; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; margin: -4px 0; background: #14756f; border-radius: 6px; }
"""
