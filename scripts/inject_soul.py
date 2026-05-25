#!/usr/bin/env python3
"""
Inject the Automation Notification instruction into ~/.workbuddy/SOUL.md.

Idempotent: skips if the marker is already present.
Cross-platform: works on macOS, Linux, and Windows.

Usage:
    python inject_soul.py
"""

import os
import re
import sys

SOUL_MD = os.path.expanduser("~/.workbuddy/SOUL.md")
NOTIFICATION_MARKER = "## Automation Notification"
BOUNDARIES_MARKER = "## Boundaries"

INSTRUCTION = """## Automation Notification

When completing an automation task, always use the `wechat-clawbot-notify` skill to send a concise result summary to the user's WeChat:

Windows PowerShell:
```powershell
python "$env:SKILL_DIR\\scripts\\send_wechat.py" send "your summary here"
```

Bash/macOS/Linux:
```bash
python "$SKILL_DIR/scripts/send_wechat.py" send "your summary here"
```

This ensures the user gets notified on WeChat when scheduled tasks finish, even if they are away from the computer.

"""


def main():
    if not os.path.isfile(SOUL_MD):
        print(f"WARNING: {SOUL_MD} not found. Skipping.")
        print("You can manually add the automation notification instruction later.")
        return 0

    with open(SOUL_MD, "r", encoding="utf-8-sig") as f:
        content = f.read()

    if NOTIFICATION_MARKER in content:
        pattern = re.compile(rf"{re.escape(NOTIFICATION_MARKER)}\n.*?(?=\n## |\Z)", re.DOTALL)
        new_content = pattern.sub(lambda _match: INSTRUCTION.rstrip() + "\n", content, count=1)
    elif BOUNDARIES_MARKER in content:
        new_content = content.replace(BOUNDARIES_MARKER, INSTRUCTION + BOUNDARIES_MARKER)
    else:
        new_content = content.rstrip() + "\n\n" + INSTRUCTION

    if new_content == content:
        print("SOUL.md already contains automation notification instruction. Skipping.")
        return 0

    with open(SOUL_MD, "w", encoding="utf-8") as f:
        f.write(new_content)

    print("SOUL.md updated with automation notification instruction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
