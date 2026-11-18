---
name: execute
description: Carry out a settled plan on cheaper models, each chunk in its own fresh context, while this conversation stays on its current model for planning and review. Use when the user approves a plan or says to go ahead and build it.
argument-hint: "[which plan, or extra instructions]"
---

Carry out the agreed plan through `model-routing:implementer` subagents (Sonnet) instead of editing in this conversation. $ARGUMENTS

1. Split the plan into chunks that can each be done and checked on their own. Chunks that touch different files can run in parallel. Chunks that depend on each other run in order.
2. For each chunk, write a brief that stands alone: the goal, exact files and line ranges, decisions already made and why, constraints, and the command that proves it works. Don't paste the conversation.
3. Hand each chunk to `model-routing:implementer`. For purely mechanical chunks (renames, boilerplate, moving code), pass `model: haiku`.
4. When the reports come back, check the risky parts yourself with `git diff`, and run the tests once if a chunk failed or skipped them. Send a failed chunk back to an implementer with the failure output, not the whole story.
5. Tell the user, in numbered steps: what was done, what passed, and what's left.

A small fix (a few lines in one file) is cheaper to make right here, so don't start a subagent for it.
