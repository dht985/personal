"""在 Windows 上跑 PowerShell 的小封装。

统一用 -EncodedCommand（UTF-16LE + base64）传脚本：
这样既不受 .ps1 文件被按 GBK 解析的影响，也不受命令行参数编码的影响。
"""

from __future__ import annotations

import base64
import os
import subprocess


def available() -> bool:
    return os.name == "nt"


def run(script: str, timeout: int = 60) -> tuple[int, str, str]:
    """执行一段 PowerShell 脚本，返回 (返回码, stdout, stderr)。"""
    if not available():
        return 1, "", "not windows"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 1, "", "powershell.exe not found"
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
    return proc.returncode, out, err
