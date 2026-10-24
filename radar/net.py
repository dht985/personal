"""网络层：限速、重试、robots 检查、原始快照留痕。"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .config import Config


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None
    text: str
    raw_path: Path | None
    fetched_at: str
    from_cache: bool = False
    error: str | None = None
    content_type: str = ""

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and not self.error


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Fetcher:
    """礼貌型抓取器：同域限速、失败重试、本地缓存、原始快照。"""

    def __init__(self, cfg: Config, offline: bool = False, force: bool = False):
        http = cfg.settings["http"]
        self.cfg = cfg
        self.offline = offline
        self.force = force  # 忽略缓存，强制重新抓取
        self.timeout = http["timeout_seconds"]
        self.min_interval = http["min_host_interval_seconds"]
        self.max_retries = http["max_retries"]
        self.ttl = timedelta(hours=http.get("cache_ttl_hours", 6))
        self.save_raw = http.get("save_raw", True)
        self.raw_dir = cfg.raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": http["user_agent"],
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
            }
        )
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0, "blocked_by_robots": 0}

    # ---- internals ----------------------------------------------------
    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return self.raw_dir / f"{key}.body", self.raw_dir / f"{key}.json"

    def _read_cache(self, url: str) -> FetchResult | None:
        body, meta = self._cache_paths(url)
        if not body.exists() or not meta.exists():
            return None
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            # fetched_at 带时区，必须用同样带时区的"现在"相减，否则抛错并被静默吞掉
            age = datetime.now().astimezone() - datetime.fromisoformat(info["fetched_at"])
        except Exception:  # noqa: BLE001
            return None
        if age > self.ttl:
            return None
        raw = body.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        self.stats["cache_hits"] += 1
        return FetchResult(
            url=url,
            final_url=info.get("final_url", url),
            status=info.get("status"),
            text=text,
            raw_path=body,
            fetched_at=info["fetched_at"],
            from_cache=True,
            content_type=info.get("content_type", ""),
        )

    def _write_cache(self, url: str, result: FetchResult, raw: bytes) -> None:
        body, meta = self._cache_paths(url)
        body.write_bytes(raw)
        meta.write_text(
            json.dumps(
                {
                    "url": url,
                    "final_url": result.final_url,
                    "status": result.status,
                    "content_type": result.content_type,
                    "fetched_at": result.fetched_at,
                    "bytes": len(raw),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def robots_allowed(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(origin + "/robots.txt")
            try:
                resp = requests.get(
                    origin + "/robots.txt",
                    headers={"User-Agent": self.session.headers["User-Agent"]},
                    timeout=10,
                )
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                else:
                    rp = None
            except Exception:  # noqa: BLE001
                rp = None
            self._robots[origin] = rp
        rp = self._robots[origin]
        if rp is None:
            return True
        allowed = rp.can_fetch(self.session.headers["User-Agent"], url)
        if not allowed:
            self.stats["blocked_by_robots"] += 1
        return allowed

    # ---- public -------------------------------------------------------
    def fetch(
        self,
        url: str,
        *,
        force: bool = False,
        use_cache: bool = True,
        check_robots: bool = True,
    ) -> FetchResult:
        if use_cache and not (force or self.force):
            cached = self._read_cache(url)
            if cached is not None:
                return cached
        if self.offline:
            return FetchResult(url, url, None, "", None, _now(), error="offline mode")
        if check_robots and not self.robots_allowed(url):
            return FetchResult(url, url, None, "", None, _now(), error="blocked by robots.txt")

        host = urllib.parse.urlsplit(url).netloc
        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            self._throttle(host)
            try:
                resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                self.stats["requests"] += 1
                if resp.status_code >= 500 and attempt < self.max_retries:
                    last_error = f"HTTP {resp.status_code}"
                    time.sleep(1.5 * attempt)
                    continue
                ctype = resp.headers.get("Content-Type", "")
                if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                    resp.encoding = resp.apparent_encoding or "utf-8"
                text = resp.text if "html" in ctype or "text" in ctype or not ctype else ""
                result = FetchResult(
                    url=url,
                    final_url=resp.url,
                    status=resp.status_code,
                    text=text,
                    raw_path=None,
                    fetched_at=_now(),
                    content_type=ctype,
                )
                # 只缓存成功响应：把重试耗尽的 5xx 缓存 6 小时会把瞬时故障固化
                if self.save_raw and 200 <= resp.status_code < 300:
                    body, _ = self._cache_paths(url)
                    result.raw_path = body
                    self._write_cache(url, result, resp.content)
                return result
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_retries:
                    time.sleep(1.5 * attempt)
        self.stats["errors"] += 1
        return FetchResult(url, url, None, "", None, _now(), error=last_error or "unknown error")

    def fetch_bytes(self, url: str, referer: str | None = None) -> tuple[bytes | None, str]:
        """下载二进制附件（PDF/Office），返回 (内容, 服务端文件名)。"""
        body, meta = self._cache_paths(url)
        if body.exists() and meta.exists():
            try:
                info = json.loads(meta.read_text(encoding="utf-8"))
                age = datetime.now().astimezone() - datetime.fromisoformat(info["fetched_at"])
                if age <= self.ttl * 4:
                    self.stats["cache_hits"] += 1
                    return body.read_bytes(), info.get("filename", "")
            except Exception:  # noqa: BLE001
                pass
        host = urllib.parse.urlsplit(url).netloc
        headers = {"Referer": referer} if referer else {}
        for attempt in range(1, self.max_retries + 1):
            self._throttle(host)
            try:
                resp = self.session.get(url, timeout=self.timeout, headers=headers)
                self.stats["requests"] += 1
                if resp.status_code != 200:
                    time.sleep(1.2 * attempt)
                    continue
                disp = resp.headers.get("Content-Disposition", "")
                filename = ""
                if "filename" in disp:
                    filename = urllib.parse.unquote(
                        disp.split("filename=", 1)[1].strip().strip('"').strip("'")
                    )
                if self.save_raw:
                    body.write_bytes(resp.content)
                    meta.write_text(
                        json.dumps(
                            {
                                "url": url,
                                "status": resp.status_code,
                                "content_type": resp.headers.get("Content-Type", ""),
                                "filename": filename,
                                "fetched_at": _now(),
                                "bytes": len(resp.content),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                return resp.content, filename
            except requests.RequestException:
                time.sleep(1.2 * attempt)
        self.stats["errors"] += 1
        return None, ""
