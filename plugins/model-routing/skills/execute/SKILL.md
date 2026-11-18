---
name: execute
description: Carry out the agreed plan, or whatever is left of the current task, on a chosen model in fresh subagent contexts, so no model re-reads this conversation. Use when the user approves a plan, says to build it, or wants a different model to take over the remaining work.
argument-hint: "[opus | sonnet | haiku]"
---

Carry out the agreed plan, or the remaining steps of the current task, through `model-routing:implementer` subagents instead of editing in this conversation. Requested model: $ARGUMENTS

Which model runs the work:
- If a model is named above, use it for every chunk.
- Otherwise, if the plan has an `Executor:` line, use that model.
- Otherwise use Sonnet, and use `haiku` for purely mechanical chunks (renames, boilerplate, moving code).
Pass the model as the subagent's `model`.

1. Split the work into chunks that can each be done and checked on their own. Chunks that touch different files can run in parallel. Chunks that depend on each other run in order. If work is already partly done, include only what's left, and say what's already done in each brief.
2. For each chunk, write a brief that stands alone: the goal, exact files and line ranges, decisions already made and why, constraints, and the command that proves it works. Don't paste the conversation.
3. Before starting, tell the user in one short numbered list which model takes each chunk. If they want a chunk on a different model, switch it. That costs nothing extra, because every chunk starts fresh.
4. When the reports come back, check the risky parts yourself with `git diff`, and run the tests once if a chunk failed or skipped them. Send a failed chunk back with the failure output, not the whole story.
5. Tell the user, in numbered steps: what was done, what passed, and what's left.

A small fix (a few lines in one file) is cheaper to make right here, so don't start a subagent for it.
