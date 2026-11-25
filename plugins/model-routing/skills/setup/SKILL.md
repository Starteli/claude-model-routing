---
name: setup
description: Check settings that block or weaken the model mix and routing, and fix the ones you pick.
argument-hint: "[all]"
disable-model-invocation: true
allowed-tools: Bash(sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_setup *)
---
!`sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_setup --check --data "${CLAUDE_PLUGIN_DATA}" --project "${CLAUDE_PROJECT_DIR}" || true`

1. Show the user the check above exactly.
2. If it lists fixes: when the argument is "all", run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" routing_setup --apply all --data "${CLAUDE_PLUGIN_DATA}" --project "${CLAUDE_PROJECT_DIR}"`. Otherwise ask exactly: "Which to fix? Reply with numbers (e.g. 1 3) or all." Then run the same command with `--apply <numbers, comma-separated>`.
3. Show its output exactly. If it has a line starting "Removed" or "Turned on", add one line: "Takes effect in new sessions."
