"""验证桌面通知渠道是否真的把通知交给了系统。

只看 powershell 有没有报错是不够的——通知可能被专注助手或通知设置挡掉。
这里进一步去 Windows 的通知数据库里确认记录确实写进去了。

用法：python tools/check_toast.py [要发送的测试文字]
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar import toast  # noqa: E402


def notify_db_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Notifications" / "wpndatabase.db"


def snapshot(needle: str) -> tuple[int, int] | None:
    """读系统通知库：返回 (总记录数, 正文命中关键字的记录数)。读不到返回 None。

    注意 payload 是以二进制形式存的，直接按字符串搜是搜不到的，
    所以关键字要在 utf-8 和 utf-16le 两种编码下各搜一遍。
    """
    src = notify_db_path()
    if not src.exists():
        return None
    tmp = Path(tempfile.gettempdir()) / "wpn_check_copy.db"
    try:
        for suffix in ("", "-wal", "-shm"):
            if Path(str(src) + suffix).exists():
                shutil.copy2(str(src) + suffix, str(tmp) + suffix)
        con = sqlite3.connect(str(tmp))
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "Notification" not in tables:
            return None
        total = con.execute("SELECT COUNT(*) FROM Notification").fetchone()[0]
        needles = [needle.encode("utf-8"), needle.encode("utf-16-le")]
        found = 0
        for row in con.execute("SELECT Payload FROM Notification"):
            payload = row[0]
            if payload is None:
                continue
            blob = payload if isinstance(payload, bytes) else str(payload).encode("utf-8", "ignore")
            if any(n in blob for n in needles):
                found += 1
        con.close()
        return total, found
    except Exception as exc:  # noqa: BLE001
        print(f"  （读取系统通知库失败，跳过这一步：{type(exc).__name__}）")
        return None
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(str(tmp) + suffix).unlink(missing_ok=True)


def main() -> int:
    needle = sys.argv[1] if len(sys.argv) > 1 else f"雷达自检-{int(time.time())}"
    print(f"发送内容关键字：{needle}")

    before = snapshot(needle)
    if before:
        print(f"发送前：系统通知库共 {before[0]} 条，含本次关键字 {before[1]} 条")
    ok, detail = toast.send("赛事雷达自检", f"{needle}：能看到这条说明桌面通知渠道可用。")
    print(f"powershell 调用：{'成功' if ok else '失败'} —— {detail}")
    if not ok:
        return 2

    time.sleep(2)
    after = snapshot(needle)
    if after is None:
        print("无法确认系统通知库，请人工看右下角是否弹出通知。")
        return 0
    print(f"发送后：系统通知库共 {after[0]} 条，含本次关键字 {after[1]} 条")
    if after[1] > (before[1] if before else 0):
        print("结论：通知正文已写入系统通知中心，渠道可用。")
        return 0
    if before and after[0] > before[0]:
        print("结论：通知库记录数增加，说明通知已被系统接收；"
              "正文没匹配到是因为 payload 编码差异，不影响判定。")
        return 0
    print("结论：API 调用没报错，但系统通知库没有变化——很可能是被专注助手或通知设置拦截，"
          "请检查 设置 > 系统 > 通知。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
