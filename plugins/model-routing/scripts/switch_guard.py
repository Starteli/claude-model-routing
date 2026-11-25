#!/usr/bin/env python3
"""PreModelSwitch hook.

A /model switch throws away the current model's prompt cache, so the new model
re-reads the whole conversation uncached. This hook:
  - lets cheap switches through without Claude Code's confirmation prompt;
  - for expensive ones (big context, warm cache) asks first and names the
    cheaper path, and says when the switch also leaves the model mix;
  - with ROUTING_MIX_GUARD=1, also asks on a cheap switch away from the mix lead;
  - never asks in a non-interactive session (CLAUDE_CODE_SESSION_ATTENDED=0),
    where "ask" would be a refusal.

It reads only the small session record: never ~/.claude.json or settings
files, because a hook that times out blocks the switch.

Config (settings.json "env"): ROUTING_ASK_TOKENS (40000), ROUTING_ASK_USD (0.10),
ROUTING_FAST_SWITCH (1), ROUTING_MIX_GUARD (0), ROUTING_HANDOFF_DIR (.handoff).
Any failure exits 0 with no output, so the switch proceeds normally.
"""
import os
import time

import routing_lib as rl


def compacted_recently(session_id, window_min=15):
    if not session_id:
        return False
    try:
        return (time.time() - os.path.getmtime(rl.compacted_path(session_id))) / 60 <= window_min
    except OSError:
        return False


def fresh_handoff(pdir, session_id):
    """True only when /clear would really reload it (same test as session_start)."""
    latest = os.path.join(pdir, os.environ.get("ROUTING_HANDOFF_DIR", ".handoff"), "LATEST.md")
    return rl.handoff_loads_after_clear(latest, session_id)


def ask(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreModelSwitch",
                                   "permissionDecision": "ask",
                                   "permissionDecisionReason": reason}}


def main():
    d = rl.read_stdin_json()
    if d is None:
        return
    frm, to = d.get("from_model"), d.get("to_model")
    if not to or rl.canon(frm) == rl.canon(to):
        return
    rec = rl.load_record(sid=d.get("session_id"))
    E = os.environ
    locked = rl.truthy(E.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE"))
    state = rec.get("state") if rec and isinstance(rec.get("state"), dict) else None
    origin = state.get("origin") if state and state.get("mode") == "LOCKED" else "unknown"
    lead = (rec.get("lead") if rec else None) or frm
    worker = rl.live_worker(E) or (state.get("worker") if state else None)
    label = rec.get("label") if rec else None
    leaving_mix = (locked and origin in ("mix", "unknown")
                   and rl.canon(frm) == rl.canon(lead) and rl.canon(to) != rl.canon(lead))
    # Non-interactive (-p): "ask" is a refusal (F12), so never ask there.
    headless = E.get("CLAUDE_CODE_SESSION_ATTENDED") == "0"

    try:
        ctx = int(d.get("context_tokens") or 0)
    except (TypeError, ValueError):
        ctx = 0
    warm = bool(d.get("prompt_cache_warm"))
    usd, pricing, src = d.get("estimated_cache_write_usd"), d.get("pricing"), d.get("source")
    is_priced = rl.priced(usd, pricing)
    cheap = (ctx < rl.env_float("ROUTING_ASK_TOKENS", 40000)
             or (is_priced and usd < rl.env_float("ROUTING_ASK_USD", 0.10))
             or compacted_recently(d.get("session_id")))

    if cheap or not warm or headless:
        if (os.environ.get("ROUTING_MIX_GUARD") == "1" and leaving_mix and src in ("command", "picker")
                and not headless):
            rl.emit(ask(rl.lines.U14(lead, worker, label)))
        elif os.environ.get("ROUTING_FAST_SWITCH", "1") != "0":
            rl.emit({"hookSpecificOutput": {"hookEventName": "PreModelSwitch",
                                            "permissionDecision": "allow"}})
        return

    ktok = ctx // 1000
    if src == "sdk":
        # "ask" is a refusal on the SDK surface: let it through, say so for next time.
        if rl.attended():
            rl.emit({"systemMessage": rl.lines.U12_sdk(ktok, to, usd, pricing)})
        return
    req = d.get("requested_model") or rl.alias(to)
    has_lead = bool(rec and rec.get("lead"))
    mix_lead = rec.get("mix_lead") if rec else None
    # An inline /model <name> drops the mix (F8): when the target is the mix lead, point at the row.
    back_to_lead = (locked and origin in ("mix", "unknown") and has_lead
                    and rl.canon(to) == rl.canon(lead) and rl.canon(frm) != rl.canon(lead))
    to_mix_row = back_to_lead or (not locked and (
        (label and req == label) or (mix_lead and rl.canon(to) == rl.canon(mix_lead))))
    reason = rl.lines.U12(ktok, to, usd, pricing, req, fresh_handoff(rl.project_dir(d), d.get("session_id")),
                          leaving_mix, locked, lead, worker, label=label, to_mix_row=to_mix_row,
                          mix_sure=(origin == "mix" or bool(label)))
    rl.emit(ask(reason))


if __name__ == "__main__":
    rl.safe_main(main)
