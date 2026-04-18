---
name: wechat-clawbot-notify
description: "Send notification messages to the user's WeChat via ClawBot (iLink API). Use when automation tasks complete and need to notify the user, or when the user asks to send a message to their WeChat. Triggers on: 'notify me on WeChat', 'send to my WeChat', 'push result to WeChat', '发微信通知', '推送到微信', '通知我'."
description_zh: "通过微信 ClawBot 发送通知消息给用户"
description_en: "Send notification messages to user's WeChat via ClawBot"
version: 1.2.0
allowed-tools: Bash,Read
compatibility: Requires macOS with python3. Reads config from WorkBuddy settings.json.
metadata:
  version: "1.2.0"
  openclaw:
    emoji: "\U0001F4AC"
    requires:
      bins:
        - python3
---

# WeChat ClawBot Notify

通过微信 ClawBot iLink API 发送文本消息给用户。

## 初始化检查（必须优先执行）

**使用任何命令前，先检查 `$SKILL_DIR/.token_cache.json` 是否存在。**

- **文件存在** → 技能已就绪，直接跳到 [发送消息](#发送消息)。
- **文件不存在** → 首次使用，按以下步骤**依次执行**。

### 第 1 步：检查 ClawBot 配置

```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" status
```

- **成功** → 进入第 2 步。
- **报错** → ClawBot 未配置。告诉用户："请先在 WorkBuddy 设置中连接你的微信 ClawBot 通道。" 到此停止。

### 第 2 步：获取 context_token

```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" refresh
```

- **成功**（输出 "Token refreshed successfully"）→ 进入第 3 步。
- **失败**（输出 "No messages with context_token found"）→ 告诉用户："请打开微信，给你的 ClawBot 发一条消息，然后告诉我继续。" **等待用户确认后**，重试本步骤。

### 第 3 步：配置自动通知

```bash
bash "$SKILL_DIR/scripts/inject_soul.sh"
```

将自动通知指令写入 `~/.workbuddy/SOUL.md`，后续自动化任务完成后会自动使用本技能通知用户。幂等操作，可重复执行。

### 第 4 步：发送验证消息

```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" send "微信 ClawBot 通知技能配置完成！后续自动化任务完成后会自动通知你的微信。"
```

- **成功** → 告诉用户："配置完成！验证消息已发送到你的微信，后续自动化任务会自动通知你。"
- **失败** → 告诉用户："配置基本完成，但验证消息发送失败。稍后可以尝试执行 refresh 刷新 token。"

---

## 发送消息

```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" send "消息内容"
```

## 其他命令

### 查看状态

```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" status
```

### 刷新 token

发送失败时，刷新缓存的 token：

```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" refresh
```

## 在自动化任务中使用

自动化任务完成后，发送简要的结果摘要：

```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" send "任务完成：<结果摘要>"
```

## 示例

**每日简报通知：**
```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" send "每日简报：今天 3 个会议，5 个待办任务。"
```

**充电提醒：**
```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" send "充电提醒：该给设备充电了！"
```

## 故障排查

| 问题 | 解决方法 |
|---|---|
| `.token_cache.json` 不存在 | 按上面的初始化步骤执行 |
| "No cached context_token" | 用户给 ClawBot 发一条消息，然后执行 `refresh` |
| 发送静默失败 | 执行 `refresh` 获取新的 token |
| "HTTP 401" | 检查 WorkBuddy 设置中的 botToken |

## 工作原理

1. **配置**：从 WorkBuddy settings 读取 `claw.channels.weixinClawBot`（botToken、userId、baseUrl）
2. **Token**：调用 `/ilink/bot/getupdates` 从最近的消息中获取 `context_token`，缓存到本地
3. **发送**：使用缓存的 token 向 `/ilink/bot/sendmessage` 发送消息
4. **重试**：发送失败时自动刷新 token 并重试一次
5. **日志**：所有操作记录到 `logs/send_wechat.log`
