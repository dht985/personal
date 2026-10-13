"""Windows 桌面通知渠道：不需要任何账号或密钥。

实现要点：
- 用 powershell 的 -EncodedCommand（UTF-16LE + base64）传脚本，绕开 .ps1 文件被
  按 GBK 解析、以及命令行参数按 ANSI 编码丢失中文的两个坑。
- toast 正文只放标题和摘要前几行，完整内容仍在 outbox 的提醒文件里。
"""

from __future__ import annotations

import html
import os

from . import winps

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
  # 未注册的应用用自造 AUMID 发 toast，API 不报错但通知会被系统静默丢弃，
  # 所以借用已注册的 Windows PowerShell 身份来发。
  $aumid = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'
  [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($aumid).Show($toast)
  Write-Output 'OK'
} catch {
  Write-Output ('ERR ' + $_.Exception.Message)
}
"""


def _ps_literal(text: str) -> str:
    """放进 PowerShell 单引号字符串里：先转义单引号，再去掉换行。"""
    cleaned = " ".join((text or "").split())
    return cleaned.replace("'", "''")


def _xml_text(text: str) -> str:
    return html.escape(text or "", quote=False).replace("'", "&#39;")


def send(title: str, message: str, launch_path: str | None = None) -> tuple[bool, str]:
    """弹一条桌面通知。返回 (是否成功, 说明)。"""
    if os.name != "nt":
        return False, "桌面通知渠道只在 Windows 上可用"
    script = (
        SCRIPT.replace("__TITLE__", _ps_literal(_xml_text(title)))
        .replace("__MESSAGE__", _ps_literal(_xml_text(message)))
        .replace("__LAUNCH__", (launch_path or "").replace("\\", "/"))
    )
    rc, out, err = winps.run(script)
    if out.startswith("OK"):
        return True, "已弹出 Windows 桌面通知"
    return False, (out or err or f"powershell 返回码 {rc}")[:300]
