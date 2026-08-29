"""识别结果 → 名单匹配（核心降级机制）。

学号优先：学号唯一命中 → 高置信自动接受（姓名仅交叉校验）
姓名模糊匹配：rapidfuzz 相似度 ≥ 阈值取候选
返回三态：唯一命中 / 多候选 / 无匹配
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from rapidfuzz import fuzz

from app.roster import Roster, Student

NAME_THRESHOLD = 0.65   # 姓名整体相似度阈值（Levenshtein ratio）
CHAR_THRESHOLD = 0.5    # 逐字重合率阈值（防 OCR 漏字/多字）


@dataclass
class MatchResult:
    status: str                 # unique / multiple / none
    student: Optional[Student] = None
    candidates: List[Student] = None  # type: ignore[assignment]
    method: str = ""            # id / name

    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []

    @property
    def is_unique(self) -> bool:
        return self.status == "unique"


def _char_overlap(a: str, b: str) -> float:
    """逐字重合率（Jaccard），抗 OCR 多字/漏字。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _name_similarity(a: str, b: str) -> float:
    """综合相似度：整体编辑距离 + 逐字重合。"""
    ratio = fuzz.ratio(a, b) / 100.0
    overlap = _char_overlap(a, b)
    return max(ratio, overlap)


def match_student(name: str, student_id: str, roster: Roster) -> MatchResult:
    """匹配名单。姓名/学号都可能为空。"""
    id_index = roster.id_index()

    if student_id:
        id_hits = id_index.get(student_id, [])
        if len(id_hits) == 1:
            st = id_hits[0]
            # 学号唯一命中：姓名仅交叉校验，不阻断（姓名识别失败也不影响）
            return MatchResult(status="unique", student=st, candidates=[st], method="id")
        if len(id_hits) > 1:
            # 同名学号重复（异常数据），用姓名再收窄
            narrowed = [s for s in id_hits if name and _name_similarity(name, s.name) >= NAME_THRESHOLD]
            if len(narrowed) == 1:
                return MatchResult(status="unique", student=narrowed[0], candidates=narrowed, method="id+name")
            if narrowed:
                return MatchResult(status="multiple", candidates=narrowed, method="id+name")
            return MatchResult(status="multiple", candidates=id_hits, method="id")

    if name:
        scored = [(s, _name_similarity(name, s.name)) for s in roster.students]
        scored = [(s, sc) for s, sc in scored if sc >= NAME_THRESHOLD]
        scored.sort(key=lambda t: -t[1])
        if not scored:
            return MatchResult(status="none")
        best_score = scored[0][1]
        top = [s for s, sc in scored if sc >= best_score - 0.05]
        if len(top) == 1:
            return MatchResult(status="unique", student=top[0], candidates=top, method="name")
        # 得分并列的多个候选
        if len({s.klass for s in top}) == 1 and len({s.name for s in top}) == 1:
            # 同名（不同学号？）按第一个算唯一
            return MatchResult(status="unique", student=top[0], candidates=top, method="name")
        return MatchResult(status="multiple", candidates=top[:5], method="name")

    return MatchResult(status="none")
