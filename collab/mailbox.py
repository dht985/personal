"""极简 Agent 信箱：让同一台机器上的多个 AI 通过共享文件夹留言。

不依赖网络、服务端或第三方工具，消息就是 Markdown 文件，人和 AI 都能直接读。

用法:
    python collab/mailbox.py send --from codex --to trae --subject "..." \
        --type review-request --thread radar-v2 --body "正文"
    python collab/mailbox.py inbox --for trae
    python collab/mailbox.py read <id>
    python collab/mailbox.py mark-read <id> --for trae
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MESSAGES = ROOT / "messages"
STATE = ROOT / "state.json"
META_RE = re.compile(r"<!--META\n(.*?)\nMETA-->", re.S)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    MESSAGES.mkdir(parents=True, exist_ok=True)


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_message(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    m = META_RE.search(text)
    if not m:
        return None
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    meta["path"] = str(path)
    meta["body"] = text[m.end():].strip()
    return meta


def all_messages() -> list[dict]:
    ensure_dirs()
    out = []
    for path in sorted(MESSAGES.glob("*.md")):
        msg = parse_message(path)
        if msg:
            out.append(msg)
    out.sort(key=lambda x: x.get("created", ""), reverse=True)
    return out


def cmd_send(args) -> int:
    ensure_dirs()
    created = now()
    digest = hashlib.sha1(
        f"{created}{args.sender}{args.recipient}{args.subject}".encode("utf-8")
    ).hexdigest()[:8]
    msg_id = f"{created.replace(':', '').replace('-', '')[:15]}-{digest}"
    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    meta = {
        "id": msg_id,
        "from": args.sender,
        "to": args.recipient,
        "type": args.type,
        "thread": args.thread,
        "subject": args.subject,
        "created": created,
    }
    path = MESSAGES / f"{msg_id}-{args.sender}-to-{args.recipient}.md"
    path.write_text(
        "<!--META\n" + json.dumps(meta, ensure_ascii=False) + "\nMETA-->\n"
        + f"# {args.subject}\n\n{body}\n",
        encoding="utf-8",
    )
    print(f"已发送 {msg_id} -> {args.recipient}")
    print(f"  {path}")
    return 0


def cmd_inbox(args) -> int:
    state = load_state()
    read_ids = set(state.get(args.recipient, {}).get("read", []))
    msgs = [m for m in all_messages() if m["to"] in (args.recipient, "all")]
    if not args.all:
        msgs = [m for m in msgs if m["id"] not in read_ids]
    if not msgs:
        print(f"{args.recipient} 没有{'更多' if not args.all else ''}消息")
        return 0
    for m in msgs:
        flag = " " if m["id"] in read_ids else "*"
        print(f"{flag} [{m['type']}] {m['id']}")
        print(f"    from {m['from']} · {m['created'][:19]} · thread={m.get('thread','-')}")
        print(f"    {m['subject']}")
    print(f"\n共 {len(msgs)} 条；带 * 为未读。用 `read <id>` 查看正文。")
    return 0


def find(msg_id: str) -> dict | None:
    for msg in all_messages():
        if msg["id"] == msg_id:
            return msg
    return None


def cmd_read(args) -> int:
    msg = find(args.msg_id)
    if not msg:
        print(f"找不到消息 {args.msg_id}")
        return 1
    print(f"# {msg['subject']}")
    print(f"from {msg['from']} -> {msg['to']} · {msg['created']} · {msg['type']}")
    print()
    print(msg["body"])
    return 0


def cmd_mark_read(args) -> int:
    msg = find(args.msg_id)
    if not msg:
        print(f"找不到消息 {args.msg_id}")
        return 1
    state = load_state()
    entry = state.setdefault(args.recipient, {}).setdefault("read", [])
    if args.msg_id not in entry:
        entry.append(args.msg_id)
    save_state(state)
    print(f"{args.recipient} 已标记 {args.msg_id} 为已读")
    return 0


def cmd_list(args) -> int:
    for m in all_messages():
        print(f"{m['id']}  {m['from']}->{m['to']}  [{m['type']}]  {m['subject'][:50]}")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    ap = argparse.ArgumentParser(description="Agent 共享信箱")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("send")
    s.add_argument("--from", dest="sender", required=True)
    s.add_argument("--to", dest="recipient", required=True)
    s.add_argument("--subject", required=True)
    s.add_argument("--type", default="note")
    s.add_argument("--thread", default="")
    s.add_argument("--body", default="")
    s.add_argument("--body-file", default="")
    s.set_defaults(func=cmd_send)

    i = sub.add_parser("inbox")
    i.add_argument("--for", dest="recipient", required=True)
    i.add_argument("--all", action="store_true", help="包含已读")
    i.set_defaults(func=cmd_inbox)

    r = sub.add_parser("read")
    r.add_argument("msg_id")
    r.set_defaults(func=cmd_read)

    m = sub.add_parser("mark-read")
    m.add_argument("msg_id")
    m.add_argument("--for", dest="recipient", required=True)
    m.set_defaults(func=cmd_mark_read)

    l = sub.add_parser("list")
    l.set_defaults(func=cmd_list)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
