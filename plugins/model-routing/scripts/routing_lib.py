"""Shared code for the model-routing hooks and commands (v2).

Every public function catches its own errors and returns a safe default, so a
hook never fails because of this module. Nothing here writes
CLAUDE_CODE_SUBAGENT_* or CLAUDE_CODE_EFFORT_LEVEL, and nothing pins a model.
"""
import contextlib
import glob
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time

TRUTHY = {"1", "true", "yes", "on"}
SUBAGENT_KEYS = ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE")
SCAN_ENV_KEYS = (
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "CLAUDE_CODE_SIMPLE",
)
SCOPES = ("user", "project", "local", "managed")
# Claude Code precedence, highest first: used to name the scope of a match.
PRECEDENCE = ("managed", "local", "project", "user")

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Third-party providers and gateways: no model mix there, and model env vars are often required.
PROVIDER_FLAGS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
# Stamp written by bin/handoff-finalize: "<!-- handoff-source: written ...; session <sid>; ..."
STAMP_SID = re.compile(r"<!-- handoff-source:[^\n]*?;\s*session\s+([^;\s]+)")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def now():
    return int(time.time())


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def read_stdin_json():
    """Hook stdin is UTF-8 JSON; decode it as such on every platform (Windows: cp1252)."""
    try:
        buf = getattr(sys.stdin, "buffer", None)
        raw = buf.read().decode("utf-8", "replace") if buf is not None else sys.stdin.read()
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def utf8_stdout():
    """Claude Code reads hook and `!` output as UTF-8 (Windows defaults to the ANSI page)."""
    try:
        if (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") != "utf8":
            sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def provider_active(E=None):
    """True on Bedrock, Vertex, Foundry or a custom gateway (no model mix there)."""
    try:
        E = os.environ if E is None else E
        return any(truthy(E.get(k)) for k in PROVIDER_FLAGS) or bool((E.get("ANTHROPIC_BASE_URL") or "").strip())
    except Exception:
        return False


def emit(obj):
    """Print a hook JSON object, dropping empty fields. Prints nothing if empty."""
    try:
        utf8_stdout()
        out = {}
        for k, v in obj.items():
            if v is None or v == "" or v == {}:
                continue
            if isinstance(v, dict):
                inner = {ik: iv for ik, iv in v.items() if iv not in (None, "")}
                if set(inner) <= {"hookEventName"}:
                    continue
                v = inner
            out[k] = v
        if out:
            sys.stdout.write(json.dumps(out) + "\n")
    except Exception:
        pass


def truthy(v):
    try:
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in TRUTHY
    except Exception:
        return False


def canon(m):
    try:
        if not m:
            return ""
        return re.sub(r"\[(1|2)m\]$", "", str(m).strip(), flags=re.I).lower()
    except Exception:
        return ""


_SUFFIX = re.compile(r"(-v\d+(:\d+)?|@\d{8}|-\d{8})$")


def display(m):
    """Human name for a model id: claude-opus-5-5 -> Opus 5.5."""
    try:
        if not m:
            return "the main model"
        raw = str(m)
        s = re.sub(r"\[(1|2)m\]$", "", raw.strip(), flags=re.I)
        if s.lower() == "opusplan":
            return "Opus Plan"
        i = s.lower().find("claude-")
        if i > 0:
            s = s[i:]  # bedrock / vertex prefixes
        prefixed = s.lower().startswith("claude-")
        # The spec strips one suffix; ids such as ...-20251001-v1:0 carry two.
        prev = None
        while prev != s:
            prev, s = s, _SUFFIX.sub("", s)
        parts = s.split("-")
        if parts[0].lower() == "claude":
            parts = parts[1:]
        elif len(parts) > 1:
            return raw[:40]  # not a Claude id (gateway model): show as given
        if not parts or not parts[0].isalpha():
            return raw[:40]
        nums = [p for p in parts[1:] if p.isdigit()]
        if not prefixed and not nums and len(parts) == 1:
            return parts[0].capitalize()
        return parts[0].capitalize() + (" " + ".".join(nums) if nums else "")
    except Exception:
        return "the main model"


def alias(m):
    """Short /model argument for an id: claude-sonnet-5 -> sonnet."""
    try:
        d = display(m)
        first = d.split()[0].lower() if d else ""
        return first if first.isalpha() and d != "the main model" else (m or "")
    except Exception:
        return m or ""


def row(label):
    return f'"{label}" row' if label else "the mix row"


def attended():
    try:
        return not (os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0"
                    and os.environ.get("ROUTING_SHOW_HEADLESS") != "1")
    except Exception:
        return True


def fmt_age(minutes):
    if minutes < 90:
        return f"{max(1, round(minutes))} min"
    return f"{minutes / 60:.1f} h"


def priced(usd, pricing):
    return isinstance(usd, (int, float)) and not isinstance(usd, bool) and pricing in ("catalog", "configured")


# --------------------------------------------------------------------------
# files and records
# --------------------------------------------------------------------------

def data_dir(override=None):
    d = override or os.environ.get("CLAUDE_PLUGIN_DATA")
    if not d:
        d = os.path.join(tempfile.gettempdir(), "claude-model-routing")
    return d


def project_dir(data=None, override=None):
    """Project root. Hooks get CLAUDE_PROJECT_DIR; Bash and `!` commands don't (pass --project)."""
    if override and str(override).strip() and "${" not in str(override):
        return str(override)
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return os.environ["CLAUDE_PROJECT_DIR"]
    if (data or {}).get("cwd"):
        return data["cwd"]
    return os.getcwd()


def command_project_dir(arg=None):
    """Project root for a Bash/`!` command: --project, CLAUDE_PROJECT_DIR, git top level, cwd."""
    try:
        if arg and str(arg).strip() and "${" not in str(arg):
            return str(arg)
        if os.environ.get("CLAUDE_PROJECT_DIR"):
            return os.environ["CLAUDE_PROJECT_DIR"]
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, timeout=3)
        top = out.stdout.strip()
        if out.returncode == 0 and top and os.path.isdir(top):
            return top
    except Exception:
        pass
    return os.getcwd()


