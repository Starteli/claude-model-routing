#!/usr/bin/env python3
"""PostModelSwitch hook.

Records the switch (main model, source, time) for prompt_hook, which decides
the routing state at the next prompt. It never changes the mix lead.

Switches Claude Code makes by itself (source "auto") can't be stopped
beforehand, so a big one gets one line saying what it cost.

Config (settings.json "env"): ROUTING_ASK_TOKENS (40000), ROUTING_ASK_USD (0.10).
"""
import os

import routing_lib as rl


def main():
    d = rl.read_stdin_json()
    if d is None:
        return
    with rl.record_lock(sid=d.get("session_id")):
        rec = rl.load_record(sid=d.get("session_id")) or rl.new_record(d.get("session_id"))
        st = rec.get("state") if isinstance(rec.get("state"), dict) else None
        if (not rec.get("lead") and not rec.get("lead_hint") and not rec.get("last_switch")
                and d.get("from_model") and st and st.get("mode") == "LOCKED"
                and rl.truthy(os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE"))):
            # Lead unknown (SessionStart had no model): the first switch starts from it.
            # The target is never the lead while FORCE stays set (§2.3).
            rec["lead_hint"] = d.get("from_model")
        if d.get("to_model"):
            rec["main_model"] = d.get("to_model")
        rec["last_switch"] = {"source": d.get("source"), "from": d.get("from_model"),
                              "to": d.get("to_model"), "ts": rl.now()}
        rl.save_record(rec)

    if d.get("source") != "auto" or rl.canon(d.get("from_model")) == rl.canon(d.get("to_model")):
        return
    if not d.get("prompt_cache_warm") or not rl.attended():
        return
    try:
        ctx = int(d.get("context_tokens") or 0)
    except (TypeError, ValueError):
        return
    usd, pricing = d.get("estimated_cache_write_usd"), d.get("pricing")
    if ctx < rl.env_float("ROUTING_ASK_TOKENS", 40000):
        return
    if rl.priced(usd, pricing) and usd < rl.env_float("ROUTING_ASK_USD", 0.10):
        return
    rl.emit({"systemMessage": rl.lines.U13(d.get("to_model"), ctx // 1000, usd, pricing)})


if __name__ == "__main__":
    rl.safe_main(main)
