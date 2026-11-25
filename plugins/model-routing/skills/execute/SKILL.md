---
name: execute
description: Carry out the agreed plan or the rest of the task through implementer subagents with standalone briefs, so no model re-reads this chat.
argument-hint: "[opus | sonnet | haiku]"
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_status *)
---
!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_status --brief --data "${CLAUDE_PLUGIN_DATA}" --project "${CLAUDE_PROJECT_DIR}" || true`

Requested model: $ARGUMENTS

1. Split the work into chunks that can each be done and checked alone. Independent chunks run in parallel; dependent ones in order. If work is partly done, include only what's left and say what's done in each brief.
2. For each chunk, write a standalone brief: goal, exact files and line ranges, decisions and why, constraints, and the command that proves it works. No pasted conversation.
3. Who runs each chunk, by the routing line above:
   - LOCKED: every chunk runs on the forced subagent model. A requested model has no effect; if one was given, say so in one line. Set `effort` per chunk: low for mechanical, medium by default, high for tricky. Send open design questions to model-routing:think instead. Tell the user one line: "<N> chunks → <worker's short name from the routing line, e.g. Sonnet 5> subagents."
   - OPEN: use the requested model for every chunk; else the plan's `Executor:` line; else implementer's own model (Sonnet). Mechanical chunks may use haiku if your Agent tool has a `model` parameter. Tell the user a short numbered list: chunk → model.
4. When reports return, check risky parts with `git diff`; rerun tests once if a chunk failed or skipped them. Send a failed chunk back with its failure output only.
5. Tell the user in numbered steps: done, passed, left.

A fix of a few lines in one file is cheaper to make here; don't start a subagent for it.
