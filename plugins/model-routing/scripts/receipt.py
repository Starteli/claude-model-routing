#!/usr/bin/env python3
"""Stop hook: one line per turn saying where subagents ran.

run.sh skips Python entirely when no receipts are pending. Output is
systemMessage only: additionalContext or decision on Stop would make the turn
continue.

Config (settings.json "env"): ROUTING_RECEIPTS (1), ROUTING_QUIET (0).
"""
import json
import os

import routing_lib as rl


def take_lines(path):
    """Grab the pending file atomically, then read and delete it."""
    grabbed = path + f".taking-{os.getpid()}"
    try:
        os.replace(path, grabbed)
    except OSError:
        return []
    out = []
    try:
        with open(grabbed, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    finally:
        try:
            os.unlink(grabbed)
        except OSError:
            pass
    return out


def main():
    d = rl.read_stdin_json() or {}
    items = take_lines(rl.receipts_path())
    pid = d.get("prompt_id")
    # Without a prompt_id on Stop, every pending line belongs to this turn.
    mine = [i for i in items if i.get("p") == pid] if pid else items
    if any(i.get("k") == "fork" and not i.get("m") for i in mine):
        main = rl.transcript_model(d.get("transcript_path"))  # forks run on the main model
        for i in mine:
            if i.get("k") == "fork" and not i.get("m"):
                i["m"] = main
    with rl.record_lock(sid=d.get("session_id")):
        rec = rl.load_record(sid=d.get("session_id"))
        if rec is not None:
            totals = rec.get("totals") or {}
            for i in mine:
                key = ("fork:" if i.get("k") == "fork" else "") + (i.get("m") or "")
                totals[key] = int(totals.get(key) or 0) + 1
            rec["totals"] = totals
            eff = d.get("effort")
            if isinstance(eff, dict) and eff.get("level"):
                rec["session_effort"] = eff.get("level")
            rl.save_record(rec)
    if (not mine or os.environ.get("ROUTING_RECEIPTS", "1") == "0"
            or os.environ.get("ROUTING_QUIET") == "1" or not rl.attended()):
        return
    rl.emit({"systemMessage": rl.lines.U9(mine)})


if __name__ == "__main__":
    rl.safe_main(main)
