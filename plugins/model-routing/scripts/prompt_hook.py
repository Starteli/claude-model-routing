#!/usr/bin/env python3
"""UserPromptSubmit hook: the only place that reports routing changes.

- Re-tells Claude the routing (C1/C2) whenever the state signature changes,
  and on the first prompt after a resume or fork.
- One user line for the two states Claude Code never shows: a mix silently
  dropped by a resume (U10) and a half-on mix (U11, once per event).
- In plan mode: the stand-alone plan note, once per plan-mode entry.

Cheap: one small JSON read and write. Settings, /proc and the mix cache are
read only when FORCE / SUBAGENT_MODEL differ from the stored state.

Config (settings.json "env"): ROUTING_POLICY, ROUTING_EXECUTE, ROUTING_MIX_CACHE.
"""
import os

import routing_lib as rl


DROP_GRACE_S = 30  # a resume switch recorded this soon after a drop explains it


def main():
    data = rl.read_stdin_json()
    if data is None or data.get("agent_id"):
        return
    with rl.record_lock(sid=data.get("session_id")):
        run(data)


def run(data):
    sid = data.get("session_id")
    rec = rl.load_record(sid=sid)
    if rec is None:
        rec = rl.new_record(sid)
    E = os.environ
    prev_state = rec.get("state") if isinstance(rec.get("state"), dict) else None
    prev_origin = prev_state.get("origin") if prev_state else None

    if rl.state_matches_env(prev_state, E):
        st = dict(prev_state)
        st["effort_locked"] = E.get("CLAUDE_CODE_EFFORT_LEVEL") is not None
    else:
        now_locked = rl.truthy(E.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE"))
        was_open = prev_state is None or prev_state.get("mode") != "LOCKED"
        cache = rl.mixcache(rec.get("main_model")) if (now_locked and was_open) else None
        st = rl.detect(E, rl.launch_env(), rl.scan_settings(rl.project_dir(data)), cache, rec.get("main_model"))
        if cache:
            rec["label"] = cache.get("label")
            rec["mix_lead"] = cache.get("lead")
    rl.apply_lead_rules(st, rec, prev_state)
    rec["state"] = st

    s = rl.sig(st, rec)
    ctx, msg = [], None
    if s != rec.get("claude_sig") and os.environ.get("ROUTING_POLICY", "1") != "0":
        ctx.append(rl.notes.note(st, rec))
        rec["claude_sig"] = s

    prev = rec.get("user_sig")
    orphan = rl.is_orphan(st, rec)
    now_locked = st.get("mode") == "LOCKED"
    sw = rec.get("last_switch") if isinstance(rec.get("last_switch"), dict) else None
    if sw and float(sw.get("ts") or 0) < float(rec.get("last_prompt_ts") or 0):
        sw = None
    pending = rec.get("drop_pending")
    rec["drop_pending"] = None
    if prev is not None and s != prev:
        was_locked = str(prev).startswith("LOCKED")
        if was_locked and not now_locked and prev_origin in ("mix", "unknown"):
            if sw and sw.get("source") == "resume":
                msg = rl.lines.U10(sw.get("to"), rec.get("label"))
            elif not sw:
                # PostModelSwitch is async: a resume switch may be recorded just after this prompt.
                rec["drop_pending"] = rl.now()
        elif now_locked and orphan and not rec.get("orphan_told"):
            msg = rl.lines.U11(rec.get("main_model"), st.get("worker"), rec.get("label"), st.get("origin"))
            rec["orphan_told"] = True
        # Every other change: no user line. /model already shows "· <label> on/off".
    elif (pending and not now_locked and sw and sw.get("source") == "resume"
          and abs(float(sw.get("ts") or 0) - float(pending)) <= DROP_GRACE_S):
        msg = rl.lines.U10(sw.get("to"), rec.get("label"))
    if not orphan:
        rec["orphan_told"] = False
    rec["user_sig"] = s

    if data.get("permission_mode") == "plan" and os.environ.get("ROUTING_EXECUTE", "1") != "0":
        if not rec.get("plan_note_given"):
            ctx.append(rl.notes.C8_LOCKED if st.get("mode") == "LOCKED" else rl.notes.C8_OPEN)
            rec["plan_note_given"] = True
    else:
        rec["plan_note_given"] = False

    rec["last_prompt_ts"] = rl.now()
    rl.save_record(rec)
    if not rl.attended():
        msg = None
    rl.emit({
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n\n".join(ctx)},
        "systemMessage": msg,
    })


if __name__ == "__main__":
    rl.safe_main(main)
