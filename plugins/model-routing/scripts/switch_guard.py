#!/usr/bin/env python3
"""PreModelSwitch hook.

A /model switch throws away the current model's prompt cache, so the new model
re-reads the whole conversation uncached. This hook:
  - lets cheap switches through without Claude Code's confirmation prompt
  - for expensive ones (big context, warm cache), asks first and names the
    cheaper path: /compact, then /model

Config (settings.json "env"):
  ROUTING_ASK_TOKENS   ask when the switch re-sends at least this many tokens (default 40000)
  ROUTING_ASK_USD      ...and the estimated re-cache cost is at least this much (default 0.10)
  ROUTING_FAST_SWITCH  0 = keep Claude Code's own confirmation on cheap switches (default 1)
  ROUTING_HANDOFF_DIR  where handoffs live, relative to the project (default .handoff)

Any failure exits 0 with no output, so the switch proceeds normally.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def just_compacted(session_id, window_min=15):
    """True if post_compact.py marked this session as compacted recently.

    Right after /compact the context is small, but the token count this hook
    is handed may still describe the last pre-compaction response.
    """
    if not session_id:
        return False
    marker = Path(tempfile.gettempdir()) / "claude-model-routing" / f"{session_id}.compacted"
    try:
        return (time.time() - marker.stat().st_mtime) / 60 <= window_min
    except OSError:
        return False


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def fresh_handoff_minutes(project_dir):
    """Age in minutes of LATEST.md if it was written in the last 30 minutes."""
    handoff_dir = os.environ.get("ROUTING_HANDOFF_DIR", ".handoff")
    latest = Path(project_dir) / handoff_dir / "LATEST.md"
    try:
        age = (time.time() - latest.stat().st_mtime) / 60
    except OSError:
        return None
    return age if age <= 30 else None


def emit(obj):
    print(json.dumps(obj))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    from_model = data.get("from_model")
    to_model = data.get("to_model")
    if not to_model or from_model == to_model:
        return 0

    ctx = int(data.get("context_tokens") or 0)
    warm = bool(data.get("prompt_cache_warm"))
    usd = data.get("estimated_cache_write_usd")
    pricing = data.get("pricing")
    source = data.get("source")
    target = data.get("requested_model") or to_model

    ask_tokens = env_float("ROUTING_ASK_TOKENS", 40000)
    ask_usd = env_float("ROUTING_ASK_USD", 0.10)
    fast = os.environ.get("ROUTING_FAST_SWITCH", "1") != "0"

    priced = isinstance(usd, (int, float)) and pricing in ("catalog", "configured")
    cheap = (ctx < ask_tokens or (priced and usd < ask_usd)
             or just_compacted(data.get("session_id")))

    # Nothing to lose: small context, cheap target, or the cache is already cold
    # (staying would re-read everything too).
    if cheap or not warm:
        if fast:
            emit({"hookSpecificOutput": {"hookEventName": "PreModelSwitch",
                                         "permissionDecision": "allow"}})
        return 0

    cost = ""
    if priced:
        who = "your" if pricing == "configured" else "list"
        cost = f", about ${usd:.2f} at {who} prices"

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    age = fresh_handoff_minutes(project_dir)
    if age is not None:
        steps = ["/clear", f"/model {target}"]
        note = f" Your handoff from {max(1, round(age))} min ago loads by itself."
    else:
        steps = ["/compact", f"/model {target}"]
        note = ""
    escalate = " Or stay on this model and use /escalate for the hard part."
    head = f"This re-sends ~{ctx // 1000}K tokens to {to_model} with no cache{cost}."

    if source == "sdk":
        # Remote Control / SDK: "ask" would count as a refusal, so the switch
        # goes ahead and this is just a heads-up for next time.
        numbered = ", ".join(f"({i}) {s}" for i, s in enumerate(steps, 1))
        emit({"systemMessage": f"{head} Next time, cheaper: {numbered}.{note}{escalate}"})
    else:
        numbered = ", ".join(f"({i}) {s}" for i, s in enumerate(["choose No"] + steps, 1))
        emit({"hookSpecificOutput": {
            "hookEventName": "PreModelSwitch",
            "permissionDecision": "ask",
            "permissionDecisionReason": f"{head} Cheaper: {numbered}.{note}{escalate} Switch anyway?",
        }})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
