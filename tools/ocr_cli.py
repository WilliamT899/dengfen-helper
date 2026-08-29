#!/usr/bin/env python3
"""阶段1 验收 CLI：对样本图片跑全管线，打印逐字段结果（含标准答案校验）。

用法:
  python tools/ocr_cli.py                       # 跑全部样本
  python tools/ocr_cli.py 样本图片/样本图片2.jpg  # 单张
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ocr.engine import get_engine  # noqa: E402
from app.ocr.pipeline import recognize_file  # noqa: E402

GROUND_TRUTH = {
    "样本图片1": ("邢子洋", "28", 99.0),
    "样本图片2": ("陈曦", "20", 88.5),
    "样本图片3": ("邓睿泽", "22", 96.0),
    "样本图片4": ("张梓凌", "13", 100.0),
    "样本图片5": ("朱芷瑶", "14", 97.0),
    "样本图片6": ("柯梓涵", "38", 98.0),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="登分助手 OCR 管线 CLI")
    ap.add_argument("images", nargs="*", help="图片路径（缺省跑全部样本）")
    args = ap.parse_args()

    engine = get_engine()
    files = [Path(p) for p in args.images] if args.images else sorted(Path("样本图片").glob("*.jpg"))
    if not files:
        print("未找到图片")
        return 1

    stats = {"name": 0, "id": 0, "score": 0}
    total = 0
    for img_path in files:
        result = recognize_file(img_path, engine)
        print(f"===== {img_path.name} (角度={result.angle}°, 耗时={result.seconds:.1f}s) =====")
        print(f"  姓名: {result.name!r}  学号: {result.student_id!r}  班级: {result.klass!r}")
        print(f"  分数: {result.score} (conf={result.score_conf:.2f}, 原文={result.score_raw!r})")

        gt = GROUND_TRUTH.get(img_path.stem)
        if gt:
            total += 1
            marks = []
            if result.name == gt[0]:
                stats["name"] += 1
                marks.append("姓名✓")
            else:
                marks.append(f"姓名✗(应={gt[0]})")
            if result.student_id == gt[1]:
                stats["id"] += 1
                marks.append("学号✓")
            else:
                marks.append(f"学号✗(应={gt[1]})")
            if result.score == gt[2]:
                stats["score"] += 1
                marks.append("分数✓")
            else:
                marks.append(f"分数✗(应={gt[2]})")
            print(f"  校验: {' '.join(marks)}")

    if total:
        print(f"\n汇总: 姓名 {stats['name']}/{total}, 学号 {stats['id']}/{total}, 分数 {stats['score']}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
