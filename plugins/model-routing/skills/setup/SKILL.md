---
name: setup
description: Turn on the plan-then-execute split in the user's Claude Code settings, so Opus plans and Sonnet carries out the approved plan in a fresh context.
disable-model-invocation: true
allowed-tools: Bash(routing-setup *)
---

Run `routing-setup --check` and show the user, in a short numbered list, what it would change in their settings.

If something would change, run `routing-setup --apply` and report the result in two or three lines.

Then tell the user how the flow works now, as numbered steps:
1. For a bigger task, press Shift+Tab to enter plan mode. Opus writes the plan.
2. When the plan looks right, pick "Yes, clear context". Sonnet then carries out the plan in a fresh session, so it never re-reads the planning chat.
3. In a long session, run /compact before entering plan mode, because entering plan mode re-sends the conversation to Opus.
