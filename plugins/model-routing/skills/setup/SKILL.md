---
name: setup
description: Turn on running approved plans in a fresh context, and choose whether they run on Sonnet automatically (opusplan) or on whatever model the user is using.
argument-hint: "[sonnet | same]"
disable-model-invocation: true
allowed-tools: Bash(routing-setup *)
---

The user's choice: "$ARGUMENTS". "same" means plans run on whatever model they're using. Anything else, including nothing, means "sonnet": Opus plans and Sonnet executes (opusplan).

1. Run `routing-setup --check --executor <sonnet|same>` and show the user, in a short numbered list, what it would change in their settings.
2. If something would change, run `routing-setup --apply --executor <sonnet|same>` and report the result in two or three lines.
3. Tell the user how it works now, as numbered steps:
   1. For a bigger task, press Shift+Tab to enter plan mode.
   2. The plan's first line says which model carries it out (`Executor: sonnet` by default). To pick another, press Ctrl+G and edit that line before approving.
   3. Approve with "Yes, clear context". The plan runs in a fresh session, so nothing re-reads the planning chat.
   4. To hand the rest of a task to a different model midway, run `/execute opus` (or sonnet or haiku). The work goes to a fresh subagent, with no re-read.
