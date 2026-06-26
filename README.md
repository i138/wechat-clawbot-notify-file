# WeChat ClawBot Message

一个 WorkBuddy AI Agent Skill，让你的 AI 助手能够通过微信 ClawBot 给你发送通知消息和文件。

当 AI 完成自动化任务后，会自动通过微信通知你结果；也可以让 AI 把报告、PDF 等文件直接发到你微信。

感谢：https://github.com/plustar35/wechat-clawbot-notify 提供的思路。

## 工作原理

```
AI 助手 → ClawBot iLink API → 微信 ClawBot → 你的微信
```

1. **读取配置**：从 WorkBuddy settings.json 读取 ClawBot 通道配置
2. **获取 Token**：调用 `/ilink/bot/getupdates` 提取 `context_token` 并缓存
3. **发送文本/文件**：通过 `/ilink/bot/sendmessage` 发送消息
4. **自动重试**：失败时自动刷新 token 重试一次

## 前置条件

- macOS / Windows / Linux
- Python 3 + `cryptography`（`pip install cryptography`）
- 已安装 WorkBuddy 并在设置中开启微信 ClawBot 通道

## 项目结构

```
wechat-clawbot-notify/
  SKILL.md               # Skill 描述（AI 读取）
  README.md              # 本文件
  scripts/
    send_wechat.py       # 统一入口脚本（send/sendfile/status/refresh/setup）
  logs/
    send_wechat.log      # 运行日志
  .token_cache.json      # 缓存的 context_token（自动生成）
```

## 使用指南

### 初始化

在 AI 助手中输入：

```
/wechat-clawbot-notify 帮我初始化微信通知
```

AI 会自动执行 `setup` 完成全部配置。如果提示需要用户给 ClawBot 发消息 → 去微信发一条 → 告诉 AI "已经发了，继续"。

### 日常使用

AI 在完成自动化任务后会自动推送通知。也可以主动说：

```
明天上午 10 点微信提醒我有会议
```

### 手动命令

```bash
# 发送文本
python scripts/send_wechat.py send "任务完成：报告已生成"

# 发送文件
python scripts/send_wechat.py sendfile "/path/to/report.pdf"

# 查看状态
python scripts/send_wechat.py status

# 刷新 token
python scripts/send_wechat.py refresh
```

### JSON 模式（适合 LLM）

```bash
python scripts/send_wechat.py --json status
```

## License

MIT
