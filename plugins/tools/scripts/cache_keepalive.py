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
which the timer reads every few seconds: no PID, no signal. The timer also
gives up when the transcript grows after a short grace: the session is busy
again (a turn a Stop hook continued, a task notification), so its requests keep
the cache warm and its own Stop arms the next timer. The deadline is wall time:
the cache expires while the Mac sleeps, and a wake after the TTL is pointless.

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
import math
import os
import signal
import sys
import tempfile
import time
import uuid

TTL = 3600
DEFAULT_AFTER = 3300
MAX_AFTER = 3540
DEFAULT_MAX = 12
POLL = 5.0
GRACE = 15.0  # Claude Code's own writes to the transcript once the turn has ended

MARKER = "Cache keep-alive (tools plugin, cache-keepalive hook)"
MESSAGE = (
    MARKER + ": the prompt cache is about to expire and the session is still waiting. Reply with one short line,"
    " no tool call, and change nothing; this request keeps the cache warm for another hour."
)


def number(name, default, low, high):
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    if not math.isfinite(value):
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


def size(path):
    try:
        return os.path.getsize(path) if path else None
    except OSError:
        return None


def waiting(payload):
    return bool(payload.get("background_tasks")) or bool(payload.get("session_crons"))


def is_own_wake(prompt):
    # Claude Code hands the wake to UserPromptSubmit as a task notification wrapping MESSAGE; a prompt that only
    # quotes the marker is the user's own
    return MESSAGE in prompt and "<task-notification>" in prompt


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

    after = number("CACHE_KEEPALIVE_AFTER", DEFAULT_AFTER, 0, MAX_AFTER)
    poll = number("CACHE_KEEPALIVE_POLL", POLL, 0.05, 60)
    grace = min(GRACE, after / 4)
    transcript = payload.get("transcript_path")
    start = time.time()
    baseline = None
    parent = os.getppid()
    while True:
        elapsed = time.time() - start
        if load(path).get("token") != token or os.getppid() != parent:
            return 0  # superseded by a newer turn or prompt, or Claude Code is gone
        if elapsed >= TTL:
            return 0  # the Mac slept past the TTL: the cache is already gone
        current = size(transcript)
        if baseline is None and elapsed >= grace:
            baseline = current
        elif baseline is not None and current is not None and current > baseline:
            return 0  # the session is busy again: its own requests and Stop take over
        if elapsed >= after:
            break
        wait = min(poll, after - elapsed)
        if baseline is None:
            wait = min(wait, grace - elapsed)
        time.sleep(max(0.01, wait))

    save(path, {"token": token, "count": count + 1, "fired": True})
    sys.stderr.write(MESSAGE + "\n")
    return 2


def on_prompt(path, payload):
    if is_own_wake(str(payload.get("prompt") or "")):
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
