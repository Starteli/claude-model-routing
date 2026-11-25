#!/usr/bin/env python3
"""Direct Python tests: routing_lib (lib-1..lib-7) and static checks (sc-1..sc-3)."""
import glob
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PLUGIN = os.path.join(REPO, "plugins", "model-routing")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.dont_write_bytecode = True

import routing_lib as rl  # noqa: E402


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def load(p):
    return json.loads(read(p))

CACHE = {"clientDataCacheSlots": {"a": {"data": {"tengu_zesty_horizon": {
    "lead": "claude-opus-5-5", "worker": "claude-sonnet-5", "label": "Opus + Sonnet"}},
    "model": "claude-opus-5-5"}}}


class EnvCase(unittest.TestCase):
    """Isolates os.environ and a temp dir per test."""

    def setUp(self):
        self._env = dict(os.environ)
        self.T = tempfile.mkdtemp(prefix="mr-lib-")
        for k in list(os.environ):
            if k.startswith(("CLAUDE_", "ROUTING_", "ANTHROPIC_")):
                del os.environ[k]
        os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(self.T, "config")
        os.environ["HOME"] = self.T
        os.makedirs(os.environ["CLAUDE_CONFIG_DIR"])

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.T, ignore_errors=True)

    def write_cache(self, text):
        with open(os.path.join(self.T, "config", ".claude.json"), "w") as fh:
            fh.write(text)


