#!/usr/bin/env python3
"""CI 冒烟测试入口（源码模式）：转发到 app.selftest。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.selftest import run_smoke  # noqa: E402

if __name__ == "__main__":
    sys.exit(run_smoke())
