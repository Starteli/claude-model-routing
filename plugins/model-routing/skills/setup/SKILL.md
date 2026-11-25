---
name: setup
description: Turn on running approved plans in a fresh context, keeping the user's own model (default), or optionally pinning opusplan so Sonnet executes.
argument-hint: "[same | sonnet]"
disable-model-invocation: true
allowed-tools: Bash(routing-setup *)
---

The user's choice: "$ARGUMENTS". "sonnet" means pin opusplan: Opus plans and Sonnet executes. Anything else, including nothing, means "same": plans run on whatever model they're using, and an opusplan pin from an earlier setup is removed.

If they chose "sonnet", warn them first in one line: pinning opusplan switches off Claude Code's own model mix (a lead model with cheaper workers, shown as its own row in /model) if their account has one.

1. Run `routing-setup --check --executor <sonnet|same>` and show the user, in a short numbered list, what it would change in their settings.
2. If something would change, run `routing-setup --apply --executor <sonnet|same>` and report the result in two or three lines.
3. Tell the user how it works now, as numbered steps:
   1. For a bigger task, press Shift+Tab to enter plan mode.
   2. The plan's first line says which model carries it out (`Executor: sonnet` by default). To pick another, press Ctrl+G and edit that line before approving.
   3. Approve with "Yes, clear context". The plan runs in a fresh session, so nothing re-reads the planning chat.
   4. To hand the rest of a task to a different model midway, run `/execute opus` (or sonnet or haiku). The work goes to a fresh subagent, with no re-read.
