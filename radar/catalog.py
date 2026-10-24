"""云南大学认定本科生学科竞赛目录的加载与匹配。"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .textutil import normalize_name

# 这些词在所有赛事名里反复出现，去掉之后剩下的片段才是有区分度的部分
GENERIC_PARTS = [
    "全国大学生", "中国大学生", "全国高校", "全国", "中国", "大学生", "高校", "国际",
    "赛事", "大赛", "竞赛", "比赛", "挑战赛", "专业人才", "作品",
]

# 同一赛事体系下不同赛事的限定词。若目标里出现而目录条目里没有，
# 说明是另一场比赛（如"美国大学生数学建模竞赛" vs 全国赛），不能当成同一条。
CONFLICT_QUALIFIERS = ("美国", "亚太", "欧洲", "亚洲", "世界", "全球", "国际")

# 阶段后缀：目录里是"华为ICT大赛"，通知写"华为ICT大赛全球总决赛"。
# 这类后缀不能影响赛事识别，也不能让"全球"触发冲突词。
STAGE_SUFFIX_RE = re.compile(
    r"(?:全球|全国|国际|区域|大区|省级|校级)?"
    r"(?:总决赛|决赛|半决赛|复赛|初赛|选拔赛|邀请赛|分赛区|赛区|区域赛|省赛|校赛)$"
)

# 同一赛事的常见写法
ALIASES = (("acmicpc", "icpc"),)


def _apply_aliases(text: str) -> str:
    for src, dst in ALIASES:
        text = text.replace(src, dst)
    return text


def _strip_stage(text: str) -> str:
    return STAGE_SUFFIX_RE.sub("", text)


def _is_reordered_same(a: str, b: str) -> bool:
    """字符完全相同、只是顺序不同（如"国际大学生程序设计竞赛icpc" vs "icpc国际..."）。"""
    return len(a) >= 8 and len(a) == len(b) and sorted(a) == sorted(b)


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
        self._norm = [(_apply_aliases(normalize_name(e.name)), e) for e in entries]
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
        # 常见近义词 + 别名 + 阶段后缀
        raw = _apply_aliases(normalize_name(name).replace("团队", "团体"))
        if not raw:
            return None, 0.0, "empty"
        targets = [raw]
        stripped = _strip_stage(raw)
        if stripped and stripped != raw:
            targets.append(stripped)

        for target in targets:
            result = self._match_one(target, threshold)
            if result[0] is not None:
                return result
        return None, 0.0, "miss"

    def _match_one(
        self, target: str, threshold: float
    ) -> tuple[CatalogEntry | None, float, str]:
        def compatible(entry: CatalogEntry) -> bool:
            entry_norm = _apply_aliases(normalize_name(entry.name))
            return not any(
                q in target and q not in entry_norm for q in CONFLICT_QUALIFIERS
            )

        def norm_of(entry: CatalogEntry) -> str:
            return _apply_aliases(normalize_name(entry.name))

        # 1) 直接包含（通知标题通常包含完整赛事名）
        best_contain: tuple[CatalogEntry | None, float] = (None, 0.0)
        for norm, entry in self._norm:
            if not norm:
                continue
            if not compatible(entry):
                continue
            if _is_reordered_same(target, norm):
                return entry, 0.95, "alias-reorder"
            if norm in target or target in norm:
                ratio = min(len(norm), len(target)) / max(len(norm), len(target))
                score = 0.80 + 0.15 * ratio
                if score > best_contain[1]:
                    best_contain = (entry, score)
        if best_contain[0] is not None and best_contain[1] >= 0.85:
            return best_contain[0], round(best_contain[1], 3), "contains"

        # 2) 相似度
        norms = [n for n, _ in self._norm]
        candidates = [
            n for n, e in self._norm if compatible(e)
        ]
        best = difflib.get_close_matches(target, candidates, n=1, cutoff=threshold)
        if best:
            entry = next(e for n, e in self._norm if n == best[0])
            ratio = difflib.SequenceMatcher(None, target, best[0]).ratio()
            return entry, round(ratio, 3), "fuzzy"

        # 3) 目录赛事名的可区分片段全部被目标串包含（应对届次、赛道、报名等后缀）
        best_chunk: tuple[CatalogEntry | None, float] = (None, 0.0)
        for chunks, entry in self._chunks:
            if not compatible(entry):
                continue
            # 单个片段太短容易误伤（如"数学建模"），要求多片段或单片段足够长
            if not chunks or sum(len(c) for c in chunks) < 4:
                continue
            if len(chunks) == 1 and len(chunks[0]) < 6:
                continue
            if all(c in target for c in chunks):
                score = 0.75 + 0.2 * min(
                    1.0, len("".join(chunks)) / max(len(norm_of(entry)), 1)
                )
                if score > best_chunk[1]:
                    best_chunk = (entry, score)
        if best_chunk[0] is not None:
            return best_chunk[0], round(best_chunk[1], 3), "chunks"

        if best_contain[0] is not None and best_contain[1] >= 0.80:
            return best_contain[0], round(best_contain[1], 3), "contains-weak"
        return None, 0.0, "miss"
