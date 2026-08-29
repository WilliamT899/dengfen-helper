"""页方向判定：把任意 0/90/180/270 姿态的照片归一为"文字朝上"的姿态。

主通道：几何法（Canny + HoughLinesP 统计近水平长线）——试卷满页答题横线，快且稳。
备选：det 打分法（对四姿态各跑一次检测，按文本置信面积+预期区域命中打分）。
调用方优先用几何法；置信度不足时降级 det 打分。
"""
from __future__ import annotations

import math
from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

# cv2 旋转常量映射（逆时针角度 -> cv2.rotate 码）
_ROTATE_CODES = {90: cv2.ROTATE_90_COUNTERCLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_CLOCKWISE}

# 归一化坐标区域 (x0, y0, x1, y1)，用于 det 打分：左侧竖排区 + 右上角分数区
_EXPECTED_REGIONS = ((0.0, 0.0, 0.25, 0.60), (0.6, 0.0, 1.0, 0.35))


def rotate_image(image: np.ndarray, angle: int) -> np.ndarray:
    """按逆时针角度旋转（0/90/180/270）。"""
    if angle == 0:
        return image
    if angle not in _ROTATE_CODES:
        raise ValueError(f"不支持的角度: {angle}")
    return cv2.rotate(image, _ROTATE_CODES[angle])


def estimate_by_lines(gray: np.ndarray) -> Optional[int]:
    """几何法：统计四个姿态下的近水平长线，返回得分最高的姿态（逆时针角度）。

    试卷版面满页横线（答题线/表格线），正立时水平长线最多。
    返回 None 表示置信不足，调用方应降级 det 打分法。
    """
    h, w = gray.shape[:2]
    min_line_len = max(h, w) * 0.25

    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=80,
                            minLineLength=int(min_line_len), maxLineGap=20)
    if lines is None or len(lines) == 0:
        return None

    counts = [0, 0, 0, 0]
    for line in lines[:, 0]:
        x1, y1, x2, y2 = line
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < min_line_len * 0.5:
            continue
        angle_deg = abs(math.degrees(math.atan2(dy, dx)))
        # 该线段在"文字朝上"姿态下对应的角度
        if angle_deg < 10 or angle_deg > 170:      # 近水平 → 0°
            counts[0] += 1
        elif 80 < angle_deg < 100:                  # 近垂直 → 90°/270°（需进一步区分）
            counts[1] += 1
            counts[3] += 1

    total = sum(counts)
    if total == 0:
        return None
    if counts[0] >= counts[1]:  # 水平线占优 → 0°（180° 时水平线同样多，靠文字行信息修正）
        return 0
    return None  # 垂直姿态无法用本方法区分 90/270，降级


def score_by_det(gray: np.ndarray, detect: Callable[[np.ndarray], Sequence[Tuple[float, float, float, float, float]]]) -> int:
    """det 打分法：四姿态各跑一次检测，按"文本置信面积 + 预期区域命中"打分。

    detect 签名：detect(gray) -> [(x0, y0, x1, y1, confidence), ...]（像素坐标）。
    返回得分最高的姿态（逆时针角度）。速度较慢（4 次检测），仅作备选。
    """
    h, w = gray.shape[:2]
    best_angle, best_score = 0, -1.0
    for angle in (0, 90, 180, 270):
        img = rotate_image(gray, angle)
        ih, iw = img.shape[:2]
        try:
            boxes = detect(img)
        except Exception:
            continue
        score = 0.0
        for (bx0, by0, bx1, by1, conf) in boxes:
            area = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
            score += conf * area / (iw * ih)  # 置信面积占比
            cx, cy = (bx0 + bx1) / 2 / iw, (by0 + by1) / 2 / ih
            for (rx0, ry0, rx1, ry1) in _EXPECTED_REGIONS:
                if rx0 <= cx <= rx1 and ry0 <= cy <= ry1:
                    score += conf * 0.5  # 命中预期区域加分
        if score > best_score:
            best_angle, best_score = angle, score
    return best_angle


def normalize_orientation(gray: np.ndarray, detect: Optional[Callable] = None) -> Tuple[np.ndarray, int]:
    """归一页方向：返回（摆正后的灰度图, 采用的逆时针角度）。

    几何法为主；置信不足时若提供了 detect 则降级打分法；仍失败保持原图。
    """
    angle = estimate_by_lines(gray)
    if angle is None and detect is not None:
        angle = score_by_det(gray, detect)
    if angle is None:
        angle = 0
    return rotate_image(gray, angle), angle
