#!/usr/bin/env python3
"""routing_status --data DIR --session SID [--project DIR] [--brief]

Prints this session's routing state for /model-routing:status, or one line
(--brief) for the execute and escalate skills. Always exits 0: a failed `!`
command would abort the skill.
"""
import argparse
import os
import sys

import routing_lib as rl
import routing_setup


def current_state(rec, E, pdir):
    """Live env first; if it shows no SUBAGENT vars, trust the record (Bash env may be scrubbed)."""
    st = rec.get("state") if rec and isinstance(rec.get("state"), dict) else None
    has_vars = any(E.get(k) is not None for k in rl.SUBAGENT_KEYS)
    if st and not has_vars:
        return st
    if st and rl.state_matches_env(st, E):
        st = dict(st)
        st["effort_locked"] = E.get("CLAUDE_CODE_EFFORT_LEVEL") is not None or bool(st.get("effort_locked"))
        return st
    main_model = rec.get("main_model") if rec else None
    return rl.detect(E, rl.launch_env(), rl.scan_settings(pdir), rl.mixcache(main_model), main_model)


def runs_line(totals):
    groups, order = {}, []
    for key, n in (totals or {}).items():
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        fork = key.startswith("fork:")
        name = rl.display(key[5:] if fork else key) + (" fork" if fork else "")
        if name not in groups:
            groups[name] = 0
            order.append(name)
        groups[name] += n
    total = sum(groups.values())
    if not total:
        return "This session: no subagent runs yet"
    order.sort(key=lambda k: -groups[k])
    parts = [f"{groups[k]}× {k}" for k in order[:3]]
    if len(order) > 3:
        parts.append(f"+{len(order) - 3} more")
    return f"This session: {total} run{'s' if total != 1 else ''} · " + " · ".join(parts)


def full(rec, st, E, pdir, sid=None):
    label = rec.get("label") if rec else None
    main = rec.get("main_model") if rec else None
    lead = rec.get("lead") if rec else None
    origin = st.get("origin") or "unknown"
    orphan = rl.is_orphan(st, rec or {})
    out = ["Model routing"]

    if st.get("mode") == "LOCKED":
        w = rl.display(st.get("worker"))
        if origin == "mix":
            by = "by the model mix" + (f' ("{label}")' if label else "")
        elif origin == "settings:managed":
            by = "set by your admin"
        elif origin.startswith("settings:"):
            by = f"by your {origin.split(':', 1)[1]} settings"
        elif origin == "launch":
            by = "set at launch"
        elif origin == "user":
            by = "by your env setting"
        else:
            by = "source unknown (model mix or an env setting)"
        out.append(f"1. Subagents: forced to {w} · {by}")
    else:
        line = "1. Subagents: picked per task · recall Haiku · build Sonnet · hard Opus"
        if st.get("default_worker"):
            line += f" · others {rl.display(st.get('default_worker'))}"
        out.append(line)

    if orphan:
        lead_name = "mix lead is" if origin == "mix" or label else "started on"
        out.append(f"2. Main model: {rl.display(main)} · {lead_name} {rl.display(lead)} (subagents still forced)")
    else:
        if not main and sid:
            # -p and some starts give hooks no model: show the transcript's (display only).
            main = rl.transcript_model(rl.transcript_for_session(sid, pdir))
        line = f"2. Main model: {rl.display(main) if main else 'not seen yet'}"
        if (st.get("mode") == "LOCKED" and origin == "mix" and lead and main
                and rl.canon(lead) == rl.canon(main)):
            line += " (mix lead)"
        if E.get("CLAUDE_CODE_EFFORT_LEVEL"):
            line += f" · effort fixed at {E.get('CLAUDE_CODE_EFFORT_LEVEL')}"
        elif rec and rec.get("session_effort"):
            line += f" · effort {rec.get('session_effort')}"
        out.append(line)

    out.append("3. " + runs_line(rec.get("totals") if rec else None))

    problems = []
    if rec is None:
        problems.append("no hook data yet: hooks may not be running · fix: restart Claude Code "
                        "(Windows needs Git Bash)")
    if orphan:
        if origin == "mix" or label:
            problems.append(f"mix half-on: main {rl.display(main)}, subagents still {rl.display(st.get('worker'))}"
                            f" · fix: /model → {rl.row(label)}")
        else:
            problems.append(f"main changed to {rl.display(main)}, subagents still {rl.display(st.get('worker'))}"
                            " · if a model mix: /model → its row")
    try:
        found = routing_setup.blockers(pdir, E, rec)
    except Exception:
        found = []
    if st.get("effort_locked"):
        effort_items = [b for b in found if "CLAUDE_CODE_EFFORT_LEVEL" in b[0]]
        hint = effort_items[0][1] if effort_items else "unset it in your shell"
        problems.append(f"CLAUDE_CODE_EFFORT_LEVEL fixes every effort · "
                        + (hint if hint == "ask your admin" else f"fix: {hint}"))
    if st.get("mode") == "LOCKED" and origin == "launch":
        problems.append("CLAUDE_CODE_SUBAGENT_MODEL* set before launch · fix: unset in shell profile or parent")
    if st.get("mode") == "OPEN" and any(E.get(k) for k in rl.SUBAGENT_KEYS):
        var = next(k for k in rl.SUBAGENT_KEYS if E.get(k))
        if not any(var in b[0] for b in found):
            problems.append(f"{var} blocks a model mix · fix: unset it in your shell")
    for short, hint in found:
        if "CLAUDE_CODE_EFFORT_LEVEL" in short and st.get("effort_locked"):
            continue
        problems.append(f"{short} · {hint}" if hint == "ask your admin" else f"{short} · fix: {hint}")
    if problems:
        out.append("4. Problems:")
        out.extend(f"   - {p}" for p in problems)
    else:
        out.append("4. Problems: none")
    out.append("Commands: /model-routing:escalate · execute · handoff · setup")
    return "\n".join(out)


def brief(rec, st):
    if st.get("mode") == "LOCKED":
        w = st.get("worker")
        wtxt = f"{w} ({rl.display(w)})" if w else "this session's model"
        m = rec.get("main_model") if rec else None
        mtxt = f"{m} ({rl.display(m)})" if m else "unknown"
        return f"Routing: LOCKED · subagents forced to {wtxt} · main {mtxt}"
    return "Routing: OPEN"


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--data")
    ap.add_argument("--session")
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--project")
    args, _ = ap.parse_known_args()
    rl.utf8_stdout()
    E = os.environ
    ddir = args.data if args.data and "${" not in args.data else None
    sid = args.session if args.session and "${" not in args.session else None
    pdir = rl.command_project_dir(args.project)
    rec = rl.load_record(ddir=ddir) if E.get("CLAUDE_PID") else None
    if rec is None and sid:
        rec = rl.find_record_by_session(sid, ddir)
    st = current_state(rec, E, pdir)
    print(brief(rec, st) if args.brief else full(rec, st, E, pdir, sid or (rec or {}).get("session_id")))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"model-routing: status failed ({exc.__class__.__name__}).")
    sys.exit(0)