class Lib(EnvCase):
    def test_lib1_truthy(self):
        for v in ("1", "TRUE", " yes ", "on"):
            self.assertTrue(rl.truthy(v), v)
        for v in ("0", "false", "", "2", None):
            self.assertFalse(rl.truthy(v), v)

    def test_lib2_display(self):
        table = {
            "claude-opus-5-5": "Opus 5.5",
            "claude-sonnet-4-5-20250929": "Sonnet 4.5",
            "claude-opus-5[1m]": "Opus 5",
            "haiku": "Haiku",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0": "Haiku 4.5",
            "my-gw-model": "my-gw-model",
        }
        for k, v in table.items():
            self.assertEqual(rl.display(k), v, k)
        self.assertEqual(rl.display(None), "the main model")
        self.assertEqual(rl.display("opusplan"), "Opus Plan")

    def test_lib3_canon(self):
        self.assertEqual(rl.canon("claude-opus-5[1m]"), rl.canon("CLAUDE-OPUS-5"))

    def test_lib4_detect_inherit(self):
        st = rl.detect({"CLAUDE_CODE_SUBAGENT_MODEL": "inherit", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"},
                       None, [], None, None)
        self.assertEqual(st["mode"], "LOCKED")
        self.assertIsNone(st["worker"])

    def test_lib5_detect_force0(self):
        st = rl.detect({"CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "0", "CLAUDE_CODE_SUBAGENT_MODEL": "x"},
                       None, [], None, None)
        self.assertEqual(st["mode"], "OPEN")
        self.assertEqual(st["default_worker"], "x")

    def test_lib6_mixcache_valid(self):
        self.write_cache(json.dumps(CACHE))
        c = rl.mixcache("claude-opus-5-5")
        self.assertIsInstance(c, dict)
        self.assertEqual(c["label"], "Opus + Sonnet")
        self.assertEqual(c["worker"], "claude-sonnet-5")
        os.environ["ROUTING_MIX_CACHE"] = "0"
        self.assertIsNone(rl.mixcache("claude-opus-5-5"))

    def test_lib7_mixcache_invalid(self):
        self.write_cache(json.dumps({"clientDataCacheSlots": [1, 2]}))
        self.assertIsNone(rl.mixcache("claude-opus-5-5"))
        self.write_cache(json.dumps(CACHE)[:-7])  # truncated JSON
        self.assertIsNone(rl.mixcache("claude-opus-5-5"))
        big = json.dumps(CACHE)[:-1] + ', "pad": "' + "x" * (25 * 1024 * 1024) + '"}'
        self.write_cache(big)  # valid JSON but 25 MB
        self.assertIsNone(rl.mixcache("claude-opus-5-5"))
        bad = json.loads(json.dumps(CACHE))
        bad["clientDataCacheSlots"]["a"]["data"]["tengu_zesty_horizon"]["label"] = "x" * 61
        self.write_cache(json.dumps(bad))
        self.assertIsNone(rl.mixcache("claude-opus-5-5"))

    def test_detect_origins(self):
        E = {"CLAUDE_CODE_SUBAGENT_MODEL": "claude-sonnet-5", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"}
        self.assertEqual(rl.detect(E, {}, [], None, None)["origin"], "mix")
        self.assertEqual(rl.detect(E, None, [], None, None)["origin"], "unknown")
        self.assertEqual(rl.detect(E, {"CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"}, [], None, None)["origin"], "launch")
        self.assertEqual(rl.detect(E, None, [], {"worker": "claude-sonnet-5"}, None)["origin"], "mix")
        S = [{"scope": "local", "path": "x", "key": "env.CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "value": True,
              "managed": False}]
        self.assertEqual(rl.detect(E, None, S, None, None)["origin"], "settings:local")
        S2 = [{"scope": "user", "path": "y", "key": "env.CLAUDE_CODE_SUBAGENT_MODEL", "value": "haiku",
               "managed": False}]
        self.assertEqual(rl.detect(E, None, S2, None, None)["origin"], "unknown")  # value mismatch (P8)
        E2 = dict(E, CLAUDE_CODE_SUBAGENT_MODEL_FORCE="yes")
        self.assertEqual(rl.detect(E2, None, [], None, None)["origin"], "user")
        self.assertTrue(rl.detect(dict(E, CLAUDE_CODE_EFFORT_LEVEL="auto"), None, [], None, None)["effort_locked"])

    def test_sig_and_orphan(self):
        st = {"mode": "LOCKED", "worker": "claude-sonnet-5", "origin": "mix", "effort_locked": False}
        rec = {"lead": "claude-opus-5-5", "main_model": "claude-opus-5-5[1m]"}
        self.assertFalse(rl.is_orphan(st, rec))
        self.assertEqual(rl.sig(st, rec), "LOCKED|claude-sonnet-5|0|0")
        rec["main_model"] = "claude-sonnet-5"
        self.assertTrue(rl.is_orphan(st, rec))
        self.assertEqual(rl.sig(st, rec), "LOCKED|claude-sonnet-5|1|0")
        self.assertFalse(rl.is_orphan(dict(st, origin="launch"), rec))

    def test_scan_settings_case_insensitive_and_invalid(self):
        pdir = os.path.join(self.T, "proj")
        os.makedirs(os.path.join(pdir, ".claude"))
        with open(os.path.join(self.T, "config", "settings.json"), "w") as fh:
            json.dump({"env": {"claude_code_subagent_model": "haiku"}, "model": "opusplan"}, fh)
        with open(os.path.join(pdir, ".claude", "settings.json"), "w") as fh:
            fh.write("{bad")
        os.environ["ROUTING_TEST_MANAGED_DIR"] = os.path.join(self.T, "managed")
        es = rl.scan_settings(pdir)
        keys = {(e["scope"], e.get("key"), "error" in e) for e in es}
        self.assertIn(("user", "env.CLAUDE_CODE_SUBAGENT_MODEL", False), keys)
        self.assertIn(("user", "model", False), keys)
        self.assertIn(("project", None, True), keys)

    def test_record_roundtrip_and_corrupt(self):
        os.environ["CLAUDE_PLUGIN_DATA"] = os.path.join(self.T, "data")
        os.environ["CLAUDE_PID"] = "77"
        rec = rl.new_record("s1")
        rec["lead"] = "x"
        self.assertTrue(rl.save_record(rec))
        self.assertEqual(rl.load_record()["lead"], "x")
        with open(rl.record_path(), "w") as fh:
            fh.write("{{")
        self.assertIsNone(rl.load_record())
        del os.environ["CLAUDE_PID"]
        self.assertTrue(rl.record_path(sid="abc").endswith("sid-abc.json"))

    def test_agent_effort_defaults(self):
        d = rl.agent_effort_defaults(PLUGIN)
        self.assertEqual(d.get("model-routing:recall"), "low")
        self.assertEqual(d.get("model-routing:implementer"), "medium")
        self.assertEqual(d.get("model-routing:deep-thinker"), "high")
        self.assertEqual(d.get("model-routing:think"), "high")

    def test_user_lines_short(self):
        L = rl.lines
        samples = [L.U1("claude-opus-5-5", "claude-sonnet-5"), L.U2("claude-sonnet-5", "project"),
                   L.U3("claude-sonnet-5"), L.U4("claude-sonnet-5", "claude-opus-5-5"),
                   L.U4b("claude-sonnet-5"), L.U5, L.U6, L.U8,
                   L.U10("claude-sonnet-5", None), L.U11("claude-sonnet-5", "claude-haiku-5-5", None),
                   L.U15(1234, 3)]
        for s in samples:
            self.assertLessEqual(len(s), 85, s)  # spec texts are 'about 70'; U11 is 81


def frontmatter_desc(path):
    return rl.frontmatter(path).get("description", "")


class Static(unittest.TestCase):
    def test_sc1_think_agent_name(self):
        think = rl.frontmatter(os.path.join(PLUGIN, "skills", "think", "SKILL.md"))
        agent = rl.frontmatter(os.path.join(PLUGIN, "agents", "deep-thinker.md"))
        self.assertEqual(think.get("agent"), "model-routing:" + agent.get("name"))
        self.assertEqual(think.get("context"), "fork")
        self.assertEqual(think.get("background"), "false")
        self.assertEqual(think.get("user-invocable"), "false")

    def test_sc2_description_lengths(self):
        total = 0
        for p in glob.glob(os.path.join(PLUGIN, "agents", "*.md")):
            n = len(frontmatter_desc(p))
            self.assertLessEqual(n, 150, p)
            total += n
        for name, cap in (("think", 150), ("execute", 150), ("handoff", 200)):
            n = len(frontmatter_desc(os.path.join(PLUGIN, "skills", name, "SKILL.md")))
            self.assertGreater(n, 0, name)
            self.assertLessEqual(n, cap, name)
            total += n
        self.assertLessEqual(total, 900)
        for name in ("status", "setup", "escalate"):
            fm = rl.frontmatter(os.path.join(PLUGIN, "skills", name, "SKILL.md"))
            self.assertEqual(fm.get("disable-model-invocation"), "true", name)

    def test_sc_layout(self):
        self.assertFalse(os.path.exists(os.path.join(PLUGIN, "scripts", "plan_mode.py")))
        self.assertFalse(os.path.exists(os.path.join(PLUGIN, "bin", "routing-setup")))
        hooks = load(os.path.join(PLUGIN, "hooks", "hooks.json"))["hooks"]
        for ev, groups in hooks.items():
            for g in groups:
                for h in g["hooks"]:
                    self.assertTrue(h["command"].startswith('sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" '), h)
                    # A missing script must never exit 2 (that blocks prompts, switches, compaction).
                    self.assertTrue(h["command"].endswith(" || true"), h)
                    name = h["command"].split()[2]
                    self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "scripts", name + ".py")), name)
        self.assertNotIn("PreToolUse", hooks)
        self.assertNotIn("SubagentStart", hooks)
        self.assertEqual(load(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"))["version"], "2.0.0")

    def test_sc_no_forbidden_writes(self):
        """No script assigns SUBAGENT/EFFORT env vars or writes a model pin."""
        for p in glob.glob(os.path.join(PLUGIN, "scripts", "*.py")):
            src = read(p)
            for bad in ('os.environ["CLAUDE_CODE_SUBAGENT', "os.environ['CLAUDE_CODE_SUBAGENT",
                        'os.environ["CLAUDE_CODE_EFFORT', 'new["model"] =', "putenv("):
                self.assertNotIn(bad, src, p)

    def test_sc3_setup_fuzz(self):
        """Applying every fix never adds a SUBAGENT, EFFORT_LEVEL or model key."""
        rnd = random.Random(1234)
        script = os.path.join(PLUGIN, "scripts", "run.sh")
        watched = ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE",
                   "CLAUDE_CODE_EFFORT_LEVEL", "ANTHROPIC_MODEL")
        for trial in range(30):
            T = tempfile.mkdtemp(prefix="mr-fuzz-")
            try:
                paths = {"user": os.path.join(T, "config", "settings.json"),
                         "project": os.path.join(T, "project", ".claude", "settings.json"),
                         "local": os.path.join(T, "project", ".claude", "settings.local.json"),
                         "managed": os.path.join(T, "managed", "managed-settings.json")}
                before = {}
                for scope, p in paths.items():
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    if rnd.random() < 0.2:
                        continue
                    obj = {}
                    if rnd.random() < 0.5:
                        obj["model"] = rnd.choice(["opusplan", "opus", "claude-sonnet-5"])
                    env = {}
                    for k in watched + ("CLAUDE_CODE_SIMPLE", "OTHER"):
                        if rnd.random() < 0.4:
                            env[rnd.choice([k, k.lower()])] = rnd.choice(["1", "haiku", "high", True])
                    if env or rnd.random() < 0.3:
                        obj["env"] = env
                    if rnd.random() < 0.3:
                        obj["agent"] = rnd.choice(["model-routing:implementer", "other"])
                    if rnd.random() < 0.3:
                        obj["modelPicker"] = {"replaceBuiltInOptions": True}
                    if rnd.random() < 0.3:
                        obj["showClearContextOnPlanAccept"] = rnd.choice([True, False])
                    obj["keep"] = trial
                    with open(p, "w") as fh:
                        json.dump(obj, fh)
                    before[scope] = obj
                env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": T,
                       "CLAUDE_CONFIG_DIR": os.path.join(T, "config"),
                       "CLAUDE_PROJECT_DIR": os.path.join(T, "project"),
                       "ROUTING_TEST_MANAGED_DIR": os.path.join(T, "managed"),
                       "ROUTING_TEST_LOCAL": "1", "CLAUDE_PLUGIN_DATA": os.path.join(T, "data"),
                       "PYTHONDONTWRITEBYTECODE": "1"}
                arg = "all" if trial % 2 else ",".join(str(i) for i in range(1, 30))
                r = subprocess.run(["sh", script, "routing_setup", "--apply", arg], env=env,
                                   capture_output=True, text=True, timeout=20)
                self.assertEqual(r.returncode, 0, r.stderr)
                for scope, p in paths.items():
                    if scope not in before:
                        if scope != "user":
                            self.assertFalse(os.path.exists(p), p)
                        else:
                            if os.path.exists(p):
                                after = load(p)
                                self.assertEqual(set(after), {"showClearContextOnPlanAccept"})
                        continue
                    after = load(p)
                    b = before[scope]
                    if scope == "managed":
                        self.assertEqual(after, b)
                        continue
                    self.assertLessEqual(set(after) - {"showClearContextOnPlanAccept"}, set(b))
                    if "model" in after:
                        self.assertEqual(after["model"], b.get("model"))
                    benv = {k.upper() for k in (b.get("env") or {})}
                    aenv = {k.upper() for k in (after.get("env") or {})}
                    for k in watched:
                        if k in aenv:
                            self.assertIn(k, benv)
                    self.assertEqual(after["keep"], trial)
                    if "OTHER" in benv:
                        self.assertIn("OTHER", aenv)
            finally:
                shutil.rmtree(T, ignore_errors=True)


