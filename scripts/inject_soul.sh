#!/bin/bash
# Inject the Automation Notification instruction into ~/.workbuddy/SOUL.md
# Idempotent: skips if already present.
#
# Usage: bash "$SKILL_DIR/scripts/inject_soul.sh"

set -euo pipefail

SOUL_MD="$HOME/.workbuddy/SOUL.md"
NOTIFICATION_MARKER="## Automation Notification"

if [ ! -f "$SOUL_MD" ]; then
  echo "WARNING: $SOUL_MD not found. Skipping."
  echo "You can manually add the automation notification instruction later."
  exit 0
fi

if grep -qF "$NOTIFICATION_MARKER" "$SOUL_MD"; then
  echo "SOUL.md already contains automation notification instruction. Skipping."
  exit 0
fi

INSTRUCTION='## Automation Notification

When completing an automation task, always use the `wechat-clawbot-notify` skill to send a concise result summary to the user'\''s WeChat:

```bash
python3 "$SKILL_DIR/scripts/send_wechat.py" send "your summary here"
```

This ensures the user gets notified on WeChat when scheduled tasks finish, even if they are away from the computer.

'

if grep -qF "## Boundaries" "$SOUL_MD"; then
  python3 - "$SOUL_MD" "$INSTRUCTION" << 'PYEOF'
import sys
soul_path = sys.argv[1]
instruction = sys.argv[2]
with open(soul_path, "r") as f:
    content = f.read()
content = content.replace("## Boundaries", instruction + "## Boundaries")
with open(soul_path, "w") as f:
    f.write(content)
PYEOF
else
  printf "\n%s" "$INSTRUCTION" >> "$SOUL_MD"
fi

echo "SOUL.md updated with automation notification instruction."
