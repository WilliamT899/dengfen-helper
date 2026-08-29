"""版式模板：用归一化坐标（相对页宽高 0~1，左上角原点）描述识别区域。

多学科扩展 = 新增 LayoutTemplate（或加载 JSON）；用户框选区域（后期功能）
只是"可视化生成模板"的另一种入口，管线无需改动。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple


class Rotate(str, Enum):
    """区域内容相对于页面的书写方向处理策略。"""

    NONE = "none"      # 横排，不旋转
    CW90 = "cw90"      # 固定顺时针转 90° 后识别（竖排文字）
    ALL = "all"        # 0°/90°/180°/270° 各跑一次，择优（竖排手写区）

    def angles(self) -> List[int]:
        if self is Rotate.NONE:
            return [0]
        if self is Rotate.CW90:
            return [90]
        return [0, 90, 180, 270]


@dataclass
class Region:
    """归一化区域 (x0, y0, x1, y1)，左上角原点，闭区间 [0,1]。"""

    x0: float
    y0: float
    x1: float
    y1: float
    rotate: Rotate = Rotate.NONE
    # 保留给后续扩展（如后处理钩子名）
    meta: Dict = field(default_factory=dict)

    def to_pixels(self, width: int, height: int) -> Tuple[int, int, int, int]:
        return (
            int(self.x0 * width), int(self.y0 * height),
            max(int(self.x1 * width), int(self.x0 * width) + 1),
            max(int(self.y1 * height), int(self.y0 * height) + 1),
        )


@dataclass
class LayoutTemplate:
    """一个试卷版式的区域集合。字段名即语义字段（姓名/学号/分数）。"""

    name: str
    description: str
    regions: Dict[str, Region]

    def get(self, field: str) -> Region:
        if field not in self.regions:
            raise KeyError(f"模板 {self.name} 缺少区域字段: {field}")
        return self.regions[field]


# 内置模板：三年级英语期末试卷（2025-2026 学年，据 6 张样本实测标定）
# 姓名/学号在左侧竖排栏（竖写），分数在右上角大号横写。
# 坐标经 PP-OCRv5 全页检测实测修正（2026-08-29）。
GRADE3_ENGLISH_FINAL = LayoutTemplate(
    name="grade3_english_final",
    description="三年级英语期末试卷：左竖排姓名/学号栏，右上角手写分数",
    regions={
        # 左侧竖排栏上部（姓名手写 + "姓名："标签，竖写 → 旋转识别）
        "name": Region(0.0, 0.07, 0.16, 0.38, rotate=Rotate.ALL),
        # 左侧竖排栏下部（学号手写 + "学号："标签）
        "id": Region(0.0, 0.38, 0.16, 0.70, rotate=Rotate.ALL),
        # 右上角分数区（大号横写手写 + 印刷日期"2026.7"，靠大小/位置过滤日期）
        "score": Region(0.66, 0.0, 1.0, 0.24, rotate=Rotate.NONE),
    },
)

BUILTIN_TEMPLATES: Dict[str, LayoutTemplate] = {
    GRADE3_ENGLISH_FINAL.name: GRADE3_ENGLISH_FINAL,
}


def get_template(name: str) -> LayoutTemplate:
    if name not in BUILTIN_TEMPLATES:
        raise KeyError(f"未知版式模板: {name}")
    return BUILTIN_TEMPLATES[name]
