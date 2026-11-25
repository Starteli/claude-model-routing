---
name: escalate
description: Get a stronger answer to one hard question without switching this session's model.
argument-hint: "<the question> [with fable]"
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_status *)
---
!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_status --brief --data "${CLAUDE_PLUGIN_DATA}" --project "${CLAUDE_PROJECT_DIR}" || true`

Question: $ARGUMENTS

Write a brief that stands alone, under 400 words: the goal and exact question; file paths with line numbers; what was tried or ruled out, with evidence; settled constraints; the answer shape needed. No pasted history or long code.

Then, by the routing line above:
1. LOCKED: call the Skill tool with `model-routing:think` and the brief as its argument. It runs on this session's model at high effort; no Agent subagent can reach a stronger model here. If the user asked for fable, first tell them in one line: "Subagents are forced, so this runs on <main model's short name> at high effort."
2. OPEN: start the `model-routing:deep-thinker` subagent with the brief; its definition runs it on Opus. If the user asked for fable and your Agent tool has a `model` parameter, pass `model: fable`.

When it returns: give its recommendation in three lines or fewer, then say whether you agree and why.