def host_tag():
    """Short host name: containers sharing one ~/.claude can reuse the same PID."""
    try:
        h = re.sub(r"[^A-Za-z0-9_.-]", "_", socket.gethostname() or "")[:48]
        return h or "host"
    except Exception:
        return "host"


def pid_key(pid=None):
    pid = pid if pid is not None else os.environ.get("CLAUDE_PID")
    return f"{host_tag()}-{pid}" if pid else None


def record_key(pid=None, sid=None):
    k = pid_key(pid)
    if k:
        return k
    if sid:
        return "sid-" + re.sub(r"[^A-Za-z0-9_.-]", "_", str(sid))
    return None


def record_path(pid=None, sid=None, ddir=None):
    key = record_key(pid, sid)
    if not key:
        return None
    return os.path.join(data_dir(ddir), "sessions", key + ".json")


def receipts_path(ddir=None):
    # run.sh's Stop fast path looks for receipts/*-${CLAUDE_PID}.jsonl
    return os.path.join(data_dir(ddir), "receipts", (pid_key() or "none") + ".jsonl")


def compacted_path(session_id, ddir=None):
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(session_id))
    return os.path.join(data_dir(ddir), "compacted", sid)


def new_record(session_id=None):
    t = now()
    return {
        "v": 2, "pid": os.environ.get("CLAUDE_PID"),
        "session_id": session_id, "prev_session_id": None,
        "session_ids": [session_id] if session_id else [],
        "created": t, "updated": t,
        "main_model": None, "lead": None, "lead_hint": None, "state": None, "label": None,
        "mix_lead": None, "drop_pending": None,
        "claude_sig": None, "user_sig": None, "orphan_told": False,
        "last_switch": None, "last_prompt_ts": None,
        "plan_note_given": False, "session_effort": None, "totals": {},
    }


def load_record(pid=None, sid=None, ddir=None):
    try:
        p = record_path(pid, sid, ddir)
        if not p:
            return None
        with open(p, encoding="utf-8") as fh:
            rec = json.load(fh)
        if not isinstance(rec, dict):
            return None
        base = new_record(rec.get("session_id"))
        base.update(rec)
        if not isinstance(base.get("totals"), dict):
            base["totals"] = {}
        if base.get("state") is not None and not isinstance(base.get("state"), dict):
            base["state"] = None
        return base
    except Exception:
        return None


