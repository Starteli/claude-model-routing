#!/usr/bin/env python3
"""SessionStart hook (startup | clear | resume | compact).

  - startup/clear/compact: adds a short routing note so Claude delegates to
    other models through subagents instead of suggesting /model. (Compaction
    drops earlier context, so the note is added again.)
  - clear: if a handoff was written in the last 10 minutes, loads it in full.
    This is the second half of the /handoff -> /clear flow.
  - startup/clear with an older handoff (< 24h): adds a one-line pointer only.
  - resume: if the cache has expired on a big conversation, says that switching
    models right now costs nothing extra.

Config (settings.json "env"):
  ROUTING_POLICY            0 = don't add the routing note (default 1)
  ROUTING_HANDOFF_DIR       default .handoff
  ROUTING_HANDOFF_LOAD_MIN  load the full handoff after /clear if younger than this (default 10)
  ROUTING_ASK_TOKENS        resume tip threshold (default 40000)
"""
import json
import os
import sys
import time
from pathlib import Path

POLICY = (
    "Model routing: a /model switch makes the new model re-read this whole "
    "conversation uncached, so route work to other models through subagents "
    "instead. Codebase search goes to Explore. Details from earlier sessions go "
    "to model-routing:recall. A settled implementation goes to "
    "model-routing:implementer, on the model the user picks (Sonnet by default). "
    "A hard design or debugging question on a smaller model goes to "
    "model-routing:deep-thinker (Opus). Subagents start empty, so brief them with "
    "the goal, file paths and decisions, never the history. If an approved plan "
    "names an Executor model that isn't you, hand the plan to "
    "model-routing:implementer with that model. If the user wants a different "
    "model to take over a task midway, use /execute <model> rather than /model. "
    "If they want a different model for the whole conversation, tell them to run "
    "/compact first, then /model <name>. For a bigger build, suggest plan mode."
)


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def fmt_age(minutes):
    if minutes < 90:
        return f"{max(1, round(minutes))} min"
    return f"{minutes / 60:.1f} h"


def goal_line(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## goal"):
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()[:200]
    for line in lines:
        if line.startswith("# "):
            return line[2:].strip()[:200]
    return ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    source = data.get("source")
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    handoff_dir = os.environ.get("ROUTING_HANDOFF_DIR", ".handoff")
    latest = Path(project_dir) / handoff_dir / "LATEST.md"

    context = []
    notice = None

    if source in ("startup", "clear", "compact") and os.environ.get("ROUTING_POLICY", "1") != "0":
        context.append(POLICY)

    if source in ("startup", "clear") and latest.is_file():
        age = (time.time() - latest.stat().st_mtime) / 60
        # Short window: /handoff -> /clear happens within minutes. A longer one
        # would leak an old handoff into unrelated fresh sessions, such as the
        # one that "Yes, clear context" starts for an approved plan.
        load_min = env_float("ROUTING_HANDOFF_LOAD_MIN", 10)
        text = latest.read_text(encoding="utf-8", errors="replace")
        if source == "clear" and age <= load_min:
            context.append(
                f"Handoff from the previous session ({latest}, written {fmt_age(age)} ago). "
                f"Continue from it; ask the user before redoing anything it marks done. "
                f"Use the recall agent if you need a detail it leaves out.\n\n{text}"
            )
            notice = f"Loaded handoff ({len(text) // 4:,} tokens est.) written {fmt_age(age)} ago."
        elif age <= 24 * 60:
            goal = goal_line(text)
            context.append(
                f"A handoff from {fmt_age(age)} ago is at {latest}"
                + (f" (goal: {goal})" if goal else "")
                + ". Read it only if the user's request continues that work."
            )

    if source == "resume":
        ctx = int(data.get("context_tokens") or 0)
        if data.get("prompt_cache_likely_expired") and ctx >= env_float("ROUTING_ASK_TOKENS", 40000):
            usd = data.get("estimated_cache_write_usd")
            cost = f" (about ${usd:.2f})" if isinstance(usd, (int, float)) else ""
            notice = (
                f"The cache expired, so your next message re-sends ~{ctx // 1000}K tokens"
                f"{cost} whichever model you use. If you want a different model, "
                f"switch now: it costs no more than staying."
            )

    out = {}
    if context:
        out["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(context),
        }
    if notice:
        out["systemMessage"] = notice
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
