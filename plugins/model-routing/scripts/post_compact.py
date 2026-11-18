#!/usr/bin/env python3
"""PostCompact hook (manual and auto).

  - Every compaction: leaves a marker so the switch guard knows the context is
    small now, even if the token count it's handed still reflects the old one.
  - Manual /compact: also saves the summary as .handoff/LATEST.md (archived,
    kept out of git), so the state survives on disk for other tools and the
    recall agent.

Config (settings.json "env"):
  ROUTING_SAVE_COMPACT  0 = don't save /compact summaries to .handoff (default 1)
  ROUTING_HANDOFF_DIR   default .handoff
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def clean(summary):
    """Keep only the <summary> body; drop the model's <analysis> scratch notes."""
    m = re.search(r"<summary>(.*?)(?:</summary>|$)", summary, re.S)
    if m:
        summary = m.group(1)
    else:
        summary = re.sub(r"<analysis>.*?</analysis>", "", summary, flags=re.S)
    return summary.strip()


def marker_path(session_id):
    return Path(tempfile.gettempdir()) / "claude-model-routing" / f"{session_id}.compacted"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    session_id = data.get("session_id") or ""
    if session_id:
        marker = marker_path(session_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(data.get("trigger") or ""))

    summary = clean(data.get("compact_summary") or "")
    if data.get("trigger") != "manual" or not summary:
        return 0
    if os.environ.get("ROUTING_SAVE_COMPACT", "1") == "0":
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    root = Path(project_dir) / os.environ.get("ROUTING_HANDOFF_DIR", ".handoff")
    root.mkdir(parents=True, exist_ok=True)
    (root / "LATEST.md").write_text(f"# Handoff (from /compact)\n\n{summary}\n", encoding="utf-8")

    finalize = Path(__file__).resolve().parent.parent / "bin" / "handoff-finalize"
    subprocess.run([sys.executable, str(finalize), project_dir, session_id],
                   capture_output=True, timeout=20)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