def find_record_by_session(sid, ddir=None):
    try:
        for p in glob.glob(os.path.join(data_dir(ddir), "sessions", "*.json")):
            try:
                with open(p, encoding="utf-8") as fh:
                    rec = json.load(fh)
            except Exception:
                continue
            if isinstance(rec, dict) and (rec.get("session_id") == sid or sid in (rec.get("session_ids") or [])):
                base = new_record(rec.get("session_id"))
                base.update(rec)
                return base
    except Exception:
        pass
    return None


def atomic_write(path, text, keep_file=False):
    """Temp file + os.replace. keep_file: write through a symlink and keep the file's mode."""
    mode = None
    if keep_file:
        path = os.path.realpath(path)
        try:
            mode = stat.S_IMODE(os.stat(path).st_mode)
        except OSError:
            mode = 0o644
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def record_lock(pid=None, sid=None, ddir=None, timeout=2.0):
    """Exclusive lock for one load -> modify -> save of a session record.

    Hooks run concurrently (PostModelSwitch is async), so without it the last
    writer wins. Falls back to no lock (old behaviour) when it can't lock in time.
    """
    fh = None
    try:
        import fcntl  # not on Windows: no lock there
        p = record_path(pid, sid, ddir)
        if p:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            fh = open(p[:-5] + ".lock", "a")
            try:
                os.utime(p[:-5] + ".lock", None)  # keep it clear of the 7-day prune
            except OSError:
                pass
            deadline = time.time() + timeout
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.time() >= deadline:
                        fh.close()
                        fh = None
                        break
                    time.sleep(0.02)
    except Exception:
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass
        fh = None
    try:
        yield
    finally:
        if fh is not None:
            try:
                fh.close()  # closing releases the flock
            except Exception:
                pass


def save_record(rec, pid=None, ddir=None):
    try:
        p = record_path(pid, rec.get("session_id"), ddir)
        if not p:
            return False
        rec["v"] = 2
        rec["updated"] = now()
        atomic_write(p, json.dumps(rec, indent=1, sort_keys=True))
        return True
    except Exception:
        return False


def append_line(path, obj):
    """One write() under 4 KB with O_APPEND, so parallel hooks don't interleave."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = (json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8")
        if len(line) > 4000:
            return False
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
        return True
    except Exception:
        return False


def prune(ddir=None, days=7):
    try:
        cutoff = time.time() - days * 86400
        base = data_dir(ddir)
        for pat in ("sessions/*.json", "sessions/*.lock", "receipts/*.jsonl", "compacted/*",
                    "setup-plan-*.json"):
            for p in glob.glob(os.path.join(base, pat)):
                try:
                    if os.path.getmtime(p) < cutoff:
                        os.unlink(p)
                except OSError:
                    pass
    except Exception:
        pass


def transcript_for_session(sid, pdir=None):
    """Main transcript path of a session (Claude Code's projects/<sanitised cwd>/<sid>.jsonl)."""
    try:
        if not sid or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(sid)):
            return None
        base = os.path.join(config_dir(), "projects")
        if pdir:
            guess = os.path.join(base, re.sub(r"[^a-zA-Z0-9]", "-", str(pdir)), f"{sid}.jsonl")
            if os.path.isfile(guess):
                return guess
        hits = glob.glob(os.path.join(base, "*", f"{sid}.jsonl"))
        return hits[0] if hits else None
    except Exception:
        return None


def handoff_stamp_sid(text):
    m = STAMP_SID.search(text or "")
    return m.group(1) if m else None


def handoff_loads_after_clear(latest, session_id):
    """True when /clear in this session would load LATEST.md in full (same test as session_start)."""
    try:
        if not session_id or not os.path.isfile(latest):
            return False
        age = (time.time() - os.path.getmtime(latest)) / 60
        if age > env_float("ROUTING_HANDOFF_LOAD_MIN", 10):
            return False
        with open(latest, encoding="utf-8", errors="replace") as fh:
            text = fh.read(65536)
        return handoff_stamp_sid(text) == session_id
    except Exception:
        return False


def transcript_model(path, max_bytes=262144):
    """Model of the last main-thread assistant message in a transcript tail, or None.

    Display fallback only (hook inputs in -p carry no model); never stored as main_model.
    """
    try:
        if not path or not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - max_bytes))
            tail = fh.read().decode("utf-8", "replace")
        for line in reversed(tail.splitlines()):
            if '"assistant"' not in line or '"model"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") != "assistant" or obj.get("isSidechain"):
                continue
            m = (obj.get("message") or {}).get("model")
            if isinstance(m, str) and m and not m.startswith("<"):
                return m
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------
# launch env, settings, mix cache
# --------------------------------------------------------------------------

