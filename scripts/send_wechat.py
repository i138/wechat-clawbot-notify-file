#!/usr/bin/env python3
"""
WeChat ClawBot Notify — single entry point for agent/LLM.

Usage:
    send_wechat.py setup                      # One-time init
    send_wechat.py send "text"                # Send text message
    send_wechat.py sendfile "/path/to/file"   # Send file
    send_wechat.py status                     # Check config & token
    send_wechat.py refresh                    # Refresh context_token

Add --json before the command for structured JSON output (agent-friendly).
"""

import json, os, sys, time, uuid, base64, hashlib, urllib.request, urllib.error
from urllib.parse import urlparse, parse_qs
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as crypto_padding

if sys.version_info < (3, 8):
    print("Error: Python 3.8+ required.", file=sys.stderr); sys.exit(1)

# --- Globals ---
SKILL_DIR = os.environ.get("SKILL_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_FILE = os.path.join(SKILL_DIR, ".token_cache.json")
LOG_FILE = os.path.join(SKILL_DIR, "logs", "send_wechat.log")
CHANNEL_VERSION = "workbuddy-desktop-1.0.0"
JSON_MODE = False  # set after parsing --json flag

# --- Helpers ---

def log(msg):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{ts}\t{msg}\n")

def out(text, json_data=None, exit_code=0):
    """Print output. In JSON mode, always output dict; in text mode, print text."""
    if JSON_MODE:
        d = json_data or {"message": text}
        print(json.dumps(d, ensure_ascii=False))
    else:
        if text:
            print(text)
    if exit_code:
        sys.exit(exit_code)

def err(text, exit_code=1):
    if JSON_MODE:
        print(json.dumps({"error": text}, ensure_ascii=False))
    else:
        print(text, file=sys.stderr)
    sys.exit(exit_code)

# --- Config ---

def _settings_candidates():
    if sys.platform == "darwin":
        return [os.path.expanduser("~/.workbuddy/settings.json"),
                os.path.expanduser("~/Library/Application Support/WorkBuddy/User/settings.json")]
    if sys.platform == "win32":
        c = []
        if os.environ.get("USERPROFILE"):
            c.append(os.path.join(os.environ["USERPROFILE"], ".workbuddy", "settings.json"))
        if os.environ.get("APPDATA"):
            c.append(os.path.join(os.environ["APPDATA"], "WorkBuddy", "User", "settings.json"))
        return c or [os.path.expanduser("~/AppData/Roaming/WorkBuddy/User/settings.json")]
    return [os.path.expanduser("~/.workbuddy/settings.json"),
            os.path.expanduser("~/.config/WorkBuddy/User/settings.json")]

def _extract_cfg(settings):
    channels = settings.get("claw", {}).get("channels")
    if isinstance(channels, dict) and "weixinClawBot" in channels:
        return channels["weixinClawBot"]
    for uid, u in settings.get("claw", {}).get("users", {}).items():
        if isinstance(u, dict):
            ch = u.get("channels", {})
            if isinstance(ch, dict) and "weixinClawBot" in ch:
                return ch["weixinClawBot"]
    return {}

def load_config():
    errors = []
    for p in _settings_candidates():
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                s = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            errors.append(str(e)); continue
        cfg = _extract_cfg(s)
        if cfg.get("enabled"):
            cfg["_settings_path"] = p
            for k in ["botToken", "baseUrl", "userId"]:
                if not cfg.get(k):
                    err(f"Missing '{k}' in weixinClawBot config.")
            return cfg
    detail = "; ".join(errors) if errors else "weixinClawBot channel not enabled"
    err(f"Cannot read WorkBuddy settings: {detail}")

# --- Cache ---

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_cache(cfg=None, **kwargs):
    cache = load_cache()
    cache.update(kwargs)
    if cfg:
        cache["account_id"] = cfg.get("accountId")
        cache["settings_path"] = cfg.get("_settings_path")
    cache["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)

def cached_token(cfg):
    c = load_cache()
    if c and (not c.get("account_id") or c.get("account_id") == cfg.get("accountId")):
        return c.get("context_token")
    return None

def cached_buf(cfg):
    c = load_cache()
    if c and c.get("account_id") and c["account_id"] == cfg.get("accountId"):
        return c.get("get_updates_buf", "")
    return ""

# --- Network ---

def gen_uin():
    return base64.b64encode(str(int.from_bytes(os.urandom(4), "little")).encode()).decode()

def api_req(base_url, path, bot_token, payload, timeout=15):
    headers = {"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
               "Authorization": f"Bearer {bot_token}", "X-WECHAT-UIN": gen_uin()}
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        log(f"HTTP_ERROR\t{path}\t{e.code}")
        return {"_http_error": e.code, "_body": e.read().decode("utf-8", errors="replace")[:300]}
    except (urllib.error.URLError, OSError) as e:
        log(f"NETWORK_ERROR\t{path}\t{getattr(e,'reason',str(e))}")
        return {"_network_error": str(e)}

# --- Crypto ---

def aes_ecb_encrypt(data: bytes, key: bytes) -> bytes:
    padder = crypto_padding.PKCS7(128).padder()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(padder.update(data) + padder.finalize()) + enc.finalize()

# --- Core Operations ---

def refresh_token(cfg, retry_no_cursor=True):
    buf = cached_buf(cfg)
    result = api_req(cfg["baseUrl"], "/ilink/bot/getupdates", cfg["botToken"],
                     {"get_updates_buf": buf, "base_info": {"channel_version": CHANNEL_VERSION}}, timeout=45)
    if result is None or result.get("_http_error") or result.get("_network_error"):
        return None

    ret = result.get("ret")
    if ret is not None and ret != 0:
        log(f"TOKEN_REFRESH_FAILED\tret={ret}")
        if retry_no_cursor and buf:
            save_cache(get_updates_buf="", cfg=cfg)
            return refresh_token(cfg, retry_no_cursor=False)
        return None

    if result.get("get_updates_buf"):
        save_cache(get_updates_buf=result["get_updates_buf"], cfg=cfg)

    for msg in reversed(result.get("msgs", [])):
        token = msg.get("context_token", "")
        if token:
            save_cache(context_token=token, cfg=cfg)
            log(f"TOKEN_REFRESHED\t{token[:32]}...")
            return token
    log("TOKEN_REFRESH_FAILED\tno context_token found")
    return None

def send_msg(cfg, text, token):
    payload = {"msg": {"from_user_id": "", "to_user_id": cfg["userId"],
                "client_id": f"wb-notify-{uuid.uuid4().hex[:16]}",
                "message_type": 2, "message_state": 2, "context_token": token,
                "item_list": [{"type": 1, "text_item": {"text": text}}]},
               "base_info": {"channel_version": CHANNEL_VERSION}}
    result = api_req(cfg["baseUrl"], "/ilink/bot/sendmessage", cfg["botToken"], payload)
    if not result or result.get("_http_error"):
        return False
    r = result.get("ret", result.get("errcode"))
    if r is not None and r != 0:
        log(f"SEND_FAILED\tret={r}")
        return False
    log(f"SEND_OK\t{text[:50]}")
    return True

def get_upload_url(cfg, file_key, raw_size, raw_md5, enc_size, aes_hex):
    result = api_req(cfg["baseUrl"], "/ilink/bot/getuploadurl", cfg["botToken"],
                     {"filekey": file_key, "media_type": 3, "to_user_id": cfg["userId"],
                      "rawsize": raw_size, "rawfilemd5": raw_md5, "filesize": enc_size,
                      "no_need_thumb": True, "aeskey": aes_hex})
    if not result or result.get("_http_error") or result.get("ret", 0) != 0:
        return None, None

    param = result.get("upload_param", "")
    if param:
        return f"https://novac2c.cdn.weixin.qq.com/c2c/upload?encrypted_query_param={param}&filekey={file_key}", param
    url = result.get("upload_full_url", "")
    if url:
        q = parse_qs(urlparse(url).query)
        ep = q.get("encrypted_query_param", [""])[0]
        if ep:
            return url, ep
    return None, None

def upload_cdn(upload_url, param, file_key, data):
    url = upload_url if "encrypted_query_param=" in upload_url else f"{upload_url}?encrypted_query_param={param}&filekey={file_key}"
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            ep = r.headers.get("x-encrypted-param") or r.headers.get("X-Encrypted-Param") or ""
            if not ep:
                log("CDN_UPLOAD_FAILED\tno_x_encrypted_param")
            return ep
    except Exception as e:
        log(f"CDN_UPLOAD_FAILED\t{e}")
        return None

def send_file_msg(cfg, token, file_path, enc_param, aes_key, raw_size):
    aes_b64 = base64.b64encode(aes_key.hex().encode("ascii")).decode("ascii")
    payload = {"msg": {"from_user_id": "", "to_user_id": cfg["userId"],
                "client_id": f"wb-notify-{uuid.uuid4().hex[:16]}",
                "message_type": 2, "message_state": 2, "context_token": token,
                "item_list": [{"type": 4, "file_item": {"media": {"encrypt_query_param": enc_param,
                    "aes_key": aes_b64, "encrypt_type": 1},
                    "file_name": os.path.basename(file_path), "len": str(raw_size)}}]},
               "base_info": {"channel_version": CHANNEL_VERSION}}
    result = api_req(cfg["baseUrl"], "/ilink/bot/sendmessage", cfg["botToken"], payload)
    if not result or result.get("ret", 0) != 0:
        return False
    log(f"SEND_FILE_OK\t{os.path.basename(file_path)}\t{raw_size}")
    return True

def send_file(cfg, token, file_path):
    with open(file_path, "rb") as f:
        data = f.read()
    raw_size = len(data)
    raw_md5 = hashlib.md5(data).hexdigest()
    aes_key = os.urandom(16)
    aes_hex = aes_key.hex()
    enc_data = aes_ecb_encrypt(data, aes_key)
    file_key = uuid.uuid4().hex

    upload_url, param = get_upload_url(cfg, file_key, raw_size, raw_md5, len(enc_data), aes_hex)
    if not param:
        return False
    ep = upload_cdn(upload_url, param, file_key, enc_data)
    if not ep:
        return False
    return send_file_msg(cfg, token, file_path, ep, aes_key, raw_size)

def send_with_retry(cfg, send_fn, *args):
    """Try sending; refresh token and retry once on failure."""
    token = cached_token(cfg)
    if not token:
        token = refresh_token(cfg)
    if not token:
        return False, "No context_token. User must send a message to ClawBot first."
    if send_fn(cfg, token, *args):
        return True, "ok"
    token = refresh_token(cfg)
    if token and send_fn(cfg, token, *args):
        return True, "ok (after refresh)"
    return False, "Failed after retry."

# --- SOUL injection ---

def inject_soul():
    """Add auto-notify instruction to ~/.workbuddy/SOUL.md. Idempotent."""
    soul_path = os.path.expanduser("~/.workbuddy/SOUL.md")
    if not os.path.isfile(soul_path):
        return "SOUL.md not found (WorkBuddy not installed?). Skipped."

    with open(soul_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    marker = "## Automation Notification"
    boundaries = "## Boundaries"
    instruction = f"""## Automation Notification

When completing an automation task, always use the `wechat-clawbot-notify` skill to send a concise result summary to the user's WeChat:

```bash
python "$SKILL_DIR/scripts/send_wechat.py" send "your summary here"
```

This ensures the user gets notified on WeChat when scheduled tasks finish, even if they are away from the computer.

"""

    import re
    if marker in content:
        pat = re.compile(rf"{re.escape(marker)}\n.*?(?=\n## |\Z)", re.DOTALL)
        new = pat.sub(lambda _: instruction.rstrip() + "\n", content, 1)
    elif boundaries in content:
        new = content.replace(boundaries, instruction + boundaries)
    else:
        new = content.rstrip() + "\n\n" + instruction

    if new == content:
        return "Already injected. Skipped."
    with open(soul_path, "w", encoding="utf-8") as f:
        f.write(new)
    return "SOUL.md updated."

# --- Commands ---

def cmd_setup(args):
    """Single-step initialization: check config → get token → inject soul → send test."""
    import subprocess
    cfg = load_config()
    out("Config OK.", {"status": "config_ok", "settings": cfg.get("_settings_path")})

    token = cached_token(cfg)
    if not token:
        out("No cached token; refreshing...", {"status": "refreshing"})
        token = refresh_token(cfg)
        if not token:
            out("No messages found.", {"status": "need_user_msg",
                 "message": "Please send any message to your ClawBot in WeChat, then run setup again."})
            return
    out("Token ready.", {"status": "token_ok"})

    soul_msg = inject_soul()
    out(f"Soul injection: {soul_msg}", {"status": "soul_ok", "detail": soul_msg})

    ok, msg = send_msg(cfg, "微信 ClawBot 通知技能配置完成！后续自动化任务完成后会自动通知你的微信。", token), ""
    if ok:
        out("Ready. Test message sent.", {"status": "ready", "test_message_sent": True})
    else:
        out("Ready (test message failed; try refresh later).", {"status": "ready", "test_message_sent": False})

def cmd_send(args):
    if not args:
        err("Usage: send_wechat.py send \"message\"")
    cfg = load_config()
    text = " ".join(args)
    ok, msg = send_with_retry(cfg, send_msg, text)
    if ok:
        out(f"Sent: {text[:80]}", {"status": "ok", "type": "text", "text": text[:200]})
    else:
        err(f"Send failed: {msg}")

def cmd_sendfile(args):
    if not args:
        err("Usage: send_wechat.py sendfile <path>")
    path = args[0]
    if not os.path.exists(path):
        err(f"File not found: {path}")
    cfg = load_config()
    fn = os.path.basename(path)
    ok, msg = send_with_retry(cfg, send_file, path)
    if ok:
        out(f"Sent: {fn} ({os.path.getsize(path):,} bytes)", {"status": "ok", "type": "file", "file": fn})
    else:
        err(f"Send failed: {msg}")

def cmd_refresh(args):
    cfg = load_config()
    token = refresh_token(cfg)
    if token:
        out("Token refreshed.", {"status": "ok", "token_prefix": token[:16]})
    else:
        err("No token found. Send a message to ClawBot first, then retry.")

def cmd_status(args):
    cfg = load_config()
    cache = load_cache()
    token = cache.get("context_token")
    d = {"settings": cfg.get("_settings_path"), "bot_id": cfg.get("accountId", "N/A"),
         "user_id": cfg["userId"], "base_url": cfg["baseUrl"],
         "enabled": cfg.get("enabled", False), "ready": bool(token),
         "token": f"{token[:16]}..." if token else None,
         "cache_updated": cache.get("updated_at", "N/A"),
         "cache_bot": cache.get("account_id", "legacy")}
    if JSON_MODE:
        out(None, d)
    else:
        for k, v in d.items():
            print(f"{k.replace('_',' ').title():12s} {v}")

COMMANDS = {"setup": cmd_setup, "send": cmd_send, "sendfile": cmd_sendfile,
            "refresh": cmd_refresh, "status": cmd_status}

def main():
    global JSON_MODE
    args = sys.argv[1:]
    if "--json" in args:
        JSON_MODE = True
        args.remove("--json")
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__.strip()); sys.exit(0)
    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}. Available: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)
    COMMANDS[cmd](args[1:])

if __name__ == "__main__":
    main()
