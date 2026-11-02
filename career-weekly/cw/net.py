from __future__ import annotations

import hashlib
import time
import urllib.parse
from dataclasses import dataclass

import requests

from .config import Config


@dataclass
class BinaryPage:
    url: str
    final_url: str
    status: int | None
    content: bytes
    content_type: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error


@dataclass
class Page:
    url: str
    final_url: str
    status: int | None
    text: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error


class Fetcher:
    def __init__(self, cfg: Config):
        http = cfg.settings["http"]
        self.timeout = http["timeout_seconds"]
        self.interval = http["min_interval_seconds"]
        self.retries = http["max_retries"]
        self.raw_dir = cfg.raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": http["user_agent"], "Accept-Language": "zh-CN,zh;q=0.9"}
        )
        self._last: dict[str, float] = {}
        self.stats = {"requests": 0, "errors": 0}

    def _throttle(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self.interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()

    def get(self, url: str) -> Page:
        host = urllib.parse.urlsplit(url).netloc
        err = ""
        for attempt in range(1, self.retries + 1):
            self._throttle(host)
            try:
                r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                self.stats["requests"] += 1
                if r.status_code >= 500 and attempt < self.retries:
                    err = f"HTTP {r.status_code}"
                    time.sleep(1.2 * attempt)
                    continue
                if not r.encoding or r.encoding.lower() == "iso-8859-1":
                    r.encoding = r.apparent_encoding or "utf-8"
                key = hashlib.sha1(url.encode("utf-8")).hexdigest()
                (self.raw_dir / f"{key}.html").write_bytes(r.content)
                return Page(url, r.url, r.status_code, r.text)
            except requests.RequestException as exc:
                err = type(exc).__name__
                time.sleep(1.2 * attempt)
        self.stats["errors"] += 1
        return Page(url, url, None, "", error=err or "request failed")

    def get_bytes(self, url: str, max_bytes: int = 12 * 1024 * 1024) -> BinaryPage:
        host = urllib.parse.urlsplit(url).netloc
        err = ""
        for attempt in range(1, self.retries + 1):
            self._throttle(host)
            try:
                with self.session.get(
                    url, timeout=self.timeout, allow_redirects=True, stream=True,
                ) as response:
                    self.stats["requests"] += 1
                    content_type = response.headers.get("Content-Type", "")
                    if response.status_code >= 500 and attempt < self.retries:
                        err = f"HTTP {response.status_code}"
                        time.sleep(1.2 * attempt)
                        continue
                    chunks = []
                    size = 0
                    for chunk in response.iter_content(64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > max_bytes:
                            return BinaryPage(
                                url, response.url, response.status_code, b"",
                                content_type, "文件超过大小限制",
                            )
                        chunks.append(chunk)
                    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
                    content = b"".join(chunks)
                    (self.raw_dir / f"{key}.bin").write_bytes(content)
                    return BinaryPage(
                        url, response.url, response.status_code, content, content_type,
                    )
            except requests.RequestException as exc:
                err = type(exc).__name__
                time.sleep(1.2 * attempt)
        self.stats["errors"] += 1
        return BinaryPage(url, url, None, b"", "", error=err or "request failed")
