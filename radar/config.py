"""配置加载：TOML 配置 + 项目路径。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


@dataclass
class Config:
    root: Path
    settings: dict[str, Any]
    sources: list[dict[str, Any]]
    keywords: dict[str, Any]
    scoring: dict[str, Any] = field(default_factory=dict)

    # ---- path helpers -------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self.root / self.settings["paths"]["data"]

    @property
    def raw_dir(self) -> Path:
        return self.root / self.settings["paths"]["raw"]

    @property
    def outbox_dir(self) -> Path:
        return self.root / self.settings["paths"]["outbox"]

    @property
    def catalog_path(self) -> Path:
        return self.root / self.settings["paths"]["catalog"]

    @property
    def catalog_prev_path(self) -> Path:
        return self.root / self.settings["paths"]["catalog_prev"]

    @property
    def candidates_path(self) -> Path:
        return self.root / self.settings["paths"]["candidates"]

    @property
    def db_path(self) -> Path:
        return self.root / self.settings["paths"]["db"]

    @property
    def szcp_path(self) -> Path:
        return self.root / self.settings["paths"]["szcp"]

    @property
    def szcp_college_path(self) -> Path:
        return self.root / self.settings["paths"]["szcp_college"]

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.raw_dir, self.outbox_dir):
            p.mkdir(parents=True, exist_ok=True)


def load_config(root: Path | None = None) -> Config:
    root = root or project_root()
    cfg_dir = root / "config"
    scoring_path = cfg_dir / "scoring.toml"
    return Config(
        root=root,
        settings=_read_toml(cfg_dir / "settings.toml"),
        sources=_read_toml(cfg_dir / "sources.toml")["source"],
        keywords=_read_toml(cfg_dir / "keywords.toml"),
        scoring=_read_toml(scoring_path) if scoring_path.exists() else {},
    )
