"""综合测评加分计算。

分两层证据：
- 校级：学科竞赛获奖落在 G22 模块，模块上限 5 分（云大学〔2020〕2号）
- 院级（计科）：成果加分 = 成果基础分 × 竞赛分类等级权重 × 获奖等级分值权重 × 团队排名分值权重
  数值来自《2023级计科综合评测细则 v3.2》，由 tools/import_szcp.py 从 PDF 解析。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# 2025 目录有、2026 目录没有的竞赛，按细则降一级处理
DOWNGRADE = {"一类": "二类", "二类": "三类", "三类": "四类", "四类": "五类", "五类": "五类"}


@dataclass
class Bonus:
    category: str
    level: str
    award: str
    rank: str
    base: float
    category_weight: float
    award_weight: float
    rank_weight: float
    raw: float
    capped: float
    cap: float
    downgraded_from: str | None = None

    @property
    def formula(self) -> str:
        return (
            f"{self.base:g} × {self.category_weight:g} × "
            f"{self.award_weight:g} × {self.rank_weight:g} = {self.capped:g} 分"
        )

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "level": self.level,
            "award": self.award,
            "rank": self.rank,
            "formula": self.formula,
            "raw": round(self.raw, 2),
            "capped": round(self.capped, 2),
            "cap": self.cap,
            "downgraded_from": self.downgraded_from,
        }


class SzcpRules:
    """加载计科综测细则里的加分规则。"""

    def __init__(self, data: dict | None):
        self.data = data or {}
        self.rules = self.data.get("rules") or {}
        self.meta = self.data.get("meta") or {}

    @classmethod
    def load(cls, path: Path) -> "SzcpRules":
        if not path.exists():
            return cls(None)
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            return cls(None)

    @property
    def available(self) -> bool:
        return bool(self.rules.get("category_weight")) and bool(self.rules.get("base_score"))

    def resolve_category(self, current: str | None, previous: str | None) -> tuple[str | None, str | None]:
        """返回 (用于算分的类别, 降级来源)。2026 目录为准，掉出目录的按降一级处理。"""
        if current:
            return current, None
        if previous and previous in DOWNGRADE:
            return DOWNGRADE[previous], previous
        return None, None

    def estimate(
        self,
        category: str | None,
        level: str = "国家级",
        award: str = "一等及以上",
        rank: str = "第一",
        downgraded_from: str | None = None,
    ) -> Bonus | None:
        if not self.available or not category:
            return None
        weights = self.rules["category_weight"]
        bases = self.rules["base_score"]
        if category not in weights or level not in bases:
            return None
        base = float(bases[level])
        w_cat = float(weights[category])
        w_award = float(self.rules["award_weight"].get(award, 0))
        w_rank = float(self.rules["rank_weight"].get(rank, 0))
        cap = float(self.rules.get("cap", 5))
        raw = base * w_cat * w_award * w_rank
        return Bonus(
            category=category, level=level, award=award, rank=rank,
            base=base, category_weight=w_cat, award_weight=w_award, rank_weight=w_rank,
            raw=raw, capped=min(raw, cap), cap=cap, downgraded_from=downgraded_from,
        )

    def describe(self) -> str:
        if not self.available:
            return ""
        weights = "、".join(f"{k} {v:g}" for k, v in self.rules["category_weight"].items())
        return (
            f"依据《{self.meta.get('title', '计科综测细则')}》"
            f"（{self.meta.get('applicable_major', '')}，{self.meta.get('effective_year', '')}）："
            f"加分 = 基础分 × 分类权重 × 获奖权重 × 排名权重，"
            f"分类权重 {weights}，上限 {self.rules.get('cap')} 分。"
        )