class Fixes(EnvCase):
    """Tests for the post-review fixes (lock, keys, lines, static guards)."""

    def _hook_env(self):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.T,
               "CLAUDE_PLUGIN_ROOT": PLUGIN, "CLAUDE_PLUGIN_DATA": os.path.join(self.T, "data"),
               "CLAUDE_CONFIG_DIR": os.path.join(self.T, "config"),
               "CLAUDE_PROJECT_DIR": os.path.join(self.T, "project"), "CLAUDE_PID": "4242",
               "CLAUDE_CODE_SESSION_ATTENDED": "1", "ROUTING_TEST_LAUNCH_ENV": "",
               "ROUTING_TEST_MANAGED_DIR": os.path.join(self.T, "managed"), "PYTHONDONTWRITEBYTECODE": "1"}
        os.makedirs(os.path.join(self.T, "project"), exist_ok=True)
        return env

    def test_record_lock_serialises_concurrent_hooks(self):
        """prompt_hook must load the record only after a concurrent writer (after_switch) saved it."""
        import fcntl
        import time as _t
        env = self._hook_env()
        os.environ.update({"CLAUDE_PLUGIN_DATA": env["CLAUDE_PLUGIN_DATA"], "CLAUDE_PID": "4242"})
        path = rl.record_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec = rl.new_record("s1")
        rec["state"] = {"mode": "OPEN", "worker": None, "default_worker": None, "origin": None,
                        "effort_locked": False}
        with open(path, "w") as fh:
            json.dump(rec, fh)
        lock = open(path[:-5] + ".lock", "a")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        proc = subprocess.Popen(["sh", os.path.join(PLUGIN, "scripts", "run.sh"), "prompt_hook"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True)
        proc.stdin.write(json.dumps({"session_id": "s1", "prompt": "hi", "permission_mode": "default"}))
        proc.stdin.close()
        _t.sleep(0.5)
        rec["last_switch"] = {"source": "resume", "from": "a", "to": "b", "ts": rl.now()}
        rec["main_model"] = "b"
        with open(path, "w") as fh:  # the concurrent writer saves while holding the lock
            json.dump(rec, fh)
        lock.close()
        proc.communicate(timeout=10)
        after = load(path)
        self.assertEqual(after["last_switch"]["source"], "resume")  # not lost
        self.assertEqual(after["main_model"], "b")
        self.assertIsNotNone(after["user_sig"])  # prompt_hook's own write landed too

    def test_record_lock_times_out_instead_of_hanging(self):
        import fcntl
        import time as _t
        os.environ.update({"CLAUDE_PLUGIN_DATA": os.path.join(self.T, "data"), "CLAUDE_PID": "4242"})
        path = rl.record_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = open(path[:-5] + ".lock", "a")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        t0 = _t.time()
        with rl.record_lock(timeout=0.3):
            pass
        self.assertLess(_t.time() - t0, 2)
        lock.close()

    def test_record_key_has_host_and_matches_run_sh_glob(self):
        import fnmatch
        os.environ["CLAUDE_PID"] = "4242"
        key = rl.record_key()
        self.assertTrue(key.endswith("-4242"), key)
        self.assertNotEqual(key, "4242")
        self.assertTrue(fnmatch.fnmatch(os.path.basename(rl.receipts_path()), "*-4242.jsonl"))
        self.assertFalse(fnmatch.fnmatch(rl.host_tag() + "-14242.jsonl", "*-4242.jsonl"))
        self.assertIn('receipts/*-"${CLAUDE_PID:-none}".jsonl', read(os.path.join(PLUGIN, "scripts", "run.sh")))

    def test_switch_guard_never_reads_big_files(self):
        """F13: a slow PreModelSwitch blocks the switch. No cache, settings or /proc reads."""
        import ast
        tree = ast.parse(read(os.path.join(PLUGIN, "scripts", "switch_guard.py")))
        tree.body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        src = ast.unparse(tree)  # code only: the docstring may name what it avoids
        for bad in ("mixcache", "scan_settings", "launch_env", ".claude.json", "settings_files"):
            self.assertNotIn(bad, src)

    def test_line_lengths(self):
        lab = "Opus + Sonnet"
        for text in (rl.lines.U10("claude-sonnet-5", lab),
                     rl.lines.U11("claude-sonnet-5", "claude-haiku-5-5", lab, "mix"),
                     rl.lines.U11("claude-sonnet-5", "claude-haiku-5-5", None, "unknown"),
                     rl.lines.U13("claude-sonnet-5", 182, 1.14, "catalog"),
                     rl.lines.U17("CLAUDE_CODE_SUBAGENT_MODEL", True),
                     rl.lines.U6, rl.lines.U6_managed, rl.lines.U5,
                     rl.lines.U4(None, "claude-opus-5-5"), rl.lines.U4("claude-sonnet-5", None)):
            self.assertLessEqual(len(text), 80, text)
        self.assertNotIn("the main model", rl.lines.U4("claude-sonnet-5", None))
        self.assertEqual(rl.lines.U4(None, "claude-opus-5-5"),
                         "Subagents run on the main model (Opus 5.5) · /model-routing:status")
        self.assertEqual(rl.lines.U9([{"m": None, "k": "fork", "e": "high"}]), "Routed: 1× Main model fork (high)")
        self.assertIn("Keep the mix: /model → the mix row.", rl.lines.U16(120, 0.9, "catalog", True, None))
        self.assertTrue(rl.lines.U12(182, "claude-sonnet-5", 1.14, "catalog", "sonnet", False, False, False,
                                     None, None).endswith(" Or: /model-routing:execute sonnet."))

    def test_provider_active(self):
        self.assertFalse(rl.provider_active({}))
        self.assertTrue(rl.provider_active({"CLAUDE_CODE_USE_BEDROCK": "1"}))
        self.assertTrue(rl.provider_active({"CLAUDE_CODE_USE_VERTEX": "true"}))
        self.assertTrue(rl.provider_active({"ANTHROPIC_BASE_URL": "https://gw.example"}))
        self.assertFalse(rl.provider_active({"CLAUDE_CODE_USE_BEDROCK": "0"}))

    def test_backup_names_are_unique(self):
        import routing_setup
        real = os.path.join(self.T, "settings.json")
        a = routing_setup._backup_name(real, "20260101-000000")
        open(a, "w").close()
        b = routing_setup._backup_name(real, "20260101-000000")
        self.assertNotEqual(a, b)

    def test_handoff_stamp_shared(self):
        self.assertEqual(rl.handoff_stamp_sid("x\n<!-- handoff-source: written w; session abc-1; transcript t -->"),
                         "abc-1")
        self.assertNotIn("STAMP_SID = re.compile", read(os.path.join(PLUGIN, "scripts", "session_start.py")))

    def test_skill_texts(self):
        sk = lambda n: read(os.path.join(PLUGIN, "skills", n, "SKILL.md"))
        for n in ("status", "setup", "execute", "escalate"):
            self.assertIn('--project "${CLAUDE_PROJECT_DIR}"', sk(n), n)
        self.assertEqual(sk("setup").count('--project "${CLAUDE_PROJECT_DIR}"'), 2)
        self.assertIn('from "Model routing" through "Commands:"', sk("status"))
        self.assertIn('If it has a line starting "Removed" or "Turned on"', sk("setup"))
        self.assertIn("by the model mix or by CLAUDE_CODE_SUBAGENT_MODEL_FORCE", sk("handoff"))
        self.assertIn("If the user asked for fable, first tell them", sk("escalate"))
        self.assertIn("short name", sk("execute"))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a == "-v"], verbosity=2 if "-v" in sys.argv else 1)
