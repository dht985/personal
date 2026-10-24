# Agent 信箱（跨工具沟通）

同一台机器上的多个 AI（Codex / TRAE / 其他）可以通过这个共享文件夹交换消息。
没有服务端、没有端口、没有第三方依赖，消息就是 Markdown 文件。

## 为什么需要它

Codex 和 TRAE 是两个独立程序：

- TRAE 是 Electron 桌面应用，没有开放本地 API 或调试端口（实测无监听端口）。
- Codex 只能调用自己配置的 MCP 工具，无法"拨号"到另一个 GUI 程序。
- 同在一台机器 ≠ 能互相发消息，中间缺一个双方都认的通道。

共享文件夹就是最小的那个通道。

## 双方约定

| 角色 | 收件箱 | 发件 |
| --- | --- | --- |
| Codex | `collab/messages/` 中 `to: codex` 的消息 | `python collab/mailbox.py send --from codex ...` |
| TRAE | `collab/messages/` 中 `to: trae` 的消息 | 同上，`--from trae` |

消息格式是 Markdown + 一段 JSON 元信息，人和 AI 都能直接读。

## 常用命令

```powershell
# 发消息
python collab/mailbox.py send --from codex --to trae `
  --type review-request --thread radar-v2 `
  --subject "第二轮评审：请先读 REVIEW_REQUEST.md" `
  --body "上一轮 16 条意见已处理 13 条，请核对第二章。"

# 发长文（从文件读）
python collab/mailbox.py send --from trae --to codex `
  --subject "评审结论" --type review-result --body-file collab/outbox/review.md

# 查收件箱（默认只看未读）
python collab/mailbox.py inbox --for trae

# 看正文
python collab/mailbox.py read <id>

# 标记已读
python collab/mailbox.py mark-read <id> --for trae

# 列出全部消息
python collab/mailbox.py list
```

## 给 TRAE 的开场指令

在 TRAE 里粘贴：

```
请先运行 `python collab/mailbox.py inbox --for trae`，
把未读消息读完后按消息里的要求处理；处理完用
`python collab/mailbox.py send --from trae --to codex --type review-result ...` 回复。
不要直接改代码，先给结论。
```

## 局限

- **不是实时的**：对方需要主动查收件箱（或你在提示词里让它每次先查）。
- **没有权限控制**：任何能读写这个目录的程序都能看消息，不要放密钥。
- **只有本机可用**：跨机器需要 Git 或 HTTP 服务。

## 想升级成实时通信

1. **本地 HTTP 信箱**：一个常驻进程（127.0.0.1:8765），双方用 `POST /send`、`GET /inbox`。
   TRAE 可以在终端里 `curl` 调用。改动不大，但多一个需要保持运行的进程。
2. **MCP 服务**：写一个 `agent-mail` MCP server，在 Codex 的 `config.toml`
   和 TRAE 的 MCP 设置里各注册一次。双方都能把它当原生工具调用，最"正规"，
   但要重启两个应用。
