"""演示推送内容：用一个本地 HTTP 服务端当作企业微信机器人，打印真实发出的请求体。"""

import http.server
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar import notify  # noqa: E402
from radar.config import load_config  # noqa: E402


class Receiver(http.server.BaseHTTPRequestHandler):
    captured: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        type(self).captured.append(json.loads(self.rfile.read(length).decode("utf-8")))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')

    def log_message(self, *args):
        pass


ROWS = [
    {
        "push_type": "临近截止",
        "title": "临近截止：全国大学生智能汽车竞赛",
        "body": "赛事等级：重点关注（总分 63）\n"
                "云南大学认定目录：三类\n"
                "报名截止：2026-11-01（30天内截止）\n"
                "适配度：核心\n"
                "通知来源：https://jwc.ynu.edu.cn/info/1009/4315.htm",
    },
    {
        "push_type": "新赛事待确认",
        "title": "新赛事待确认：“码蹄杯”程序设计大赛",
        "body": "赛事等级：低优先级/证据不足（总分 25）\n"
                "云南大学认定目录：未收录认定目录\n"
                "报名截止：通知中未写明（未找到日期）\n"
                "通知来源：https://jwc.ynu.edu.cn/info/1009/4179.htm\n"
                "该赛事不在《云南大学认定本科生学科竞赛目录（2025版）》中，"
                "建议向学院或本科生院确认是否纳入认定范围。",
    },
]


def main() -> int:
    server = http.server.HTTPServer(("127.0.0.1", 0), Receiver)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    os.environ["COMPRADAR_WECOM_WEBHOOK"] = (
        f"http://127.0.0.1:{port}/cgi-bin/webhook/send?key=DEMO-KEY"
    )
    cfg = load_config(ROOT)
    cfg.settings = dict(cfg.settings)
    cfg.settings["notify"] = {
        "enabled": True,
        "channel": "wecom",
        "dry_run": False,
        "max_items": 10,
        "wecom": {"webhook_env": "COMPRADAR_WECOM_WEBHOOK"},
    }

    title, body = notify.build_message(ROWS)
    print("=" * 66)
    print("推送给你的正文长这样（企业微信 markdown 消息）")
    print("=" * 66)
    print(f"### {title}\n")
    print(body)
    print()

    result = notify.dispatch(cfg, ROWS, log=print)
    print(f"\n投递结果：{'成功' if result.ok else '失败'} —— {result.detail}")

    if Receiver.captured:
        payload = Receiver.captured[0]
        content = payload["markdown"]["content"]
        print("\n实际发出的 HTTP 请求体（已省略未发送域名的真实密钥）：")
        print(f"  msgtype: {payload['msgtype']}")
        print(f"  正文字节数: {len(content.encode('utf-8'))}（企业微信上限约 4096）")
        print("  正文前 200 字：")
        print("   " + content[:200].replace("\n", "\n   "))
    server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
