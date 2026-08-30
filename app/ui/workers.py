"""后台 OCR 识别队列：拍摄/上传只管入队，识别在独立线程逐个处理。

界面全程可操作：拍照、继续上传照片与识别互不阻塞；
每识别完一张立即通过 result 信号回填表格。
"""
from __future__ import annotations

import queue
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

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


class OcrQueueThread(QThread):
    """常驻识别线程：queue.Queue 接收照片路径，逐张识别。"""

    progress = Signal(int, int, str)     # 已识别, 队列总数, 详情
    result = Signal(object)              # PhotoResult（单张完成即发）
    error = Signal(str)
    model_ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: "queue.Queue[Path]" = queue.Queue()
        self._total = 0
        self._done = 0

    def enqueue(self, paths: List[Path]):
        for p in paths:
            self._queue.put(p)
        self._total += len(paths)
        if not self.isRunning():
            self.start()

    def queue_length(self) -> int:
        return self._queue.qsize()

    def stop(self):
        self._queue.put(Path("__STOP__"))
        self.wait(5000)

    def run(self):
        try:
            engine = get_engine()
            self.model_ready.emit("识别模型加载完成")
        except Exception as exc:
            self.error.emit(f"识别引擎初始化失败：{exc}")
            return
        while True:
            try:
                p = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if p.name == "__STOP__":
                break
            self.progress.emit(self._done, self._total, f"正在识别：{p.name}")
            try:
                r = recognize_file(p, engine)
                self.result.emit(PhotoResult(
                    path=str(p), name=r.name, student_id=r.student_id,
                    klass=r.klass, score=r.score, score_conf=r.score_conf))
            except Exception as exc:
                self.error.emit(f"{p.name} 识别失败：{exc}")
            self._done += 1
            self.progress.emit(self._done, self._total, f"已完成 {self._done}/{self._total}")


class EngineWarmupWorker:  # 占位保留：队列线程本身承担预热
    pass
