"""SpecLab — entry point."""

import sys
import argparse
from pathlib import Path

# Ensure src_python is on the import path regardless of working directory.
_SRC_DIR = str(Path(__file__).resolve().parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402

from app.main_window import MainWindow  # noqa: E402
from ui.theme import light_palette  # noqa: E402


def configure_application(app: QApplication) -> None:
    app.setApplicationName("SpecLab Studio")
    app.setOrganizationName("SpecLab")
    app.setStyle("Fusion")
    app.setFont(QFont("Avenir Next" if sys.platform == "darwin" else "Segoe UI", 11))
    app.setPalette(light_palette(app.style()))


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
    configure_application(app)
    window = MainWindow()
    if args.demo:
        window.load_demo()
    if args.files:
        window._load_files(args.files)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
