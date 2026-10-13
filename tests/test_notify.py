"""通知渠道自测：用本地 HTTP 服务端接收真实请求，验证投递格式；邮件走打桩验证。"""

from __future__ import annotations

import http.server
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar import notify  # noqa: E402
from radar.config import load_config  # noqa: E402


class _Recorder(http.server.BaseHTTPRequestHandler):
    captured: list[dict] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        type(self).captured.append({"path": self.path, "body": raw})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')

    def log_message(self, *args):  # 静音
        pass


SAMPLE_ROWS = [
    {
        "push_type": "临近截止",
        "title": "临近截止：全国大学生软件测试大赛",
        "body": "赛事等级：重点关注（总分 55）\n云南大学认定目录：四类\n报名截止：2026-10-30（30天内截止）",
    }
]


class TestNotifyChannels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _Recorder.captured.clear()
        self.cfg = load_config(ROOT)
        self.cfg.settings = dict(self.cfg.settings)

    def _notify_cfg(self, channel: str, **overrides) -> dict:
        base = {
            "enabled": True,
            "channel": channel,
            "dry_run": False,
            "max_items": 10,
            "wecom": {"webhook_env": "COMPRADAR_WECOM_WEBHOOK"},
            "serverchan": {"key_env": "COMPRADAR_SERVERCHAN_KEY",
                           "url": f"http://127.0.0.1:{self.port}/sctapi/send"},
            "email": {},
        }
        base.update(overrides)
        self.cfg.settings["notify"] = base
        return base

    def test_wecom_payload(self):
        os.environ["COMPRADAR_WECOM_WEBHOOK"] = (
            f"http://127.0.0.1:{self.port}/cgi-bin/webhook/send?key=test"
        )
        self._notify_cfg("wecom")
        result = notify.dispatch(self.cfg, SAMPLE_ROWS, log=lambda *_: None)

        self.assertTrue(result.ok, result.detail)
        self.assertFalse(result.dry_run)
        self.assertEqual(len(_Recorder.captured), 1)
        payload = json.loads(_Recorder.captured[0]["body"])
        self.assertEqual(payload["msgtype"], "markdown")
        content = payload["markdown"]["content"]
        self.assertIn("临近截止", content)
        self.assertIn("全国大学生软件测试大赛", content)
        self.assertIn("2026-10-30", content)

    def test_serverchan_payload(self):
        os.environ["COMPRADAR_SERVERCHAN_KEY"] = "SCTtest"
        self._notify_cfg("serverchan")
        result = notify.dispatch(self.cfg, SAMPLE_ROWS, log=lambda *_: None)

        self.assertTrue(result.ok, result.detail)
        payload = json.loads(_Recorder.captured[0]["body"])
        self.assertIn("赛事雷达", payload["title"])
        self.assertIn("软件测试大赛", payload["desp"])
        self.assertLessEqual(len(payload["title"]), 32)

    def test_dry_run_does_not_send(self):
        os.environ["COMPRADAR_WECOM_WEBHOOK"] = f"http://127.0.0.1:{self.port}/hook"
        self._notify_cfg("wecom", dry_run=True)
        result = notify.dispatch(self.cfg, SAMPLE_ROWS, log=lambda *_: None)
        self.assertTrue(result.dry_run)
        self.assertEqual(_Recorder.captured, [])

    def test_disabled_does_not_send(self):
        self._notify_cfg("wecom", enabled=False)
        result = notify.dispatch(self.cfg, SAMPLE_ROWS, log=lambda *_: None)
        self.assertTrue(result.skipped)
        self.assertEqual(_Recorder.captured, [])

    def test_missing_env_reports_clearly(self):
        os.environ.pop("COMPRADAR_WECOM_WEBHOOK", None)
        self._notify_cfg("wecom")
        result = notify.dispatch(self.cfg, SAMPLE_ROWS, log=lambda *_: None)
        self.assertFalse(result.ok)
        self.assertIn("COMPRADAR_WECOM_WEBHOOK", result.detail)

    def test_unknown_channel(self):
        self._notify_cfg("telegram")
        result = notify.dispatch(self.cfg, SAMPLE_ROWS, log=lambda *_: None)
        self.assertFalse(result.ok)
        self.assertIn("未知渠道", result.detail)

    def test_failed_send_is_reported(self):
        # 端口没人监听 -> 应当失败并且错误信息可读
        os.environ["COMPRADAR_WECOM_WEBHOOK"] = "http://127.0.0.1:9/hook"
        self._notify_cfg("wecom")
        result = notify.dispatch(self.cfg, SAMPLE_ROWS, log=lambda *_: None)
        self.assertFalse(result.ok)
        self.assertTrue(result.detail)

    def test_email_message_built_correctly(self):
        sent: dict = {}

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def login(self, user, password):
                sent["login"] = (user, password)

            def send_message(self, msg):
                sent["subject"] = msg["Subject"]
                sent["to"] = msg["To"]
                sent["body"] = msg.get_content()

        os.environ["COMPRADAR_SMTP_USER"] = "u@example.com"
        os.environ["COMPRADAR_SMTP_PASS"] = "secret"
        self._notify_cfg(
            "email",
            email={
                "host": "smtp.example.com", "port": 465, "use_ssl": True,
                "username_env": "COMPRADAR_SMTP_USER",
                "password_env": "COMPRADAR_SMTP_PASS",
                "from_addr": "u@example.com",
                "to_addrs": ["me@example.com"],
            },
        )
        with mock.patch("smtplib.SMTP_SSL", FakeSMTP):
            result = notify.dispatch(self.cfg, SAMPLE_ROWS, log=lambda *_: None)

        self.assertTrue(result.ok, result.detail)
        self.assertEqual(sent["login"], ("u@example.com", "secret"))
        self.assertEqual(sent["to"], "me@example.com")
        self.assertIn("赛事雷达", sent["subject"])
        self.assertIn("软件测试大赛", sent["body"])


class TestMessageRendering(unittest.TestCase):
    def test_empty_queue(self):
        title, body = notify.build_message([])
        self.assertIn("没有需要处理", title)

    def test_truncates_long_queue(self):
        rows = [dict(SAMPLE_ROWS[0], title=f"赛事{i}") for i in range(15)]
        title, body = notify.build_message(rows, max_items=3)
        self.assertIn("15", title)
        self.assertIn("另有 12 条", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
