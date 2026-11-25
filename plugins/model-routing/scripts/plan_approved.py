#!/usr/bin/env python3
"""PostToolUse hook on ExitPlanMode.

Fires when a plan is approved and the conversation keeps its context. (With
"Yes, clear context", Claude Code starts a fresh session for the plan, and the
SessionStart note covers it.) Says how to carry out the plan for the current
routing mode.

Config (settings.json "env"): ROUTING_EXECUTE  0 = off (default 1)
"""
import os

import routing_lib as rl


def main():
    data = rl.read_stdin_json()
    if data is None or os.environ.get("ROUTING_EXECUTE", "1") == "0" or data.get("agent_id"):
        return
    locked = rl.truthy(os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE"))
    rl.emit({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": rl.notes.C9_LOCKED if locked else rl.notes.C9_OPEN,
    }})


if __name__ == "__main__":
    rl.safe_main(main)
