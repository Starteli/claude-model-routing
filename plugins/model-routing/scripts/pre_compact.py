#!/usr/bin/env python3
"""PreCompact hook (manual and auto).

Steers the compaction summary into handoff shape, so that `/compact` followed by
`/model <name>` gives the new model everything it needs from a short summary.

Config (settings.json "env"):
  ROUTING_COMPACT_FORMAT  0 = leave compaction summaries alone (default 1)
"""
import os
import sys

INSTRUCTIONS = """\
A different model may continue from this summary with no other context. Make sure it includes:
- what "done" means for the current task
- each decision with its reason and what was rejected, so it isn't relitigated
- key files as path:line with their current state
- exact commands, error messages and values that were expensive to find
- next steps, numbered, the first one concrete
Point to files instead of pasting long code. Leave out dead ends that taught nothing."""


def main():
    sys.stdin.read()  # input not needed; drain it
    if os.environ.get("ROUTING_COMPACT_FORMAT", "1") == "0":
        return 0
    print(INSTRUCTIONS)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
