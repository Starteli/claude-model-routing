---
name: status
description: Show this session's model routing state.
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_status *)
---
!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_status --data "${CLAUDE_PLUGIN_DATA}" --session "${CLAUDE_SESSION_ID}" --project "${CLAUDE_PROJECT_DIR}" || true`

Reply with every line of the block above, from "Model routing" through "Commands:", exactly as written. Add nothing.
