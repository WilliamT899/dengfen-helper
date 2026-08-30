"""后台批量 OCR：QThreadPool 任务，识别结果通过信号回主线程。

无论成功与否都发出 done（带已完成的结果），保证界面按钮恢复。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from app.ocr.engine import get_engine
from app.ocr.pipeline import recognize_file


@dataclass
class PhotoResult:
    path: str
    name: str
    student_id: str
    klass: str
    score: Optional[float]
    score_conf: float
    photo: str = ""


class WorkerSignals(QObject):
    progress = Signal(int, int, str)     # done, total, 当前文件名
    done = Signal(list)                  # List[PhotoResult]
    error = Signal(str)                  # 错误信息（用户可读）


class OcrBatchWorker(QRunnable):
    def __init__(self, paths: List[Path]):
        super().__init__()
        self.paths = paths
        self.signals = WorkerSignals()
        self.progress = self.signals.progress
        self.done = self.signals.done
        self.error = self.signals.error

    @Slot()
    def run(self):
        results: List[PhotoResult] = []
        total = len(self.paths)
        self.signals.progress.emit(0, total, "正在加载识别模型…")
        try:
            engine = get_engine()   # 惰性加载模型（首个任务稍慢）
        except Exception as exc:
            self.signals.error.emit(f"识别引擎初始化失败：{exc}")
            self.signals.done.emit([])
            return
        for i, p in enumerate(self.paths, 1):
            self.signals.progress.emit(i - 1, total, f"正在识别：{p.name}")
            try:
                r = recognize_file(p, engine)
                results.append(PhotoResult(
                    path=str(p), name=r.name, student_id=r.student_id,
                    klass=r.klass, score=r.score, score_conf=r.score_conf))
            except Exception as exc:
                self.signals.error.emit(f"{p.name} 识别失败：{exc}")
            self.signals.progress.emit(i, total, f"完成 {i}/{total}")
        self.signals.done.emit(results)


class EngineWarmupWorker(QRunnable):
    """启动时后台预热识别模型。"""

    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            get_engine()
            self.signals.done.emit(["ok", "识别模型加载完成"])
        except Exception as exc:
            self.signals.done.emit(["error", f"识别模型加载失败：{exc}"])
