from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


def root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


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
        sources=_load(cfg_dir / "sources.toml")["source"],
        focus=focus,
    )