def _parse_env_blob(blob):
    out = {}
    for item in re.split(r"[\0\n]", blob):
        if "=" in item:
            k, v = item.split("=", 1)
            if k:
                out[k] = v
    return out


def launch_env():
    """Env the claude process was launched with (Linux /proc), or None."""
    try:
        if "ROUTING_TEST_LAUNCH_ENV" in os.environ:
            f = os.environ.get("ROUTING_TEST_LAUNCH_ENV")
            if not f:
                return None
            with open(f, encoding="utf-8", errors="replace") as fh:
                return _parse_env_blob(fh.read())
        pid = os.environ.get("CLAUDE_PID")
        if not pid or not sys.platform.startswith("linux"):
            return None
        with open(f"/proc/{pid}/environ", "rb") as fh:
            return _parse_env_blob(fh.read().decode("utf-8", "replace"))
    except Exception:
        return None


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def managed_dir():
    if os.environ.get("ROUTING_TEST_MANAGED_DIR"):
        return os.environ["ROUTING_TEST_MANAGED_DIR"]
    if sys.platform == "darwin":
        return "/Library/Application Support/ClaudeCode"
    if sys.platform.startswith("win"):
        return r"C:\Program Files\ClaudeCode"
    return "/etc/claude-code"


def settings_files(pdir=None):
    """[(scope, path)] in a fixed order: user, project, local, managed."""
    files = [("user", os.path.join(config_dir(), "settings.json"))]
    if pdir:
        files.append(("project", os.path.join(pdir, ".claude", "settings.json")))
        files.append(("local", os.path.join(pdir, ".claude", "settings.local.json")))
    md = managed_dir()
    files.append(("managed", os.path.join(md, "managed-settings.json")))
    try:
        for p in sorted(glob.glob(os.path.join(md, "managed-settings.d", "*.json"))):
            files.append(("managed", p))
    except Exception:
        pass
    seen, out = set(), []
    for scope, p in files:
        try:
            rp = os.path.realpath(p)
        except Exception:
            rp = p
        if rp in seen:
            continue
        seen.add(rp)
        out.append((scope, p))
    return out


def load_json_file(path):
    """(obj, error). obj is None when the file is missing or invalid."""
    try:
        if not os.path.isfile(path):
            return None, None
        if os.path.getsize(path) > 5 * 1024 * 1024:
            return None, "file too large"
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        if not isinstance(obj, dict):
            return None, "not a JSON object"
        return obj, None
    except ValueError as exc:
        return None, str(exc)
    except Exception as exc:
        return None, str(exc) or exc.__class__.__name__


def scan_settings(pdir=None):
    """Entries {scope, path, key, value, managed} or {scope, path, error}."""
    entries = []
    try:
        if pdir is None:
            pdir = project_dir()
        for scope, path in settings_files(pdir):
            obj, err = load_json_file(path)
            managed = scope == "managed"
            if err:
                entries.append({"scope": scope, "path": path, "error": err, "managed": managed})
                continue
            if obj is None:
                continue
            def add(key, value):
                entries.append({"scope": scope, "path": path, "key": key, "value": value, "managed": managed})
            if "model" in obj:
                add("model", obj.get("model"))
            env = obj.get("env")
            if isinstance(env, dict):
                for k, v in env.items():
                    ku = str(k).upper()
                    if ku in SCAN_ENV_KEYS:
                        add("env." + ku, v)
            mp = obj.get("modelPicker")
            if isinstance(mp, dict) and "replaceBuiltInOptions" in mp:
                add("modelPicker.replaceBuiltInOptions", mp.get("replaceBuiltInOptions"))
            if "agent" in obj:
                add("agent", obj.get("agent"))
            if "showClearContextOnPlanAccept" in obj:
                add("showClearContextOnPlanAccept", obj.get("showClearContextOnPlanAccept"))
    except Exception:
        pass
    return entries


def _env_value_matches(key, file_value, live_value):
    if live_value is None:
        return False
    if key.endswith("_FORCE"):
        return truthy(file_value) == truthy(live_value)
    if isinstance(file_value, bool):
        file_value = "true" if file_value else "false"
    return canon(str(file_value)) == canon(str(live_value))


