"""通知投递：企业微信机器人 / Server酱 / 邮件 / 本地文件。

原则：
- 密钥只从环境变量读，不落进配置文件，也不会被写进日志或报告。
- 默认 dry_run，先把内容渲染出来给你看；确认无误再真正发送。
- 发送失败的记录保持 pending，下一轮自动重试；同一件事不会重复提醒。
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Callable

from .config import Config

CHANNELS = ("file", "wecom", "serverchan", "email")
WECOM_LIMIT = 3800  # 企业微信 markdown 内容上限约 4096 字节，留出余量


@dataclass
class DeliveryResult:
    ok: bool
    channel: str
    detail: str
    dry_run: bool = False
    skipped: bool = False
    title: str = ""
    preview: str = ""
    attempts: list[dict] = field(default_factory=list)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def build_message(rows, max_items: int = 10) -> tuple[str, str]:
    """把待推送记录渲染成中文标题 + 正文。"""
    rows = list(rows)
    if not rows:
        return "赛事雷达：本轮没有需要处理的新信息", "没有新赛事、临近截止或重要变化。"

    title = f"赛事雷达：{len(rows)} 条需要关注的赛事信息"
    lines: list[str] = []
    for row in rows[:max_items]:
        lines.append(f"【{row['push_type']}】{row['title']}")
        for line in (row["body"] or "").splitlines():
            if line.strip():
                lines.append(f"　{line}")
        lines.append("")
    if len(rows) > max_items:
        lines.append(f"…… 另有 {len(rows) - max_items} 条，详见 outbox 目录下的提醒文件。")
    return title, "\n".join(lines).strip()


def _post_json(url: str, payload: dict, timeout: int = 15) -> tuple[bool, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if 200 <= resp.status < 300:
                return True, body[:200]
            return False, f"HTTP {resp.status}: {body[:200]}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:200]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _send_wecom(cfg: dict, title: str, body: str) -> tuple[bool, str]:
    env_name = cfg.get("webhook_env", "COMPRADAR_WECOM_WEBHOOK")
    url = _env(env_name)
    if not url:
        return False, f"未配置环境变量 {env_name}（企业微信机器人 Webhook 地址）"
    content = f"## {title}\n\n{body}"
    if len(content.encode("utf-8")) > WECOM_LIMIT:
        content = content.encode("utf-8")[:WECOM_LIMIT].decode("utf-8", errors="ignore")
        content += "\n\n（内容过长已截断，完整版见 outbox 目录）"
    return _post_json(url, {"msgtype": "markdown", "markdown": {"content": content}})


def _send_serverchan(cfg: dict, title: str, body: str) -> tuple[bool, str]:
    env_name = cfg.get("key_env", "COMPRADAR_SERVERCHAN_KEY")
    key = _env(env_name)
    if not key:
        return False, f"未配置环境变量 {env_name}（Server酱 SendKey）"
    url = cfg.get("url") or f"https://sctapi.ftqq.com/{key}.send"
    return _post_json(url, {"title": title[:32], "desp": body})


def _send_email(cfg: dict, title: str, body: str) -> tuple[bool, str]:
    host = cfg.get("host") or ""
    if not host:
        return False, "未配置 [notify.email].host"
    port = int(cfg.get("port", 465))
    user = _env(cfg.get("username_env", "COMPRADAR_SMTP_USER"))
    password = _env(cfg.get("password_env", "COMPRADAR_SMTP_PASS"))
    if not user or not password:
        return False, "未配置 SMTP 账号环境变量（用户名/授权码）"
    to_addrs = list(cfg.get("to_addrs") or [])
    if not to_addrs:
        return False, "未配置 [notify.email].to_addrs"

    msg = EmailMessage()
    msg["Subject"] = title
    msg["From"] = cfg.get("from_addr") or user
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(body)
    try:
        if cfg.get("use_ssl", True):
            with smtplib.SMTP_SSL(host, port, timeout=20,
                                  context=ssl.create_default_context()) as server:
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(user, password)
                server.send_message(msg)
        return True, f"已发送至 {', '.join(to_addrs)}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


SENDERS: dict[str, Callable[[dict, str, str], tuple[bool, str]]] = {
    "wecom": _send_wecom,
    "serverchan": _send_serverchan,
    "email": _send_email,
}


def dispatch(cfg: Config, rows, log: Callable[[str], None] = print) -> DeliveryResult:
    """把待推送记录投递出去。返回结果里带 dry_run 标记，调用方据此决定是否标记已发送。"""
    notify_cfg = cfg.settings.get("notify", {}) or {}
    channel = notify_cfg.get("channel", "file")
    enabled = bool(notify_cfg.get("enabled", False))
    dry_run = bool(notify_cfg.get("dry_run", True))
    title, body = build_message(rows, int(notify_cfg.get("max_items", 10)))

    if not rows:
        return DeliveryResult(True, channel, "本轮没有需要推送的内容", dry_run=True,
                              skipped=True, title=title, preview=body)
    if not enabled:
        return DeliveryResult(
            True, channel, "通知未启用（[notify].enabled = false），仅写入 outbox 文件",
            dry_run=True, skipped=True, title=title, preview=body,
        )
    if channel == "file":
        return DeliveryResult(True, channel, "已写入 outbox 文件（file 渠道）",
                              dry_run=True, title=title, preview=body)
    if channel not in SENDERS:
        return DeliveryResult(False, channel,
                              f"未知渠道 {channel!r}，可选：{', '.join(CHANNELS)}",
                              dry_run=True, title=title, preview=body)
    if dry_run:
        log(f"      [干跑] 渠道 {channel}，不实际发送；如需真发请把 [notify].dry_run 设为 false")
        return DeliveryResult(True, channel, "干跑模式：内容已渲染但未发送",
                              dry_run=True, title=title, preview=body)

    ok, detail = SENDERS[channel](notify_cfg.get(channel, {}) or {}, title, body)
    if ok:
        log(f"      已通过 {channel} 投递：{detail}")
    else:
        log(f"      {channel} 投递失败：{detail}（记录保持待推送，下轮自动重试）")
    return DeliveryResult(ok, channel, detail, dry_run=False, title=title, preview=body)
