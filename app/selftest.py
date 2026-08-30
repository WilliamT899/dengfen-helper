"""打包完整性自测：合成试卷图跑全管线（exe 内置 --smoke 模式调用）。

验证：模型可加载、rapidocr 包数据（yaml）齐全、识别管线可用。
结果写入 smoke_result.txt 供 CI 检查（windowed exe 无控制台输出）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.ocr.engine import get_engine
from app.ocr.pipeline import recognize_image


_CJK_FONTS = (
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)
_DIGIT_FONTS = _CJK_FONTS + ("C:/Windows/Fonts/arial.ttf",)


def _find_font(cjk: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (_CJK_FONTS if cjk else _DIGIT_FONTS):
        if Path(path).exists():
            return ImageFont.truetype(path, 48)
    return ImageFont.load_default()


def make_paper(name: str, sid: str, klass: str, score: str) -> np.ndarray:
    """生成 1280x1707 模拟试卷：左竖排信息栏 + 右上角分数。"""
    img = Image.new("RGB", (1280, 1707), "white")
    draw = ImageDraw.Draw(img)
    font_big = _find_font()
    font_small = ImageFont.truetype(font_big.path, 36) if hasattr(font_big, "path") else font_big
    # 分数是数字：无中文字体的环境（CI Windows）用 Arial 渲染保证可识别
    score_font = _find_font(cjk=False)
    font_score = ImageFont.truetype(score_font.path, 140) if hasattr(score_font, "path") else score_font

    draw.text((280, 80), "2025-2026学年第二学期期末水平测试", fill="black", font=font_small)
    draw.text((960, 140), score, fill="black", font=font_score, stroke_width=2)

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

    draw.line([(180, 0), (180, 1707)], fill="gray", width=2)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def run_smoke(result_file: str = "smoke_result.txt") -> int:
    """跑合成图冒烟，成功写 SMOKE_OK 到结果文件。"""
    try:
        engine = get_engine()
        has_cjk = any(Path(p).exists() for p in _CJK_FONTS)
        cases = [("王小明", "01", "三年级1班", "95.5"), ("李小红", "02", "三年级1班", "100")]
        for name, sid, klass, score in cases:
            img = make_paper(name, sid, klass, score)
            r = recognize_image(img, engine)
            assert r.score is not None, f"分数识别失败（{name}）"
            if has_cjk:
                assert r.name, f"姓名识别失败（{name}）"
        Path(result_file).write_text("SMOKE_OK", encoding="utf-8")
        return 0
    except Exception as exc:
        Path(result_file).write_text(f"SMOKE_FAIL: {exc}", encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(run_smoke())