def env_in_effect(entries_for_file, E):
    """True when every SUBAGENT key a file sets equals the live env value."""
    keys = [e for e in entries_for_file if e.get("key", "").replace("env.", "") in SUBAGENT_KEYS]
    if not keys:
        return False
    return all(_env_value_matches(e["key"][4:], e["value"], E.get(e["key"][4:])) for e in keys)


def settings_match_scope(entries, E):
    """Scope of the highest-precedence settings file whose SUBAGENT values match E."""
    try:
        by_file = {}
        for e in entries:
            if "error" in e:
                continue
            if e.get("key", "")[4:] in SUBAGENT_KEYS and e["key"].startswith("env."):
                by_file.setdefault((e["scope"], e["path"]), []).append(e)
        for scope in PRECEDENCE:
            for (s, _p), es in by_file.items():
                if s == scope and env_in_effect(es, E):
                    return scope
    except Exception:
        pass
    return None


def _valid_str(v, maxlen):
    return isinstance(v, str) and 1 <= len(v.strip()) and len(v) <= maxlen


def mixcache(main_model=None):
    """Best-effort read of a cached mix recipe from .claude.json (format unverified)."""
    try:
        if os.environ.get("ROUTING_MIX_CACHE", "1") == "0":
            return None
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            path = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], ".claude.json")
        else:
            path = os.path.join(os.path.expanduser("~"), ".claude.json")
        if not os.path.isfile(path):  # also rules out FIFOs and devices
            return None
        if os.path.getsize(path) > 20 * 1024 * 1024:
            return None
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        slots = obj.get("clientDataCacheSlots") if isinstance(obj, dict) else None
        if not isinstance(slots, dict):
            return None
        valid = []
        for slot in slots.values():
            if not isinstance(slot, dict) or not isinstance(slot.get("data"), dict):
                continue
            h = slot["data"].get("tengu_zesty_horizon")
            if not isinstance(h, dict):
                continue
            lead, worker, label = h.get("lead"), h.get("worker"), h.get("label")
            if not (_valid_str(lead, 100) and _valid_str(worker, 100) and _valid_str(label, 60)):
                continue
            sm = slot.get("model") if isinstance(slot.get("model"), str) else None
            valid.append({"lead": lead, "worker": worker, "label": label, "slot_model": sm})
        if not valid:
            return None
        if main_model:
            for v in valid:
                if canon(v["slot_model"] or v["lead"]) == canon(main_model):
                    return v
        if len(valid) == 1:
            return valid[0]
        return None
    except Exception:
        return None


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------

def live_worker(E):
    w = (E.get("CLAUDE_CODE_SUBAGENT_MODEL") or "").strip() or None
    if w and w.lower() == "inherit":
        w = None  # nPe() treats inherit as unset
    return w


def detect(E, L, S, C, main_model=None):
    """Routing state: LOCKED (FORCE truthy) or OPEN. Origin is a label only."""
    try:
        force_raw = E.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE")
        worker = live_worker(E)
        locked = (force_raw or "").strip().lower() in TRUTHY
        effort_locked = E.get("CLAUDE_CODE_EFFORT_LEVEL") is not None
        if not locked:
            return {"mode": "OPEN", "worker": None, "default_worker": worker,
                    "origin": None, "effort_locked": effort_locked}
        scope = settings_match_scope(S or [], E)
        if L is not None and any(k in L for k in SUBAGENT_KEYS):
            origin = "launch"
        elif scope:
            origin = "settings:" + scope
        elif force_raw.strip() != "1":
            origin = "user"  # the mix always writes exactly "1"
        elif C and worker and canon(C.get("worker")) == canon(worker):
            origin = "mix"
        elif L is not None:
            origin = "mix"  # Linux: not launch, not readable settings
        else:
            origin = "unknown"
        return {"mode": "LOCKED", "worker": worker, "default_worker": None,
                "origin": origin, "effort_locked": effort_locked}
    except Exception:
        return {"mode": "OPEN", "worker": None, "default_worker": None,
                "origin": None, "effort_locked": False}


