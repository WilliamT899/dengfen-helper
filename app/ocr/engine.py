"""RapidOCR 引擎单例封装。

- 模型全部本地化（app/models），纯离线
- QMutex 串行推理（RapidOCR 非线程安全）
- 对外只暴露 numpy 图像接口，输出 [(x0,y0,x1,y1), text, score]
"""
from __future__ import annotations

import threading
from typing import List, Optional, Tuple

import numpy as np

from app import config

Box = Tuple[float, float, float, float]
OcrLine = Tuple[Box, str, float]


def _to_rect(points) -> Box:
    """四点框 (4,2) → 轴对齐矩形 (x0,y0,x1,y1)。"""
    arr = np.asarray(points, dtype=float).reshape(-1, 2)
    return (float(arr[:, 0].min()), float(arr[:, 1].min()),
            float(arr[:, 0].max()), float(arr[:, 1].max()))


class OcrEngine:
    """RapidOCR 封装。线程安全（内部互斥）。

    params 使用 RapidOCR 的 dot-key 格式（如 'Rec.ocr_version'）。
    """

    def __init__(self, models_dir: Optional[str] = None, params: Optional[dict] = None):
        from rapidocr import RapidOCR, LangDet, LangRec, ModelType, OCRVersion

        # 默认使用 PP-OCRv5 server 模型（官方唯一训练过中文手写体的模型）
        effective: dict = {
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": ModelType.SERVER,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.lang_type": LangRec.CH,
            "Rec.model_type": ModelType.SERVER,
        }
        if params:
            effective.update(params)
        if models_dir:
            # 模型根目录：首次运行自动下载模型到此目录，之后离线复用
            effective["Global.model_root_dir"] = models_dir
        self._ocr = RapidOCR(params=effective)
        self._lock = threading.Lock()

    def run(self, image: np.ndarray) -> List[OcrLine]:
        """整图 OCR：返回 [(box, text, confidence)]。box 为轴对齐矩形 (x0,y0,x1,y1)。

        关闭行方向分类（cls）：我们的管线自行处理竖排旋转，cls 只增加耗时。
        """
        with self._lock:
            result = self._ocr(image, use_cls=False)
        if result is None or result.boxes is None or result.txts is None:
            return []
        boxes = result.boxes
        txts = result.txts
        scores = result.scores if result.scores is not None else (0.0,) * len(txts)
        return [(_to_rect(b), str(t), float(s)) for b, t, s in zip(boxes, txts, scores)]

    def detect(self, image: np.ndarray) -> List[Tuple[Box, float]]:
        """仅检测文本行框（用于方向判定等）。"""
        with self._lock:
            result = self._ocr.det(image)
        if result is None or result.boxes is None:
            return []
        scores = result.scores if result.scores is not None else (0.0,) * len(result.boxes)
        return [(_to_rect(b), float(s)) for b, s in zip(result.boxes, scores)]

    def recognize_lines(self, image: np.ndarray, boxes: List[Box]) -> List[Tuple[Box, str, float]]:
        """对给定框逐行识别（竖排分割后按块识别时使用）。"""
        outs: List[Tuple[Box, str, float]] = []
        with self._lock:
            for box in boxes:
                rec = self._ocr.rec(image, box)
                if rec is None:
                    continue
                text = "".join(rec.txts or [])
                score = float(np.mean(rec.scores)) if rec.scores is not None and len(rec.scores) else 0.0
                outs.append((tuple(map(float, box)), text, score))
        return outs


_engine: Optional[OcrEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> OcrEngine:
    """进程级单例（懒加载，首次调用会初始化模型，耗时数秒）。"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = OcrEngine(models_dir=str(config.models_dir()))
    return _engine
