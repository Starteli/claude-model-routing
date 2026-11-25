#!/usr/bin/env python3
"""SessionStart hook (startup | clear | resume | compact | fork).

- startup/clear/compact: tells Claude the current routing (C1 LOCKED / C2 OPEN).
- resume/fork: no routing claim (the mix may be dropped a moment later);
  the next prompt re-tells Claude.
- startup: one user line saying what routes where (U1-U7).
- clear: loads a fresh handoff written by this same session (prev_session_id).
- resume: cold-cache tip.

Config (settings.json "env"): ROUTING_POLICY, ROUTING_QUIET, ROUTING_MIX_CACHE,
ROUTING_HANDOFF_DIR, ROUTING_HANDOFF_LOAD_MIN, ROUTING_ASK_TOKENS.
"""
import os
import time

import routing_lib as rl

U6_EVERY_S = 24 * 3600  # without a cached mix recipe, the opusplan line shows at most daily


def goal_line(text):
    ls = text.splitlines()
    for i, line in enumerate(ls):
        if line.strip().lower().startswith("## goal"):
            for nxt in ls[i + 1:]:
                if nxt.strip():
                    return nxt.strip()[:200]
    for line in ls:
        if line.startswith("# "):
            return line[2:].strip()[:200]
    return ""


def lifecycle(src, sid):
    """§3.3: decide which record this event works on."""
    if src == "startup":
        rl.prune()
        return rl.new_record(sid)
    rec = rl.load_record(sid=sid)
    if src in ("resume", "fork"):
        fresh = rec is not None and (rl.now() - int(rec.get("updated") or 0)) < 12 * 3600
        if not fresh:
            rec = rl.new_record(sid)
        rec["claude_sig"] = None
    elif rec is None:
        rec = rl.new_record(sid)
    if src == "clear":
        if rec.get("session_id") != sid:
            rec["prev_session_id"] = rec.get("session_id")
    if sid and rec.get("session_id") != sid:
        rec["session_id"] = sid
    if sid and sid not in rec["session_ids"]:
        rec["session_ids"] = (rec["session_ids"] + [sid])[-20:]
    return rec


def u6_due(cache):
    """A deliberate opusplan pin on an account without a mix shouldn't nag every launch."""
    if cache:
        return True
    stamp = os.path.join(rl.data_dir(), "u6-shown")
    try:
        if time.time() - os.path.getmtime(stamp) < U6_EVERY_S:
            return False
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w") as fh:
            fh.write(str(rl.now()))
    except OSError:
        pass
    return True


def startup_line(st, rec, entries, cache, model):
    # 1. problem lines, shown even when quiet
    pins = [e for e in entries if e.get("key") == "model" and e.get("value") == "opusplan"]
    if pins and u6_due(cache):
        return rl.lines.U6 if any(not e.get("managed") for e in pins) else rl.lines.U6_managed
    mix_due = (st["mode"] == "OPEN" and cache and model
               and rl.canon(cache.get("lead")) == rl.canon(model))
    set_vars = [k for k in rl.SUBAGENT_KEYS if os.environ.get(k)]
    if mix_due and set_vars:
        # F4: any SUBAGENT var the user set blocks the mix; say which one.
        var = set_vars[0]
        in_settings = any(e.get("key") == "env." + var and not e.get("managed") for e in entries)
        return rl.lines.U17(var, in_settings)
    if mix_due:
        return rl.lines.U7(cache.get("label"))
    # 2. quiet
    if os.environ.get("ROUTING_QUIET") == "1":
        return None
    # 3. LOCKED by origin; 4. OPEN
    if st["mode"] == "LOCKED":
        origin = st.get("origin") or "unknown"
        w = st.get("worker")
        if origin == "mix":
            return rl.lines.U1(rec.get("lead"), w)
        if origin.startswith("settings:"):
            return rl.lines.U2(w, origin.split(":", 1)[1])
        if origin == "launch":
            return rl.lines.U3(w)
        if origin == "user":
            return rl.lines.U4b(w)
        return rl.lines.U4(w, rec.get("main_model"))
    return rl.lines.U5


def main():
    data = rl.read_stdin_json()
    if data is None:
        return
    with rl.record_lock(sid=data.get("session_id")):
        run(data)


def run(data):
    src = data.get("source")
    sid = data.get("session_id")
    rec = lifecycle(src, sid)
    model = data.get("model") if isinstance(data.get("model"), str) and data.get("model") else None
    if model:
        rec["main_model"] = model

    E = os.environ
    pdir = rl.project_dir(data)
    entries = rl.scan_settings(pdir)
    cache = rl.mixcache(rec.get("main_model")) if src == "startup" else None
    st = rl.detect(E, rl.launch_env(), entries, cache, rec.get("main_model"))
    if src == "startup" and st["mode"] == "LOCKED" and model:
        rec["lead"] = model
    if st["mode"] == "OPEN":
        rec["lead"] = None
    if cache:
        rec["label"] = cache.get("label")
        rec["mix_lead"] = cache.get("lead")
    rec["state"] = st

    ctx, msg = [], None
    if src in ("startup", "clear", "compact") and os.environ.get("ROUTING_POLICY", "1") != "0":
        ctx.append(rl.notes.note(st, rec))
        rec["claude_sig"] = rl.sig(st, rec)
    if src in ("resume", "fork"):
        rec["claude_sig"] = None

    if src == "startup":
        rec["user_sig"] = rl.sig(st, rec)
        msg = startup_line(st, rec, entries, cache, model)

    # Handoff: load in full only after /clear in the session that wrote it.
    latest = os.path.join(pdir, os.environ.get("ROUTING_HANDOFF_DIR", ".handoff"), "LATEST.md")
    if src in ("startup", "clear") and os.path.isfile(latest):
        try:
            age = (time.time() - os.path.getmtime(latest)) / 60
            with open(latest, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            stamp_sid = rl.handoff_stamp_sid(text)
            load_min = rl.env_float("ROUTING_HANDOFF_LOAD_MIN", 10)
            if (src == "clear" and stamp_sid and stamp_sid == rec.get("prev_session_id")
                    and age <= load_min):
                ctx.append(rl.notes.handoff_load(latest, age, text))
                msg = rl.lines.U15(len(text) // 4, age)
            elif age <= 24 * 60:
                ctx.append(rl.notes.handoff_pointer(latest, age, goal_line(text)))
        except Exception:
            pass

    if src == "resume":
        try:
            ktok = int(data.get("context_tokens") or 0)
        except (TypeError, ValueError):
            ktok = 0
        if data.get("prompt_cache_likely_expired") and ktok >= rl.env_float("ROUTING_ASK_TOKENS", 40000):
            msg = rl.lines.U16(ktok // 1000, data.get("estimated_cache_write_usd"), data.get("pricing"),
                               st["mode"] == "LOCKED", rec.get("label"))

    if not rl.attended():
        msg = None
    rl.save_record(rec)
    rl.emit({
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n\n".join(ctx)},
        "systemMessage": msg,
    })


if __name__ == "__main__":
    rl.safe_main(main)
