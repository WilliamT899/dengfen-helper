# -*- mode: python ; coding: utf-8 -*-
# 登分助手 PyInstaller 打包配置（Windows onefile）
import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# onnxruntime 动态 DLL 收集
_ort_datas, _ort_binaries, _ort_hidden = collect_all("onnxruntime")

a = Analysis(
    ["../main.py"],
    pathex=[".."],
    binaries=_ort_binaries,
    datas=[
        # OCR 模型（构建前由 CI 下载到 app/models/）
        ("../app/models", "app/models"),
        # 深色主题
        ("../app/ui/resources/style.qss", "app/ui/resources"),
    ] + _ort_datas,
    hiddenimports=_ort_hidden + ["rapidocr", "rapidocr.main"],
    hookspath=["."],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="登分助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX 易引发杀软误报，禁用
    console=False,       # GUI 应用，无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
