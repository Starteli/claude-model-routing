#!/usr/bin/env python3
"""PostToolUse hook on ExitPlanMode.

Fires when a plan is approved and the conversation keeps its context. (With
"Yes, clear context", Claude Code starts a fresh session for the plan instead,
and this hook doesn't fire.) Tells Claude how to carry out the plan cheaply,
depending on which model it's running on.

Config (settings.json "env"):
  ROUTING_EXECUTE  0 = off (default 1)
"""
import json
import os
import sys

NOTE = (
    "The plan is approved. If you're running on Opus or Fable, don't carry it out "
    "in this conversation: follow /execute and hand the chunks to "
    "model-routing:implementer subagents (Sonnet), each with a brief that stands "
    "alone, then check the results here. If you're running on Sonnet or Haiku, "
    "carry it out directly, and hand only large, purely mechanical chunks to "
    "model-routing:implementer with model: haiku. Either way, make small fixes "
    "(a few lines) directly."
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if os.environ.get("ROUTING_EXECUTE", "1") == "0":
        return 0
    if data.get("agent_id"):  # a subagent's own plan, not the main conversation's
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": NOTE,
    }}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
