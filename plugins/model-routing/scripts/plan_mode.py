#!/usr/bin/env python3
"""UserPromptSubmit hook: only acts in plan mode.

With "Yes, clear context" on plan approval, the approved plan is the only thing
the executing model (Sonnet under opusplan) gets. This makes sure the plan is
written to stand on its own.

Config (settings.json "env"):
  ROUTING_EXECUTE  0 = off (default 1)
"""
import json
import os
import sys

NOTE = (
    "Plan mode: the approved plan may be all the executing model sees (often "
    "Sonnet, in a fresh context). Write it to stand alone: the goal and what done "
    "means; decisions with their reasons; exact files and line ranges; ordered "
    "steps, marking which can run in parallel; the command that verifies each "
    "step; known gotchas with exact error strings. Start the plan with these two "
    "lines, using the model the user asked for, or sonnet if they didn't say:\n"
    "Executor: sonnet\n"
    "(Whoever runs this plan: if you aren't the executor model, hand the whole "
    "plan to the model-routing:implementer subagent with that model instead of "
    "doing it yourself.)"
)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if os.environ.get("ROUTING_EXECUTE", "1") == "0":
        return 0
    if data.get("permission_mode") != "plan" or data.get("agent_id"):
        return 0
    print(NOTE)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
