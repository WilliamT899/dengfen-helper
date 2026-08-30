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
    label_ys: Dict[str, float] = {}
    loose: List[Tuple[str, float, float]] = []   # (text, y_center, conf)

    for box, text, conf in lines:
        t = text.strip()
        yc = (box[1] + box[3]) / 2
        if "：" in t or ":" in t:
            label, _, value = t.replace(":", "：").partition("：")
            label = label.strip()
            if label in LABELS:
                if label not in fields:
                    fields[label] = (value.strip(), conf)
                    label_ys[label] = yc
        else:
            loose.append((t, yc, conf))

    # 标签行缺值 → 按 y 位置最近配对（值与标签同高度），再按置信度破平
    for label in VALUE_LABELS:
        cur = fields.get(label)
        if cur and cur[0]:
            continue
        ly = label_ys.get(label)
        if ly is None or not loose:
            continue
        cands = [(abs(yc - ly), conf, text) for text, yc, conf in loose]
        cands.sort()
        _, conf, text = cands[0]
        fields[label] = (text, conf)
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
    """右上角分数提取（速度优先设计）。

    1) CV 墨迹定位（阈值+连通域找最大手写块）→ rec-only 识别（最快）
    2) 失败 → 区域 det+rec
    3) 失败 → 全页检测兜底
    返回 (分数, 置信度, 原文)。失败返回 (None, 0, "")。
    """
    h, w = img.shape[:2]
    crop = img[0:int(0.25 * h), int(0.62 * w):w]
    if crop.size == 0:
        return None, 0.0, ""

    # 1) CV 墨迹定位 + rec-only（每个候选墨块逐个识别，命中分数即返回；
    #    低置信度/单字结果不可信，继续走 det 路径）
    for box in _locate_score_blobs(crop):
        try:
            outs = engine.recognize_lines(crop, [box])
            for _, text, conf in outs:
                parsed = postprocess.parse_score(text)
                if parsed.value is None:
                    continue
                if conf >= 0.4 and len(text.strip()) >= 2:
                    return parsed.value, conf, text
        except Exception:
            continue

    # 2) 区域 det+rec（两个裁剪框，大字优先）
    best: Optional[Tuple[float, float, str]] = None
    for (y0, y1, x0, x1) in SCORE_CROPS:
        c = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        if c.size == 0:
            continue
        crop_h = c.shape[0]
        try:
            lines = engine.run(c)
        except Exception:
            continue
        for box, text, conf in lines:
            hh = (box[3] - box[1]) / crop_h
            parsed = postprocess.parse_score(text)
            if parsed.value is None:
                continue
            cand = (conf, parsed.value, text)
            if best is None or (hh > 0.3 and conf > best[0]):
                best = cand
    return (best[1], best[0], best[2]) if best is not None else (None, 0.0, "")


def _locate_score_blobs(crop: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """CV 定位分数候选墨块：固定阈值二值化 → 行带聚类 → 列簇切分。

    - 固定阈值 150（比 OTSU 对浅色笔迹更敏感）
    - 排除左 30%（印刷标题尾）与右 3%（页面边框竖线）
    - 行带（连续墨迹行）按高度降序；带内按列间隙切分数个数字簇
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    bw = (gray < 150).astype(np.uint8)
    ch, cw = crop.shape[:2]
    # 排除左侧印刷标题尾（标题在区域 x<0.10 内）与右边缘页面边框线；
    # 真实试卷分数在区域 x>0.29 处
    bw[:, :int(0.25 * cw)] = 0
    bw[:, int(0.97 * cw):] = 0
    if bw.sum() == 0:
        return []

    row_ink = bw.sum(axis=1)
    # 行带聚类（连续有墨迹的行）
    bands: List[Tuple[int, int]] = []
    in_band = False
    for y in range(ch):
        has_ink = row_ink[y] >= 2
        if has_ink and not in_band:
            start = y
            in_band = True
        elif not has_ink and in_band:
            bands.append((start, y))
            in_band = False
    if in_band:
        bands.append((start, ch))
    bands.sort(key=lambda b: -(b[1] - b[0]))  # 高度降序

    boxes: List[Tuple[int, int, int, int]] = []
    for y0, y1 in bands:
        bh = y1 - y0
        if bh < ch * 0.12:
            continue
        col_ink = bw[y0:y1].sum(axis=0)
        cols = np.where(col_ink >= 1)[0]
        if len(cols) == 0:
            continue
        # 列簇切分（数字之间可能有空隙，间隙 > 0.5 字高视为分界）
        clusters: List[Tuple[int, int]] = []
        c_start = cols[0]
        prev = cols[0]
        for c in cols[1:]:
            if c - prev > max(8, int(bh * 0.5)):
                clusters.append((c_start, prev))
                c_start = c
            prev = c
        clusters.append((c_start, prev))
        for x0, x1 in clusters:
            pad_x, pad_y = int(bh * 0.15), int(bh * 0.08)
            boxes.append((max(0, x0 - pad_x), max(0, y0 - pad_y),
                          min(cw, x1 + pad_x), min(ch, y1 + pad_y)))
        if len(boxes) >= 8:
            break
    return boxes[:8]


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
