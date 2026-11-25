#!/usr/bin/env python3
"""PostToolUse hook (Agent | Skill): notes each subagent run for the Stop receipt.

Appends one line per run to receipts/<CLAUDE_PID>.jsonl:
  {"p": prompt_id, "m": model, "e": requested effort, "k": fg|bg|fork, "a": agent}
Effort is the requested level (tool_input.effort, else the plugin's frontmatter
default, else null). CLAUDE_CODE_EFFORT_LEVEL overrides both (F6), so when it is
set the receipt shows that level. No output.

Without CLAUDE_PLUGIN_DATA nothing is written: run.sh's Stop fast path only
looks there, so lines written elsewhere would never be shown or cleaned up.
"""
import os

import routing_lib as rl

LEVELS = ("low", "medium", "high", "xhigh", "max")


def env_effort():
    """(set, level) for CLAUDE_CODE_EFFORT_LEVEL; level None = model default (auto/unset)."""
    v = os.environ.get("CLAUDE_CODE_EFFORT_LEVEL")
    if v is None:
        return False, None
    v = v.strip().lower()
    return True, (v if v in LEVELS else None)


def guess_model(agent, defaults):
    """Model when the hook input names none (fallback; P5 normally gives resolvedModel)."""
    E = os.environ
    if rl.truthy(E.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE")):
        return rl.live_worker(E)  # None = runs on the main model
    fm = rl.lookup(defaults, agent) or {}
    m = fm.get("model")
    if m and m != "inherit":
        return m
    return rl.live_worker(E)


def main():
    d = rl.read_stdin_json()
    if d is None or not os.environ.get("CLAUDE_PLUGIN_DATA"):
        return
    tr = d.get("tool_response") if isinstance(d.get("tool_response"), dict) else {}
    ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
    defaults = rl.agent_defaults()
    name = d.get("tool_name")
    if name in ("Agent", "Task"):
        agent = ti.get("subagent_type") or "general-purpose"
        model = tr.get("resolvedModel") or ti.get("model") or guess_model(agent, defaults)
        effort = ti.get("effort") or (rl.lookup(defaults, agent) or {}).get("effort") or None
        kind = "bg" if tr.get("status") == "async_launched" else "fg"
    elif name == "Skill" and tr.get("status") == "forked":
        rec = rl.load_record(sid=d.get("session_id"))
        model = rec.get("main_model") if rec else None
        agent = ti.get("skill")
        effort = (rl.lookup(defaults, agent) or {}).get("effort") or None
        kind = "fork"
    else:
        return
    forced, level = env_effort()
    if forced:
        effort = level
    rl.append_line(rl.receipts_path(), {"p": d.get("prompt_id"), "m": model, "e": effort,
                                         "k": kind, "a": agent})


if __name__ == "__main__":
    rl.safe_main(main)