def state_matches_env(state, E):
    """True when E's FORCE/SUBAGENT_MODEL describe the same state as the record."""
    try:
        if not isinstance(state, dict):
            return False
        mode = "LOCKED" if truthy(E.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE")) else "OPEN"
        if state.get("mode") != mode:
            return False
        rec_worker = state.get("worker") if mode == "LOCKED" else state.get("default_worker")
        return canon(rec_worker) == canon(live_worker(E))
    except Exception:
        return False


def is_orphan(state, rec):
    try:
        return bool(state and state.get("mode") == "LOCKED"
                    and state.get("origin") in ("mix", "unknown")
                    and rec.get("lead") and rec.get("main_model")
                    and canon(rec["main_model"]) != canon(rec["lead"]))
    except Exception:
        return False


def sig(state, rec):
    try:
        w = state.get("worker") or state.get("default_worker") or ""
        return f"{state.get('mode')}|{canon(w)}|{int(is_orphan(state, rec))}|{int(bool(state.get('effort_locked')))}"
    except Exception:
        return None


def apply_lead_rules(state, rec, prev_state=None):
    """§2.3: lead is never taken from a switch target while FORCE stays set."""
    try:
        if state.get("mode") != "LOCKED":
            rec["lead"] = None
            rec["lead_hint"] = None
            return
        prev_mode = prev_state.get("mode") if isinstance(prev_state, dict) else None
        if prev_mode == "OPEN" and rec.get("main_model"):
            rec["lead"] = rec.get("main_model")
            rec["lead_hint"] = None
        elif not rec.get("lead"):
            # main_model may already be a switch target (the model the user moved TO):
            # adopt it only when no switch happened; else use the first switch's `from`.
            if rec.get("lead_hint"):
                rec["lead"] = rec.get("lead_hint")
            elif rec.get("main_model") and not rec.get("last_switch"):
                rec["lead"] = rec.get("main_model")
    except Exception:
        pass


# --------------------------------------------------------------------------
# agent and skill frontmatter
# --------------------------------------------------------------------------

def frontmatter(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if not text.startswith("---"):
            return out
        end = text.find("\n---", 3)
        if end < 0:
            return out
        for line in text[3:end].splitlines():
            if not line or line.startswith((" ", "\t", "#")) or ":" not in line:
                continue
            k, v = line.split(":", 1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k.strip()] = v
    except Exception:
        pass
    return out


def agent_defaults(plugin_root=None):
    """{"model-routing:<name>": {"effort": e, "model": m}} from agents/*.md."""
    root = plugin_root or os.environ.get("CLAUDE_PLUGIN_ROOT") or PLUGIN_ROOT
    out = {}
    try:
        for p in sorted(glob.glob(os.path.join(root, "agents", "*.md"))):
            fm = frontmatter(p)
            name = fm.get("name") or os.path.splitext(os.path.basename(p))[0]
            out["model-routing:" + name] = {"effort": fm.get("effort") or None,
                                            "model": fm.get("model") or None}
        fm = frontmatter(os.path.join(root, "skills", "think", "SKILL.md"))
        out["model-routing:think"] = {"effort": fm.get("effort") or "high", "model": None}
    except Exception:
        pass
    return out


def agent_effort_defaults(plugin_root=None):
    return {k: v.get("effort") for k, v in agent_defaults(plugin_root).items() if v.get("effort")}


def lookup(defaults, name):
    if not name:
        return None
    return defaults.get(name) or defaults.get("model-routing:" + str(name))


# --------------------------------------------------------------------------
# Claude-facing notes (additionalContext): factual statements
# --------------------------------------------------------------------------

class notes:
    MARK = "Current routing (replaces earlier routing notes): "
    EFFORT_LOCKED = "Effort is fixed by CLAUDE_CODE_EFFORT_LEVEL."

    @staticmethod
    def forced_by(origin):
        origin = origin or "unknown"
        if origin == "mix":
            return "the model mix"
        if origin.startswith("settings:"):
            return origin.split(":", 1)[1] + " settings"
        if origin == "launch":
            return "a launch environment setting"
        if origin == "user":
            return "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"
        # unknown: on macOS/Windows a real mix looks exactly like this
        return "CLAUDE_CODE_SUBAGENT_MODEL_FORCE (possibly the model mix)"

    @staticmethod
    def locked(state, rec):
        worker = state.get("worker") or "this session's model"
        effort = (notes.EFFORT_LOCKED if state.get("effort_locked") else
                  "Per-call `effort` still applies, named levels only: low for search or "
                  "mechanical work, high for hard work.")
        text = (notes.MARK + f"subagents run on {worker}, forced by {notes.forced_by(state.get('origin'))}, "
                "so the Agent `model` parameter and agent `model:` fields have no effect. "
                f"{effort} The model-routing:think skill runs a hard question on this session's model.")
        if is_orphan(state, rec):
            m = rec.get("main_model")
            lead_name = "the mix lead" if state.get("origin") == "mix" else "the model the session started on"
            text += (f" The session model ({m}) differs from {lead_name} ({rec.get('lead')}); "
                     f"forks and model-routing:think run on {m}.")
        return text

    @staticmethod
    def open(state, rec):
        effort = notes.EFFORT_LOCKED if state.get("effort_locked") else "Per-call `effort` takes named levels."
        text = (notes.MARK + "subagent models are selectable. model-routing:recall runs on Haiku "
                "(past-session details), model-routing:implementer on Sonnet (settled plans), "
                "model-routing:deep-thinker on Opus (hard design or debugging). "
                f"{effort} Subagents start empty, so briefs carry goal, paths and decisions. "
                "A whole-session model switch costs less right after /compact.")
        if state.get("default_worker"):
            text += f" Subagents without their own model default to {state['default_worker']}."
        return text

    @staticmethod
    def note(state, rec):
        if state.get("mode") == "LOCKED":
            return notes.locked(state, rec)
        return notes.open(state, rec)

    C8_LOCKED = (
        "Plan mode: the approved plan may be all a fresh session sees. Write it to stand alone: "
        "the goal and what done means; decisions with their reasons; exact files and line ranges; "
        "ordered steps, marking which can run in parallel; the command that verifies each step; "
        "known gotchas with exact error strings."
    )
    C8_OPEN = C8_LOCKED + (
        " Start the plan with these two lines, using the model the user asked for, or sonnet if "
        "they didn't say:\n"
        "Executor: sonnet\n"
        "(Whoever runs this plan: if you aren't the executor model, hand the whole "
        "plan to the model-routing:implementer subagent with that model instead of "
        "doing it yourself.)"
    )
    C9_LOCKED = (
        "The plan is approved. Subagents run on the forced model, so carry it out here and hand "
        "only large mechanical chunks to model-routing:implementer with effort low or medium. "
        "Hard questions go to model-routing:think. Small fixes happen directly."
    )
    C9_OPEN = (
        "The plan is approved. Check its Executor line (Sonnet if there is none). If "
        "you are that model, carry the plan out directly, handing only large, purely "
        "mechanical chunks to model-routing:implementer with model: haiku if the Agent tool "
        "offers a model parameter. If you "
        "aren't, follow /execute: hand the chunks to model-routing:implementer "
        "subagents running the executor model, each with a brief that stands alone, "
        "then check the results here. Either way, make small fixes (a few lines) "
        "directly."
    )

    @staticmethod
    def handoff_load(latest, age_min, text):
        return (f"Handoff from the previous session ({latest}, written {fmt_age(age_min)} ago). "
                f"Continue from it; ask the user before redoing anything it marks done. "
                f"Use the recall agent if you need a detail it leaves out.\n\n{text}")

    @staticmethod
    def handoff_pointer(latest, age_min, goal):
        return (f"A handoff from {fmt_age(age_min)} ago is at {latest}"
                + (f" (goal: {goal})" if goal else "")
                + ". Read it only if the user's request continues that work.")


# --------------------------------------------------------------------------
# user-facing lines (systemMessage): one short line each, display names only
# --------------------------------------------------------------------------

class lines:
    @staticmethod
    def U1(lead, worker):
        if lead:
            return f"Model mix on · {display(lead)} leads · {display(worker)} runs subagents"
        return f"Model mix on · {display(worker)} runs subagents"

    @staticmethod
    def U2(worker, scope):
        if scope == "managed":
            return f"Subagents forced to {display(worker)} (set by your admin) · /model-routing:status"
        return f"Subagents forced to {display(worker)} (your {scope} settings) · /model-routing:status"

    @staticmethod
    def U3(worker):
        return f"Subagents forced to {display(worker)} (set at launch) · /model-routing:status"

    @staticmethod
    def U4(worker, main):
        if not worker:
            if main:
                return f"Subagents run on the main model ({display(main)}) · /model-routing:status"
            return "Subagents run on the main model · /model-routing:status"
        if not main:
            return f"Subagents forced to {display(worker)} · /model-routing:status"
        return f"Subagents forced to {display(worker)} · main {display(main)} · /model-routing:status"

    @staticmethod
    def U4b(worker):
        return f"Subagents forced to {display(worker)} (your env setting) · /model-routing:status"

    U5 = "Routing on · recall Haiku · build Sonnet · hard Opus"
    U6 = "Old opusplan pin may block your model mix · Fix: /model-routing:setup"
    U6_managed = "Admin opusplan pin may block your model mix · ask your admin"

    @staticmethod
    def U7(label):
        return f"Model mix didn't load in time · /model → {row(label)} turns it on"

    @staticmethod
    def U17(var, in_settings):
        fix = "fix: /model-routing:setup" if in_settings else "unset it, then restart"
        return f"Model mix blocked by {var} · {fix}"

    U8 = "model-routing is off: Python 3 not found."

    @staticmethod
    def U9(items):
        groups, order = {}, []
        for it in items:
            key = (display(it.get("m")) if it.get("m") else "Main model", it.get("k") == "fork")
            if key not in groups:
                groups[key] = {"n": 0, "e": []}
                order.append(key)
            g = groups[key]
            g["n"] += 1
            e = it.get("e") or "default"
            if e not in g["e"]:
                g["e"].append(e)
        parts = []
        for key in order[:3]:
            g = groups[key]
            parts.append(f"{g['n']}× {key[0]}{' fork' if key[1] else ''} ({'/'.join(g['e'])})")
        if len(order) > 3:
            parts.append(f"+{len(order) - 3} more")
        return "Routed: " + " | ".join(parts)

    @staticmethod
    def U10(to, label):
        return f"Mix off after resume · restore: /model → {row(label)}"

    @staticmethod
    def U11(main, worker, label, origin=None):
        if origin == "mix" or label:
            return f"Mix half-on (main {display(main)}) · fix: /model → {row(label)}"
        # origin unknown and no mix evidence: say only what the env shows
        return f"Main now {display(main)}; subagents still {display(worker)} · /model-routing:status"

    @staticmethod
    def cost(usd, pricing):
        return f" (~${usd:.2f})" if priced(usd, pricing) else ""

    @staticmethod
    def U12(ktok, to, usd, pricing, req, handoff_fresh, leaving_mix, locked, lead, worker,
            label=None, to_mix_row=False, mix_sure=True):
        step1 = "/clear (your handoff reloads)" if handoff_fresh else "/compact"
        step2 = f"/model → {row(label)}" if to_mix_row else f"/model {req}"
        text = (f"Re-sends ~{ktok}K tokens to {display(to)} uncached{lines.cost(usd, pricing)}. "
                f"Cheaper: 1) {step1} 2) {step2}.")
        if leaving_mix:
            verb = "Also leaves the model mix" if mix_sure else "May also leave a model mix"
            text += f" {verb} ({display(lead)} lead · {display(worker)} subagents)."
        if not locked and not to_mix_row:
            text += f" Or: /model-routing:execute {req}."
        return text

    @staticmethod
    def U12_sdk(ktok, to, usd, pricing):
        return (f"Re-sent ~{ktok}K tokens to {display(to)} uncached{lines.cost(usd, pricing)}. "
                f"Next time: 1) /compact 2) switch.")

    @staticmethod
    def U13(to, ktok, usd, pricing):
        return f"Auto-switch to {display(to)} re-sent ~{ktok}K tokens{lines.cost(usd, pricing)} · /compact first"

    @staticmethod
    def U14(lead, worker, label):
        return (f"Leaving {display(lead)} turns the model mix off ({display(worker)} subagents). "
                f"Keep it: /model → {row(label)}.")

    @staticmethod
    def U15(tokens, age_min):
        return f"Loaded handoff (~{tokens:,} tokens) from {fmt_age(age_min)} ago."

    @staticmethod
    def U16(ktok, usd, pricing, locked, label):
        price = f", ~${usd:.2f}" if priced(usd, pricing) else ""
        text = f"Cache expired: switching model now costs nothing extra (~{ktok}K tokens re-sent anyway{price})."
        if locked:
            text += f" Keep the mix: /model → {row(label)}."
        return text


def safe_main(fn):
    """Run a hook main(); never raise, always exit 0."""
    try:
        fn()
    except Exception:
        pass
    sys.exit(0)
