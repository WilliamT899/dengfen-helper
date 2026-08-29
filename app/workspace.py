"""登分工作区数据模型：表格行的内存表示 + 本地 JSON 自动保存。

一次"登分"= 一个工作区：名单导入后按名单初始化行，识别结果回填分数。
意外关闭不丢失；支持"新建登分"与"继续上次"。
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app import config
from app.roster import Roster, Student, _id_sort_key

# 行状态
EMPTY = "empty"              # 分数未登
PENDING = "pending"          # 识别不明确，待人工确认（黄色高亮）
FILLED = "filled"            # 已登分


@dataclass
class Row:
    student_id: str = ""
    name: str = ""
    klass: str = ""
    score: Optional[float] = None
    status: str = EMPTY
    photo: str = ""          # 存档照片路径

    @property
    def key(self):
        return (self.student_id, self.name)


@dataclass
class Workspace:
    rows: List[Row] = field(default_factory=list)
    save_path: Path = field(default_factory=config.workspace_path)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- 名单初始化 -------------------------------------------------
    def init_from_roster(self, roster: Roster, keep_scores: bool = True):
        """按名单重建行。keep_scores=True 时保留已有分数（同名同学号）。"""
        old: Dict = {r.key: r for r in self.rows}
        new_rows = []
        for st in sorted(roster.students, key=lambda s: (s.klass, _id_sort_key(s))):
            prev = old.get((st.student_id, st.name))
            new_rows.append(Row(
                student_id=st.student_id, name=st.name, klass=st.klass,
                score=prev.score if keep_scores and prev else None,
                status=(FILLED if prev and prev.score is not None else EMPTY),
                photo=prev.photo if prev else "",
            ))
        with self._lock:
            self.rows = new_rows

    # ---- 识别结果回填 -------------------------------------------------
    def apply_result(self, student_id: str, name: str, klass: str,
                     score: Optional[float], photo: str,
                     match_status: str = "unique") -> Row:
        """把一张照片的识别结果落到表格行。

        - 名单中存在（学号/姓名命中）→ 回填对应行
        - 名单外 → 追加一行（klass 未知时用"未分班"）
        - PENDING（多候选/无匹配）→ 新行状态 pending
        """
        with self._lock:
            for r in self.rows:
                if student_id and r.student_id == student_id:
                    r.score = score
                    r.status = FILLED if score is not None else PENDING
                    r.photo = photo
                    return r
            for r in self.rows:
                if name and r.name == name:
                    r.score = score
                    r.status = FILLED if score is not None else PENDING
                    r.photo = photo
                    return r
            row = Row(student_id=student_id, name=name or "", klass=klass or "未分班",
                      score=score, status=(FILLED if match_status == "unique" and score is not None else PENDING),
                      photo=photo)
            self.rows.append(row)
            return row

    def find_by_name(self, name: str) -> Optional[Row]:
        with self._lock:
            for r in self.rows:
                if r.name == name:
                    return r
        return None

    # ---- 持久化 ------------------------------------------------------
    def to_json(self) -> str:
        with self._lock:
            return json.dumps({"rows": [asdict(r) for r in self.rows]},
                              ensure_ascii=False, indent=1)

    def save(self, path: Optional[Path] = None) -> Path:
        target = path or self.save_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Workspace":
        target = path or config.workspace_path()
        ws = cls(save_path=target)
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                ws.rows = [Row(**{k: r.get(k) for k in ("student_id", "name", "klass", "score", "status", "photo")})
                           for r in data.get("rows", [])]
            except (json.JSONDecodeError, TypeError):
                ws.rows = []
        return ws
