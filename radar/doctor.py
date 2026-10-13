"""启用自检：逐项确认这个工具真的能跑起来，而不是"看起来配好了"。"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import winps
from .catalog import Catalog
from .config import Config
from .szcp import SzcpRules

TASK_NAME = "CompRadar-Weekly"


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str


def _deps() -> Check:
    missing = []
    for module in ("requests", "lxml", "pdfplumber"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        return Check("依赖库", "fail", f"缺少 {', '.join(missing)}，请先 pip install -r requirements.txt")
    import sys

    return Check("依赖库", "ok", f"Python {sys.version.split()[0]}，requests/lxml/pdfplumber 均可用")


def _configs(cfg: Config) -> Check:
    missing = [
        name for name in ("settings.toml", "sources.toml", "keywords.toml", "scoring.toml")
        if not (cfg.root / "config" / name).exists()
    ]
    if missing:
        return Check("配置文件", "fail", f"缺少 {', '.join(missing)}")
    n_sources = len(cfg.sources)
    return Check("配置文件", "ok", f"4 个配置文件齐全，采集源 {n_sources} 个")


def _catalogs(cfg: Config) -> list[Check]:
    out: list[Check] = []
    current = Catalog.load(cfg.catalog_path)
    if not current.entries:
        out.append(Check("认定目录", "fail", f"读不到 {cfg.catalog_path.name}"))
    else:
        out.append(Check(
            "认定目录",
            "ok",
            f"{current.meta.get('title', '')}，{len(current.entries)} 项，"
            f"分布 {current.categories}",
        ))
    prev = Catalog.load(cfg.catalog_prev_path)
    out.append(Check(
        "上一版目录", "ok" if prev.entries else "warn",
        f"{prev.meta.get('title', '')}，{len(prev.entries)} 项（用于判断掉出目录的赛事）"
        if prev.entries else "未找到，掉出目录的赛事将无法降级处理",
    ))
    return out


def _szcp(cfg: Config) -> list[Check]:
    out: list[Check] = []
    rules = SzcpRules.load(cfg.szcp_college_path)
    if rules.available:
        r = rules.rules
        out.append(Check(
            "综测规则", "ok",
            f"{rules.meta.get('title', '')}（上限 {r.get('cap')} 分，"
            f"分类权重 {'/'.join(f'{k}{v:g}' for k, v in r['category_weight'].items())}）",
        ))
        sample = rules.estimate("二类")
        out.append(Check(
            "综测算例", "ok" if sample else "fail",
            f"二类国家级一等奖第一 = {sample.formula}" if sample else "算不出分值，权重表可能不完整",
        ))
    else:
        out.append(Check("综测规则", "warn", f"未加载 {cfg.szcp_college_path.name}，综测维度只能到校级"))
    school = json.loads(cfg.szcp_path.read_text(encoding="utf-8")) if cfg.szcp_path.exists() else {}
    out.append(Check(
        "校级综测依据", "ok" if school else "warn",
        f"{school.get('meta', {}).get('document_no', '')}（加分模块与上限）" if school else "未找到",
    ))
    return out


def _database(cfg: Config) -> Check:
    if not cfg.db_path.exists():
        return Check("数据库", "warn", "还没有数据库，首次运行会自动创建")
    from .store import Store

    store = Store(cfg.db_path)
    summary = store.summary()
    store.close()
    tiers = summary["tiers"]
    return Check(
        "数据库", "ok",
        f"{summary['competitions']} 个赛事 / {summary['notices']} 条通知 / "
        f"{summary['changes']} 处变化 / {summary['pushes']} 条提醒；"
        f"重点 {tiers.get('重点关注', 0)}、潜在 {tiers.get('潜在机会', 0)}",
    )


def _runtime(cfg: Config) -> list[Check]:
    out: list[Check] = []
    for path in (cfg.data_dir, cfg.raw_dir, cfg.outbox_dir):
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            out.append(Check("目录可写", "fail", f"{path} 不可写：{exc}"))
            return out
    cached = len(list(cfg.raw_dir.glob("*.body")))
    free = shutil.disk_usage(cfg.root).free / (1024 ** 3)
    out.append(Check("目录可写", "ok", f"data/、data/raw/、outbox/ 均可写"))
    out.append(Check("抓取缓存", "ok" if cached else "warn",
                     f"{cached} 个页面缓存；缓存命中时整轮只需数秒，否则首次约 2~3 分钟"))
    out.append(Check("磁盘空间", "ok" if free > 1 else "warn", f"剩余 {free:.1f} GB"))
    return out


def _notify(cfg: Config, send_test: bool) -> list[Check]:
    from .notify import build_message, dispatch

    notify_cfg = cfg.settings.get("notify", {}) or {}
    channel = notify_cfg.get("channel", "file")
    out = [Check(
        "通知配置", "ok" if notify_cfg.get("enabled") else "warn",
        f"渠道 {channel}，enabled={bool(notify_cfg.get('enabled'))}，"
        f"dry_run={bool(notify_cfg.get('dry_run', True))}",
    )]
    if channel in ("wecom", "serverchan"):
        env_name = (notify_cfg.get(channel) or {}).get(
            "webhook_env" if channel == "wecom" else "key_env", "")
        import os

        out.append(Check(
            f"{channel} 密钥", "ok" if os.environ.get(env_name) else "warn",
            f"环境变量 {env_name} " + ("已设置" if os.environ.get(env_name) else "未设置"),
        ))
    if channel == "email":
        host = (notify_cfg.get("email") or {}).get("host")
        out.append(Check("邮件配置", "ok" if host else "warn",
                         f"SMTP 主机 {host}" if host else "未配置 [notify.email].host"))
    if send_test and channel == "toast":
        import copy

        probe = copy.deepcopy(cfg)
        probe.settings["notify"] = dict(notify_cfg)
        probe.settings["notify"]["enabled"] = True
        probe.settings["notify"]["dry_run"] = False
        rows = [{
            "push_type": "启用自检",
            "title": "赛事雷达已启用",
            "body": "收到这条桌面通知说明推送渠道工作正常。\n"
                    "以后每周一 09:00 自动运行，只有需要行动的信息才会提醒你。",
        }]
        result = dispatch(probe, rows, log=lambda *_: None)
        out.append(Check("通知实测", "ok" if result.ok else "fail", result.detail))
    return out


def _schedule() -> list[Check]:
    if not winps.available():
        return [Check("计划任务", "warn", "当前不是 Windows，定时运行请用 cron")]
    script = f"""
