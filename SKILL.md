---
name: wechat-clawbot-notify
description: "Send notification messages and files to the user's WeChat via ClawBot (iLink API). Supports: text, PDF, images. Use when automation completes and user needs notification, or when user asks to send a message/file to their WeChat. Triggers: 'notify me on WeChat', 'send to my WeChat', 'push to WeChat', '发微信通知'，'文件发到微信', '推送到微信'."
description_zh: "通过微信 ClawBot 发送通知消息和文件给用户"
description_en: "Send notification messages and files to user's WeChat via ClawBot"
version: 2.0.0
allowed-tools: Bash,Read
compatibility: macOS / Windows / Linux. Requires Python 3 + cryptography. Reads config from WorkBuddy settings.json.
metadata:
  version: "2.0.0"
  openclaw:
    emoji: "\U0001F4AC"
    requires:
      bins:
        - python
        - cryptography
---

# WeChat ClawBot Notify

通过微信 ClawBot iLink API 发送文本消息和文件给用户。

**单入口脚本**（自动适配平台，无需区分 macOS/Windows）：

```bash
python "$SKILL_DIR/scripts/send_wechat.py" <command> [args]
```

---

## 初始化（仅首次使用需要）

执行 `setup` 命令完成全部初始化：

```bash
python "$SKILL_DIR/scripts/send_wechat.py" setup
```

`setup` 自动完成：①检查 ClawBot 配置 ②获取 context_token ③注入自动通知配置 ④发送验证消息。

**如果提示 "need_user_msg"** → 让用户给微信 ClawBot 发一条消息，然后再次运行 `setup`。

---

## 发送消息

```bash
# 发送文本
python "$SKILL_DIR/scripts/send_wechat.py" send "消息内容"

# 发送文件（PDF/图片等）
python "$SKILL_DIR/scripts/send_wechat.py" sendfile "/path/to/file.pdf"
```

## 其他命令

```bash
python "$SKILL_DIR/scripts/send_wechat.py" status    # 查看配置和 token 状态
python "$SKILL_DIR/scripts/send_wechat.py" refresh   # 手动刷新 token
```

## JSON 模式（LLM 友好）

所有命令前加 `--json` 输出结构化 JSON：

```bash
python "$SKILL_DIR/scripts/send_wechat.py" --json status
python "$SKILL_DIR/scripts/send_wechat.py" --json send "hello"
```

输出示例：
```json
{"status": "ok", "type": "text", "text": "hello"}
{"status": "ok", "type": "file", "file": "report.pdf"}
{"ready": true, "user_id": "xxx", "token": "abc123...", "settings": "..."}
```

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `setup` | 一键初始化（配置检查 → 获取 token → 注入通知 → 发验证消息） |
| `send` | 发送文本消息 |
| `sendfile` | 发送文件 |
| `status` | 查看配置和 token 状态 |
| `refresh` | 刷新缓存的 context_token |
| `--json` | 任何命令前加此标志，输出 JSON |

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| "No context_token" | 用户给 ClawBot 发一条消息 → `refresh` |
| "HTTP 401" | 检查 WorkBuddy 设置中的 botToken |
| ModuleNotFoundError | `pip install cryptography` |
| 文件显示卡片但下载失败 | aes_key 编码已修复，更新到脚本最新版本 |

## 工作原理

1. 从 WorkBuddy settings 读取 ClawBot 配置
2. 调用 `/ilink/bot/getupdates` 获取 context_token 并缓存
3. 发送文本：`/ilink/bot/sendmessage` (type:1)
4. 发送文件：AES-128-ECB 加密 → getuploadurl → CDN 上传 → sendmessage (type:4)
5. 失败时自动刷新 token 重试一次
