#!/usr/bin/env python3
"""登分助手 - 程序入口"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app import config
from app.ui.main_window import MainWindow


def _ensure_stdio() -> None:
    """windowed 打包模式下 stdout/stderr 为 None，重定向到日志文件防崩。"""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            log = config.data_dir() / f"{name}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            setattr(sys, name, open(log, "a", encoding="utf-8", buffering=1))


def _load_style(app: QApplication) -> None:
    qss = Path(__file__).parent / "app" / "ui" / "resources" / "style.qss"
    if qss.exists():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))


def main() -> int:
    _ensure_stdio()
    # 打包完整性自测（CI 对构建产物运行）：无需 GUI，跑合成图识别
    if "--smoke" in sys.argv:
        from app.selftest import run_smoke
        return run_smoke()
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    _load_style(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