$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if ($null -eq $t) {{ Write-Output 'MISSING' }} else {{
  $i = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}'
  Write-Output ('STATE=' + $t.State)
  Write-Output ('NEXT=' + $i.NextRunTime.ToString('yyyy-MM-dd HH:mm'))
  Write-Output ('LAST=' + $i.LastRunTime.ToString('yyyy-MM-dd HH:mm'))
  Write-Output ('RESULT=' + $i.LastTaskResult)
}}
"""
    rc, out, err = winps.run(script)
    if rc != 0 or "MISSING" in out or not out:
        return [Check("计划任务", "warn",
                      f"未注册 {TASK_NAME}；运行 scripts\\install_task.ps1 可开启每周自动运行")]
    fields = dict(
        line.split("=", 1) for line in out.splitlines() if "=" in line
    )
    result_code = fields.get("RESULT", "")
    ok = fields.get("STATE") == "Ready" and result_code in ("0", "")
    return [Check(
        "计划任务", "ok" if ok else "warn",
        f"{TASK_NAME}：状态 {fields.get('STATE')}，下次运行 {fields.get('NEXT')}，"
        f"上次运行 {fields.get('LAST')}（返回码 {result_code}）",
    )]


def run_checks(cfg: Config, send_test: bool = False) -> list[Check]:
    checks = [_deps(), _configs(cfg)]
    checks.extend(_catalogs(cfg))
    checks.extend(_szcp(cfg))
    checks.append(_database(cfg))
    checks.extend(_runtime(cfg))
    checks.extend(_notify(cfg, send_test))
    checks.extend(_schedule())
    return checks


def verdict(checks: list[Check]) -> tuple[str, str]:
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    if fails:
        return "fail", f"{len(fails)} 项未通过，需要先修掉才能正常跑"
    if warns:
        return "warn", f"可以跑，但有 {len(warns)} 项待完善"
    return "ok", "全部就绪"
