"""识别结果后处理（纯函数，可单测）。

分数：正则校验 + 小数点启发式（手写常漏点，"985"→98.5）+ 日期过滤
姓名：仅保留汉字，去重去标签
学号：仅保留数字，保留前导 0
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# 分数合法范围（上限容忍到 110 并标黄，便于发现异常）
SCORE_MIN = 0.0
SCORE_MAX = 100.0
SCORE_WARN_MAX = 110.0

_SCORE_RE = re.compile(r"^\d{1,3}(\.\d{1,2})?$")
_DATE_RE = re.compile(r"^\d{4}\.\d{1,2}$")  # 印刷日期"2026.7"
_NAME_KEEP_RE = re.compile(r"[^一-鿿·]")
_NAME_LABELS = {"姓名", "学号", "班级", "学校", "年级"}


@dataclass
class ScoreResult:
    value: Optional[float] = None
    raw: str = ""
    warning: bool = False  # 超出 0~100 但 <110，或经小数点启发式修补


def parse_score(text: str) -> ScoreResult:
    """解析分数文本。手写常漏小数点：'985' → 98.5。

    规则：去掉空格/逗号/句号噪声；若为纯数字但超出 100，
    尝试在末位前插小数点；仍不合法则返回 None（留空人工，绝不错填）。
    """
    raw = text.strip().replace(" ", "").replace(",", ".").replace("。", ".")
    if not raw or _DATE_RE.match(raw):
        return ScoreResult(raw=text)
    if _SCORE_RE.match(raw):
        v = float(raw)
        if v <= SCORE_WARN_MAX:
            return ScoreResult(value=v, raw=text, warning=not (SCORE_MIN <= v <= SCORE_MAX))
    # 纯数字但超范围（如 985/1005，_SCORE_RE 只放行 ≤3 位整数）：
    # 尝试插入小数点，候选优先级：末位 0/5 优先 → 小数位少优先 → 值大优先
    # （985→98.5，1005→100.5，987→98.7）
    if raw.isdigit():
        candidates = []
        for i in range(1, len(raw)):
            cand = float(raw[:i] + "." + raw[i:])
            if SCORE_MIN <= cand <= SCORE_MAX:
                tail_05 = raw.endswith(("0", "5"))
                candidates.append((not tail_05, len(raw) - i, -cand, cand))
        if candidates:
            candidates.sort()
            return ScoreResult(value=candidates[0][3], raw=text, warning=True)
        return ScoreResult(raw=text)  # 无合法插入点 → 噪声
    return ScoreResult(raw=text)


def normalize_name(text: str) -> str:
    """姓名清洗：仅保留汉字与间隔号，去掉"姓名"等印刷标签。"""
    cleaned = _NAME_KEEP_RE.sub("", text)
    for label in _NAME_LABELS:
        cleaned = cleaned.replace(label, "")
    return cleaned.strip()


def normalize_student_id(text: str) -> str:
    """学号：仅保留数字，保留前导 0。"""
    return re.sub(r"\D", "", text).strip()


def is_score_candidate(text: str) -> bool:
    """是否为分数候选文本（用于分数区多行结果挑选）。"""
    t = text.strip()
    return bool(_SCORE_RE.match(t) or re.fullmatch(r"\d{2,4}", t))
