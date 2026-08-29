"""后台批量 OCR：QThreadPool 任务，识别结果通过信号回主线程。"""
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
    progress = Signal(int, int)          # done, total
    done = Signal(list)                  # List[PhotoResult]
    error = Signal(str, str)             # 文件, 错误信息


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
        engine = get_engine()   # 惰性加载模型（首个任务稍慢）
        results: List[PhotoResult] = []
        total = len(self.paths)
        for i, p in enumerate(self.paths, 1):
            try:
                r = recognize_file(p, engine)
                results.append(PhotoResult(
                    path=str(p), name=r.name, student_id=r.student_id,
                    klass=r.klass, score=r.score, score_conf=r.score_conf))
            except Exception as exc:
                self.signals.error.emit(str(p), str(exc))
            self.signals.progress.emit(i, total)
        self.signals.done.emit(results)
