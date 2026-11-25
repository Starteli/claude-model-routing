#!/usr/bin/env python3
"""routing_setup --check | --apply all|1,3  [--data DIR] [--project DIR]

Finds settings that block or weaken the model mix and routing, and fixes the
ones the user picks. Fixes only ever remove keys, apart from turning on
showClearContextOnPlanAccept. It never pins a model and never writes
CLAUDE_CODE_SUBAGENT_* or CLAUDE_CODE_EFFORT_LEVEL. Managed files and files
with invalid JSON are reported, never written. Always exits 0.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

import routing_lib as rl

CANT_CHECK = "Not checked: --settings flags, admin (MDM/server) settings, shell exports."
PLAN_MAX_AGE_S = 3600
SETUP = "/model-routing:setup"


def _scope_name(scope, cap=True):
    s = f"{scope} settings"
    return s[0].upper() + s[1:] if cap else s


def _team(scope, lead=""):
    """'(shared with your team)', or '(<lead>; shared with your team)' when there is a lead note."""
    if scope == "project":
        return f" ({lead + '; ' if lead else ''}shared with your team)"
    return f" ({lead})" if lead else ""


def short_path(path, scope=None, pdir=None):
    """Short, readable path: .claude/settings.json for project files, ~/... for home."""
    try:
        if not path:
            return ""
        if scope in ("project", "local") and pdir:
            rel = os.path.relpath(path, pdir)
            if not rel.startswith(".."):
                return rel
        home = os.path.expanduser("~")
        if home and home != os.sep and path.startswith(home.rstrip(os.sep) + os.sep):
            return "~" + path[len(home.rstrip(os.sep)):]
    except Exception:
        pass
    return path


def _json_where(err):
    m = re.search(r"line (\d+) column (\d+)", err or "")
    return f" at line {m.group(1)}, column {m.group(2)}" if m else ""


def collect(pdir, E, rec):
    """Ordered findings. Each: {check, scope, path, text, short, hint, fix, info, in_all, n?}.

    short/hint feed /model-routing:status; hint is the fix that really works for that item.
    """
    entries = rl.scan_settings(pdir)
    provider = rl.provider_active(E)
    items = []

    def add(check, e, text, short, fix=None, info=False, in_all=True, hint=None):
        scope = e.get("scope") if e else None
        managed = bool(e and e.get("managed"))
        fixable = not (managed or info) and fix is not None
        if hint is None:
            hint = "ask your admin" if managed else (SETUP if fixable else "remove it by hand")
        items.append({"check": check, "scope": scope, "path": e.get("path") if e else None,
                      "text": text, "short": short, "hint": hint,
                      "fix": fix if fixable else None,
                      "info": not fixable, "in_all": in_all})

    def managed_text(what):
        return f"Managed settings set {what}. Ask your admin."

    def provider_text(scope, what):
        return (f"{_scope_name(scope)} set {what}{_team(scope)}. You use a third-party provider or "
                "gateway, where this is often required and no model mix applies. Left as is.")

    good = [e for e in entries if "error" not in e]
    for e in entries:
        if "error" in e:
            where = short_path(e["path"], e["scope"], pdir)
            items.append({"check": 0, "scope": e["scope"], "path": e["path"],
                          "text": f"{_scope_name(e['scope'])} ({where}) is not valid JSON{_json_where(e['error'])}. "
                                  "Fix it by hand; it was not changed.",
                          "short": f"{_scope_name(e['scope'], False)} file is not valid JSON",
                          "hint": "ask your admin" if e.get("managed") else "edit it by hand",
                          "fix": None, "info": True, "in_all": False})

    # 1. opusplan pin
    for e in good:
        if e["key"] == "model" and e["value"] == "opusplan":
            if e["managed"]:
                add(1, e, managed_text('"model": "opusplan"'), "managed opusplan pin")
            else:
                add(1, e, f'{_scope_name(e["scope"])} pin "model": "opusplan"'
                    f'{_team(e["scope"], "left by model-routing v1")}. Sessions start on Sonnet, so an '
                    "Opus-led mix can't apply. Fix: remove it.",
                    f'opusplan pin in {_scope_name(e["scope"], False)}', ("del", ["model"]))
    # 2. any other model pin (not part of "all": it may be deliberate)
    for e in good:
        if e["key"] == "model" and e["value"] != "opusplan":
            if e["managed"]:
                add(2, e, managed_text(f'"model": "{e["value"]}"'), "managed model pin")
            else:
                add(2, e, f'{_scope_name(e["scope"])} pin the model to {rl.display(str(e["value"]))}'
                    f'{_team(e["scope"], chr(34) + "model" + chr(34) + ": " + chr(34) + str(e["value"]) + chr(34))}. '
                    "If /model shows a mix row led by another model, remove it. "
                    "Fix: remove it (only if you pick this number).",
                    None, ("del", ["model"]), in_all=False)
    # 3. SUBAGENT vars in a settings file (one finding per file)
    by_file = {}
    for e in good:
        if e["key"] in ("env.CLAUDE_CODE_SUBAGENT_MODEL", "env.CLAUDE_CODE_SUBAGENT_MODEL_FORCE"):
            by_file.setdefault((e["scope"], e["path"]), []).append(e)
    for (scope, path), es in by_file.items():
        keys = sorted(x["key"][4:] for x in es)
        what = " and ".join(keys)
        in_effect = rl.env_in_effect(es, E)
        if es[0]["managed"]:
            add(3, es[0], managed_text(what), "managed settings force subagents")
        elif provider:
            add(3, es[0], provider_text(scope, what), None, info=True)
        elif in_effect:
            add(3, es[0], f"{_scope_name(scope)} set {what}{_team(scope, 'in effect')}. "
                "This blocks any model mix. Fix: remove it.",
                f"{what} in {_scope_name(scope, False)}", ("del_env", keys))
        else:
            add(3, es[0], f"{_scope_name(scope)} set {what}{_team(scope, 'not in effect this session')}. "
                "It can block any model mix. Fix: remove it.",
                f"{what} in {_scope_name(scope, False)}", ("del_env", keys))
    # 4. ANTHROPIC_MODEL (not part of "all": often deliberate, e.g. a provider model id)
    for e in good:
        if e["key"] == "env.ANTHROPIC_MODEL":
            if e["managed"]:
                add(4, e, managed_text("ANTHROPIC_MODEL"), "managed ANTHROPIC_MODEL")
            elif provider:
                add(4, e, provider_text(e["scope"], "ANTHROPIC_MODEL"), None, info=True)
            else:
                add(4, e, f"{_scope_name(e['scope'])} set ANTHROPIC_MODEL{_team(e['scope'])}. "
                    "It pins the session model, so a mix led by another model can't apply. "
                    "Fix: remove it (only if you pick this number).",
                    f"ANTHROPIC_MODEL in {_scope_name(e['scope'], False)}", ("del_env", ["ANTHROPIC_MODEL"]),
                    in_all=False)
    # 5. CLAUDE_CODE_EFFORT_LEVEL
    for e in good:
        if e["key"] == "env.CLAUDE_CODE_EFFORT_LEVEL":
            if e["managed"]:
                add(5, e, managed_text("CLAUDE_CODE_EFFORT_LEVEL"), "managed CLAUDE_CODE_EFFORT_LEVEL")
            else:
                add(5, e, f"{_scope_name(e['scope'])} set CLAUDE_CODE_EFFORT_LEVEL{_team(e['scope'])}. "
                    "It fixes every effort, so per-subagent effort is ignored. Fix: remove it.",
                    f"CLAUDE_CODE_EFFORT_LEVEL in {_scope_name(e['scope'], False)}",
                    ("del_env", ["CLAUDE_CODE_EFFORT_LEVEL"]))
    # 6. CLAUDE_CODE_SIMPLE (report only)
    for e in good:
        if e["key"] == "env.CLAUDE_CODE_SIMPLE" and rl.truthy(e["value"]):
            add(6, e, f"{_scope_name(e['scope'])} set CLAUDE_CODE_SIMPLE. Simple mode can turn off "
                "this plugin's hooks and skills.", f"CLAUDE_CODE_SIMPLE in {_scope_name(e['scope'], False)}",
                info=True)
    # 7. modelPicker.replaceBuiltInOptions (report only)
    for e in good:
        if e["key"] == "modelPicker.replaceBuiltInOptions" and e["value"] is True:
            add(7, e, f"{_scope_name(e['scope'])} set modelPicker.replaceBuiltInOptions, which hides the mix row.",
                f"modelPicker.replaceBuiltInOptions hides the mix row ({_scope_name(e['scope'], False)})",
                info=True)
    # 8. agent set to a model-routing agent
    for e in good:
        if e["key"] == "agent" and isinstance(e["value"], str) and e["value"].startswith("model-routing:"):
            if e["managed"]:
                add(8, e, managed_text(f'"agent": "{e["value"]}"'), "managed agent setting")
            else:
                add(8, e, f'{_scope_name(e["scope"])} set "agent": "{e["value"]}"{_team(e["scope"])}. '
                    "Starting as an agent turns the model mix off. Fix: remove it.",
                    f'"agent" in {_scope_name(e["scope"], False)}', ("del", ["agent"]))
    # 9. launch-env SUBAGENT vars (from the record)
    st = rec.get("state") if rec and isinstance(rec.get("state"), dict) else None
    if st and st.get("origin") == "launch":
        add(9, None, "CLAUDE_CODE_SUBAGENT_MODEL or _FORCE was set before Claude Code started "
            "(a shell export, or a parent Claude session). Unset it there.",
            "CLAUDE_CODE_SUBAGENT_MODEL* set before launch", info=True,
            hint="unset in shell profile or parent")
    # 10. showClearContextOnPlanAccept in user settings
    user_path = os.path.join(rl.config_dir(), "settings.json")
    user_bad = any("error" in e and e["scope"] == "user" for e in entries)
    user_on = any(e["scope"] == "user" and e["key"] == "showClearContextOnPlanAccept" and e["value"] is True
                  for e in good)
    if not user_bad and not user_on:
        items.append({"check": 10, "scope": "user", "path": user_path,
                      "text": 'Plans don\'t offer "Yes, clear context". Fix: turn on showClearContextOnPlanAccept.',
                      "short": None, "hint": SETUP, "fix": ("set_true", ["showClearContextOnPlanAccept"]),
                      "info": False, "in_all": True})
    # number the fixable ones in check order (stable sort keeps file order)
    items.sort(key=lambda i: i["check"] if i["check"] else 99)
    n = 0
    for i in items:
        if not i["info"] and i["fix"]:
            n += 1
            i["n"] = n
    return items


def blockers(pdir, E, rec):
    """(short, hint) problem pairs for /model-routing:status (checks 1, 3-8 and bad JSON)."""
    out = []
    for i in collect(pdir, E, rec):
        if i["check"] in (2, 9, 10) or not i.get("short"):
            continue
        out.append((i["short"], i.get("hint") or SETUP))
    return out


def find_record(ddir):
    return rl.load_record(ddir=ddir) if os.environ.get("CLAUDE_PID") else None


def print_check(items):
    print("Model routing check")
    numbered = [i for i in items if i.get("n")]
    for i in numbered:
        print(f"{i['n']}. {i['text']}")
    if not numbered:
        print("Nothing to fix.")
    for i in items:
        if not i.get("n"):
            print(f"Info: {i['text'][0].lower() + i['text'][1:] if i['text'].startswith('Managed') else i['text']}")
    print(CANT_CHECK)


def _plan_entries(items):
    return [{"n": i["n"], "check": i["check"], "path": os.path.realpath(i["path"]) if i["path"] else None,
             "fix": [i["fix"][0], list(i["fix"][1])]}
            for i in items if i.get("n")]


def plan_path(ddir):
    return os.path.join(rl.data_dir(ddir), f"setup-plan-{rl.pid_key() or 'none'}.json")


def save_plan(ddir, pdir, items):
    """Remember the numbered list the user saw, so --apply N fixes exactly that item."""
    try:
        rl.atomic_write(plan_path(ddir), json.dumps({"ts": rl.now(), "project": os.path.realpath(pdir),
                                                    "items": _plan_entries(items)}))
    except Exception:
        pass


def plan_matches(ddir, pdir, items):
    """True when there is no recent saved plan, or it lists the same numbered fixes."""
    try:
        with open(plan_path(ddir), encoding="utf-8") as fh:
            plan = json.load(fh)
        if rl.now() - int(plan.get("ts") or 0) > PLAN_MAX_AGE_S:
            return True
    except Exception:
        return True
    return plan.get("project") == os.path.realpath(pdir) and plan.get("items") == _plan_entries(items)


def _backup_name(real, stamp):
    base = f"{real}.bak-{stamp}"
    name, k = base, 1
    while os.path.exists(name):
        k += 1
        name = f"{base}-{k}"
    return name


def apply(items, which, pdir=None, ddir=None):
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true" and os.environ.get("ROUTING_TEST_LOCAL") != "1":
        print("Cloud session: settings here are temporary, so nothing was written. "
              "Add the plugin at claude.ai/customize/plugins.")
        return
    if pdir is not None and not plan_matches(ddir, pdir, items):
        print("Settings changed since the check, so nothing was written. Run /model-routing:setup again.")
        return
    numbered = {i["n"]: i for i in items if i.get("n")}
    if which.strip().lower() == "all":
        chosen = [i for i in numbered.values() if i["in_all"]]
    else:
        chosen = []
        for tok in which.replace(",", " ").split():
            try:
                k = int(tok.strip().rstrip("."))
            except ValueError:
                print(f"Skipped {tok!r}: not a number.")
                continue
            if k in numbered:
                if numbered[k] not in chosen:
                    chosen.append(numbered[k])
            else:
                print(f"Skipped {k}: no fix has that number.")
    if not chosen:
        print("Nothing changed.")
        return
    by_path = {}
    for i in chosen:
        by_path.setdefault(i["path"], []).append(i)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for path, fixes in by_path.items():
        scope = fixes[0].get("scope")
        where = f"{_scope_name(scope, False)} ({short_path(path, scope, pdir)})"
        obj, err = rl.load_json_file(path)
        if err:
            print(f"Skipped {where}: {err}. Nothing written.")
            continue
        exists = obj is not None
        obj = obj if exists else {}
        new = json.loads(json.dumps(obj))
        changes = []
        for i in fixes:
            kind, keys = i["fix"]
            if kind == "del":
                for k in keys:
                    if k in new:
                        del new[k]
                        changes.append(f'Removed "{k}" from {where}')
            elif kind == "del_env":
                env = new.get("env")
                if isinstance(env, dict):
                    for k in list(env):
                        if str(k).upper() in keys:
                            del env[k]
                            changes.append(f"Removed {str(k).upper()} from {where}")
            elif kind == "set_true":
                for k in keys:
                    if new.get(k) is not True:
                        new[k] = True
                        changes.append('Turned on "Yes, clear context" for plans '
                                       f"({_scope_name(scope, False)})"
                                       if k == "showClearContextOnPlanAccept" else f"Set {k}: true in {where}")
        if not changes:
            continue
        try:
            real = os.path.realpath(path)  # a symlinked settings file: change its target, keep the link
            if exists:
                shutil.copy2(real, _backup_name(real, stamp))
            os.makedirs(os.path.dirname(real), exist_ok=True)
            rl.atomic_write(real, json.dumps(new, indent=2) + "\n", keep_file=True)
            for c in changes:
                print(c)
        except OSError as exc:
            print(f"Couldn't write {where}: {exc}")


def main():
    rl.utf8_stdout()
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply")
    ap.add_argument("--data")
    ap.add_argument("--project")
    try:
        args, _ = ap.parse_known_args()
    except SystemExit:
        print("model-routing: setup got arguments it doesn't understand.")
        return
    ddir = args.data if args.data and "${" not in args.data else None
    pdir = rl.command_project_dir(args.project)
    rec = find_record(ddir)
    items = collect(pdir, os.environ, rec)
    if args.apply:
        apply(items, args.apply, pdir, ddir)
    else:
        save_plan(ddir, pdir, items)
        print_check(items)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # never fail a `!` command (it would abort the skill)
        print(f"model-routing: setup check failed ({exc.__class__.__name__}).")
    sys.exit(0)
