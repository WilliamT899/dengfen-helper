#!/usr/bin/env python3
"""CI 冒烟测试：程序生成模拟试卷图（印刷体），跑全管线验证字段提取与导出。

不依赖真实样本（隐私原因，样本图不入公开仓库）。
模拟图版式与真实试卷一致：左竖排姓名/学号/班级栏 + 右上角大号分数。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.ocr.engine import get_engine  # noqa: E402
from app.ocr.pipeline import recognize_image  # noqa: E402


def _find_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, 48)
    return ImageFont.load_default()


def make_paper(name: str, sid: str, klass: str, score: str) -> np.ndarray:
    """生成 1280x1707 模拟试卷：左竖排信息栏 + 右上角分数。"""
    img = Image.new("RGB", (1280, 1707), "white")
    draw = ImageDraw.Draw(img)
    font_big = _find_font()
    font_small = ImageFont.truetype(font_big.path, 36) if hasattr(font_big, "path") else font_big

    # 顶部标题
    title = "2025-2026学年第二学期期末水平测试"
    draw.text((280, 80), title, fill="black", font=font_small)

    # 右上角大号分数（模拟手写：粗体大字）
    font_score = ImageFont.truetype(font_big.path, 140) if hasattr(font_big, "path") else font_big
    draw.text((880, 140), score, fill="black", font=font_score, stroke_width=2)

    # 左侧竖排信息栏（逐字竖写；真实版式：值在上、印刷标签在下）
    x = 60
    def draw_vertical(text: str, y: int, font, fill="black"):
        for ch in text:
            draw.text((x, y), ch, fill=fill, font=font)
            y += font.size + 12
        return y

    y = 200
    y = draw_vertical(name, y, font_small)
    y = draw_vertical("姓名：", y + 10, font_small)
    y += 100
    y = draw_vertical(sid, y, font_small)
    y = draw_vertical("学号：", y + 10, font_small)
    y += 100
    y = draw_vertical(klass, y, font_small)
    draw_vertical("班级：", y + 10, font_small)

    # 密封线
    draw.line([(180, 0), (180, 1707)], fill="gray", width=2)

    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def main() -> int:
    engine = get_engine()
    cases = [("王小明", "01", "三年级1班", "95.5"), ("李小红", "02", "三年级1班", "100")]
    for name, sid, klass, score in cases:
        img = make_paper(name, sid, klass, score)
        r = recognize_image(img, engine)
        print(f"合成图 {name}: OCR姓名={r.name!r} 学号={r.student_id!r} 分数={r.score}")
        assert r.score is not None, "分数识别失败"
        assert r.name, "姓名识别失败"
    print("合成图冒烟测试通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
