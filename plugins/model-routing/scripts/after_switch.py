#!/usr/bin/env python3
"""PostModelSwitch hook.

Switches you make with /model go through switch_guard.py first. This catches
the ones Claude Code makes by itself, mainly opusplan entering plan mode, which
re-sends the whole conversation to Opus. It can't stop them, so it just says
what it cost and how to keep it small next time.

Config (settings.json "env"):
  ROUTING_ASK_TOKENS  default 40000
  ROUTING_ASK_USD     default 0.10
"""
import json
import os
import sys


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("source") != "auto":
        return 0
    if data.get("from_model") == data.get("to_model") or not data.get("prompt_cache_warm"):
        return 0
    ctx = int(data.get("context_tokens") or 0)
    usd = data.get("estimated_cache_write_usd")
    priced = isinstance(usd, (int, float)) and data.get("pricing") in ("catalog", "configured")
    if ctx < env_float("ROUTING_ASK_TOKENS", 40000) or (priced and usd < env_float("ROUTING_ASK_USD", 0.10)):
        return 0
    cost = f" (about ${usd:.2f})" if priced else ""
    print(json.dumps({"systemMessage": (
        f"Claude Code switched to {data.get('to_model')} by itself (plan mode or a "
        f"fallback) and re-sent ~{ctx // 1000}K tokens{cost}. In a long session, "
        f"run /compact before entering plan mode to keep this small."
    )}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
