"""字段提取：左竖条旋转读姓名/学号/班级 + 右上角分数。

经 6 张样本实测验证的策略（2026-08-29）：
- 左侧竖条（密封线内 x<0.16）顺时针旋转 90° 后，"标签:值"同行或标签/值
  分两行，全分辨率识别效果显著优于降采样
- 分数在右上角横写：用多个裁剪框 + 大字/分数规则择优，避免单框漏检
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.ocr import postprocess
from app.ocr.engine import OcrEngine

STRIP_WIDTHS = (0.16, 0.08)   # 宽条优先；姓名/学号缺失时才用窄条（排除密封线"封/线"文字）
SCORE_CROPS = (         # (y0, y1, x0, x1) 归一化：顶部窄框 + 稍宽框
    (0.0, 0.15, 0.65, 1.0),
    (0.0, 0.25, 0.65, 1.0),
)
LABELS = ("姓名", "学号", "班级", "学校")
VALUE_LABELS = ("姓名", "学号", "班级")
SEAL_CHARS = {"封", "线", "密"}   # 密封线单字，不参与配对


def _read_strip(engine: OcrEngine, strip: np.ndarray) -> Dict[str, Tuple[str, float]]:
    """单条竖条（已旋转 90°）解析：'标签:值'同行 + 独立值行配对。"""
    lines = sorted(engine.run(strip), key=lambda ln: ln[0][1])
    fields: Dict[str, Tuple[str, float]] = {}
    loose: List[Tuple[str, float, float]] = []   # (text, y_center, conf)

    for box, text, conf in lines:
        t = text.strip()
        if "：" in t or ":" in t:
            label, _, value = t.replace(":", "：").partition("：")
            label = label.strip()
            if label in LABELS:
                fields.setdefault(label, (value.strip(), conf))
        else:
            yc = (box[1] + box[3]) / 2
            loose.append((t, yc, conf))

    # 标签行缺值 → 找最近高度的独立值行配对（排除密封线单字）
    for label in VALUE_LABELS:
        cur = fields.get(label)
        if cur and cur[0]:
            continue
        if not loose:
            continue
        best = max(loose, key=lambda x: x[2])
        fields[label] = (best[0], best[2])
    return fields


def extract_left_fields(engine: OcrEngine, img: np.ndarray) -> Dict[str, Tuple[str, float]]:
    """左竖条顺时针旋转 90° 后提取 {标签: (值, 置信度)}。

    宽条（x<0.16）覆盖全部字段；姓名/学号缺失时才用窄条（x<0.08）
    重扫（窄条排除密封线文字，某些样本只有窄条能检出姓名）。
    """
    h, w = img.shape[:2]
    merged: Dict[str, Tuple[str, float]] = {}
    for xw in STRIP_WIDTHS:
        strip = img[:, 0:int(xw * w)]
        rot = cv2.rotate(strip, cv2.ROTATE_90_CLOCKWISE)
        fields = _read_strip(engine, rot)
        for label, (value, conf) in fields.items():
            cur = merged.get(label)
            if cur is None or (value and not cur[0]):
                merged[label] = (value, conf)
            elif value and label in ("姓名", "学号") and len(value) > len(cur[0]):
                # 更完整的值优先
                merged[label] = (value, conf)
        # 宽条已拿到姓名和学号 → 不再扫窄条
        if merged.get("姓名", ("",))[0] and merged.get("学号", ("",))[0]:
            break

    # 清洗
    out: Dict[str, Tuple[str, float]] = {}
    for label, (value, conf) in merged.items():
        if label == "姓名":
            cleaned = postprocess.normalize_name(value)
            if cleaned:
                out[label] = (cleaned, conf)
            else:
                out[label] = (value, conf)  # 保留原始供匹配
        elif label == "学号":
            cleaned = postprocess.normalize_student_id(value)
            if cleaned:
                out[label] = (cleaned, conf)
        elif label == "班级":
            if value:
                out[label] = (value, conf)
    return out


def extract_score(engine: OcrEngine, img: np.ndarray) -> Tuple[Optional[float], float, str]:
    """右上角分数：多裁剪框 + 大字/分数规则择优。

    返回 (分数, 置信度, 原文)。失败返回 (None, 0, "")。
    """
    h, w = img.shape[:2]
    best: Optional[Tuple[float, float, str, float]] = None  # (conf, 值, 原文, 框高比)

    for (y0, y1, x0, x1) in SCORE_CROPS:
        crop = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        if crop.size == 0:
            continue
        crop_h = crop.shape[0]
        try:
            lines = engine.run(crop)
        except Exception:
            continue
        if not lines:
            continue
        for box, text, conf in lines:
            hh = (box[3] - box[1]) / crop_h
            parsed = postprocess.parse_score(text)
            if parsed.value is None:
                continue
            # 大字优先；非修补优先；然后置信度
            key = (hh if hh > 0.3 else 0, not parsed.warning, conf)
            cand = (conf, parsed.value, text, hh)
            if best is None or key > (best[3] if best[3] > 0.3 else 0, True, best[0]):
                best = cand

    if best is None:
        # 兜底：全页检测找右上角最大文本行
        try:
            lines = engine.run(img)
        except Exception:
            return None, 0.0, ""
        cands = []
        for box, text, conf in lines:
            x0, y0, x1, y1 = box
            if x0 / w > 0.60 and y1 / h < 0.22 and (y1 - y0) / h >= 0.08:
                parsed = postprocess.parse_score(text)
                if parsed.value is not None:
                    cands.append((conf, parsed.value, text))
        if cands:
            cands.sort(reverse=True)
            return cands[0][1], cands[0][0], cands[0][2]
        return None, 0.0, ""

    return best[1], best[0], best[2]


def extract_page(engine: OcrEngine, img: np.ndarray):
    """单页全字段提取：返回 {name, id, klass, score}。"""
    fields = extract_left_fields(engine, img)
    score, sconf, sraw = extract_score(engine, img)
    return {
        "name": fields.get("姓名", ("", 0.0)),
        "id": fields.get("学号", ("", 0.0)),
        "klass": fields.get("班级", ("", 0.0)),
        "score": (score, sconf),
        "score_raw": sraw,
    }
