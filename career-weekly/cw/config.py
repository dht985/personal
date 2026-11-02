from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCE_PURPOSES = ("recruit", "policy", "news")


def source_purpose(source: dict) -> str:
    """返回信源用途；未显式标注时按名称和 ID 做保守推断。"""
    explicit = source.get("purpose")
    if explicit in SOURCE_PURPOSES:
        return explicit
    label = f"{source.get('id', '')} {source.get('name', '')}".lower()
    if any(k in label for k in ("recruit", "招聘", "人才")):
        return "recruit"
    if any(k in label for k in (
        "policy", "xxgk", "信息公开", "政策", "规划", "制度",
        "通知公告", "公示公告", "企业公告",
    )):
        return "policy"
    return "news"


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _sources(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = _load(path).get("source", [])
    out = []
    for item in items:
        normalized = dict(item)
        normalized["purpose"] = source_purpose(normalized)
        out.append(normalized)
    return out


@dataclass
class Config:
    base: Path
    settings: dict
    units: list[dict]
    tracks: list[dict]
    tags: list[dict]
    sources: list[dict]
    focus: list[str]

    @property
    def data_dir(self) -> Path:
        return self.base / self.settings["paths"]["data"]

    @property
    def raw_dir(self) -> Path:
        return self.base / self.settings["paths"]["raw"]

    @property
    def outbox_dir(self) -> Path:
        return self.base / self.settings["paths"]["outbox"]

    @property
    def db_path(self) -> Path:
        return self.base / self.settings["paths"]["db"]

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.raw_dir, self.outbox_dir):
            p.mkdir(parents=True, exist_ok=True)

    def unit_map(self) -> dict[str, dict]:
        return {u["id"]: u for u in self.units}

    def level_of(self, unit_id: str) -> int:
        return int(self.unit_map().get(unit_id, {}).get("level", 0))

    def path_of(self, unit_id: str) -> str:
        units = self.unit_map()
        chain = []
        cur = unit_id
        while cur and cur in units:
            chain.append(units[cur].get("short") or units[cur]["name"])
            cur = units[cur].get("parent")
        return " > ".join(reversed(chain))


def load(base: Path | None = None) -> Config:
    base = base or root()
    cfg_dir = base / "config"
    tracks_data = _load(cfg_dir / "tracks.toml")
    sources = _sources(cfg_dir / "sources.toml")
    sources += _sources(cfg_dir / "sources_auto.toml")
    deduped: list[dict] = []
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    for source in sources:
        url = source.get("url")
        if (url and url in seen_urls) or source.get("id") in seen_ids:
            continue
        if url:
            seen_urls.add(url)
        seen_ids.add(source.get("id"))
        deduped.append(source)
    sources = deduped
    units = _load(cfg_dir / "units.toml")["unit"]
    l2_path = cfg_dir / "units_l2.toml"
    if l2_path.exists():
        units = units + _load(l2_path)["unit"]
    focus_path = cfg_dir / "focus.toml"
    focus = _load(focus_path)["active"] if focus_path.exists() else [u["id"] for u in units]
    return Config(
        base=base,
        settings=_load(cfg_dir / "settings.toml"),
        units=units,
        tracks=tracks_data.get("track", []),
        tags=tracks_data.get("tag", []),
        sources=sources,
        focus=focus,
    )
