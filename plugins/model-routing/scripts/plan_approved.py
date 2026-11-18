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
    "The plan is approved. Check its Executor line (Sonnet if there is none). If "
    "you are that model, carry the plan out directly, handing only large, purely "
    "mechanical chunks to model-routing:implementer with model: haiku. If you "
    "aren't, follow /execute: hand the chunks to model-routing:implementer "
    "subagents running the executor model, each with a brief that stands alone, "
    "then check the results here. Either way, make small fixes (a few lines) "
    "directly."
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
