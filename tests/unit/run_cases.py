#!/usr/bin/env python3
"""Unit-test harness for the model-routing plugin (spec §12.1).

    python3 tests/unit/run_cases.py [-v] [name-filter]

Runs every tests/unit/cases/*.json case against `sh scripts/run.sh <script>`
in a throwaway temp dir, then the direct Python tests (test_routing_lib.py).
No network and no Claude. Never touches the real ~/.claude or ~/.claude.json:
each case gets HOME, CLAUDE_CONFIG_DIR and CLAUDE_PROJECT_DIR inside its temp
dir, and a clean environment (nothing inherited apart from PATH and LANG).

Case file: one case object or a list of them.
  name, script, args, stdin (object or raw string), env, launch (file text),
  files {relpath: object|string}, record (object -> data/sessions/4242.json),
  receipts_pre [lines], mtimes {relpath: "$NOW-60"}, fifos [relpath],
  nopy (PATH = bin-nopy), steps [ {stdin, env, args, cwd, expect} ], expect {...},
  cwd (relpath, default "project"), symlinks {relpath: target relpath}, chmod {relpath: "644"},
  dirs [relpath], git_init [relpath].
Values: "$T" in strings -> temp root; "$KEY" -> record key (<host>-4242); "$NOW" / "$NOW-<s>" / "$NOW+<s>" -> epoch int.
Expect keys: exit (default 0), stdout_empty, stdout_contains, stdout_not_contains,
  stdout_startswith, stdout_json (subset), json_absent [dotted paths],
  json_contains {path: str|[str]}, json_not_contains {path: str|[str]},
  json_startswith {path: str}, json_equals {path: value}, record (subset),
  record_unchanged, record_absent, receipts (list of subsets, exact length),
  files_absent, files_exist, glob_exists, glob_absent, file_equals {relpath: text},
  file_json {relpath: subset}, file_json_absent_keys {relpath: [dotted]},
  max_seconds, line_count_min, lines_startwith [[i, prefix]], file_mode {relpath: "644"},
  is_symlink [relpath].
Matching: expected null matches missing or null; "$RECENT" matches an epoch
within 60 s of now; "$ANY" matches anything present.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PLUGIN = os.path.join(REPO, "plugins", "model-routing")
RUN_SH = os.path.join(PLUGIN, "scripts", "run.sh")
PID = "4242"
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.dont_write_bytecode = True
import routing_lib  # noqa: E402  (record files are keyed <host>-<pid>)
KEY = routing_lib.host_tag() + "-" + PID


def subst(v, T, now):
    if isinstance(v, str):
        m = re.fullmatch(r"\$NOW(?:([+-])(\d+))?", v)
        if m:
            off = int(m.group(2) or 0)
            return now + off if m.group(1) == "+" else now - off
        return v.replace("$T", T).replace("$KEY", KEY)
    if isinstance(v, list):
        return [subst(x, T, now) for x in v]
    if isinstance(v, dict):
        return {k: subst(x, T, now) for k, x in v.items()}
    return v


def subset(expected, actual, path="$"):
    """Return None if expected ⊆ actual, else an error string."""
    if expected == "$ANY":
        return None if actual is not None else f"{path}: missing"
    if expected == "$RECENT":
        if isinstance(actual, (int, float)) and abs(time.time() - actual) < 60:
            return None
        return f"{path}: {actual!r} is not a recent timestamp"
    if expected is None:
        return None if actual is None else f"{path}: expected null, got {actual!r}"
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return f"{path}: expected object, got {actual!r}"
        for k, v in expected.items():
            err = subset(v, actual.get(k), f"{path}.{k}")
            if err:
                return err
        return None
    if expected != actual:
        return f"{path}: expected {expected!r}, got {actual!r}"
    return None


def dig(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def make_nopy(T):
    d = os.path.join(T, "bin-nopy")
    os.makedirs(d, exist_ok=True)
    for b in ("sh", "cat", "dirname", "test"):
        src = shutil.which(b)
        if src:
            os.symlink(os.path.realpath(src), os.path.join(d, b))
    return d


def setup_dir(case, now):
    T = tempfile.mkdtemp(prefix="mr-case-", dir=os.environ.get("MR_TMP"))
    for sub in ("data", "config", "project", "managed"):
        os.makedirs(os.path.join(T, sub), exist_ok=True)
    make_nopy(T)
    for rel, content in (case.get("files") or {}).items():
        p = os.path.join(T, subst(rel, T, now))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        content = subst(content, T, now)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(content if isinstance(content, str) else json.dumps(content))
    if "record" in case:
        p = os.path.join(T, "data", "sessions", KEY + ".json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        rec = subst(case["record"], T, now)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(rec if isinstance(rec, str) else json.dumps(rec))
    if "receipts_pre" in case:
        p = os.path.join(T, "data", "receipts", KEY + ".jsonl")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            for line in case["receipts_pre"]:
                fh.write(json.dumps(line) + "\n")
    for rel in case.get("fifos") or []:
        p = os.path.join(T, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.mkfifo(p)
    for rel, target in (case.get("symlinks") or {}).items():
        p = os.path.join(T, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        os.symlink(os.path.join(T, target), p)
    for rel, mode in (case.get("chmod") or {}).items():
        os.chmod(os.path.join(T, rel), int(mode, 8))
    for rel in case.get("dirs") or []:
        os.makedirs(os.path.join(T, rel), exist_ok=True)
    for rel in case.get("git_init") or []:
        subprocess.run(["git", "init", "-q", os.path.join(T, rel)], capture_output=True, timeout=20)
    for rel, when in (case.get("mtimes") or {}).items():
        t = subst(when, T, now)
        os.utime(os.path.join(T, subst(rel, T, now)), (t, t))
    return T


def build_env(T, case, step):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": T,
        "CLAUDE_PLUGIN_ROOT": PLUGIN,
        "CLAUDE_PLUGIN_DATA": os.path.join(T, "data"),
        "CLAUDE_CONFIG_DIR": os.path.join(T, "config"),
        "CLAUDE_PROJECT_DIR": os.path.join(T, "project"),
        "CLAUDE_PID": PID,
        "CLAUDE_CODE_SESSION_ATTENDED": "1",
        "ROUTING_TEST_MANAGED_DIR": os.path.join(T, "managed"),
        # Deterministic: no /proc read unless a case gives a launch file.
        "ROUTING_TEST_LAUNCH_ENV": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if "launch" in case:
        lp = os.path.join(T, "launch.env")
        with open(lp, "w", encoding="utf-8") as fh:
            fh.write(case["launch"])
        env["ROUTING_TEST_LAUNCH_ENV"] = lp
    for src in (case.get("env") or {}, step.get("env") or {}):
        for k, v in src.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = subst(str(v), T, int(time.time()))
    if case.get("nopy") or step.get("nopy"):
        env["PATH"] = os.path.join(T, "bin-nopy")
    return env


def check(expect, proc, out, T, elapsed, before_record):
    errs = []
    if proc.returncode != expect.get("exit", 0):
        errs.append(f"exit {proc.returncode} (stderr: {proc.stderr.strip()[:500]})")
    if expect.get("stdout_empty") and out.strip():
        errs.append(f"stdout not empty: {out.strip()[:500]}")
    for s in expect.get("stdout_contains") or []:
        if s not in out:
            errs.append(f"stdout lacks {s!r}")
    for s in expect.get("stdout_not_contains") or []:
        if s in out:
            errs.append(f"stdout has {s!r}")
    if "stdout_startswith" in expect and not out.startswith(expect["stdout_startswith"]):
        errs.append(f"stdout does not start with {expect['stdout_startswith']!r}")
    jkeys = [k for k in expect if k.startswith("json") or k == "stdout_json"]
    j = None
    if jkeys:
        try:
            j = json.loads(out) if out.strip() else {}
        except ValueError:
            errs.append(f"stdout is not JSON: {out[:300]!r}")
            j = {}
    if "stdout_json" in expect:
        e = subset(expect["stdout_json"], j)
        if e:
            errs.append("stdout_json " + e)
    for p in expect.get("json_absent") or []:
        v, ok = dig(j, p)
        if ok:
            errs.append(f"{p} present: {v!r}")
    for p, subs in (expect.get("json_contains") or {}).items():
        v, ok = dig(j, p)
        for s in [subs] if isinstance(subs, str) else subs:
            if not ok or not isinstance(v, str) or s not in v:
                errs.append(f"{p} lacks {s!r} (got {v!r})")
    for p, subs in (expect.get("json_not_contains") or {}).items():
        v, ok = dig(j, p)
        for s in [subs] if isinstance(subs, str) else subs:
            if ok and isinstance(v, str) and s in v:
                errs.append(f"{p} has {s!r}")
    for p, s in (expect.get("json_startswith") or {}).items():
        v, ok = dig(j, p)
        if not ok or not isinstance(v, str) or not v.startswith(s):
            errs.append(f"{p} does not start with {s!r} (got {v!r})")
    for p, s in (expect.get("json_equals") or {}).items():
        v, ok = dig(j, p)
        if not ok or v != s:
            errs.append(f"{p} != {s!r} (got {v!r})")
    rp = os.path.join(T, "data", "sessions", KEY + ".json")
    if "record" in expect:
        try:
            with open(rp, encoding="utf-8") as fh:
                rec = json.load(fh)
            e = subset(subst(expect["record"], T, int(time.time())), rec)
            if e:
                errs.append("record " + e)
        except (OSError, ValueError) as exc:
            errs.append(f"record unreadable: {exc}")
    if expect.get("record_unchanged"):
        after = open(rp, encoding="utf-8").read() if os.path.exists(rp) else None
        if after != before_record:
            errs.append("record changed")
    if expect.get("record_absent") and os.path.exists(rp):
        errs.append("record exists")
    if "receipts" in expect:
        lines = []
        rcp = os.path.join(T, "data", "receipts", KEY + ".jsonl")
        if os.path.exists(rcp):
            lines = [json.loads(x) for x in open(rcp, encoding="utf-8") if x.strip()]
        if len(lines) != len(expect["receipts"]):
            errs.append(f"receipts: expected {len(expect['receipts'])} lines, got {lines!r}")
        else:
            for i, (e, a) in enumerate(zip(expect["receipts"], lines)):
                err = subset(e, a, f"receipts[{i}]")
                if err:
                    errs.append(err)
    for rel, mode in (expect.get("file_mode") or {}).items():
        try:
            got = oct(os.stat(os.path.join(T, rel)).st_mode & 0o777)
        except OSError as exc:
            got = str(exc)
        if got != oct(int(mode, 8)):
            errs.append(f"{rel} mode {got} != {mode}")
    for rel in expect.get("is_symlink") or []:
        if not os.path.islink(os.path.join(T, rel)):
            errs.append(f"{rel} is not a symlink")
    for rel in expect.get("files_absent") or []:
        if os.path.exists(os.path.join(T, rel)):
            errs.append(f"{rel} exists")
    for rel in expect.get("files_exist") or []:
        if not os.path.exists(os.path.join(T, rel)):
            errs.append(f"{rel} missing")
    for pat in expect.get("glob_exists") or []:
        if not glob.glob(os.path.join(T, pat)):
            errs.append(f"nothing matches {pat}")
    for pat in expect.get("glob_absent") or []:
        if glob.glob(os.path.join(T, pat)):
            errs.append(f"something matches {pat}")
    for rel, text in (expect.get("file_equals") or {}).items():
        try:
            got = open(os.path.join(T, rel), encoding="utf-8").read()
        except OSError as exc:
            got = f"<{exc}>"
        if got != text:
            errs.append(f"{rel} content {got!r} != {text!r}")
    for rel, sub in (expect.get("file_json") or {}).items():
        try:
            got = json.load(open(os.path.join(T, rel), encoding="utf-8"))
            e = subset(sub, got, rel)
            if e:
                errs.append(e)
        except (OSError, ValueError) as exc:
            errs.append(f"{rel}: {exc}")
    for rel, keys in (expect.get("file_json_absent_keys") or {}).items():
        try:
            got = json.load(open(os.path.join(T, rel), encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errs.append(f"{rel}: {exc}")
            continue
        for k in keys:
            if dig(got, k)[1]:
                errs.append(f"{rel} still has {k}")
    if "max_seconds" in expect and elapsed > expect["max_seconds"]:
        errs.append(f"took {elapsed:.2f}s > {expect['max_seconds']}s")
    out_lines = out.rstrip("\n").splitlines()
    if "line_count_min" in expect and len(out_lines) < expect["line_count_min"]:
        errs.append(f"only {len(out_lines)} lines")
    if "line_count" in expect and len(out_lines) != expect["line_count"]:
        errs.append(f"{len(out_lines)} lines, expected {expect['line_count']}")
    for i, prefix in expect.get("lines_startwith") or []:
        if i >= len(out_lines) or not out_lines[i].startswith(prefix):
            errs.append(f"line {i} {out_lines[i] if i < len(out_lines) else None!r} does not start with {prefix!r}")
    return errs


def run_case(case):
    now = int(time.time())
    T = setup_dir(case, now)
    errors = []
    try:
        steps = case.get("steps") or [{"stdin": case.get("stdin"), "args": case.get("args"),
                                       "expect": case.get("expect") or {}}]
        for n, step in enumerate(steps, 1):
            env = build_env(T, case, step)
            stdin = step.get("stdin", case.get("stdin"))
            stdin = subst(stdin, T, now)
            if stdin is None:
                data = ""
            elif isinstance(stdin, str):
                data = stdin
            else:
                data = json.dumps(stdin)
            args = [subst(a, T, now) for a in (step.get("args") or case.get("args") or [])]
            rp = os.path.join(T, "data", "sessions", KEY + ".json")
            before = open(rp, encoding="utf-8").read() if os.path.exists(rp) else None
            sh = os.path.join(T, "bin-nopy", "sh") if (case.get("nopy") or step.get("nopy")) else "sh"
            t0 = time.time()
            try:
                proc = subprocess.run([sh, RUN_SH, step.get("script") or case["script"]] + args,
                                      input=data, capture_output=True, text=True, env=env,
                                      cwd=os.path.join(T, subst(step.get("cwd") or case.get("cwd") or "project", T, now)),
                                      timeout=20)
            except subprocess.TimeoutExpired:
                errors.append(f"step {n}: timed out")
                continue
            elapsed = time.time() - t0
            exp = subst(step.get("expect") or {}, T, now)
            for e in check(exp, proc, proc.stdout, T, elapsed, before):
                errors.append(f"step {n}: {e}" if len(steps) > 1 else e)
            if errors and os.environ.get("MR_VERBOSE"):
                errors.append(f"stdout was: {proc.stdout!r}")
    finally:
        if os.environ.get("MR_KEEP"):
            print(f"  kept {T}")
        else:
            shutil.rmtree(T, ignore_errors=True)
    return errors


def load_cases(flt):
    cases = []
    for p in sorted(glob.glob(os.path.join(HERE, "cases", "*.json"))):
        with open(p, encoding="utf-8") as fh:
            obj = json.load(fh)
        for c in obj if isinstance(obj, list) else [obj]:
            c.setdefault("_file", os.path.basename(p))
            if not flt or flt in c["name"]:
                cases.append(c)
    return cases


def main(argv):
    verbose = "-v" in argv
    if verbose:
        os.environ["MR_VERBOSE"] = "1"
    rest = [a for a in argv[1:] if a != "-v"]
    flt = rest[0] if rest else None
    passed = failed = 0
    failures = []
    for case in load_cases(flt):
        errs = run_case(case)
        if errs:
            failed += 1
            failures.append((case["name"], errs))
            print(f"FAIL {case['name']} ({case['_file']})")
            for e in errs:
                print(f"     {e}")
        else:
            passed += 1
            if verbose:
                print(f"ok   {case['name']}")
    print(f"\nhook cases: {passed} passed, {failed} failed")

    py_rc = 0
    if not flt or flt.startswith(("lib", "sc")):
        r = subprocess.run([sys.executable, os.path.join(HERE, "test_routing_lib.py")] + (["-v"] if verbose else []))
        py_rc = r.returncode
    return 1 if failed or py_rc else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
