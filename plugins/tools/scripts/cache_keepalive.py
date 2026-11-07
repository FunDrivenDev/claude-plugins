"""Keeps the prompt cache warm while a session waits.

Claude Code runs this script on three events (hooks/hooks.json):

- Stop, as an `asyncRewake` hook: when the turn ends while the session waits on
  something (a background task or a scheduled wakeup), it sleeps until shortly
  before the cache expires, then exits 2. Claude Code wakes the session with the
  stderr text as a system reminder, the model answers in one line, and that
  request refreshes the cache for another TTL.
- UserPromptSubmit: the user is back, so the pending timer is cancelled and the
  count of keep-alives in a row starts over. The keep-alive's own wake comes in
  as a prompt too (a task notification carrying MESSAGE): that one changes
  nothing, or the count would never reach its cap.
- SessionEnd: the pending timer is cancelled and the session's state removed.

A newer event supersedes the sleeping timer through a token in the state file,
which the timer reads every few seconds: no PID, no signal.

Options, from the environment Claude Code runs in (its `env` setting included):

- CACHE_KEEPALIVE: `waiting` (default) arms the timer only when the Stop input
  lists a background task or a session cron; `always` arms it after every
  turn; `off` never arms it.
- CACHE_KEEPALIVE_AFTER: seconds from the end of the turn to the keep-alive,
  default 3300 (55 minutes, for the 1-hour cache TTL), at most 3540: the hook's
  timeout is 3600 and Claude Code enforces it on an asyncRewake hook.
- CACHE_KEEPALIVE_MAX: keep-alives in a row with no other turn between them,
  default 12; then the session is left to go cold.
"""

import json
import os
import signal
import sys
import tempfile
import time
import uuid

DEFAULT_AFTER = 3300
MAX_AFTER = 3540
DEFAULT_MAX = 12
POLL = 5.0

MARKER = "Cache keep-alive (tools plugin, cache-keepalive hook)"
MESSAGE = (
    MARKER + ": the prompt cache expires in about 5 minutes and the"
    " session is still waiting. Reply with one short line, no tool call, and change nothing; this request keeps"
    " the cache warm for another hour."
)


def number(name, default, low, high):
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return min(max(value, low), high)


def state_dir():
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.join(tempfile.gettempdir(), "claude-tools-plugin")
    return os.path.join(base, "cache-keepalive")


def state_path(session_id):
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_") or "unknown"
    return os.path.join(state_dir(), safe + ".json")


def load(path):
    try:
        with open(path) as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def waiting(payload):
    return bool(payload.get("background_tasks")) or bool(payload.get("session_crons"))


def on_stop(path, payload):
    mode = os.environ.get("CACHE_KEEPALIVE", "waiting").strip().lower()
    state = load(path)
    # The turn that just ended was the keep-alive's own only when one fired and nothing else ran since
    count = int(state.get("count", 0)) if state.get("fired") else 0
    token = uuid.uuid4().hex
    save(path, {"token": token, "count": count, "fired": False})

    if mode == "off" or (mode != "always" and not waiting(payload)):
        return 0
    if count >= number("CACHE_KEEPALIVE_MAX", DEFAULT_MAX, 0, 1000):
        return 0

    deadline = time.monotonic() + number("CACHE_KEEPALIVE_AFTER", DEFAULT_AFTER, 0, MAX_AFTER)
    poll = number("CACHE_KEEPALIVE_POLL", POLL, 0.05, 60)
    parent = os.getppid()
    while True:
        left = deadline - time.monotonic()
        if load(path).get("token") != token or os.getppid() != parent:
            return 0  # superseded by a newer turn or prompt, or Claude Code is gone
        if left <= 0:
            break
        time.sleep(min(poll, left))

    save(path, {"token": token, "count": count + 1, "fired": True})
    sys.stderr.write(MESSAGE + "\n")
    return 2


def on_prompt(path, payload):
    if MARKER in str(payload.get("prompt") or ""):
        return 0
    save(path, {"token": uuid.uuid4().hex, "count": 0, "fired": False})
    return 0


def on_end(path):
    try:
        os.remove(path)
    except OSError:
        pass
    return 0


def main():
    # Superseded or cancelled, the timer leaves quietly: anything but 2 wakes nobody
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    path = state_path(str(payload.get("session_id") or ""))
    event = payload.get("hook_event_name")
    try:
        if event == "Stop":
            return on_stop(path, payload)
        if event == "UserPromptSubmit":
            return on_prompt(path, payload)
        if event == "SessionEnd":
            return on_end(path)
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
