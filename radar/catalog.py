"""云南大学认定本科生学科竞赛目录的加载与匹配。"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from .textutil import normalize_name

# 这些词在所有赛事名里反复出现，去掉之后剩下的片段才是有区分度的部分
GENERIC_PARTS = [
    "全国大学生", "中国大学生", "全国高校", "全国", "中国", "大学生", "高校", "国际",
    "赛事", "大赛", "竞赛", "比赛", "挑战赛", "专业人才", "作品",
]


def _distinctive_chunks(name: str) -> list[str]:
    """把赛事名里可区分、可检索的片段抽出来，用于"整个名字被包住"以外的匹配。"""
    s = normalize_name(name)
    for part in GENERIC_PARTS:
        s = s.replace(part, "|")
    return [c for c in s.split("|") if len(c) >= 3]


@dataclass
class CatalogEntry:
    no: int
    name: str
    dept: str
    owner: str
    category: str

    def as_dict(self) -> dict:
        return {"no": self.no, "name": self.name, "dept": self.dept,
                "owner": self.owner, "category": self.category}


class Catalog:
    """官方目录。meta 里保留来源链接与文件指纹，确保可追溯、可复核。"""

    def __init__(self, entries: list[CatalogEntry], meta: dict | None = None):
        self.entries = entries
        self.meta = meta or {}
        self._norm = [(normalize_name(e.name), e) for e in entries]
        self._chunks = [(_distinctive_chunks(e.name), e) for e in entries]

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        if not path.exists():
            return cls([], {"loaded": False})
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = [CatalogEntry(**e) for e in data["entries"]]
        return cls(entries, data.get("meta", {}))

    @property
    def categories(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            out[e.category] = out.get(e.category, 0) + 1
        return out

    def match(self, name: str, threshold: float = 0.72) -> tuple[CatalogEntry | None, float, str]:
        """返回 (命中条目, 置信度, 匹配方式)。匹配不上说明该赛事未在当前目录中。"""
        if not name or not self.entries:
            return None, 0.0, "no-catalog"
        # 常见近义词：目录写"团体程序设计"，通知写"团队程序设计"
        target = normalize_name(name).replace("团队", "团体")
        if not target:
            return None, 0.0, "empty"

        # 1) 直接包含（通知标题通常包含完整赛事名）
        best_contain: tuple[CatalogEntry | None, float] = (None, 0.0)
        for norm, entry in self._norm:
            if not norm:
                continue
            if norm in target or target in norm:
                ratio = min(len(norm), len(target)) / max(len(norm), len(target))
                score = 0.80 + 0.15 * ratio
                if score > best_contain[1]:
                    best_contain = (entry, score)
        if best_contain[0] is not None and best_contain[1] >= 0.85:
            return best_contain[0], round(best_contain[1], 3), "contains"

        # 2) 相似度
        norms = [n for n, _ in self._norm]
        best = difflib.get_close_matches(target, norms, n=1, cutoff=threshold)
        if best:
            entry = next(e for n, e in self._norm if n == best[0])
            ratio = difflib.SequenceMatcher(None, target, best[0]).ratio()
            return entry, round(ratio, 3), "fuzzy"

        # 3) 目录赛事名的可区分片段全部被目标串包含（应对届次、赛道、报名等后缀）
        best_chunk: tuple[CatalogEntry | None, float] = (None, 0.0)
        for chunks, entry in self._chunks:
            if not chunks or sum(len(c) for c in chunks) < 4:
                continue
            if all(c in target for c in chunks):
                score = 0.75 + 0.2 * min(1.0, len("".join(chunks)) / max(len(normalize_name(entry.name)), 1))
                if score > best_chunk[1]:
                    best_chunk = (entry, score)
        if best_chunk[0] is not None:
            return best_chunk[0], round(best_chunk[1], 3), "chunks"

        if best_contain[0] is not None and best_contain[1] >= 0.80:
            return best_contain[0], round(best_contain[1], 3), "contains-weak"
        return None, 0.0, "miss"
