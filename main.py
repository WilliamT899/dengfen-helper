#!/usr/bin/env python3
"""登分助手 - 程序入口"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app import config
from app.ui.main_window import MainWindow


def _load_style(app: QApplication) -> None:
    qss = Path(__file__).parent / "app" / "ui" / "resources" / "style.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    _load_style(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
