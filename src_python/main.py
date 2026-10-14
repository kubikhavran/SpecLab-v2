"""SpecLab — entry point."""

import sys
import argparse
from pathlib import Path

# Ensure src_python is on the import path regardless of working directory.
_SRC_DIR = str(Path(__file__).resolve().parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QFont, QPalette, QColor  # noqa: E402

from app.main_window import MainWindow  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SpecLab Studio — native Python spectroscopy workspace"
    )
    parser.add_argument("files", nargs="*", help="Spectrum files to import")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Load explicitly synthetic demonstration spectra",
    )
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("SpecLab Studio")
    app.setOrganizationName("SpecLab")
    app.setStyle("Fusion")
    app.setFont(QFont("Avenir Next" if sys.platform == "darwin" else "Segoe UI", 11))
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#fafbfb"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#24343c"))
    app.setPalette(palette)
    window = MainWindow()
    if args.demo:
        window.load_demo()
    if args.files:
        window._load_files(args.files)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
