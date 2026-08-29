#!/usr/bin/env python3
"""字段提取原型 v2：左竖条旋转(标签:值同行解析) + 全页检测右上角分数。

用法: python tools/proto_extract.py [--debug 样本图片X.jpg]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.ocr import postprocess  # noqa: E402
from app.ocr.engine import OcrEngine  # noqa: E402
from app.ocr.pipeline import _downscale, load_image  # noqa: E402

GROUND_TRUTH = {
    "样本图片1": ("邢子洋", "28", 99.0),
    "样本图片2": ("陈曦", "20", 88.5),
    "样本图片3": ("邓睿泽", "22", 96.0),
    "样本图片4": ("张梓凌", "13", 100.0),
    "样本图片5": ("朱芷瑶", "14", 97.0),
    "样本图片6": ("柯梓涵", "38", 98.0),
}

STRIP_X = 0.16   # 左侧竖条宽度（密封线内）


def extract_left_fields(engine: OcrEngine, img: np.ndarray):
    """左竖条顺时针转 90°，解析"标签:值"行与独立值。"""
    h, w = img.shape[:2]
    strip = img[:, 0:int(STRIP_X * w)]
    rot = cv2.rotate(strip, cv2.ROTATE_90_CLOCKWISE)
    lines = sorted(engine.run(rot), key=lambda l: l[0][1])
    fields: dict = {}
    labels = {"姓名", "学号", "班级", "学校"}
    for box, text, conf in lines:
        t = text.strip()
        if "：" in t or ":" in t:
            label, _, value = t.replace(":", "：").partition("：")
            label = label.strip()
            if label in labels:
                fields.setdefault(label, (value.strip(), conf))
        else:
            # 独立值行：留给标签行缺值时配对（按 y 最近）
            fields.setdefault("_loose", []).append((t, (box[1] + box[3]) / 2, conf))
    # 标签行没有值 → 找同行高度的独立值
    loose = fields.pop("_loose", [])
    for label in ("姓名", "学号", "班级"):
        if label in fields and not fields[label][0]:
            # 值可能在同一条竖线的相邻位置：直接用最近 loose
            if loose:
                loose.sort(key=lambda x: x[1])
                fields[label] = (loose[0][0], loose[0][2])
    return fields


def extract_score_fullpage(engine: OcrEngine, img: np.ndarray):
    """全页检测：右上角 (x>0.62, y<0.2) 高度≥8% 页高的文本行 = 分数。"""
    h, w = img.shape[:2]
    lines = engine.run(img)
    cands = []
    for box, text, conf in lines:
        x0, y0, x1, y1 = box
        if x0 / w > 0.62 and y1 / h < 0.20 and (y1 - y0) / h >= 0.08:
            parsed = postprocess.parse_score(text)
            if parsed.value is not None:
                cands.append((parsed.value, parsed.warning, conf, text))
    if not cands:
        return None, 0.0, []
    # 大字优先、非修补优先
    cands.sort(key=lambda c: (-c[2], c[1]))
    return cands[0][0], cands[0][2], [c[3] for c in cands]


def main():
    import time
    engine = OcrEngine()
    files = sorted(Path("样本图片").glob("*.jpg"))
    if len(sys.argv) > 1:
        files = [Path(sys.argv[1])]
    for f in files:
        t0 = time.monotonic()
        img = _downscale(load_image(f))
        left = extract_left_fields(engine, img)
        score, sconf, stexts = extract_score_fullpage(engine, img)
        dt = time.monotonic() - t0
        print(f"{f.name} ({dt:.1f}s)")
        print(f"   左侧字段: {left}")
        print(f"   分数: {score} (conf={sconf:.2f}, 原文={stexts})")
        if f.stem in GROUND_TRUTH:
            gt_name, gt_id, gt_score = GROUND_TRUTH[f.stem]
            name = left.get("姓名", ("",))[0]
            sid = left.get("学号", ("",))[0]
            ok = lambda a, b: "✓" if a == b else f"✗(应={b})"
            print(f"   校验: 姓名 {ok(name, gt_name)}  学号 {ok(sid, gt_id)}  分数 {ok(score, gt_score)}")


if __name__ == "__main__":
    main()
