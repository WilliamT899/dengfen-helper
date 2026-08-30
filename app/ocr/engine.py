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

    快速引擎（默认）：v5 mobile 检测 + v5 server 识别（~1s/区域）
    兜底引擎（server_det=True）：v5 server 检测（~8s/区域，仅字段缺失时使用）
    """

    def __init__(self, models_dir: Optional[str] = None, params: Optional[dict] = None,
                 server_det: bool = False):
        from rapidocr import RapidOCR, LangDet, LangRec, ModelType, OCRVersion

        # 默认：mobile det（快）+ server rec（手写识别质量）
        effective: dict = {
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.lang_type": LangDet.CH,
            "Det.model_type": ModelType.SERVER if server_det else ModelType.MOBILE,
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
            result = self._ocr(image, use_rec=False, use_cls=False)
        if result is None or result.boxes is None:
            return []
        scores = result.scores if result.scores is not None else (0.0,) * len(result.boxes)
        return [(_to_rect(b), float(s)) for b, s in zip(result.boxes, scores)]

    def recognize_lines(self, image: np.ndarray, boxes: List[Box]) -> List[Tuple[Box, str, float]]:
        """对给定框裁剪后逐行识别（rec-only，跳过 det，速度快）。

        RapidOCR 的 rec-only 接口接收裁剪图列表。
        """
        outs: List[Tuple[Box, str, float]] = []
        crops: List[np.ndarray] = []
        valid_boxes: List[Box] = []
        ih, iw = image.shape[:2]
        for box in boxes:
            x0, y0, x1, y1 = (int(v) for v in box)
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(iw, x1), min(ih, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            crops.append(image[y0:y1, x0:x1])
            valid_boxes.append((x0, y0, x1, y1))
        if not crops:
            return outs
        with self._lock:
            rec = self._ocr.recognize_txt(crops)
        if rec is None:
            return outs
        txts = rec.txts or []
        scores = rec.scores or (0.0,) * len(txts)
        for box, text, score in zip(valid_boxes, txts, scores):
            outs.append((tuple(map(float, box)), str(text), float(score)))
        return outs


_engine: Optional[OcrEngine] = None
_server_engine: Optional[OcrEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> OcrEngine:
    """快速引擎单例（mobile det + server rec）。"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = OcrEngine(models_dir=str(config.models_dir()))
    return _engine


def get_server_engine() -> OcrEngine:
    """兜底引擎单例（server det + server rec，仅字段缺失时加载使用）。"""
    global _server_engine
    if _server_engine is None:
        with _engine_lock:
            if _server_engine is None:
                _server_engine = OcrEngine(models_dir=str(config.models_dir()),
                                           server_det=True)
    return _server_engine
