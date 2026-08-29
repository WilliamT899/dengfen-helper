"""OCR 识别管线编排（纯函数、无 Qt 依赖，CLI/GUI 共用）。

载入+EXIF修正 → 页方向归一（几何法）→ 左竖条旋转提取姓名/学号/班级
→ 右上角多框分数提取 → PaperResult
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.ocr import postprocess
from app.ocr.engine import OcrEngine, get_engine
from app.ocr.extract import extract_left_fields, extract_score
from app.ocr.layout import LayoutTemplate
from app.ocr.orientation import normalize_orientation

LONG_SIDE = 1600  # 方向判定用降采样长边


@dataclass
class FieldResult:
    field: str
    value: str = ""            # 清洗后的结果
    raw: str = ""              # OCR 原文
    confidence: float = 0.0
    status: str = "ok"         # ok / low_confidence / not_found
    warning: bool = False      # 分数经启发式修补或超范围
    candidates: List[str] = field(default_factory=list)


@dataclass
class PaperResult:
    """单张试卷的识别结果。"""

    name: str = ""
    student_id: str = ""
    klass: str = ""
    score: Optional[float] = None
    score_conf: float = 0.0
    score_raw: str = ""
    fields: Dict[str, FieldResult] = field(default_factory=dict)
    angle: int = 0
    seconds: float = 0.0


def load_image(path: Path) -> np.ndarray:
    """载入图像：EXIF 方向修正 + 转 BGR numpy。"""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def _downscale(img: np.ndarray, long_side: int = LONG_SIDE) -> np.ndarray:
    h, w = img.shape[:2]
    scale = long_side / max(h, w)
    if scale >= 1:
        return img
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def recognize_image(img: np.ndarray, engine: Optional[OcrEngine] = None) -> PaperResult:
    """识别一张试卷图像（BGR numpy，全分辨率走字段提取）。"""
    t0 = time.monotonic()
    engine = engine or get_engine()

    # 页方向归一（几何法，用降采样图加速；垂直姿态降级为不旋转——相机拍照场景少见）
    small = _downscale(img)
    gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    _, angle = normalize_orientation(gray_small, detect=None)
    page = img if angle == 0 else cv2.rotate(img, {
        90: cv2.ROTATE_90_COUNTERCLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_CLOCKWISE,
    }[angle])

    left = extract_left_fields(engine, page)
    score, sconf, sraw = extract_score(engine, page)

    result = PaperResult(
        name=left.get("姓名", ("", 0.0))[0],
        student_id=left.get("学号", ("", 0.0))[0],
        klass=left.get("班级", ("", 0.0))[0],
        score=score,
        score_conf=sconf,
        score_raw=sraw,
        angle=angle,
        seconds=time.monotonic() - t0,
    )
    result.fields = {
        "name": FieldResult(field="name", value=result.name,
                            confidence=left.get("姓名", ("", 0.0))[1],
                            status="ok" if result.name else "not_found"),
        "id": FieldResult(field="id", value=result.student_id,
                          confidence=left.get("学号", ("", 0.0))[1],
                          status="ok" if result.student_id else "not_found"),
        "klass": FieldResult(field="klass", value=result.klass,
                             confidence=left.get("班级", ("", 0.0))[1],
                             status="ok" if result.klass else "not_found"),
        "score": FieldResult(field="score", value=f"{score:g}" if score is not None else "",
                             raw=sraw, confidence=sconf,
                             status="ok" if score is not None else "not_found"),
    }
    return result


def recognize_file(path: Path, engine: Optional[OcrEngine] = None) -> PaperResult:
    return recognize_image(load_image(path), engine)
