"""Windows 桌面通知（借用已注册的 PowerShell 身份，零配置）。"""

from __future__ import annotations

import base64
import html
import os
import subprocess

SCRIPT = """$ErrorActionPreference = 'Stop'
try {
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
  [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null
  $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
  $title = '__TITLE__'
  $message = '__MESSAGE__'
  $xml = @"
<toast duration="long" activationType="protocol" launch="file:///__LAUNCH__">
  <visual><binding template="ToastGeneric"><text>$title</text><text>$message</text></binding></visual>
</toast>
"@
  $doc.LoadXml($xml)
  $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
  $aumid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)
  Write-Output 'OK'
} catch {
  Write-Output ('ERR ' + $_.Exception.Message)
}
"""


def _lit(text: str) -> str:
    clean = " ".join((text or "").split())
    return html.escape(clean, quote=False).replace("'", "''")


def send(title: str, message: str, launch_path: str = "") -> tuple[bool, str]:
    if os.name != "nt":
        return False, "仅支持 Windows"
    script = (
        SCRIPT.replace("__TITLE__", _lit(title))
        .replace("__MESSAGE__", _lit(message))
        .replace("__LAUNCH__", launch_path.replace("\\", "/"))
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    return out.startswith("OK"), out[:200] or f"rc={proc.returncode}"
