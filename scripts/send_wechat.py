#!/usr/bin/env python3
"""
WeChat ClawBot Message Sender via iLink API.

Usage:
    send_wechat.py send "消息内容"          # 发送文本消息
    send_wechat.py refresh                  # 刷新 context_token
    send_wechat.py status                   # 查看当前 token 状态

Configuration is read from WorkBuddy settings.json automatically.
context_token is cached to ~/.workbuddy/skills/wechat-clawbot-notify/.token_cache.json
"""

import json
import os
import sys
import time
import uuid
import struct
import base64
import urllib.request
import urllib.error

# --- Paths ---
SKILL_DIR = os.environ.get("SKILL_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_FILE = os.path.join(SKILL_DIR, ".token_cache.json")
LOG_FILE = os.path.join(SKILL_DIR, "logs", "send_wechat.log")

WORKBUDDY_SETTINGS = os.path.expanduser(
    "~/Library/Application Support/WorkBuddy/User/settings.json"
)


def log(message):
    """Append-only action log."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(LOG_FILE, "a") as f:
        f.write(f"{ts}\t{message}\n")


def load_config():
    """Load ClawBot config from WorkBuddy settings."""
    try:
        with open(WORKBUDDY_SETTINGS, "r") as f:
            settings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error: Cannot read WorkBuddy settings: {e}", file=sys.stderr)
        sys.exit(1)

    channels = settings.get("claw.channels", {})
    bot_cfg = channels.get("weixinClawBot", {})

    if not bot_cfg.get("enabled"):
        print("Error: weixinClawBot channel is not enabled in WorkBuddy settings.", file=sys.stderr)
        sys.exit(1)

    required = ["botToken", "baseUrl", "userId"]
    for key in required:
        if not bot_cfg.get(key):
            print(f"Error: Missing '{key}' in weixinClawBot config.", file=sys.stderr)
            sys.exit(1)

    return bot_cfg


def generate_wechat_uin():
    """Generate X-WECHAT-UIN header: random uint32 -> decimal string -> base64."""
    rand_uint32 = int.from_bytes(os.urandom(4), "little")
    decimal_str = str(rand_uint32)
    return base64.b64encode(decimal_str.encode("ascii")).decode("ascii")


def make_headers(bot_token):
    """Build request headers for iLink API."""
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {bot_token}",
        "X-WECHAT-UIN": generate_wechat_uin(),
    }


def api_request(base_url, path, bot_token, payload, timeout=15):
    """Make a POST request to the iLink API."""
    url = f"{base_url}{path}"
    headers = make_headers(bot_token)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"Error: HTTP {e.code} from {path}: {error_body}", file=sys.stderr)
        log(f"HTTP_ERROR\t{path}\t{e.code}\t{error_body[:200]}")
        return None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", str(e))
        print(f"Error: Network error calling {path}: {reason}", file=sys.stderr)
        log(f"NETWORK_ERROR\t{path}\t{reason}")
        return None


def load_cached_token():
    """Load cached context_token from disk."""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        return cache.get("context_token")
    except (json.JSONDecodeError, IOError):
        return None


def save_cached_token(token):
    """Save context_token to disk (convenience wrapper)."""
    save_cache(context_token=token)


def load_getupdates_buf():
    """Load the getupdates cursor from cache."""
    if not os.path.exists(CACHE_FILE):
        return ""
    try:
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        return cache.get("get_updates_buf", "")
    except (json.JSONDecodeError, IOError):
        return ""


def save_cache(context_token=None, get_updates_buf=None):
    """Save context_token and/or get_updates_buf to disk."""
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    if context_token is not None:
        cache["context_token"] = context_token
    if get_updates_buf is not None:
        cache["get_updates_buf"] = get_updates_buf
    cache["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def refresh_token(config):
    """Fetch latest messages via getupdates to extract a fresh context_token.

    getupdates is a long-polling endpoint (holds up to 35s).
    Uses get_updates_buf as cursor for pagination.
    """
    buf = load_getupdates_buf()
    payload = {
        "get_updates_buf": buf,
        "base_info": {"channel_version": "1.0.2"}
    }

    # getupdates holds connection up to 35s waiting for new messages
    print("Polling for messages (may take up to 35 seconds)...", file=sys.stderr)
    result = api_request(
        config["baseUrl"], "/ilink/bot/getupdates", config["botToken"],
        payload, timeout=45
    )

    if result is None:
        return None

    ret = result.get("ret", None)
    if ret is not None and ret != 0:
        print(f"Warning: getupdates returned ret={ret}", file=sys.stderr)

    # Save the new cursor for next call
    new_buf = result.get("get_updates_buf", "")
    if new_buf:
        save_cache(get_updates_buf=new_buf)

    # Extract context_token from messages
    messages = result.get("msgs", [])

    if messages:
        for msg in reversed(messages):  # Most recent last
            token = msg.get("context_token", "")
            if token:
                save_cache(context_token=token)
                log(f"TOKEN_REFRESHED\t{token[:32]}...")
                print(f"Found {len(messages)} message(s).", file=sys.stderr)
                return token

    print("Warning: No messages with context_token found.", file=sys.stderr)
    print("Please send a message to your ClawBot in WeChat first, then run 'refresh' again.", file=sys.stderr)
    log("TOKEN_REFRESH_FAILED\tno messages found")
    return None


def send_message(config, text, context_token):
    """Send a text message to the user via ClawBot.

    All fields are required per the iLink protocol spec.
    Missing any field causes silent failure (HTTP 200 but no delivery).
    """
    client_id = f"workbuddy-notify-{uuid.uuid4().hex[:16]}"

    payload = {
        "msg": {
            "from_user_id": "",
            "to_user_id": config["userId"],
            "client_id": client_id,
            "message_type": 2,
            "message_state": 2,
            "context_token": context_token,
            "item_list": [
                {
                    "type": 1,
                    "text_item": {
                        "text": text
                    }
                }
            ]
        },
        "base_info": {
            "channel_version": "1.0.2"
        }
    }

    result = api_request(config["baseUrl"], "/ilink/bot/sendmessage", config["botToken"], payload)

    if result is None:
        return False

    # Check for errors - API may use "ret" or "errcode", or return empty {} on success
    ret = result.get("ret", result.get("errcode", None))
    if ret is not None and ret != 0:
        errmsg = result.get("errmsg", result.get("err_msg", json.dumps(result)))
        print(f"Error: API returned ret={ret}: {errmsg}", file=sys.stderr)
        log(f"SEND_FAILED\tret={ret}\t{errmsg}")
        return False

    log(f"SEND_OK\t{text[:50]}")
    return True


def cmd_send(args):
    """Handle 'send' command."""
    if not args:
        print("Error: No message provided. Usage: send_wechat.py send \"消息内容\"", file=sys.stderr)
        sys.exit(1)

    text = " ".join(args)
    config = load_config()

    # Get context_token: try cache first, then refresh
    context_token = load_cached_token()
    if not context_token:
        print("No cached context_token. Attempting to refresh...", file=sys.stderr)
        context_token = refresh_token(config)
        if not context_token:
            print("Error: Cannot obtain context_token. Please send a message to your ClawBot in WeChat first.", file=sys.stderr)
            sys.exit(1)

    # Attempt to send
    success = send_message(config, text, context_token)

    if not success:
        # Try refreshing token and retry once
        print("Retrying with refreshed token...", file=sys.stderr)
        context_token = refresh_token(config)
        if context_token:
            success = send_message(config, text, context_token)

    if success:
        print(f"Message sent successfully: {text[:80]}")
    else:
        print("Error: Failed to send message after retry.", file=sys.stderr)
        sys.exit(1)


def cmd_refresh(_args):
    """Handle 'refresh' command."""
    config = load_config()
    token = refresh_token(config)
    if token:
        print(f"Token refreshed successfully: {token[:32]}...")
    else:
        print("Failed to refresh token. Send a message to ClawBot first.", file=sys.stderr)
        sys.exit(1)


def cmd_status(_args):
    """Handle 'status' command."""
    config = load_config()
    print(f"Bot ID:    {config.get('accountId', 'N/A')}")
    print(f"User ID:   {config['userId']}")
    print(f"Base URL:  {config['baseUrl']}")
    print(f"Enabled:   {config.get('enabled', False)}")

    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            cache = json.load(f)
        print(f"Token:     {cache.get('context_token', 'N/A')[:32]}...")
        print(f"Updated:   {cache.get('updated_at', 'N/A')}")
    else:
        print("Token:     Not cached (run 'refresh' first)")


COMMANDS = {
    "send": cmd_send,
    "refresh": cmd_refresh,
    "status": cmd_status,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__.strip())
        print("\nCommands:")
        print("  send <message>    Send a text message to WeChat ClawBot")
        print("  refresh           Refresh context_token from recent messages")
        print("  status            Show current configuration and token status")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Error: Unknown command '{cmd}'. Use 'send', 'refresh', or 'status'.", file=sys.stderr)
        sys.exit(1)

    COMMANDS[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
