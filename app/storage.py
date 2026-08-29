"""照片存档：姓名_分数.jpg 命名 + 同名自动加序号；修正后同步重命名。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple

SANITIZE_TABLE = str.maketrans({
    "/": "／", "\\": "＼", ":": "：", "*": "＊", "?": "？",
    '"': "＂", "<": "＜", ">": "＞", "|": "｜",
})


def _safe_name_part(name: str) -> str:
    return (name or "待确认").translate(SANITIZE_TABLE).strip() or "待确认"


def build_filename(name: str, score: Optional[float], ext: str = ".jpg") -> str:
    score_part = f"{score:g}" if score is not None else ""
    parts = [p for p in (_safe_name_part(name), score_part) if p]
    return "_".join(parts) + ext


def save_photo(src: Path, dest_dir: Path, name: str, score: Optional[float]) -> Path:
    """存档照片到目标目录，同名自动加序号（姓名_分数_2.jpg）。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = build_filename(name, score, ext=src.suffix.lower() or ".jpg")
    target = dest_dir / base
    if not target.exists():
        shutil.copyfile(src, target)
        return target
    stem, suffix = base.rsplit(".", 1)
    for i in range(2, 1000):
        cand = dest_dir / f"{stem}_{i}.{suffix}"
        if not cand.exists():
            shutil.copyfile(src, cand)
            return cand
    raise OSError(f"同名文件过多，无法存档: {base}")


def rename_photo(old_path: Path, new_name: str, new_score: Optional[float]) -> Optional[Path]:
    """人工修正姓名/分数后同步重命名照片文件。返回新路径（未变化则 None）。"""
    if not old_path.exists():
        return None
    new_base = build_filename(new_name, new_score, ext=old_path.suffix)
    if old_path.name == new_base:
        return None
    target = old_path.with_name(new_base)
    if target.exists():
        stem, suffix = new_base.rsplit(".", 1)
        for i in range(2, 1000):
            cand = old_path.with_name(f"{stem}_{i}.{suffix}")
            if not cand.exists():
                target = cand
                break
    old_path.rename(target)
    return target
