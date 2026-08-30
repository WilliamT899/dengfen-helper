"""应用级常量与路径配置。

开发模式：模型放在 app/models/，数据放在 ~/登分助手/
打包模式（PyInstaller）：模型随包内置（sys._MEIPASS），数据仍在用户目录。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "登分助手"
APP_VERSION = "1.1.0"

# 打包后模型资源解压目录（PyInstaller 运行时），开发时为 None
_BUNDLE_DIR = getattr(sys, "_MEIPASS", None)


def models_dir() -> Path:
    """OCR 模型目录：优先环境变量，其次打包内置，最后开发目录。"""
    env = os.environ.get("DENGFEN_MODELS")
    if env:
        return Path(env)
    if _BUNDLE_DIR:
        return Path(_BUNDLE_DIR) / "app" / "models"
    return Path(__file__).resolve().parent / "models"


def data_dir() -> Path:
    """用户数据目录（照片存档、工作区、配置），与 exe 位置无关。"""
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE", Path.home())) / "登分助手"
    return Path.home() / "登分助手"


def photos_dir() -> Path:
    return data_dir() / "照片"


def workspace_path() -> Path:
    return data_dir() / "workspace.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"
