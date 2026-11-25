#!/bin/sh
# run.sh <name> [args]: run scripts/<name>.py with Python 3; never fail.
name="$1"; shift
here="$(cd "$(dirname "$0")" && pwd)"
case "$name" in
  routing_status|routing_setup) ;;
  *) # hooks: a missing script must not exit 2 (that would block prompts, switches, compaction)
    [ -f "$here/$name.py" ] || { cat >/dev/null 2>&1; exit 0; } ;;
esac
case "$name" in
  receipt)   # Stop fast path: no pending receipts -> no Python
    has=
    for f in "${CLAUDE_PLUGIN_DATA:-/nonexistent}"/receipts/*-"${CLAUDE_PID:-none}".jsonl; do
      [ -s "$f" ] && has=1
    done
    [ -n "$has" ] || { cat >/dev/null 2>&1; exit 0; } ;;
esac
if [ ! -f "$here/$name.py" ]; then
  echo "model-routing: $name is missing; reinstall the plugin."; exit 0
fi
# Hook stdin and `!` output are UTF-8 on every platform (Windows defaults to cp1252).
PYTHONUTF8=1; export PYTHONUTF8
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    exec "$py" "$here/$name.py" "$@"
  fi
done
if command -v py >/dev/null 2>&1; then exec py -3 "$here/$name.py" "$@"; fi
case "$name" in
  routing_status|routing_setup) echo "model-routing: Python 3 not found, so this command can't run."; exit 0 ;;
esac
input="$(cat 2>/dev/null)"
if [ "$name" = session_start ] &&
   { [ "${CLAUDE_CODE_SESSION_ATTENDED:-1}" != 0 ] || [ "${ROUTING_SHOW_HEADLESS:-0}" = 1 ]; }; then
  case "$input" in *'"source":"startup"'*|*'"source": "startup"'*)
    printf '%s\n' '{"systemMessage":"model-routing is off: Python 3 not found."}' ;; esac
fi
exit 0
