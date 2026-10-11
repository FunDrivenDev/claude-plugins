#!/usr/bin/env python3
"""Keep a handover document for a Claude Code session and load it into the next one.

The handover is written by a separate `claude -p` call from a render of the
transcript, never by the session whose context is full.

    handover.py hook                   hook entry point, hook input on stdin
    handover.py write --session ID     write or refresh the session's handover now
    handover.py request --session ID   the session asks to hand over (the handover and relay skills)
    handover.py status [--session ID]  state of one session, or of all of them
    handover.py stats [--json]         token metrics of past handovers, to tune the trigger
    handover.py guidance               SessionStart hook: the background-command tags, and the delegation
                                       guidance when `delegate` is on
    handover.py await-timeout ...      the detached watchdog that stops an [await] command the wind-down
                                       waited on for `await_minutes`
    handover.py wake-timeout ...       the detached safety net of a kill or a notice that should wake the session
    handover.py statusline             the session's handover state, status-line payload on stdin
    handover.py relay-drive ...        the relay's detached second half, started by the hooks
    handover.py afk --session ID ...   turn AFK mode on (or --off) in a running session
    handover.py until <when>           resolve an AFK deadline: epoch on stdout, the date on stderr
    handover.py yolo-settings [--merge S]  the deny rules a YOLO run starts with, as a --settings JSON,
                                       added to the user's own --settings S

A session is told once, past `suggest_tokens`, to hand over by itself at the
next boundary between scopes. Its wind-down starts once its context crosses
`trigger_tokens`, or once it asks to hand over (`request`). A session winding down starts
no new task and finishes those in progress: the current step, its subagents, its [await]
background commands. The handover is written only then, by the Stop hook of the turn that
ends with nothing left running, from the complete transcript; the hook holds the session
until it is written, then has it write its closing reply, so that the user's /clear (or the
relay's) finds the handover already there. The handover is refreshed when the session goes
on and is cleared, exited or compacted later, and the next session in the same project loads it.

Background commands: each one is tagged at launch, its description starting with
`[await]` (a test run, a build, a CI watch: its result is waited for) or `[endless]` (a dev
server, a watcher: it never ends by itself). An untagged one is refused once, then guessed
from its command, or taken for endless when the guess is unsure. During the wind-down the
plugin waits for the [await] ones, up to `await_minutes` each, and stops the [endless]
ones and those it gave up on; the session names them in its reply, the writer in the
handover.

With the relay on (HANDOVER_RELAY=1, set by scripts/claude-relay, or `request --relay`
from the relay skill, or a session the relay started), the handover runs
without the user: once the session has written its closing reply, /clear and the
resume message are typed into its tmux pane, or, outside tmux, the claude-relay loop
restarts claude with that message. The handovers of a chain are numbered, and the chain
halts for the user at `relay_limit` of them.

AFK mode (claude-relay --afk, or the afk skill) runs a relay toward a goal while the
user is away: no `relay_limit`, an optional deadline after which no new handover starts,
and a Stop hook that sends the session back to work until it ends a reply with
`AFK done: <why>` or `AFK blocked: <why>`. A YOLO run (claude-relay --afk --yolo) skips
permission prompts: every tool call goes to an audit log, tagged by whether it would have
run without YOLO, and the plugin, its data and the settings files are off limits to it.

Subagents: every session is told to give self-contained tasks to subagents, so its own
context fills more slowly. From the suggestion point no new subagent starts, and while one
runs the handover is neither written nor relayed: its result belongs in the handover.

Every step is also appended to metrics.jsonl in the data directory: token
counts, durations and costs, and the one-line reason a session gives when it
asks for a handover itself; never transcript content, apart from the command or path of a
tool call an AFK run waited on or was denied, and the command and description of a background
command that was untagged or stopped. `stats` reads it back.
"""

import argparse
import contextlib
import fcntl
import fnmatch
import glob
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import transcript as T
import writer_prompt as P

# additionalContext beyond 10,000 characters is moved to a file Claude only sees a preview of.
INJECT_CHARS = 9500
# Longest render sent to the writer, about 200K tokens.
MAX_RENDER_CHARS = 800_000
# How long a new session waits for a handover still being written: the refresh of a session that went on
# after its closing reply, a pre-compaction handover, a writer slower than STOP_WRITE_SECONDS.
WAIT_SECONDS = 150
# How long the Stop hook holds the session while the writer works, within the hook's timeout in hooks.json.
STOP_WRITE_SECONDS = 240
WRITER_TIMEOUT = 600
CLEAR_HANDOVER_SECONDS = 300
# After the plugin kills a command, or a subagent's notice is late, how long the turn it should wake is waited for.
WAKE_SECONDS = 20
STARTUP_POINTER_SECONDS = 24 * 3600
LIVE_SECONDS = 7 * 24 * 3600


OPTIONS = (
    "handover_dir",
    "suggest_tokens",
    "trigger_tokens",
    "await_minutes",
    "writer_model",
    "handover_chars",
    "warn_tokens",
    "refresh_tokens",
    "compact_reserve_tokens",
    "relay_limit",
    "delegate",
    "yolo_guard_paths",
)


def option(key, default):
    """Hook environment first; outside hooks, the values the last SessionStart hook saw."""
    v = os.environ.get(f"CLAUDE_PLUGIN_OPTION_{key.upper()}", "").strip()
    if v:
        return v
    return read_json(os.path.join(data_dir(), "options.json"), {}).get(key) or default


def save_options():
    """Keep the options the hooks see, for the status line and the commands run outside hooks."""
    seen = {
        k: os.environ[f"CLAUDE_PLUGIN_OPTION_{k.upper()}"]
        for k in OPTIONS
        if os.environ.get(f"CLAUDE_PLUGIN_OPTION_{k.upper()}")
    }
    path = os.path.join(data_dir(), "options.json")
    if read_json(path) != seen:
        write_json(path, seen)


def config():
    """The plugin options; the defaults repeat those of plugin.json."""

    def number(key, default):
        return int(float(option(key, default)))

    return {
        "dir": os.path.expanduser(option("handover_dir", "~/Notes/claude/agent-handovers")),
        "suggest": number("suggest_tokens", "150000"),
        "trigger": number("trigger_tokens", "185000"),
        # How long the wind-down waits for each [await] background command before stopping it.
        "await": number("await_minutes", "10") * 60,
        "writer_model": option("writer_model", "sonnet"),
        # Target length of the handover; loading cuts it at INJECT_CHARS.
        "chars": min(number("handover_chars", "8000"), INJECT_CHARS),
        # The status line warns this far below the trigger.
        "warn": number("warn_tokens", "20000"),
        # A handover this many tokens behind the session is refreshed before it is used.
        "refresh": number("refresh_tokens", "2000"),
        # Auto-compaction fires about this far below autoCompactWindow; `stats` uses it
        # until real compactions have been recorded.
        "reserve": number("compact_reserve_tokens", "33000"),
        # Handovers in a relay chain before it stops for the user.
        "relay_limit": number("relay_limit", "5"),
        # Tell each session to give self-contained tasks to subagents.
        "delegate": str(option("delegate", "true")).lower() not in ("false", "0", "no", "off"),
    }


def data_dir():
    """The plugin's data folder; outside a hook, derived from where the plugin is installed."""
    d = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if d and not d.startswith("${"):
        return d
    # <plugins>/cache/<marketplace>/<plugin>/<version>/scripts -> <plugins>/data/<plugin>-<marketplace>
    parts = os.path.dirname(os.path.abspath(__file__)).split(os.sep)
    if len(parts) >= 6 and parts[-5] == "cache":
        return os.sep.join(parts[:-5] + ["data", f"{parts[-3]}-{parts[-4]}"])
    return os.path.expanduser("~/.claude/plugins/data/handover-inline")


# Metric events of the plugin when it was named handoff, before 0.8.0: their names now, and their renamed fields.
OLD_EVENTS = {
    "armed": "wind_down_started",
    "untagged": "command_untagged",
    "task_stopped": "command_stopped",
    "task_left": "command_left",
    "await_timeout": "command_timed_out",
    "announced": "closing_reply_written",
    "requested": "handover_requested",
    "writer": "writer_finished",
    "chain_handoff": "chain_handover_written",
    "suggested": "suggestion_sent",
    "notified": "user_notified",
    "relayed": "relay_launched",
    "relay_started": "relay_received",
    "relay_capped": "relay_limit_reached",
    "afk_continued": "afk_sent_back",
    "afk_waiting": "afk_user_needed",
    "afk_session": "afk_session_joined",
    "precompact": "compaction_started",
    "session_end": "session_ended",
    "loaded": "handover_loaded",
    "agents_wait": "wind_down_held",
    "tasks_wait": "wind_down_held",
    "wake_wait": "wind_down_held",
}
OLD_FIELDS = {"armed": "wind_down", "model": "writer_model", "handoff_chars": "handover_chars", "tasks": "commands"}
HELD_FOR = {"agents_wait": "agents", "tasks_wait": "commands", "wake_wait": "wake"}


def old_event(e):
    """A metrics line of the handoff plugin, in today's names."""
    name = e.get("event")
    e = {OLD_FIELDS.get(k, k): v for k, v in e.items()}
    e["event"] = OLD_EVENTS.get(name, name)
    if name in HELD_FOR:
        e["for"] = HELD_FOR[name]
    return e


# Where the plugin was served from before it moved to the fundrivendev marketplace (0.13.0).
OLD_MARKETPLACE = "fundriven"


def import_old_data():
    """Once, into a new data folder: the metrics and YOLO audit logs the plugin recorded in the folders next to it,
    under its old name, handoff (its events renamed), then in its old marketplace's. The rest of those folders only
    mattered to the sessions that ran then."""
    d = data_dir()
    base = os.path.basename(d)
    marker = os.path.join(d, "imported.json")
    if not base.startswith("handover-") or os.path.exists(marker):
        return
    mp = base[len("handover-") :]
    sources = [(os.path.join(os.path.dirname(d), "handoff-" + mp), True)]
    if mp != OLD_MARKETPLACE:
        sources.append((os.path.join(os.path.dirname(d), "handover-" + OLD_MARKETPLACE), False))
    done = {"from": [old for old, _ in sources], "at": time.time(), "metrics": 0, "audit": 0}
    lines = []
    for old, renamed in sources:
        with contextlib.suppress(OSError), open(os.path.join(old, "metrics.jsonl"), encoding="utf-8") as f:
            for line in f:
                with contextlib.suppress(ValueError):
                    e = json.loads(line)
                    lines.append(json.dumps(old_event(e) if renamed else e))
        for f in glob.glob(os.path.join(old, "audit", "*.jsonl")):
            dest = os.path.join(d, "audit", os.path.basename(f))
            if not os.path.exists(dest):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(f, "rb") as src, open(dest, "wb") as out:
                    out.write(src.read())
                done["audit"] += 1
    if lines:
        os.makedirs(d, exist_ok=True)
        # Ahead of anything this folder already recorded, which is newer.
        mine = ""
        with contextlib.suppress(OSError), open(metrics_path(), encoding="utf-8") as m:
            mine = m.read()
        with open(metrics_path() + ".tmp", "w", encoding="utf-8") as m:
            m.write("".join(x + "\n" for x in lines) + mine)
        os.replace(metrics_path() + ".tmp", metrics_path())
        done["metrics"] = len(lines)
    write_json(marker, done)


def state_path(sid):
    return os.path.join(data_dir(), "sessions", f"{sid}.json")


def progress_path(sid):
    return os.path.join(data_dir(), "sessions", f"{sid}.progress.json")


def drop_progress(sid):
    with contextlib.suppress(FileNotFoundError):
        os.remove(progress_path(sid))


def live_path(sid):
    return os.path.join(data_dir(), "live", sid)


def mark_live(sid, event):
    """Mark the sessions the hooks run in, so the plugin is enabled there; the status line shows only those."""
    path = live_path(sid)
    if event == "SessionEnd":
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a"):
        os.utime(path)
    if event == "SessionStart":
        # Sessions that crashed never send SessionEnd.
        d = os.path.dirname(path)
        for f in os.listdir(d):
            with contextlib.suppress(OSError):
                if time.time() - os.path.getmtime(os.path.join(d, f)) > LIVE_SECONDS:
                    os.remove(os.path.join(d, f))


def project_key(project):
    return hashlib.sha1(os.path.realpath(project).encode()).hexdigest()[:16]


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


def metrics_path():
    return os.path.join(data_dir(), "metrics.jsonl")


def record(event, sid, **fields):
    """Append one metrics line: numbers, plus the one-line reason a session gives when it asks for a handover."""
    line = json.dumps({"at": round(time.time()), "event": event, "session": sid, **fields})
    with contextlib.suppress(OSError):
        os.makedirs(data_dir(), exist_ok=True)
        with open(metrics_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")


def compact_window():
    v = read_json(os.path.expanduser("~/.claude/settings.json"), {}).get("autoCompactWindow")
    return v if isinstance(v, int) else None


@contextlib.contextmanager
def locked_json(path):
    """A JSON file, saved on exit; the processes that share it never interleave."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        obj = read_json(path, {})
        yield obj
        write_json(path, obj)


def locked_state(sid):
    """The session's state; hooks and the writer never interleave."""
    return locked_json(state_path(sid))


def writer_running(st):
    r = st.get("writer")
    if not r:
        return False
    if time.time() - r.get("since", 0) > WRITER_TIMEOUT + 60:
        return False
    try:
        os.kill(r["pid"], 0)
    except (OSError, KeyError):
        return False
    return True


def needs_refresh(st, tokens):
    written = st.get("written") or {}
    return not written.get("ok") or abs(tokens - written.get("tokens", 0)) > config()["refresh"]


# Starts the command in a session of its own, prints its pid and exits: the command is no longer the hook's child.
SPAWN = (
    "import subprocess, sys\n"
    "print(subprocess.Popen(sys.argv[1:], stdin=subprocess.DEVNULL, stdout=sys.stderr,"
    " start_new_session=True).pid)"
)


def detach(args, stderr=subprocess.DEVNULL, env=None):
    """Run `handover.py <args>` detached from the hook; its pid, or None.

    Esc on a hook makes Claude Code kill the hook's descendants, even in a session of their own: the command
    is started through a short-lived intermediate, so that it is reparented to launchd (or init)."""
    p = subprocess.run(
        [sys.executable, "-c", SPAWN, sys.executable, os.path.abspath(__file__), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=True,
        env={**os.environ, "HANDOVER_CHILD": "1", **(env or {})},
        check=False,
    )
    with contextlib.suppress(ValueError):
        return int(p.stdout)
    return None


def start_writer(st, sid, cause):
    """Start the writer detached, so it outlives the hook and the session."""
    if writer_running(st):
        return
    with open(os.path.join(data_dir(), "sessions", f"{sid}.log"), "a") as log:
        pid = detach(["write", "--session", sid, "--cause", cause], log)
    if pid:
        st["writer"] = {"pid": pid, "since": time.time()}


def start_wind_down(st, sid, cause, tokens, cfg):
    """The session hands over: it starts no new task and finishes those in progress."""
    st.update(wind_down=True, wind_down_tokens=tokens, cause=cause)
    reset_commands(st, sid)
    record(
        "wind_down_started", sid, cause=cause, tokens=tokens, trigger=cfg["trigger"], compact_window=compact_window()
    )


def reset_commands(st, sid):
    """A new wind-down: the background commands stopped or watched for an earlier one are not its own."""
    for k in ("watched", "stopped", "stop_asked", "woken", "notices_awaited"):
        st.pop(k, None)
    with locked_json(tasks_path(sid)) as tasks:
        tasks.pop("gave_up", None)


def wait_for(sid, seconds):
    deadline = time.time() + seconds
    while True:
        st = read_json(state_path(sid), {})
        if not writer_running(st) or time.time() >= deadline:
            return st
        time.sleep(1)


def write_now(sid, cause, seconds):
    """Write the session's handover and wait for it, at most `seconds`: ("written" | "failed" | "slow", state).

    The writer stays detached, so that it outlives a hook Claude Code kills. A writer already running (a
    refresh) is joined; a handover it leaves behind the transcript is written again, and a failure is
    retried once while the time allows it. Never call it holding the session's lock: the writer takes it."""
    deadline = time.time() + seconds
    for attempt in (1, 2, 3):
        t0 = time.time()
        with locked_state(sid) as st:
            if not writer_running(st):
                if not needs_refresh(st, T.context_tokens(st["transcript"])[0]):
                    return "written", st
                if attempt == 3:
                    break
                start_writer(st, sid, cause)
        st = wait_for(sid, deadline - time.time())
        if writer_running(st):
            return "slow", st
        if (st.get("error") or {}).get("at", 0) >= t0 and (attempt > 1 or deadline - time.time() < 60):
            return "failed", st
    return ("written" if (st.get("written") or {}).get("ok") else "failed"), st


def agents_path(sid):
    return os.path.join(data_dir(), "sessions", f"{sid}.agents.json")


# A subagent with no SubagentStop after this long was interrupted or crashed.
AGENT_SECONDS = 4 * 3600
# Background tasks that do work whose result the session waits for; a shell or a monitor may run forever.
AGENT_TASKS = ("subagent", "workflow", "teammate")
TASK_DONE = ("completed", "failed", "killed", "cancelled", "canceled", "stopped", "error")


def on_subagent(inp, event):
    """SubagentStart and SubagentStop: keep the session's running subagents."""
    with locked_json(agents_path(inp["session_id"])) as agents:
        if event == "SubagentStart":
            agents[inp.get("agent_id") or "?"] = {"type": inp.get("agent_type"), "since": time.time()}
        else:
            agents.pop(inp.get("agent_id"), None)


def agents_busy(sid, inp=None):
    """How many subagents of this session still run. At Stop, the background tasks Claude Code lists
    are the truth: a turn that ended with none in flight leaves no subagent running."""
    tasks = (inp or {}).get("background_tasks")
    if tasks is not None:
        n = sum(t.get("type") in AGENT_TASKS and (t.get("status") or "running") not in TASK_DONE for t in tasks)
        if not n and os.path.exists(agents_path(sid)):
            write_json(agents_path(sid), {})
        return n
    return sum(time.time() - a.get("since", 0) < AGENT_SECONDS for a in read_json(agents_path(sid), {}).values())


def refuses_agents(st):
    """Past the suggestion, winding down, or past an AFK deadline: no new work, so no new subagent."""
    afk = st.get("afk") or {}
    return bool(st.get("suggested") or st.get("wind_down") or afk.get("deadline_told"))


NO_NEW_AGENT = (
    "Not started: this session will hand over soon (its context is past the point where a fresh session "
    "does better), so it starts no new subagent. Finish the tasks in progress with the subagents "
    "already running, and wait for their results: they belong in the handover. Leave new tasks to the next "
    "session, and name them in your closing reply."
)


def tasks_path(sid):
    return os.path.join(data_dir(), "sessions", f"{sid}.tasks.json")


TAG_RE = re.compile(r"^\s*\[(await|endless)\]", re.IGNORECASE)
# What an untagged background command most likely is. A command matching both, or neither, is unsure.
ENDLESS_RE = re.compile(
    r"\b(dev|serve|server|runserver|start|watch|preview|up|nodemon|http\.server|tail\s+-[fF]"
    r"|sleep\s+inf(inity)?)\b|(?<![\w-])--?w(atch)?(?![\w-])"
)
AWAIT_RE = re.compile(
    r"\b(test|tests|pytest|vitest|jest|build|lint|check|checks|typecheck|tsc|make|install|"
    r"sleep\s+\d+)\b"
)
# Watching a CI run ends with the run.
CI_WATCH_RE = re.compile(r"\bgh\s+(run|pr)\s+(watch|checks)\b[^;&|]*")

UNTAGGED = (
    "Not started: start the description of every background command with its tag, so that the wind-down knows "
    "what to do with it: `[await]` for a command that ends by itself and whose result you wait for (a test "
    "run, a build, a CI watch), `[endless]` for one that runs until stopped (a dev server, a watcher, "
    "`tail -f`). Launch it again with its tag."
)

TAGS = (
    "Background commands: start the description of every Bash command you run in the background with its "
    "tag. `[await]`: it ends by itself and you wait for its result (a test run, a build, a CI watch). "
    "`[endless]`: it runs until stopped (a dev server, a watcher, `tail -f`). When this session hands over, "
    "the [await] ones are waited for and the [endless] ones stopped. Subagents need no tag."
)


def guess_tag(command):
    """The tag of an untagged background command, and whether the guess is sure; unsure, it is endless:
    stopped during the wind-down rather than waited for."""
    rest = CI_WATCH_RE.sub(" test ", command)
    endless, done = bool(ENDLESS_RE.search(rest)), bool(AWAIT_RE.search(rest))
    if endless != done:
        return ("endless" if endless else "await"), True
    return "endless", False


def untagged_background(inp):
    """PreToolUse: a background command without its tag is refused once, with the format; launched the same
    way again, it runs, tagged by a guess. Each step is logged, to see why tags go missing."""
    ti = inp.get("tool_input") or {}
    if inp.get("tool_name") != "Bash" or not ti.get("run_in_background") or TAG_RE.match(ti.get("description") or ""):
        return None
    sid, command = inp["session_id"], ti.get("command") or ""
    key = hashlib.sha256(command.encode()).hexdigest()[:16]
    with locked_json(tasks_path(sid)) as tasks:
        refused = tasks.setdefault("refused", {})
        fields = {
            "command": command[:300],
            "description": (ti.get("description") or "")[:200],
            "subagent": bool(inp.get("agent_id")),
            "guided": bool(tasks.get("guided")),
        }
        if key not in refused:
            refused[key] = time.time()
            record("command_untagged", sid, step="refused", **fields)
            return UNTAGGED
        tag, sure = guess_tag(command)
        tasks.setdefault("guessed", {})[key] = tag
    record("command_untagged", sid, step="guessed", tag=tag, sure=sure, **fields)
    return None


def task_tag(task, tasks):
    m = TAG_RE.match(task.get("description") or "")
    if m:
        return m.group(1).lower()
    key = hashlib.sha256((task.get("command") or "").encode()).hexdigest()[:16]
    return (tasks.get("guessed") or {}).get(key, "endless")


def running_shells(inp):
    """The session's background commands still running at Stop, each with its tag."""
    shells = [
        t
        for t in (inp.get("background_tasks") or [])
        if t.get("type") == "shell" and (t.get("status") or "running") not in TASK_DONE
    ]
    if not shells:
        return []
    tasks = read_json(tasks_path(inp["session_id"]), {})
    gave_up = tasks.get("gave_up") or {}
    return [{**t, "tag": "endless" if t.get("id") in gave_up else task_tag(t, tasks)} for t in shells]


def session_process():
    """The claude process this hook runs under, which runs the session's background commands."""
    pid = os.getppid()
    for _ in range(6):
        p = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True, check=False)
        parts = p.stdout.split(None, 1)
        if len(parts) < 2:
            return None
        if os.path.basename(parts[1].strip()) == "claude":
            return pid
        pid = int(parts[0])
    return None


def task_groups(parent, command):
    """The process groups of the background shells `parent` runs `command` in: Claude Code starts each in a
    group of its own, as `zsh -c ... eval '<command>'`."""
    quoted = "eval '" + command.replace("'", "'\"'\"'").replace("\n", "\\012") + "'"
    ps = subprocess.run(
        ["ps", "-axww", "-o", "pid=,ppid=,pgid=,args="], capture_output=True, text=True, check=False
    ).stdout
    groups = []
    for line in ps.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[1] == str(parent) and parts[0] == parts[2] and quoted in parts[3]:
            groups.append(int(parts[2]))
    return groups


def group_alive(g):
    try:
        os.killpg(g, 0)
    except ProcessLookupError:
        return False
    except OSError:
        pass
    return True


def kill_groups(groups):
    """SIGTERM, then SIGKILL what is left after a few seconds. Whether every group is gone."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for g in groups:
            with contextlib.suppress(OSError):
                os.killpg(g, sig)
        for _ in range(30):
            alive = [g for g in groups if group_alive(g)]
            if not alive:
                return True
            time.sleep(0.1)
        groups = alive
    return False


def task_line(t):
    return f"`{t.get('command')}` ({t.get('description') or 'no description'})"


def stop_shells(sid, shells):
    """Kill the background commands the session left running at its wind-down; the lines of those that
    could not be stopped."""
    parent = session_process()
    left = []
    for t in shells:
        groups = task_groups(parent, t.get("command") or "") if parent else []
        ok = bool(groups) and kill_groups(groups)
        record(
            "command_stopped" if ok else "command_left",
            sid,
            task=t.get("id"),
            tag=t["tag"],
            by="plugin",
            command=(t.get("command") or "")[:300],
            description=(t.get("description") or "")[:200],
        )
        if not ok:
            left.append(task_line(t))
    return left


def session_stopped(st, sid, response):
    """A background command the session stopped with TaskStop during the wind-down, before or after being
    asked to: recorded once, and named in the handover."""
    if not isinstance(response, dict) or response.get("task_type") != "local_bash":
        return
    tid, command = response.get("task_id"), response.get("command") or ""
    asked = st.get("stop_asked") or {}
    if tid in asked:
        # Already in `stopped`, and no longer for the next Stop to record.
        asked.pop(tid)
    else:
        line = task_line({"command": command})
        st["stopped"] = st.get("stopped", []) + ([] if line in st.get("stopped", []) else [line])
    record("command_stopped", sid, task=tid, by="session", command=command[:300])


def watch_awaited(st, sid, shells, cfg):
    """One watchdog per [await] command the wind-down waits for: past `await_minutes` it is stopped, which
    wakes the session, and taken for endless."""
    watched = st.setdefault("watched", [])
    parent = session_process()
    for t in shells:
        if t.get("id") in watched or not parent:
            continue
        watched.append(t.get("id"))
        detach(
            [
                "await-timeout",
                "--session",
                sid,
                "--task",
                t.get("id"),
                "--parent",
                str(parent),
                "--seconds",
                str(cfg["await"]),
                f"--command={t.get('command') or ''}",
            ]
        )


def watch_wake(sid, transcript):
    """The safety net of a kill or a notice that should wake the session: see `wake-timeout`."""
    detach(
        [
            "wake-timeout",
            "--session",
            sid,
            "--transcript",
            transcript,
            "--offset",
            str(os.path.getsize(transcript)),
            "--seconds",
            str(WAKE_SECONDS),
        ],
        env={"HANDOVER_CLAUDE_PID": str(claude_pid() or "")},
    )


def turn_since(transcript, offset):
    """Whether a new turn (a message, the notice of a command's end) reached the transcript past `offset`."""
    with contextlib.suppress(OSError), open(transcript, "rb") as f:
        f.seek(offset)
        for line in f.read().decode("utf-8", "replace").splitlines():
            with contextlib.suppress(ValueError):
                if json.loads(line).get("type") in ("user", "assistant"):
                    return True
    return False


def cmd_wake_timeout(args):
    """With no turn woken by the kill or the notice within the wait, write the handover here and hand over without a
    closing reply: the relay resumes with a generic message, the user reads the status line."""
    time.sleep(args.seconds)
    if turn_since(args.transcript, args.offset):
        # That turn's Stop writes the handover.
        return 0
    with locked_state(args.session) as st:
        if st.get("closing_reply") or st.get("reply_due") or not st.get("woken"):
            return 0
        st["reply_due"] = True
        cause = st.get("cause") or "trigger"
    outcome, _ = write_now(args.session, cause, WRITER_TIMEOUT)
    with locked_state(args.session) as st:
        if st.get("closing_reply"):
            return 0
        tokens, _ = T.context_tokens(args.transcript)
        st["closing_reply"] = True
        record("closing_reply_written", args.session, tokens=tokens, reply=False, woken=False, written=outcome)
        hand_over(st, args.session, tokens, config(), None, outcome)
    return 0


def cmd_await_timeout(args):
    """The watchdog of an [await] command the wind-down waits for."""
    time.sleep(args.seconds)
    groups = task_groups(args.parent, args.command)
    if not groups:
        return 0
    with locked_json(tasks_path(args.session)) as tasks:
        tasks.setdefault("gave_up", {})[args.task] = (
            f"`{args.command}` (an [await] command still running after {round(args.seconds / 60)} minutes)"
        )
    record(
        "command_timed_out", args.session, task=args.task, minutes=round(args.seconds / 60), command=args.command[:300]
    )
    kill_groups(groups)
    return 0


def slug(title, words=5):
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    parts = [w for w in re.split(r"[^a-z0-9]+", ascii_title.lower()) if w and w not in ("handover", "handoff")]
    return "-".join(parts[:words]) or "session"


def free_base(d, base):
    """`base`, or base-b, base-c…, the first that no handover uses yet."""
    for suffix in ["", *(f"-{c}" for c in "bcdefghijklmnopqrstuvwxyz")]:
        if not os.path.exists(os.path.join(d, f"{base}{suffix}.md")):
            return base + suffix
    return f"{base}-{int(time.time())}"


def handover_path(st, text, cfg):
    """YYYY/MM/DD/HHhMM-<topic>.md under the handover folder, from when and on what it is written, in a relay
    chain too. A chain is named after its first handover's path, `base`, and numbered in the state."""
    if st.get("path"):
        return st["path"]
    m = re.search(r"^#\s*Hand(?:over|off):\s*(.+)$", text, re.MULTILINE)
    base = free_base(cfg["dir"], f"{time.strftime('%Y/%m/%d/%Hh%M')}-{slug(m.group(1) if m else '')}")
    prev = st.get("relayed_from")
    if prev:
        st["chain"] = {"base": prev["base"], "n": prev["n"] + 1}
    elif relay_on(st):
        st["chain"] = {"base": base, "n": 1}
    return os.path.join(cfg["dir"], f"{base}.md")


def chain_line(st, text, cfg):
    """In a relay chain, a line under the title: the handover's rank and the chain's first handover."""
    chain = st.get("chain")
    if not chain:
        return text
    rank = f"{chain['n']}" if afk_active(st) else f"{chain['n']}/{cfg['relay_limit']}"
    line = f"Relay {rank} · chain started with `{chain['base']}.md`"
    head, sep, rest = text.partition("\n")
    return f"{head}\n\n{line}\n{rest}" if sep and re.match(r"#\s*Hand(?:over|off):", head) else f"{line}\n\n{text}"


def git_snapshot(cwd):
    if not cwd or not os.path.isdir(cwd):
        return None
    out = []
    for args in (["status", "--short", "--branch"], ["log", "--oneline", "-5"]):
        try:
            p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if p.returncode != 0:
            return None
        lines = p.stdout.strip().splitlines()
        out.append("\n".join(lines[:40] + ([f"… {len(lines) - 40} more"] if len(lines) > 40 else [])))
    return "\n\n".join(out)


def render_for_writer(chain):
    text = T.render(chain, "condensed")
    if len(text) > MAX_RENDER_CHARS:
        text = T.render(chain, "tight")
    if len(text) > MAX_RENDER_CHARS:
        head = MAX_RENDER_CHARS // 4
        cut = len(text) - MAX_RENDER_CHARS
        text = (
            f"{text[:head]}\n\n[…{cut} chars of the middle of the session cut…]\n\n{text[-(MAX_RENDER_CHARS - head) :]}"
        )
    return text


def run_writer(cmd, prompt, cwd, progress):
    """Run the writer, streaming its progress to `progress` for the status line; returns its result event."""
    t0 = time.time()
    prog = {
        "since": t0,
        "phase": "starting",
        "input_tokens": 0,
        "thinking_tokens": 0,
        "chars": 0,
        "target": config()["chars"],
    }
    last = 0.0

    def save(force=False):
        nonlocal last
        if force or time.time() - last >= 0.5:
            last = time.time()
            with contextlib.suppress(OSError):
                write_json(progress, prog)

    save(force=True)
    with tempfile.TemporaryFile("w+") as err:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, cwd=cwd)
        killer = threading.Timer(WRITER_TIMEOUT, p.kill)
        killer.start()
        result, tail = None, []
        try:
            p.stdin.write(prompt)
            p.stdin.close()
            for line in p.stdout:
                tail = (tail + [line])[-5:]
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                kind = e.get("type")
                ev = e.get("event") or {}
                if kind == "result":
                    result = e
                elif kind == "system" and e.get("subtype") == "thinking_tokens":
                    prog["phase"] = "thinking"
                elif kind == "stream_event" and ev.get("type") == "message_start":
                    u = (ev.get("message") or {}).get("usage") or {}
                    prog["input_tokens"] = sum(
                        u.get(k) or 0
                        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                    )
                    prog["phase"] = "reading"
                elif kind == "stream_event" and ev.get("type") == "content_block_delta":
                    d = ev.get("delta") or {}
                    if d.get("type") == "thinking_delta":
                        prog["phase"] = "thinking"
                        prog["thinking_tokens"] = max(prog["thinking_tokens"], d.get("estimated_tokens") or 0)
                    elif d.get("type") == "text_delta":
                        prog["phase"] = "writing"
                        prog["chars"] += len(d.get("text") or "")
                save()
            p.wait()
        finally:
            killer.cancel()
            if p.poll() is None:
                p.kill()
        err.seek(0)
        stderr = err.read()
        if result is None:
            raise RuntimeError(f"claude -p exited {p.returncode}: {(stderr or ''.join(tail))[-500:]}")
    # An unknown --model is not an error to claude -p: it says so on stderr and runs its default model.
    result["unknown_model"] = "unrecognized_model" in stderr
    return result


def compose_handover(st, cfg, sid):
    """Render the transcript, have the writer model produce the handover.

    Returns (text, session tokens it was written at, metrics of the writer call).
    """
    tokens, _ = T.context_tokens(st["transcript"])
    chain = T.live_chain(T.load(st["transcript"]))
    meta = T.session_meta(chain)
    head = {k: meta.get(k) for k in ("cwd", "branch", "model")}
    head["files_written"] = ", ".join(T.files_written(chain)[-30:])
    render = render_for_writer(chain)
    prompt = P.external_user(
        head, render, git=git_snapshot(meta.get("cwd")), focus=st.get("focus"), stopped=st.get("stopped")
    )
    cmd = [
        "claude",
        "-p",
        "--safe-mode",
        "--tools",
        "",
        "--no-session-persistence",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--model",
        cfg["writer_model"],
        "--effort",
        "medium",
        "--system-prompt",
        P.external_system(cfg["chars"]),
    ]
    # The writer's own environment block names its cwd: the session's keeps it consistent with the transcript.
    cwd = meta.get("cwd") if os.path.isdir(meta.get("cwd") or "") else data_dir()
    out = run_writer(cmd, prompt, cwd, progress_path(sid))
    text = (out.get("result") or "").strip()
    if out.get("is_error") or not text.startswith("#"):
        raise RuntimeError(f"no handover in the reply: {text[:300] or out.get('subtype')}")
    u = out.get("usage") or {}
    used = out.get("modelUsage") or {}
    info = {
        "render_chars": len(render),
        "writer_cost_usd": out.get("total_cost_usd"),
        "writer_model_used": max(used, key=lambda m: used[m].get("outputTokens") or 0, default=None),
        "writer_model_unknown": out["unknown_model"],
        **{
            f"writer_{k}": u.get(k)
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
        },
    }
    return text + "\n", tokens, info


REQUESTED = (
    "Handover requested. Do not start a new task. End your turn now on one short line saying where the work "
    "stands, without `Ready to hand over` nor the resume message yet. As your turn ends, a separate model "
    "writes the handover from this session's complete transcript; the hook then tells you it is written, and "
    "only then do you write your closing reply. Do not write a handover yourself, and do not read the file "
    "it produces."
)


def cmd_request(args):
    """The handover and relay skills: the session asks to hand over. The handover is written as its turn ends,
    from the complete transcript, so nothing the session closes before that is missing from it; the closing
    reply comes after it."""
    cfg = config()
    sid = args.session
    with locked_state(sid) as st:
        busy = agents_busy(sid)
        if busy:
            print(
                f"handover: {busy} subagent(s) of this session still run. Start no new work and no new "
                "subagent; once their results are in, ask for the handover again.",
                file=sys.stderr,
            )
            return 3
        if not st.get("transcript"):
            st["transcript"] = find_transcript(sid)
        if args.focus is not None:
            st["focus"] = args.focus
        if args.relay and not st.get("relay_on"):
            st["relay_on"] = True
            st.setdefault("relay_start", relay_start())
            # A handover written before the relay was asked for is not part of the chain.
            if not st.get("chain"):
                st.pop("path", None)
        tokens = T.context_tokens(st["transcript"])[0]
        # Asked for in the session: where, and the session's own reason, show in `stats`.
        record(
            "handover_requested",
            sid,
            cause=args.cause,
            tokens=tokens,
            trigger=cfg["trigger"],
            suggest=cfg["suggest"],
            reason=(args.reason or "")[:300] or None,
        )
        if not st.get("wind_down"):
            start_wind_down(st, sid, args.cause, tokens, cfg)
        # The session knows: only the handover and its closing reply are left, due again after an earlier handover.
        st["user_notified"] = st["wind_down_sent"] = True
        for k in ("closing_reply", "reply_due", "reply_reminded", "held_since"):
            st.pop(k, None)
        reset_commands(st, sid)
    print(REQUESTED)
    return 0


def cmd_write(args):
    """Write the handover now: the writer the hooks start, or a handover asked for from a shell."""
    cfg = config()
    sid = args.session
    with locked_state(sid) as st:
        if args.transcript:
            st["transcript"] = args.transcript
        if not st.get("transcript"):
            st["transcript"] = find_transcript(sid)
        if args.focus is not None:
            st["focus"] = args.focus
        cause = args.cause or "cli"
        if not (st.get("wind_down") or st.get("keep_fresh")):
            start_wind_down(st, sid, cause, T.context_tokens(st["transcript"])[0], cfg)
        st["writer"] = {"pid": os.getpid(), "since": time.time()}
        # Left by a writer killed outright: the status line would show its progress until this one's first.
        drop_progress(sid)
        snapshot = dict(st)
    t0 = time.time()

    def on_kill(handler):
        for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(s, handler)

    def killed(signum, _frame):
        raise RuntimeError(f"the writer was killed ({signal.Signals(signum).name})")

    # A writer killed while it composes records its failure, as any other; SIGKILL still leaves only a dead pid.
    on_kill(killed)
    try:
        text, tokens, info = compose_handover(snapshot, cfg, sid)
    except Exception as e:  # noqa: BLE001 - every failure is reported to the user through the state
        on_kill(signal.SIG_DFL)
        with locked_state(sid) as st:
            st["writer"] = None
            st["error"] = {"at": time.time(), "message": str(e)[:1000], "reported": False}
            drop_progress(sid)
        record("writer_finished", sid, cause=cause, ok=False, seconds=round(time.time() - t0), error=str(e)[:300])
        print(f"handover: {e}", file=sys.stderr)
        return 1
    on_kill(signal.SIG_DFL)
    # What the session itself used while the writer ran.
    record(
        "writer_finished",
        sid,
        cause=cause,
        ok=True,
        writer_model=cfg["writer_model"],
        seconds=round(time.time() - t0),
        tokens_start=tokens,
        tokens_done=T.context_tokens(snapshot["transcript"])[0],
        handover_chars=len(text),
        **info,
    )
    with locked_state(sid) as st:
        path = handover_path(st, text, cfg)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(chain_line(st, text, cfg))
        os.replace(tmp, path)
        st["path"] = path
        if st.get("chain"):
            # How the chain was started: `claude-relay` for the whole session, or /handover:relay or /handover:afk.
            start = (
                None
                if st.get("relayed_from")
                else (st.get("relay_start") or ("skill" if st.get("relay_on") else "claude-relay"))
            )
            record(
                "chain_handover_written",
                sid,
                chain=st["chain"]["base"],
                n=st["chain"]["n"],
                cause=cause,
                tokens=tokens,
                start=start,
            )
        st["written"] = {
            "ok": True,
            "tokens": tokens,
            "tokens_done": T.context_tokens(snapshot["transcript"])[0],
            "at": time.time(),
            "seconds": round(time.time() - t0),
        }
        st["writer"] = None
        st.pop("error", None)
        if info["writer_model_unknown"]:
            st["model_warning"] = {
                "reported": False,
                "message": (
                    f"handover: writer_model {cfg['writer_model']!r} is not a model Claude Code knows; the handover was "
                    f"written by {info['writer_model_used']}. Fix writer_model in the plugin's options."
                ),
            }
        else:
            st.pop("model_warning", None)
        # Dropped with the state's update, not before: the status line goes from the progress to the result.
        drop_progress(sid)
    print(path)
    return 0


def find_transcript(sid):
    root = os.path.expanduser("~/.claude/projects")
    for d in os.listdir(root):
        p = os.path.join(root, d, f"{sid}.jsonl")
        if os.path.exists(p):
            return p
    raise SystemExit(f"no transcript for session {sid} under {root}")


def read_handover(st):
    try:
        with open(st["path"], encoding="utf-8") as f:
            text = f.read()
    except (OSError, KeyError):
        return None
    if len(text) > INJECT_CHARS:
        text = text[:INJECT_CHARS] + f"\n\n[… cut here; the full document is {st['path']}]"
    return text


def suggesting(cfg, tokens):
    """Past `suggest_tokens` and still short of the trigger: the session may hand over by itself."""
    s, t = cfg["suggest"], cfg["trigger"]
    return bool(s) and tokens >= s and (not t or tokens < t)


def on_activity(inp, cfg, event):
    """PostToolUse and Stop: suggest a handover, then, once winding down, have the session finish its tasks and hand over.

    Winding down (past the trigger, or asked for with the handover skill), the session is told to start no new task,
    finish the step in progress and wait for its subagents and [await] background commands, then end its
    turn. At the first stop with nothing left to wait for, the hook writes the handover from the complete
    transcript and holds the session until it is written (written while the work went on, it would miss its
    end), then blocks the stop to have the session write its closing reply. The stop after that reply hands
    over: the status line turns to ready, and the relay clears the session. While subagents or [await]
    commands run, a stop is neither the end of the wind-down nor a reason to send the session back; [endless]
    commands still running during the wind-down are stopped.
    """
    if inp.get("agent_id"):
        # A subagent's tool call: the context that fills up, and the handover, are the main session's.
        return None
    sid, tp = inp["session_id"], inp["transcript_path"]
    tokens, _ = T.context_tokens(tp)
    if (
        not os.path.exists(state_path(sid))
        and not (cfg["trigger"] and tokens >= cfg["trigger"])
        and not suggesting(cfg, tokens)
    ):
        return None
    busy = agents_busy(sid, inp if event == "Stop" else None)
    out = {}
    notes = []
    # What is left to do once the lock is released: the writer takes it.
    todo = None
    with locked_state(sid) as st:
        st["transcript"] = tp
        st.setdefault("project", project_of(inp))
        # The session works again: a compaction it was in is over, or was cancelled.
        st.pop("compacting", None)
        if st.get("wind_down") and event == "PostToolUse" and inp.get("tool_name") == "TaskStop":
            session_stopped(st, sid, inp.get("tool_response"))
        if not st.get("wind_down") and not st.get("suggested") and event == "PostToolUse" and suggesting(cfg, tokens):
            st["suggested"] = True
            record("suggestion_sent", sid, tokens=tokens, suggest=cfg["suggest"], trigger=cfg["trigger"])
            later = f"the automatic handover at {cfg['trigger'] // 1000}K" if cfg["trigger"] else "auto-compaction"
            out["hookSpecificOutput"] = {
                "hookEventName": event,
                "additionalContext": SUGGEST.format(tokens=tokens // 1000, suggest=cfg["suggest"] // 1000, later=later),
            }
        if not st.get("wind_down") and cfg["trigger"] and tokens >= cfg["trigger"]:
            start_wind_down(st, sid, "trigger", tokens, cfg)
        wind_down, closing = st.get("wind_down"), st.get("wind_down") and not st.get("closing_reply")
        if wind_down and not st.get("user_notified"):
            st["user_notified"] = True
            record("user_notified", sid, tokens=tokens)
            notes.append(
                f"handover: context at {tokens // 1000}K tokens. The session starts no new task and finishes "
                "those in progress; the handover is written then, and the session's closing reply follows it."
            )
        if closing and not st.get("wind_down_sent") and event == "PostToolUse":
            st["wind_down_sent"] = True
            out["hookSpecificOutput"] = {
                "hookEventName": event,
                "additionalContext": WIND_DOWN.format(tokens=tokens // 1000, await_minutes=cfg["await"] // 60),
            }
        shells = running_shells(inp) if event == "Stop" and closing else []
        awaited = [t for t in shells if t["tag"] == "await"]
        due = (
            [a for a in T.notifications_due(tp) if a not in st.get("notices_awaited", [])]
            if event == "Stop" and closing and not busy and not st.get("reply_due")
            else []
        )
        if event == "Stop" and busy:
            # The turn ends while subagents work: Claude Code wakes the session with their results.
            # Neither hand over, nor send it back to work, nor take this stop for idleness.
            record("wind_down_held", sid, tokens=tokens, **{"for": "agents"}, agents=busy)
        elif awaited:
            # Their end wakes the session, as a subagent's result does; a watchdog stops those that run too long.
            watch_awaited(st, sid, awaited, cfg)
            record("wind_down_held", sid, tokens=tokens, **{"for": "commands"}, commands=len(awaited))
        elif due:
            # A subagent's report came in before the notice of its end, which wakes the session once more: the
            # handover is written at that turn's stop, or by the safety net if the notice never comes.
            st["notices_awaited"] = st.get("notices_awaited", []) + due
            st["woken"] = {"at": time.time()}
            watch_wake(sid, tp)
            record("wind_down_held", sid, tokens=tokens, **{"for": "notifications"}, agents=len(due))
        elif event == "Stop" and closing:
            last = inp.get("last_assistant_message") or T.last_assistant_text(tp)
            gave_up = (read_json(tasks_path(sid), {}).get("gave_up") or {}).values()
            st["stopped"] = st.get("stopped", []) + [x for x in gave_up if x not in st.get("stopped", [])]
            asked = st.get("stop_asked")
            if asked is not None:
                running_ids = {t.get("id") for t in shells}
                for tid, line in asked.items():
                    if tid not in running_ids:
                        record("command_stopped", sid, task=tid, by="session", command=line[:300])
                # Recorded once: a later stop of this wind-down does not count them again.
                st["stop_asked"] = {tid: line for tid, line in asked.items() if tid in running_ids}
            if shells and asked is None:
                # [endless], or [await] given up on: the session stops them itself, with TaskStop, which
                # Claude Code does not report back. A command the plugin kills wakes the session once more.
                st["stop_asked"] = {t.get("id"): task_line(t) for t in shells}
                st["stopped"] = st.get("stopped", []) + list(st["stop_asked"].values())
                st["wind_down_sent"] = True
                out["decision"] = "block"
                out["reason"] = STOP_ENDLESS.format("; ".join(f"{t.get('id')}: {task_line(t)}" for t in shells))
            else:
                killed = 0
                if shells:
                    # Still running once the session was asked: the plugin stops them.
                    left = stop_shells(sid, shells)
                    killed = len(shells) - len(left)
                    st["stop_asked"] = {}
                    st["stopped"] += [task_line(t) for t in shells if task_line(t) not in st["stopped"]]
                    if left:
                        notes.append("handover: could not stop " + ", ".join(left) + "; stop it by hand.")
                if killed:
                    # The notice of their failure wakes the session for one more turn: the handover is written
                    # at its stop, once, so that it includes that turn.
                    st["woken"] = {"at": time.time()}
                    watch_wake(sid, tp)
                    record("wind_down_held", sid, tokens=tokens, **{"for": "wake"}, killed=killed)
                elif not st.get("reply_due"):
                    # Nothing left running: the handover is written now, from all of it, before the closing reply.
                    todo = "write"
                elif CLEAR_RE.search(last) or st.get("reply_reminded"):
                    st["closing_reply"] = True
                    record(
                        "closing_reply_written",
                        sid,
                        tokens=tokens,
                        reply=bool(CLEAR_RE.search(last)),
                        woken=bool(st.get("woken")),
                    )
                    todo = "hand_over"
                    note = afk_declared_end(st, sid, last) if afk_active(st) else None
                    if note:
                        # The run is over: its last handover relays to no new session.
                        st["relay_outcome"] = {"afk": st["afk"]["ended"], "n": chain_n(st)}
                        notes.append(note)
                else:
                    st["reply_reminded"] = True
                    out["decision"] = "block"
                    out["reason"] = CLOSING_REPLY.format(written=written_line(st))
        afk_out = None if event == "Stop" and (busy or todo) else afk_on_activity(st, sid, inp, event)
        if afk_out:
            ctx = afk_out.pop("hookSpecificOutput", None)
            if ctx and "hookSpecificOutput" not in out:
                out["hookSpecificOutput"] = ctx
            if "decision" not in out:
                out.update({k: v for k, v in afk_out.items() if k in ("decision", "reason")})
            notes.append(afk_out.get("systemMessage"))
        err = st.get("error")
        if err and not err.get("reported"):
            err["reported"] = True
            notes.append(f"handover: writing the handover failed: {err['message'][:300]}")
        notes.append(model_warning(st))
    if todo == "write":
        out.update(ask_closing_reply(sid, tokens, notes))
    elif todo == "hand_over":
        notes.append(close(sid, cfg, inp.get("last_assistant_message") or T.last_assistant_text(tp)))
    if todo:
        with locked_state(sid) as st:
            notes.append(model_warning(st))
    notes = [n for n in notes if n]
    if notes:
        out["systemMessage"] = "\n".join(notes)
    return out or None


def model_warning(st):
    """The writer ran on another model than writer_model: told the user once."""
    w = st.get("model_warning")
    if not w or w["reported"]:
        return None
    w["reported"] = True
    return w["message"]


def written_line(st):
    """Where the handover stands, for the session's closing reply."""
    if writer_running(st):
        return "The handover is still being written; the new session waits for it."
    if (st.get("written") or {}).get("ok") and not st.get("write_failed"):
        return f"The handover is written: {st.get('path')}. Do not read it."
    return (
        "The handover could not be written: say so in your reply, and make the resume message complete "
        "enough to resume without it (what was done, the files involved, the very next step)."
    )


def ask_closing_reply(sid, tokens, notes):
    """Stop, nothing left running: write the handover, holding the session until it is written, then block
    the stop to have the session write its closing reply. The status line shows the writer meanwhile."""
    t0 = time.time()
    with locked_state(sid) as st:
        cause = st.get("cause") or "trigger"
        st["held_since"] = t0
    outcome, _ = write_now(sid, cause, STOP_WRITE_SECONDS)
    with locked_state(sid) as st:
        st["reply_due"] = True
        st["write_failed"] = outcome == "failed"
        record("closing_reply_asked", sid, tokens=tokens, written=outcome, held_s=round(time.time() - t0))
        err = st.get("error") or {}
        if outcome == "failed":
            err["reported"] = True
            notes.append(f"handover: writing the handover failed: {err.get('message', '')[:300]}")
        loads = "" if outcome == "failed" else " The new session loads the handover by itself."
        return {"decision": "block", "reason": WRITTEN.format(written=written_line(st), loads=loads)}


def close(sid, cfg, last):
    """Stop after the closing reply: the handover is ready, so hand over; returns a note for the user.

    A session that went on past `refresh_tokens` after the handover was written, or whose handover failed, has
    it written again first, so that the next session loads it at once."""
    tokens, _ = T.context_tokens(read_json(state_path(sid), {}).get("transcript") or "")
    with locked_state(sid) as st:
        stale = not writer_running(st) and needs_refresh(st, tokens)
    outcome, _ = write_now(sid, "reply", STOP_WRITE_SECONDS) if stale else (None, None)
    with locked_state(sid) as st:
        if outcome is None:
            outcome = "slow" if writer_running(st) else "failed" if st.get("write_failed") else "written"
        st["write_failed"] = outcome == "failed"
        return hand_over(st, sid, tokens, cfg, resume_message(last), outcome)


def hand_over(st, sid, tokens, cfg, message, outcome):
    """The closing reply is written, after the handover: relay when the relay is on. Returns a note."""
    if outcome == "failed":
        if relay_on(st) and not st.get("relay_outcome"):
            # The new session would start without the handover: the user takes over.
            st["relay_outcome"] = {"failed": True, "n": chain_n(st)}
            record(
                "relay_failed",
                sid,
                chain=(st.get("chain") or {}).get("base"),
                n=chain_n(st),
                tokens=tokens,
                why="writer",
            )
            alert("Relay halted: the handover could not be written. Run /clear.")
        return (
            f"handover: the handover could not be written; /clear starts the next session without it. To retry: "
            f"python3 {os.path.abspath(__file__)} write --session {sid}"
        )
    note = relay(st, sid, tokens, cfg, message)
    if note or relay_on(st) and not (st.get("relay_outcome") or {}).get("afk"):
        return note
    if outcome == "slow":
        return "handover: the handover is still being written. Run /clear: the new session waits for it and loads it."
    return f"handover: {st.get('path')} is ready. Run /clear: the new session loads it right away."


CLEAR_RE = re.compile(r"/clear\b")


def resume_message(reply):
    """The message to send after /clear, from the code block the closing reply ends on, on one line."""
    m = CLEAR_RE.search(reply or "")
    block = re.search(r"```[^\n]*\n(.*?)```", reply[m.end() :], re.DOTALL) if m else None
    return " ".join(block.group(1).split()) if block else None


def relay_on(st):
    """Launched by claude-relay, started by the relay, or relay asked for with `request --relay`."""
    return os.environ.get("HANDOVER_RELAY") == "1" or bool(st.get("relay_on") or st.get("relayed_from"))


def relay_start():
    """How this session's relay was turned on, for `stats`."""
    return "claude-relay" if os.environ.get("HANDOVER_RELAY") == "1" else "skill"


def relay_path(project):
    return os.path.join(data_dir(), "relay", f"{project_key(project)}.json")


def relay_marker(sid):
    return os.path.join(data_dir(), "relay", f"{sid}.loaded.json")


def chain_n(st):
    """The number of this session's handover in its relay chain, known before the handover is written."""
    return (st.get("chain") or {}).get("n") or (st.get("relayed_from") or {}).get("n", 0) + 1


def relay(st, sid, tokens, cfg, message):
    """Hand the session over without the user, once its closing reply is written; returns a note for the user.

    In tmux, a detached `relay-drive` types /clear into the session's pane; the new session waits for the
    writer and loads the handover, then the resume message is typed. Under the claude-relay loop, outside
    tmux, it leaves the message for the loop and ends claude, which the loop restarts. A chain stops at
    `relay_limit`.
    """
    if not relay_on(st) or st.get("relay_outcome"):
        return None
    # The chain's name comes from the handover's title: unknown until its first handover is written.
    chain = st.get("chain") or {}
    n, limit = chain_n(st), cfg["relay_limit"]
    afk = afk_active(st)
    if afk and afk_overdue(afk):
        st["relay_outcome"] = {"limit": True, "n": n, "deadline": True}
        afk_end(st, sid, "deadline", f"deadline {fmt_until(afk['until'])} passed after {n} handovers")
        return "handover: AFK deadline passed, no new session. Run /clear to continue from its handover."
    if n >= limit and not afk:
        st["relay_outcome"] = {"limit": True, "n": n}
        record("relay_limit_reached", sid, chain=chain.get("base"), n=n, tokens=tokens)
        alert(f"Relay halted at {n} handovers. Run /clear to continue from the last one.")
        return f"handover: relay halted at its limit of {limit} handovers. Run /clear to continue from the last one."
    pane = os.environ.get("TMUX_PANE")
    loop = os.environ.get("HANDOVER_RELAY_FILE")
    pid = None if pane or not loop else claude_pid()
    if not pane and not pid:
        st["relay_outcome"] = {"failed": True, "n": n}
        record("relay_failed", sid, chain=chain.get("base"), n=n, tokens=tokens)
        alert("Relay impossible: this session runs neither in tmux nor under claude-relay. Run /clear.")
        return "handover: cannot relay outside tmux or claude-relay. Run /clear."
    from_reply = bool(message)
    message = message or "Continue the work from the handover loaded above."
    write_json(
        relay_path(st.get("project") or os.getcwd()),
        {"session": sid, "at": time.time(), "mode": "tmux" if pane else "loop"},
    )
    cmd = ["relay-drive", "--session", sid]
    if pane:
        cmd += ["--pane", pane, "--message", message]
    else:
        with open(loop, "w", encoding="utf-8") as f:
            f.write(message)
        cmd += ["--kill", str(pid)]
    detach(cmd)
    st["relay_outcome"] = {"at": time.time(), "n": n, "mode": "tmux" if pane else "loop"}
    record(
        "relay_launched",
        sid,
        chain=chain.get("base"),
        n=n,
        mode=st["relay_outcome"]["mode"],
        tokens=tokens,
        message_from_reply=from_reply,
    )
    return f"handover: relaying to a fresh session, handover {n}" + ("." if afk else f" of at most {limit}.")


AFK_RULES = (
    "AFK mode: the user is away{until}, and this run goes on, session after session, until its goal is met. "
    "Goal: {goal}\n"
    "Work toward it without asking the user anything: take the next item, do it, verify it, commit it as the "
    "repo's rules say, then take the next.{delegate} When only the user can unblock an item, note the question where "
    "the work is tracked (or in your reply) and move on to another item. Once the handover hook suggests it, "
    "hand over at the boundary between two items: the relay starts a fresh session that carries on. A stop "
    "of yours is sent back to you, unless your reply ends on one of these lines: `AFK done: <why>` once the "
    "goal is met, `AFK blocked: <why>` once nothing left can move without the user.{yolo}"
)

AFK_DELEGATE = (
    " Hand each item, or each self-contained part of one, to a subagent with a complete brief, and check "
    "its report and its diff before you commit: this session's context then lasts across many items."
)

AFK_CONTINUE = (
    "AFK mode{until}: the user is away, keep going toward the goal: {goal}\n"
    "Take the next item now. If the goal is met, or nothing left can move without the user, end your reply "
    "on `AFK done: <why>` or `AFK blocked: <why>`."
)

AFK_DEADLINE = (
    "The AFK deadline ({until}) has passed: do not start a new task. Finish the step in progress so the files and "
    "the git state are coherent, then end your reply on `AFK done: deadline, <where the work stands>`."
)

AFK_END_RE = re.compile(r"^\W*AFK (done|blocked):\s*(.*)$", re.MULTILINE | re.IGNORECASE)
# Stops sent back in a row without a tool call in between: the session has nothing left to do.
AFK_IDLE_MAX = 3


def parse_until(spec, now=None):
    """An AFK deadline: a time (`8`, `8:30`, `8h30`, `8am`: the next one to come), a day and a time
    (`tomorrow 8`, `mon 9:00`), a duration (`+10h`, `in 2h30m`), `2026-10-06 08:00`, or `@<epoch>`."""
    now = now or datetime.now()
    s = spec.strip().lower()
    if s.startswith("@"):
        return datetime.fromtimestamp(int(s[1:]))
    # A duration needs `+` or `in`: a bare `8h` is a time, as in `8h30`.
    m = re.fullmatch(r"(?:\+|in\s+)(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?", s)
    if m and (m.group(1) or m.group(2)):
        return now + timedelta(hours=int(m.group(1) or 0), minutes=int(m.group(2) or 0))
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(spec.strip())
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    m = re.fullmatch(
        r"(?:(today|tomorrow|tmrw|(?:mon|tue|wed|thu|fri|sat|sun)\w*)\s+(?:at\s+)?)?"
        r"(\d{1,2})(?:[:h](\d{2})?)?\s*(am|pm)?",
        s,
    )
    if not m:
        raise ValueError(f"cannot read the deadline {spec!r}: try 8, 8:30, tomorrow 8, mon 9:00, +10h")
    day, hour, minute, ampm = m.group(1), int(m.group(2)), int(m.group(3) or 0), m.group(4)
    if ampm:
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    if hour > 23 or minute > 59:
        raise ValueError(f"no such time: {spec!r}")
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day == "today":
        pass
    elif day in ("tomorrow", "tmrw"):
        at += timedelta(days=1)
    elif day:
        at += timedelta(days=(days.index(day[:3]) - now.weekday()) % 7)
        if at <= now:
            at += timedelta(days=7)
    elif at <= now:
        at += timedelta(days=1)
    if at <= now:
        raise ValueError(f"the deadline {spec!r} is already past")
    return at


def fmt_until(epoch):
    return datetime.fromtimestamp(epoch).strftime("%a %d %b %H:%M")


def afk_active(st):
    afk = st.get("afk")
    return afk if afk and not afk.get("ended") else None


def afk_overdue(afk):
    return bool(afk.get("until")) and time.time() >= afk["until"]


AFK_YOLO = (
    "\nYOLO: this run skips permission prompts. Every tool call goes to an audit log the user reads "
    "afterwards, with what would have needed their approval. Deny rules still apply, and the handover "
    "plugin, its data and the Claude Code settings files are off limits: leave them alone."
)


def afk_texts(afk):
    until = f" until {fmt_until(afk['until'])}" if afk.get("until") else ""
    return {
        "until": until,
        "goal": afk["goal"],
        "yolo": AFK_YOLO if afk.get("yolo") else "",
        "delegate": AFK_DELEGATE if config()["delegate"] else "",
    }


def afk_start(st, sid, goal, until, how, yolo=False):
    """Turn AFK mode on in this session's state, as a new run."""
    st["afk"] = {
        "goal": goal,
        "until": until,
        "run": f"{time.strftime('%y%m%d-%H%M')}-{sid[:4]}",
        "since": time.time(),
        "yolo": yolo,
    }
    st["relay_on"] = True
    st.setdefault("relay_start", relay_start())
    extra = {}
    if yolo:
        # What the audit compares against, and the plugin as it was when the run started.
        st["afk"]["baseline"] = extra["baseline"] = baseline_mode(st.get("project"))
        extra.update(plugin_root=plugin_root(), plugin_sha=plugin_sha())
    record("afk_started", sid, run=st["afk"]["run"], how=how, until=until, goal=goal[:200], yolo=yolo, **extra)
    return st["afk"]


def afk_end(st, sid, kind, reason):
    afk = st["afk"]
    afk["ended"] = kind
    afk["reason"] = reason
    # The audit log's length and last hash, kept apart from it: a cut or rewritten log no longer matches.
    lines, head = audit_head(afk["run"])
    record(
        "afk_ended",
        sid,
        run=afk["run"],
        kind=kind,
        reason=(reason or "")[:300],
        hours=round((time.time() - afk["since"]) / 3600, 1),
        **({"audit_lines": lines, "audit_head": head} if lines else {}),
    )
    alert(f"AFK run {kind}: {reason}"[:200])


def afk_declared_end(st, sid, last):
    """End the run on the `AFK done:` or `AFK blocked:` line the session's reply ends it with; returns a note."""
    ends = AFK_END_RE.findall(last or "")
    if not ends:
        return None
    kind, why = ends[-1]
    afk_end(st, sid, kind.lower(), why.strip())
    return f"handover: AFK run {kind.lower()}: {why.strip()[:200]}"


def afk_on_activity(st, sid, inp, event):
    """PostToolUse: the session works; Stop: send it back to work, unless it declared the run over."""
    afk = afk_active(st)
    if not afk:
        return None
    if event == "PostToolUse":
        st["afk_idle"] = st["afk_denied"] = 0
        if afk_overdue(afk) and not afk.get("deadline_told"):
            afk["deadline_told"] = True
            return {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": AFK_DEADLINE.format(until=fmt_until(afk["until"])),
                }
            }
        return None
    # A wind-down under way, or one the relay could not make: the handover flow owns this stop.
    if (st.get("wind_down") and not st.get("closing_reply")) or st.get("relay_outcome"):
        return None
    last = inp.get("last_assistant_message") or T.last_assistant_text(inp["transcript_path"]) or ""
    note = afk_declared_end(st, sid, last)
    if note:
        return {"systemMessage": note}
    if afk_overdue(afk):
        afk_end(st, sid, "deadline", f"deadline {fmt_until(afk['until'])} passed")
        return None
    st["afk_idle"] = st.get("afk_idle", 0) + 1
    if st["afk_idle"] > AFK_IDLE_MAX:
        # Denied calls are not work: a session whose every call is denied stands still all the same.
        n = st.get("afk_denied", 0)
        denied = f", {n} tool call{'s' * (n > 1)} denied" if n else ""
        afk_end(st, sid, "idle", f"stopped {AFK_IDLE_MAX} times in a row without working{denied}")
        return None
    record("afk_sent_back", sid, run=afk["run"], idle=st["afk_idle"])
    return {"decision": "block", "reason": AFK_CONTINUE.format(**afk_texts(afk))}


def cmd_afk(args):
    """The afk skill: AFK mode on (or off) in a running session, which must be able to relay."""
    with locked_state(args.session) as st:
        if args.off:
            if not afk_active(st):
                print("handover: AFK mode is not on in this session.")
                return 0
            afk_end(st, args.session, "off", "turned off by the user")
            print("handover: AFK mode off. The relay stays on, within relay_limit.")
            return 0
        if not os.environ.get("TMUX_PANE") and not os.environ.get("HANDOVER_RELAY_FILE"):
            print("handover: AFK mode needs tmux (start Claude Code with gmux or claude-relay).", file=sys.stderr)
            return 1
        try:
            until = parse_until(args.until).timestamp() if args.until else None
        except ValueError as e:
            print(f"handover: {e}", file=sys.stderr)
            return 1
        if not args.goal:
            print("handover: AFK mode needs a goal.", file=sys.stderr)
            return 1
        st.setdefault("project", os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        afk = afk_start(st, args.session, args.goal, until and round(until), "skill")
    print(AFK_RULES.format(**afk_texts(afk)))
    return 0


def cmd_until(args):
    try:
        at = parse_until(" ".join(args.when))
    except ValueError as e:
        print(f"handover: {e}", file=sys.stderr)
        return 1
    left = at - datetime.now()
    print(
        f"AFK until {at.strftime('%a %d %b %H:%M')} (in {left.days * 24 + left.seconds // 3600}h"
        f"{left.seconds % 3600 // 60:02d})",
        file=sys.stderr,
    )
    print(round(at.timestamp()))
    return 0


def plugin_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plugin_sha(root=None):
    """One hash over the plugin's hooks and scripts: a run that edits them changes it."""
    root, h = root or plugin_root(), hashlib.sha256()
    files = [os.path.join(root, "hooks", "hooks.json"), *sorted(glob.glob(os.path.join(root, "scripts", "*")))]
    for f in files:
        if os.path.isfile(f):
            h.update(os.path.relpath(f, root).encode())
            with open(f, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:16]


def guarded_paths(project=None):
    """What a YOLO run must not write: the plugin, its data (audit log included), the settings that load
    them, and the user's own `yolo_guard_paths`. Its own memory and worktrees under ~/.claude stay writable."""
    home = os.path.expanduser("~")
    paths = [
        plugin_root(),
        data_dir(),
        os.path.join(home, ".claude", "plugins"),
        os.path.join(home, ".claude", "settings.json"),
        os.path.join(home, ".claude", "settings.local.json"),
        os.path.join(home, ".claude", "hooks"),
    ]
    paths += [os.path.expanduser(p) for p in re.split(r"[\s,]+", option("yolo_guard_paths", "")) if p]
    if project:
        paths += [
            os.path.join(project, ".claude", "settings.json"),
            os.path.join(project, ".claude", "settings.local.json"),
        ]
    return sorted({os.path.realpath(p) for p in paths} | {os.path.abspath(p) for p in paths})


def cmd_yolo_settings(args):
    """The --settings a YOLO run starts with: deny rules, which bypassPermissions still enforces. With
    `--merge`, the user's own --settings (a JSON string or a file) gets them added: claude takes one --settings."""
    settings = {}
    if args.merge:
        try:
            settings = json.loads(args.merge)
        except ValueError:
            try:
                with open(os.path.expanduser(args.merge), encoding="utf-8") as f:
                    settings = json.load(f)
            except (OSError, ValueError) as e:
                print(f"yolo-settings: cannot read --settings {args.merge}: {e}", file=sys.stderr)
                return 2
        if not isinstance(settings, dict):
            print("yolo-settings: --settings is not a JSON object", file=sys.stderr)
            return 2
    deny = settings.setdefault("permissions", {}).setdefault("deny", [])
    for p in guarded_paths(os.getcwd()):
        rule = "//" + p.lstrip("/")
        # A path without an extension that is not a file yet may be either: both rules.
        rules = (
            [f"Edit({rule})"] if os.path.isfile(p) or os.path.splitext(p)[1] else [f"Edit({rule})", f"Edit({rule}/**)"]
        )
        deny += [r for r in rules if r not in deny]
    print(json.dumps(settings))
    return 0


# Ways to write a guarded path, or to unload the plugin, that a Bash command may spell.
GUARD_WORDS = re.compile(r"\bclaude\s+plugins?\s+(disable|uninstall|remove|update)\b|disableAllHooks|chflags")


def guard_hit(inp):
    """The guarded path or word a tool call names, if any. Bash commands are matched as text, so a path
    spelled `~/.claude/plugins` or `$HOME/.claude/plugins` counts too; reading tools stay free."""
    tool, ti = inp.get("tool_name") or "", inp.get("tool_input") or {}
    if tool in ("Read", "Glob", "Grep", "LS"):
        return None
    home = os.path.expanduser("~")
    text = " ".join(str(ti.get(k) or "") for k in ("command", "file_path", "notebook_path", "path"))
    if not text.strip():
        return None
    for p in guarded_paths(project_of(inp)):
        forms = {p}
        if p.startswith(home + os.sep):
            rest = p[len(home) :]
            forms |= {"~" + rest, "$HOME" + rest, "${HOME}" + rest}
        if any(f in text for f in forms):
            return p
    m = GUARD_WORDS.search(text) if tool == "Bash" else None
    return m.group(0) if m else None


def on_pre_tool_use(inp):
    """No background command without its tag; no new subagent once the session winds down; in a YOLO run,
    nothing that writes the plugin, its audit log or the settings that load it."""
    sid = inp["session_id"]
    reason = untagged_background(inp)
    st = read_json(state_path(sid), {})
    if not st and not reason:
        return None
    tool = inp.get("tool_name") or ""
    if not reason and tool in ("Agent", "Task", "Workflow") and refuses_agents(st):
        reason = NO_NEW_AGENT
        record("agent_refused", sid, tool=tool, agent=(inp.get("tool_input") or {}).get("subagent_type"))
    afk = afk_active(st)
    if not reason and afk and yolo_on(afk, inp):
        hit = guard_hit(inp)
        if hit:
            reason = (
                f"Denied: this YOLO run must leave {hit} alone (the handover plugin, its audit log and the "
                "settings that load them). Do the work another way, or note it for the user."
            )
            audit_write(afk, inp, "guarded", hit)
    if not reason:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def yolo_on(afk, inp):
    return bool(afk.get("yolo")) or inp.get("permission_mode") == "bypassPermissions"


def audit_path(run):
    return os.path.join(data_dir(), "audit", f"{run}.jsonl")


def audit_line_hash(prev, entry):
    return hashlib.sha256((prev + json.dumps(entry, sort_keys=True)).encode()).hexdigest()[:16]


def audit_head(run):
    """(lines, hash of the last line) of a run's audit log; (0, None) without one."""
    try:
        with open(audit_path(run), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return 0, None
    try:
        return len(lines), json.loads(lines[-1]).get("h") if lines else None
    except ValueError:
        return len(lines), None


def audit_entries(run):
    """A run's audit log as (entries, lines that are not JSON)."""
    entries, bad = [], 0
    with contextlib.suppress(OSError), open(audit_path(run), encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except ValueError:
                bad += 1
    return entries, bad


def audit_write(afk, inp, verdict, why=None):
    """Append one tool call to the run's audit log: who, which tool, its command or path, never file contents,
    and whether it would have run without YOLO. Each line chains the hash of the one before."""
    tool, ti = inp.get("tool_name") or "", inp.get("tool_input") or {}
    entry = {
        "at": round(time.time()),
        "session": inp["session_id"][:8],
        "tool": tool,
        "target": tool_target(tool, ti),
        "verdict": verdict,
    }
    if why:
        entry["why"] = why
    if inp.get("agent_id"):
        entry["agent"] = inp.get("agent_type") or inp["agent_id"]
    path = audit_path(afk["run"])
    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(max(0, f.seek(0, os.SEEK_END) - 8192))
            tail = f.read().splitlines()
            prev = ""
            with contextlib.suppress(ValueError, IndexError):
                prev = json.loads(tail[-1]).get("h") or ""
            entry["h"] = audit_line_hash(prev, entry)
            f.write(json.dumps(entry) + "\n")


def tool_target(tool, ti):
    """What a tool call acts on, in one short line: a command, a path, a URL, never the content written."""
    if tool == "Bash":
        return " ".join(str(ti.get("command") or "").split())[:300]
    for k in ("file_path", "notebook_path", "url"):
        if ti.get(k):
            return str(ti[k])
    if tool in ("Glob", "Grep"):
        return f"{ti.get('pattern')} in {ti.get('path') or '.'}"
    if tool in ("Agent", "Task"):
        return f"{ti.get('subagent_type') or 'agent'}: {ti.get('description') or ''}"[:200]
    if tool == "WebSearch":
        return str(ti.get("query"))[:200]
    if tool == "Skill":
        return str(ti.get("skill") or ti.get("command"))
    return json.dumps(
        {k: v for k, v in ti.items() if k not in ("content", "new_string", "old_string", "edits")}, ensure_ascii=False
    )[:200]


# Tools that run without a prompt in every mode.
FREE_TOOLS = {
    "TodoWrite",
    "TodoRead",
    "Agent",
    "Task",
    "ToolSearch",
    "AskUserQuestion",
    "ExitPlanMode",
    "EnterPlanMode",
    "TaskCreate",
    "TaskUpdate",
    "TaskList",
    "TaskGet",
    "TaskOutput",
    "TaskStop",
    "SendMessage",
    "ListAgents",
    "ScheduleWakeup",
    "CronList",
    "Monitor",
    "LSP",
}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
READONLY_CMDS = {
    "ls",
    "cat",
    "echo",
    "pwd",
    "head",
    "tail",
    "grep",
    "find",
    "wc",
    "which",
    "diff",
    "stat",
    "du",
    "cd",
    "true",
    "printf",
    "file",
    "basename",
    "dirname",
    "realpath",
    "date",
    "test",
    "[",
}
READONLY_GIT = {
    "status",
    "log",
    "diff",
    "show",
    "rev-parse",
    "ls-files",
    "blame",
    "branch",
    "remote",
    "describe",
    "shortlog",
    "merge-base",
    "cat-file",
    "ls-tree",
    "reflog",
    "worktree",
}
PROTECTED_DIRS = {".git", ".vscode", ".idea", ".husky", ".cargo", ".devcontainer", ".yarn", ".mvn", ".claude"}
PROTECTED_FILES = {
    ".gitconfig",
    ".gitmodules",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".bash_aliases",
    ".bash_logout",
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".zlogin",
    ".zlogout",
    ".profile",
    ".envrc",
    ".npmrc",
    ".yarnrc",
    ".yarnrc.yml",
    ".pre-commit-config.yaml",
    "lefthook.yml",
    ".mcp.json",
    ".claude.json",
    ".devcontainer.json",
}


def baseline_mode(project):
    """The mode the run would have had without YOLO: defaultMode from the settings files, local first."""
    for f in settings_files(project):
        mode = ((read_json(f, {}) or {}).get("permissions") or {}).get("defaultMode")
        if mode and mode != "bypassPermissions":
            return mode
    return "default"


def settings_files(project):
    home = os.path.join(os.path.expanduser("~"), ".claude")
    files = [os.path.join(project, ".claude", n) for n in ("settings.local.json", "settings.json")] if project else []
    return files + [os.path.join(home, "settings.local.json"), os.path.join(home, "settings.json")]


def allow_rules(project):
    rules = []
    for f in settings_files(project):
        rules += ((read_json(f, {}) or {}).get("permissions") or {}).get("allow") or []
    return rules


def rule_regex(pattern, path=False):
    """A permission rule's pattern as a regex: `*` any text in a command; in a path, `*` one segment, `**` any."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i) and path:
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + ("[^/]*" if path else ".*"), i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + ("(/.*)?" if path else "") + r"\Z", re.DOTALL)


def rule_path(spec, project):
    if spec.startswith("//"):
        return spec[1:]
    if spec.startswith("~/"):
        return os.path.expanduser(spec)
    if spec.startswith("/"):
        return os.path.join(project or "/", spec[1:])
    spec = spec.removeprefix("./")
    return os.path.join(project or "", spec) if "/" in spec else os.path.join(project or "", "**", spec)


def allowed_by(tool, ti, rules, project, part=None):
    """The allow rule that covers this call (one Bash subcommand when `part` is given), if any."""
    for r in rules:
        m = re.fullmatch(r"([\w*-]+)(?:\((.*)\))?", r.strip(), re.DOTALL)
        if not m:
            continue
        name, arg = m.group(1), m.group(2)
        if tool.startswith("mcp__"):
            if fnmatch.fnmatchcase(tool, name) or tool.startswith(name + "__"):
                return r
            continue
        same = name == tool or (name == "Edit" and tool in EDIT_TOOLS)
        if not same:
            continue
        if arg is None or arg in ("", "*"):
            return r
        if tool == "Bash" and part is not None:
            pat = arg[:-2] + " *" if arg.endswith(":*") else arg
            if rule_regex(pat).match(part) or (pat.endswith(" *") and part == pat[:-2]):
                return r
        elif tool == "WebFetch" and arg.startswith("domain:"):
            host = re.sub(r"^\w+://", "", ti.get("url") or "").split("/")[0].split(":")[0]
            if fnmatch.fnmatchcase(host, arg[7:]):
                return r
        elif tool in EDIT_TOOLS or tool == "Read":
            target = ti.get("file_path") or ti.get("notebook_path") or ""
            if rule_regex(rule_path(arg, project), path=True).match(target):
                return r
        elif arg and tool not in ("Bash", "WebFetch") and arg in json.dumps(ti):
            return r
    return None


def bash_parts(command):
    """A command split on its operators, the way permission rules check each subcommand."""
    return [p.strip() for p in re.split(r"&&|\|\||;|\||\n", command) if p.strip()]


def readonly_part(part):
    if re.search(r"(^|[^0-9&])>(?!\s*/dev/null)", part):
        return False
    words = part.split()
    if not words:
        return True
    if words[0] == "git":
        rest = [w for w in words[1:] if not w.startswith("-")]
        return bool(rest) and rest[0] in READONLY_GIT
    return words[0] in READONLY_CMDS


def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def protected(path):
    parts = os.path.normpath(path).split(os.sep)
    if os.path.basename(path) in PROTECTED_FILES:
        return True
    for i, d in enumerate(parts[:-1]):
        if d in PROTECTED_DIRS:
            # Claude's own worktrees and auto memory under .claude stay unprotected.
            return not (d == ".claude" and parts[i + 1 : i + 2] in (["worktrees"], ["projects"]))
    return False


def classify(inp, baseline):
    """Would this call have run without YOLO, in the run's baseline mode?

    `read-only` and `free`: no prompt in any mode; `rule`: an allow rule covers it (named in `why`);
    `mode`: the baseline mode allows it (edits in the project under acceptEdits or auto);
    `prompt`: it would have waited for the user; `classifier`: auto mode's classifier would have judged it;
    `protected`: a write to a protected path, which only YOLO approves without asking.
    An approximation of Claude Code's own checks, which this hook cannot see.
    """
    tool, ti = inp.get("tool_name") or "", inp.get("tool_input") or {}
    project = project_of(inp)
    rules = allow_rules(project)
    unknown = "classifier" if baseline == "auto" else "prompt"
    if tool in FREE_TOOLS:
        return "free", None
    if tool == "Bash":
        parts = bash_parts(ti.get("command") or "")
        why = []
        for part in parts:
            if readonly_part(part):
                continue
            r = allowed_by(tool, ti, rules, project, part)
            if not r:
                return unknown, None
            why.append(r)
        return ("rule", ", ".join(sorted(set(why)))) if why else ("read-only", None)
    if tool in ("Read", "Glob", "Grep", "LS"):
        target = ti.get("file_path") or ti.get("path") or project
        if inside(target, project):
            return "read-only", None
        r = allowed_by("Read", ti, rules, project)
        return ("rule", r) if r else (unknown, None)
    if tool in EDIT_TOOLS:
        target = ti.get("file_path") or ti.get("notebook_path") or ""
        if protected(target):
            return "protected", None
        r = allowed_by(tool, ti, rules, project)
        if r:
            return "rule", r
        if baseline in ("acceptEdits", "auto") and inside(target, project):
            return "mode", baseline
        return unknown, None
    r = allowed_by(tool, ti, rules, project)
    return ("rule", r) if r else (unknown, None)


YOLO_ONLY = ("prompt", "classifier", "protected")


def on_afk_signal(inp, event):
    """Why an AFK run stopped, waits, or was denied: a permission prompt, an idle session, an API error,
    an auto-mode denial. Recorded for `stats`; the user is alerted when the run stands still."""
    sid = inp["session_id"]
    afk = afk_active(read_json(state_path(sid), {}))
    if not afk:
        return
    tool, ti = inp.get("tool_name") or "", inp.get("tool_input") or {}
    fields = {"run": afk["run"], "mode": inp.get("permission_mode")}
    if inp.get("agent_id"):
        fields["agent"] = inp.get("agent_type") or inp["agent_id"]
    if event == "Notification":
        kind = inp.get("notification_type") or "notification"
        if kind not in (
            "permission_prompt",
            "idle_prompt",
            "elicitation_dialog",
            "elicitation_url_dialog",
            "agent_needs_input",
        ):
            return
        record("afk_user_needed", sid, kind=kind, detail=(inp.get("message") or "")[:200], **fields)
        alert(f"AFK run waiting: {kind.replace('_', ' ')}. {inp.get('message') or ''}"[:200])
    elif event == "PermissionRequest":
        record("afk_user_needed", sid, kind="permission", tool=tool, detail=tool_target(tool, ti), **fields)
    elif event == "PermissionDenied":
        with locked_state(sid) as st:
            st["afk_denied"] = st.get("afk_denied", 0) + 1
        record(
            "afk_denied", sid, tool=tool, detail=tool_target(tool, ti), reason=(inp.get("reason") or "")[:200], **fields
        )
    elif event == "StopFailure":
        record(
            "afk_user_needed",
            sid,
            kind="api_error",
            detail=f"{inp.get('error')}: {inp.get('error_details') or ''}"[:200],
            **fields,
        )
        alert(f"AFK run stopped on an API error: {inp.get('error')}")
    return


def claude_pid():
    """The claude process this hook runs under: the ancestor whose parent is the claude-relay loop."""
    if os.environ.get("HANDOVER_CLAUDE_PID"):
        # A detached watchdog, no longer under claude: the hook that started it found the process.
        return int(os.environ["HANDOVER_CLAUDE_PID"])
    loop_pid, pid = os.environ.get("HANDOVER_RELAY_PID"), os.getpid()
    for _ in range(10):
        p = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, check=False)
        ppid = p.stdout.strip()
        if not ppid or ppid in ("0", "1"):
            return None
        if ppid == loop_pid:
            return pid
        pid = int(ppid)
    return None


def alert(message):
    """A macOS notification and a terminal bell: the user is needed back at the keyboard."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            [
                "osascript",
                "-e",
                "on run argv",
                "-e",
                'display notification (item 1 of argv) with title "Claude Code handover"',
                "-e",
                "end run",
                message,
            ],
            capture_output=True,
            timeout=5,
            check=False,
        )
    tty = "/dev/tty"
    if os.environ.get("TMUX_PANE"):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            tty = (
                subprocess.run(
                    ["tmux", "display-message", "-p", "-t", os.environ["TMUX_PANE"], "#{pane_tty}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                ).stdout.strip()
                or tty
            )
    with contextlib.suppress(OSError), open(tty, "w") as f:
        f.write("\a")


def cmd_relay_drive(args):
    """The relay's second half, detached from the hook so the turn can end first."""
    time.sleep(2)
    if args.kill:
        with contextlib.suppress(OSError):
            os.kill(args.kill, signal.SIGTERM)
        return 0

    def keys(*k):
        subprocess.run(["tmux", "send-keys", "-t", args.pane, *k], check=True, timeout=5)

    t0 = time.time()
    keys("-l", "/clear")
    time.sleep(0.5)
    keys("Enter")
    marker = relay_marker(args.session)
    deadline = time.time() + WAIT_SECONDS + 60
    while not os.path.exists(marker) and time.time() < deadline:
        time.sleep(1)
    loaded = read_json(marker, {})
    with contextlib.suppress(FileNotFoundError):
        os.remove(marker)
    if not loaded.get("ok"):
        record("relay_stalled", args.session, seconds=round(time.time() - t0))
        os.environ["TMUX_PANE"] = args.pane
        alert("Relay stalled: the new session did not load the handover. Check the session.")
        return 1
    time.sleep(1)
    keys("-l", args.message)
    time.sleep(0.5)
    keys("Enter")
    record("relay_resumed", args.session, mode="tmux", seconds=round(time.time() - t0))
    return 0


CLOSING_FORMAT = (
    "one line on where the work stands (what is done, what is left mid-step, the background commands you "
    "stopped and how to restart each), then the handover's full path when given above, then `Ready to hand "
    "over: run /clear.`, then, in a code block, the "
    "message the user should send after /clear to resume, naming the very next step"
)

WRITTEN = (
    "{written} This session ends now. Start nothing new, and end your turn on your closing reply: "
    + CLOSING_FORMAT
    + ".{loads}"
)

CLOSING_REPLY = (
    "{written} Your closing reply is still missing. Start nothing new, and end your turn on it: " + CLOSING_FORMAT + "."
)

SUGGEST = (
    "This session's context is at {tokens}K tokens, past the {suggest}K point from which a fresh session "
    "reasons better. Finish what is in progress; at the next boundary between scopes (a task done, a PR "
    "pushed, before an unrelated task or a long new investigation), hand over with the handover skill "
    "rather than waiting for {later}. Start no new subagent from now on: let the running ones finish, "
    "since their results belong in the handover."
)

WIND_DOWN = (
    "This session's context is at {tokens}K tokens: this session ends once its tasks are finished, and a "
    "fresh session continues from a handover. Do not start a new task, nor a new subagent. Finish every task "
    "in progress, then write your closing reply:\n"
    "1. Finish the current step, so that the files and the git state are coherent.\n"
    "2. Wait for the running subagents and [await] background commands. While any still runs, end your turn "
    "without the closing reply: its result wakes you up. The plugin stops an [await] command still running after "
    "{await_minutes} minutes.\n"
    "3. Stop the [endless] background commands with TaskStop, and do not restart them.\n"
    "4. Once nothing is left running, end your turn on one short line on where the work stands, without "
    "`Ready to hand over` nor the resume message yet.\n"
    "5. As that turn ends, a separate model writes the handover from the complete transcript (do not write one "
    "yourself), and the hook tells you once it is written. Only then write your closing reply: one line on where "
    "the work stands and the commands you stopped, with how to restart each; then the handover's full path, "
    "as the hook gives it; then `Ready to hand over: run /clear.`; then, in a code block, the message the user should send after /clear to resume, naming the very "
    "next step.\n"
    "If a notice that the plugin stopped a command wakes you, answer it with one short line."
)

STOP_ENDLESS = (
    "Before the handover is written, stop these background commands with TaskStop, and do not restart them: {}. "
    "Then end your turn on one short line naming each command you stopped, with how to restart it, without "
    "`Ready to hand over` yet: the handover is written as your turn ends, and the hook then tells you to write "
    "your closing reply. One still running when your turn ends is stopped by the plugin, and the notice of its "
    "failure wakes you once more: answer it with one short line."
)

DELEGATE = (
    "Context budget: this session hands over to a fresh one once its context fills up, so keep your own "
    "context for steering: the user's intent, decisions, integration, verification. Give a subagent each "
    "self-contained task whose working detail you will not need afterwards (an investigation across many "
    "files, a well-specified change, a test-and-fix loop, a review), and run independent ones in parallel. "
    "Brief it fully, since it starts without your context (goal, constraints, files, how to verify, what to "
    "report), and ask for a short report: conclusions, paths, what was verified. Do quick tasks yourself: a "
    "subagent costs a brief and a report."
)


def on_precompact(inp):
    sid = inp["session_id"]
    tokens, _ = T.context_tokens(inp["transcript_path"])
    with locked_state(sid) as st:
        st["transcript"] = inp["transcript_path"]
        st.setdefault("project", project_of(inp))
        # Auto-compactions show where compaction really fires, winding down or not.
        record(
            "compaction_started",
            sid,
            tokens=tokens,
            kind=inp.get("trigger"),
            wind_down=bool(st.get("wind_down")),
            compact_window=compact_window(),
        )
        # No wind-down: the handover is kept fresh for the summary the compaction loads it next to.
        st["keep_fresh"] = True
        st["compacting"] = True
        if needs_refresh(st, tokens):
            start_writer(st, sid, "precompact")


def audit_post(inp):
    """PostToolUse in a YOLO run: the call goes to the audit log, tagged by whether it needed YOLO."""
    afk = afk_active(read_json(state_path(inp["session_id"]), {}))
    if afk and yolo_on(afk, inp):
        verdict, why = classify(inp, afk.get("baseline") or baseline_mode(project_of(inp)))
        audit_write(afk, inp, verdict, why)


def on_session_end(inp):
    sid = inp["session_id"]
    if not os.path.exists(state_path(sid)):
        return
    with locked_state(sid) as st:
        if afk_active(st) and not st.get("relay_outcome"):
            # Not a handover: the run ends with this session (an exit, a /clear by hand, a crash of claude).
            afk_end(st, sid, "exit", f"session ended ({inp.get('reason') or 'unknown'})")
        if not (st.get("wind_down") or st.get("keep_fresh")):
            return
        tokens, _ = T.context_tokens(inp["transcript_path"])
        record("session_ended", sid, tokens=tokens, reason=inp.get("reason"))
        if needs_refresh(st, tokens):
            start_writer(st, sid, "session_end")
        project = st.get("project") or project_of(inp)
    write_json(
        os.path.join(data_dir(), "latest", f"{project_key(project)}.json"),
        {"session": sid, "at": time.time(), "reason": inp.get("reason")},
    )
    return


def on_session_start(inp):
    source = inp.get("source")
    if source == "compact":
        return after_compact(inp)
    if source not in ("clear", "startup"):
        return None
    relayed = take_relay(inp)
    if relayed:
        return relayed
    goal = os.environ.get("HANDOVER_AFK_GOAL")
    if goal:
        # claude-relay --afk: a new run, whose goal is also the first prompt.
        until = os.environ.get("HANDOVER_AFK_UNTIL")
        with locked_state(inp["session_id"]) as new:
            new.update(transcript=inp.get("transcript_path"), project=project_of(inp))
            afk = afk_active(new) or afk_start(
                new,
                inp["session_id"],
                goal,
                int(until) if until else None,
                "claude-relay",
                yolo=os.environ.get("HANDOVER_AFK_YOLO") == "1",
            )
        return {
            "systemMessage": f"handover: AFK mode{afk_texts(afk)['until']}",
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": AFK_RULES.format(**afk_texts(afk)),
            },
        }
    latest_path = os.path.join(data_dir(), "latest", f"{project_key(project_of(inp))}.json")
    latest = read_json(latest_path)
    if not latest or latest["session"] == inp["session_id"]:
        return None
    age = time.time() - latest["at"]
    if source == "clear" and latest.get("reason") == "clear" and age <= CLEAR_HANDOVER_SECONDS:
        t0 = time.time()
        st = wait_for(latest["session"], WAIT_SECONDS)
        text = read_handover(st) if (st.get("written") or {}).get("ok") else None
        record(
            "handover_loaded",
            latest["session"],
            source="clear",
            chars=len(text or ""),
            waited_s=round(time.time() - t0),
            refresh_running=writer_running(st),
        )
        if not text:
            return None
        with contextlib.suppress(FileNotFoundError):
            os.remove(latest_path)
        with locked_state(inp["session_id"]) as new:
            new.update(transcript=inp.get("transcript_path"), project=project_of(inp), loaded_from=st["path"])
        note = "" if not writer_running(st) else " It may miss the last steps: its refresh was still running."
        return {
            "systemMessage": f"handover: loaded {st['path']}",
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "Handover from the session the user just cleared, written by a separate model from its transcript "
                    f"(file: {st['path']}).{note} If the user's request continues that work, continue from it; "
                    f"otherwise ignore it.\n\n{text}"
                ),
            },
        }
    if source == "startup" and age <= STARTUP_POINTER_SECONDS:
        st = read_json(state_path(latest["session"]), {})
        if not (st.get("written") or {}).get("ok") or not os.path.exists(st.get("path", "")):
            return None
        with contextlib.suppress(FileNotFoundError):
            os.remove(latest_path)
        return {
            "systemMessage": f"handover: the last session here left {st['path']}. Ask to continue from it to load it.",
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    f"The previous session in this project left a handover at {st['path']}. Read it only if the user "
                    "asks to continue earlier work."
                ),
            },
        }
    return None


def take_relay(inp):
    """A session the relay started: load the handover of the session it replaces, and carry the chain on."""
    path = relay_path(project_of(inp))
    pending = read_json(path)
    if not pending or pending["session"] == inp["session_id"] or time.time() - pending["at"] > CLEAR_HANDOVER_SECONDS:
        return None
    for p in (path, os.path.join(data_dir(), "latest", f"{project_key(project_of(inp))}.json")):
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
    t0 = time.time()
    st = wait_for(pending["session"], WAIT_SECONDS)
    text = read_handover(st) if (st.get("written") or {}).get("ok") else None
    record(
        "handover_loaded",
        pending["session"],
        source="relay",
        chars=len(text or ""),
        waited_s=round(time.time() - t0),
        refresh_running=writer_running(st),
    )
    write_json(relay_marker(pending["session"]), {"ok": bool(text)})
    if not text:
        return None
    chain = st.get("chain") or {}
    record(
        "relay_received",
        inp["session_id"],
        prev=pending["session"],
        chain=chain.get("base"),
        n=(chain.get("n") or 0) + 1,
        source=inp.get("source"),
    )
    if pending.get("mode") == "loop":
        # The loop starts claude with the message: it is resumed as soon as it loads.
        record("relay_resumed", pending["session"], mode="loop", seconds=round(time.time() - pending["at"]))
    afk = afk_active(st)
    with locked_state(inp["session_id"]) as new:
        new.update(
            transcript=inp.get("transcript_path"), project=project_of(inp), loaded_from=st["path"], relayed_from=chain
        )
        if afk:
            new["afk"] = dict(afk)
            record("afk_session_joined", inp["session_id"], run=afk["run"], prev=pending["session"])
    limit = config()["relay_limit"]
    if afk:
        return {
            "systemMessage": f"handover: AFK relay, loaded {st['path']}",
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "The handover relay started this session, without the user, from the handover of the previous "
                    f"session (handover {chain.get('n')} of an AFK run, file: {st['path']}), written by a separate "
                    "model from its transcript. The next message is the step it named: carry on from it right away."
                    f"\n\n{AFK_RULES.format(**afk_texts(afk))}\n\n{text}"
                ),
            },
        }
    return {
        "systemMessage": f"handover: relay, loaded {st['path']}",
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "The handover relay started this session, without the user, from the handover of the previous "
                f"session (handover {chain.get('n')} of at most {limit}, file: {st['path']}), written by a separate "
                "model from its transcript. The next message is the step it named: carry on from it right away. "
                f"When this context fills up, the relay hands over again.\n\n{text}"
            ),
        },
    }


def after_compact(inp):
    sid = inp["session_id"]
    t0 = time.time()
    st = wait_for(sid, WAIT_SECONDS)
    if not (st.get("wind_down") or st.get("keep_fresh")):
        return None
    text = read_handover(st) if (st.get("written") or {}).get("ok") else None
    record(
        "handover_loaded",
        sid,
        source="compact",
        chars=len(text or ""),
        waited_s=round(time.time() - t0),
        refresh_running=writer_running(st),
    )
    with locked_state(sid) as st:
        # The session starts over from a small context: wind down and notify again at the next trigger.
        for k in (
            "wind_down",
            "wind_down_tokens",
            "keep_fresh",
            "cause",
            "suggested",
            "user_notified",
            "wind_down_sent",
            "reply_due",
            "reply_reminded",
            "held_since",
            "write_failed",
            "closing_reply",
            "written",
            "compacting",
        ):
            st.pop(k, None)
        reset_commands(st, sid)
    if not text:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "Handover written by a separate model from this session's transcript just before the compaction "
                f"(file: {st['path']}). Use it alongside the summary above; it quotes the user's instructions "
                f"and records decisions and pitfalls.\n\n{text}"
            ),
        }
    }


def project_of(inp):
    return os.environ.get("CLAUDE_PROJECT_DIR") or inp.get("cwd") or os.getcwd()


def cmd_hook(_args):
    if os.environ.get("HANDOVER_CHILD"):
        return 0
    inp = json.load(sys.stdin)
    cfg = config()
    event = inp.get("hook_event_name")
    if event == "SessionStart":
        import_old_data()
    save_options()
    if inp.get("session_id"):
        mark_live(inp["session_id"], event)
    handler = {
        "PostToolUse": lambda: audit_post(inp) or on_activity(inp, cfg, event),
        "PreToolUse": lambda: on_pre_tool_use(inp),
        "SubagentStart": lambda: on_subagent(inp, event),
        "SubagentStop": lambda: on_subagent(inp, event),
        "Notification": lambda: on_afk_signal(inp, event),
        "PermissionRequest": lambda: on_afk_signal(inp, event),
        "PermissionDenied": lambda: on_afk_signal(inp, event),
        "StopFailure": lambda: on_afk_signal(inp, event),
        "Stop": lambda: on_activity(inp, cfg, event),
        "PreCompact": lambda: on_precompact(inp),
        "SessionEnd": lambda: on_session_end(inp),
        "SessionStart": lambda: on_session_start(inp),
    }.get(event)
    out = handler() if handler else None
    if out:
        print(json.dumps(out))
    return 0


def cmd_guidance(_args):
    """SessionStart on a fresh context: the background-command tags, and the delegation guidance when
    `delegate` is on. A hook of its own, so that it never pushes a loaded handover past Claude Code's limit for
    injected context."""
    if os.environ.get("HANDOVER_CHILD"):
        return 0
    with (
        contextlib.suppress(ValueError, KeyError, OSError),
        locked_json(tasks_path(json.load(sys.stdin)["session_id"])) as tasks,
    ):
        # Recorded with each untagged command: was the session told the tags?
        tasks["guided"] = True
    text = TAGS + ("\n\n" + DELEGATE if config()["delegate"] else "")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
    return 0


def cmd_status(args):
    d = os.path.join(data_dir(), "sessions")
    sids = (
        [args.session]
        if args.session
        else sorted(
            (f[:-5] for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else [],
            key=lambda s: os.path.getmtime(state_path(s)),
            reverse=True,
        )[:10]
    )
    print(
        json.dumps(
            {"config": config(), "data_dir": data_dir(), "sessions": {s: read_json(state_path(s), {}) for s in sids}},
            indent=1,
        )
    )
    return 0


# Status line colours, bold for the host's dimColor wrapper (same palette as a typical statusline.sh).
C = {
    "gray": "\033[1;38;5;245m",
    "yellow": "\033[1;38;5;226m",
    "orange": "\033[1;38;5;214m",
    "green": "\033[1;38;5;82m",
    "red": "\033[1;38;5;196m",
    "dim": "\033[38;5;240m",
    "off": "\033[0m",
}


def kfmt(n):
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}k" if n < 10_000 else f"{n // 1000}k"


def status_line(st, prog, tokens, cfg):
    """(colour, text) of the session's handover state, for the status line; the first line shows the tokens."""
    written, trig, suggest = st.get("written") or {}, cfg["trigger"], cfg["suggest"]
    if st.get("error") and not written.get("ok") and not writer_running(st):
        return "red", f"Handover failed · {st['error']['message'][:60]}"
    if writer_running(st):
        verb = "refreshing" if written.get("ok") else "writing"
        phase = (prog or {}).get("phase")
        if phase == "writing":
            target = prog.get("target") or cfg["chars"]
            cells = min(10, prog["chars"] * 10 // max(1, target))
            detail = f"{kfmt(prog['chars'])}/{kfmt(target)} chars {'▓' * cells}{'░' * (10 - cells)}"
        elif phase == "thinking":
            detail = "thinking"
        elif phase == "reading":
            detail = "reading"
        else:
            detail = "starting"
        secs = round(time.time() - (prog or {}).get("since", time.time()))
        return "orange", f"Handover {verb} · {detail} · {secs}s"
    if st.get("compacting"):
        # The handover is loaded after the compaction, next to its summary: no /clear to run.
        return "gray", "Compacting · handover " + ("written, loads after it" if written.get("ok") else "not written")
    outcome = st.get("relay_outcome") or {}
    if outcome.get("at"):
        return "green", "Handover ready · relaying"
    if outcome.get("limit") and outcome.get("deadline"):
        return "red", f"AFK deadline · {outcome['n']} handovers · run /clear"
    if outcome.get("limit"):
        return "red", f"Relay limit · {outcome['n']} handovers · run /clear"
    afk = st.get("afk") or {}
    if afk.get("ended") and afk["ended"] != "off":
        return ("green" if afk["ended"] == "done" else "red"), f"AFK {afk['ended']} · {afk.get('reason', '')[:60]}"
    loaded = " · loaded" if st.get("loaded_from") else ""
    if st.get("relayed_from"):
        n = st["relayed_from"].get("n", 0) + 1
        loaded = f" · relay {n}" if afk_active(st) else f" · relay {n}/{cfg['relay_limit']}"
    if afk_active(st):
        loaded += " · AFK" + (
            f" until {datetime.fromtimestamp(afk['until']).strftime('%H:%M')}" if afk.get("until") else ""
        )
    if st.get("wind_down") and not st.get("closing_reply"):
        # Ready only once the closing reply is written: /clear before it would lose the resume message.
        # Written while the Stop hook holds the session: the hook sets reply_due a moment later.
        held = st.get("held_since")
        if st.get("reply_due") or held and written.get("ok") and written.get("at", 0) >= held:
            return "orange", f"Handover written · closing reply{loaded}"
        return "orange", f"Winding down · finishing tasks{loaded}"
    if written.get("ok"):
        return "green", "Handover ready · run /clear"
    suggested = suggest and tokens >= suggest
    if not trig:
        return "gray", f"Handover {'suggested' if suggested else 'trigger off'}{loaded}"
    if tokens >= trig:
        return "orange", f"Wind-down on the next tool call{loaded}"
    colour = "yellow" if tokens >= trig - cfg["warn"] else "gray"
    head = "Handover suggested · will trigger" if suggested else "Handover will trigger"
    return colour, f"{head} at {kfmt(trig)}{loaded}"


def cmd_statusline(_args):
    """One line for the status line, from its JSON payload on stdin."""
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        return 0
    sid = inp.get("session_id")
    # Nothing in a session the plugin's hooks never ran in: the plugin is disabled there.
    if not sid or not os.path.exists(live_path(sid)):
        return 0
    cfg = config()
    tokens = int((inp.get("context_window") or {}).get("total_input_tokens") or 0)
    if not tokens and inp.get("transcript_path"):
        tokens = T.context_tokens(inp["transcript_path"])[0]
    colour, text = status_line(read_json(state_path(sid), {}), read_json(progress_path(sid)), tokens, cfg)
    print(f"{C[colour]}✋ {text}{C['off']}", end="")
    return 0


def cycles(events):
    """Split a session's metrics into cycles: a compaction ends one and starts the next."""
    out, cur = [], []
    for e in events:
        # The pre-compaction writer and the load that follows land after the boundary.
        after_compact = (
            e["event"] == "handover_loaded"
            and e.get("source") == "compact"
            or e["event"] == "writer_finished"
            and e.get("cause") == "precompact"
        )
        if after_compact and out and not cur:
            out[-1].append(e)
            continue
        cur.append(e)
        if e["event"] == "compaction_started":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def summarize(sid, events):
    def first(name, **match):
        return next((e for e in events if e["event"] == name and all(e.get(k) == v for k, v in match.items())), {})

    started = first("wind_down_started")
    requested = first("handover_requested")
    # The first handover of the wind-down, not a refresh at the session's end or before a compaction.
    ready = next(
        (
            e
            for e in events
            if e["event"] == "writer_finished" and e.get("ok") and e.get("cause") not in ("precompact", "session_end")
        ),
        {},
    )
    compacted, ended = first("compaction_started"), first("session_ended")
    end = compacted or ended
    writers = [e for e in events if e["event"] == "writer_finished"]
    loaded = first("handover_loaded")

    def delta(a, b):
        return b - a if a is not None and b is not None else None

    return {
        "session": sid,
        "date": time.strftime("%Y-%m-%d", time.localtime(events[0]["at"])),
        "cause": started.get("cause"),
        "trigger": started.get("trigger"),
        "compact_window": started.get("compact_window") or end.get("compact_window"),
        "wind_down_at": started.get("tokens"),
        "ready_at": ready.get("tokens_done"),
        "notified_at": first("user_notified").get("tokens"),
        "reply_at": first("closing_reply_written").get("tokens"),
        "end": (f"compact-{compacted.get('kind')}" if compacted else ended.get("reason")),
        "end_at": end.get("tokens"),
        "auto_compact_at": compacted.get("tokens") if compacted.get("kind") == "auto" else None,
        # Tokens the main session used during its wind-down, up to its closing reply, then until the session ended.
        "main_tokens_wind_down": delta(started.get("tokens"), first("closing_reply_written").get("tokens")),
        "main_tokens_after_wind_down": delta(started.get("tokens"), end.get("tokens")),
        "writer_runs": len(writers),
        "writer_failures": sum(not e.get("ok") for e in writers),
        "writer_seconds": ready.get("seconds"),
        "writer_input_tokens": sum(
            (e.get("writer_input_tokens") or 0)
            + (e.get("writer_cache_creation_input_tokens") or 0)
            + (e.get("writer_cache_read_input_tokens") or 0)
            for e in writers
        ),
        "writer_output_tokens": sum(e.get("writer_output_tokens") or 0 for e in writers),
        "writer_cost_usd": round(sum(e.get("writer_cost_usd") or 0 for e in writers), 3),
        "requested_by": requested.get("cause"),
        "requested_at": requested.get("tokens"),
        "suggested_at": first("suggestion_sent").get("tokens"),
        "suggest": requested.get("suggest"),
        "request_reason": requested.get("reason"),
        "loaded": loaded.get("source"),
        "load_wait_s": loaded.get("waited_s"),
        # How long the Stop hook held the session for the writer, before its closing reply.
        "hold_s": first("closing_reply_asked").get("held_s"),
    }


def relay_chains(sessions):
    """One summary per relay chain: how it started, how far it went, how each relay went, how it ended."""
    chain_of, chains = {}, {}
    for sid, events in sessions.items():
        for e in events:
            if e.get("chain"):
                chain_of[sid] = e["chain"]
                if e["event"] == "relay_received" and e.get("prev"):
                    chain_of.setdefault(e["prev"], e["chain"])
    for sid, events in sessions.items():
        for e in events:
            if sid in chain_of or e.get("chain"):
                chains.setdefault(e.get("chain") or chain_of[sid], []).append(e)
    out = []
    for base, events in chains.items():
        events.sort(key=lambda e: e["at"])

        def every(name, events=events):
            return [e for e in events if e["event"] == name]

        handovers, started = every("chain_handover_written"), every("relay_received")
        # The chain's sessions in order: the one that wrote handover n, or that the relay started as n.
        order = {e["session"]: e["n"] for e in handovers}
        order.update({e["session"]: e["n"] for e in started})
        last = max(order, key=order.get) if order else None
        last_end = next(
            (e for e in events if e["session"] == last and e["event"] in ("session_ended", "compaction_started")), {}
        )
        limited, failed, stalled = every("relay_limit_reached"), every("relay_failed"), every("relay_stalled")
        resumed = every("relay_resumed")
        writers = [e for e in events if e["event"] == "writer_finished"]
        end = (
            "limit"
            if limited
            else "failed"
            if failed
            else "stalled"
            if stalled
            else f"compact-{last_end.get('kind')}"
            if last_end.get("event") == "compaction_started"
            else last_end.get("reason") or "open"
        )
        out.append(
            {
                "chain": base,
                "date": time.strftime("%Y-%m-%d", time.localtime(events[0]["at"])),
                "start": next((e.get("start") for e in handovers if e.get("start")), None),
                "sessions": len(order),
                "handovers": max((e["n"] for e in handovers), default=0),
                "relays": len(every("relay_launched")),
                "modes": sorted({e.get("mode") for e in every("relay_launched") if e.get("mode")}),
                "resumed": len(resumed),
                "stalls": len(stalled),
                "failures": len(failed),
                "relay_s": median(e.get("seconds") for e in resumed),
                "handover_at": median(e.get("tokens") for e in handovers),
                "message_from_reply": sum(bool(e.get("message_from_reply")) for e in every("relay_launched")),
                "end": end,
                "minutes": round((events[-1]["at"] - events[0]["at"]) / 60),
                "writer_cost_usd": round(sum(e.get("writer_cost_usd") or 0 for e in writers), 3),
            }
        )
    out.sort(key=lambda c: c["date"])
    return out


def afk_runs(sessions):
    """One summary per AFK run: its goal and deadline, how far it went, how often it was sent back, how it ended."""
    runs = {}
    for sid, events in sessions.items():
        for e in events:
            if e.get("run") and e["event"].startswith("afk_"):
                runs.setdefault(e["run"], {"events": [], "sessions": set()})
                runs[e["run"]]["events"].append(e)
                runs[e["run"]]["sessions"].add(sid)
    out = []
    for run, r in runs.items():
        events = sorted(r["events"], key=lambda e: e["at"])
        mine = [e for sid in r["sessions"] for e in sessions[sid]]
        started = next((e for e in events if e["event"] == "afk_started"), {})
        ended = next((e for e in events if e["event"] == "afk_ended"), {})
        last = max(e["at"] for e in mine)
        audit = audit_entries(run)[0] if started.get("yolo") else []
        out.append(
            {
                "run": run,
                "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(events[0]["at"])),
                "yolo": bool(started.get("yolo")),
                "calls": len(audit),
                "yolo_only": sum(a.get("verdict") in YOLO_ONLY for a in audit),
                "guarded": sum(a.get("verdict") == "guarded" for a in audit),
                "waits": sum(e["event"] == "afk_user_needed" for e in events),
                "denied": sum(e["event"] == "afk_denied" for e in events),
                "agent_waits": sum(e["event"] == "wind_down_held" and e.get("for") == "agents" for e in mine),
                "how": started.get("how"),
                "goal": started.get("goal"),
                "until": started.get("until"),
                "sessions": len(r["sessions"]),
                "handovers": sum(e["event"] == "chain_handover_written" for e in mine),
                "sent_back": sum(e["event"] == "afk_sent_back" for e in events),
                "end": ended.get("kind") or "open",
                "reason": ended.get("reason"),
                "hours": round((last - events[0]["at"]) / 3600, 1),
                "writer_cost_usd": round(
                    sum(e.get("writer_cost_usd") or 0 for e in mine if e["event"] == "writer_finished"), 3
                ),
            }
        )
    out.sort(key=lambda r: r["date"])
    return out


def table_print(cols, rows):
    table = [[name for name, _ in cols]] + [[f(r) for _, f in cols] for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(cols))]
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())


def median(values):
    v = sorted(x for x in values if x is not None)
    return v[len(v) // 2] if v else None


def audit_check(run, sessions):
    """`stats --audit <run>`: is the run's audit log whole, and is the plugin the run started with unchanged?
    Exit 0 when both hold, 1 otherwise. Evidence against tampering, not proof: see the README."""
    events = sorted((e for evs in sessions.values() for e in evs if e.get("run") == run), key=lambda e: e["at"])
    started = next((e for e in events if e["event"] == "afk_started"), None)
    if not started:
        print(f"handover: no AFK run {run} in {metrics_path()}", file=sys.stderr)
        return 1
    ended = next((e for e in events if e["event"] == "afk_ended"), {})
    entries, bad = audit_entries(run)
    problems, prev, heads = [], "", []
    if bad:
        problems.append(f"{bad} line(s) are not JSON")
    for i, e in enumerate(entries, 1):
        h = e.get("h")
        if h != audit_line_hash(prev, {k: v for k, v in e.items() if k != "h"}):
            problems.append(f"line {i} breaks the hash chain: edited, or a line inserted or removed before it")
            break
        prev = h
        heads.append(h)
    n = ended.get("audit_lines")
    if n:
        # Length and last hash at the end of the run, recorded in the metrics, apart from the log.
        if len(entries) + bad < n:
            problems.append(f"{n} lines when the run ended, {len(entries) + bad} now: the log was cut")
        elif len(heads) >= n and heads[n - 1] != ended.get("audit_head"):
            problems.append(f"line {n}, the last when the run ended, no longer matches the hash recorded then")
    elif ended and entries:
        problems.append("the run ended with no audit log, which has lines now")
    root, then = started.get("plugin_root"), started.get("plugin_sha")
    if not then:
        problems.append("no plugin hash recorded at the start (not a YOLO run?)")
    elif not root or not os.path.isdir(root):
        problems.append(f"the plugin the run started with ({root}) is gone; its hash cannot be checked")
    else:
        now = plugin_sha(root)
        if now != then:
            problems.append(f"the plugin's hooks or scripts in {root} changed since the start ({then} -> {now})")
    verdicts = {}
    for e in entries:
        verdicts[e.get("verdict")] = verdicts.get(e.get("verdict"), 0) + 1
    print(
        f"AFK run {run}: {len(entries)} audited calls, "
        + (", ".join(f"{n} {v}" for v, n in sorted(verdicts.items(), key=lambda x: -x[1])) or "none")
        + f"; end: {ended.get('kind') or 'open'}"
    )
    print(f"plugin at start: {then or '-'} ({root or '-'})")
    if problems:
        print("NOT VERIFIED:\n" + "\n".join(f"  - {p}" for p in problems))
        return 1
    print(
        "verified: hash chain whole"
        + (", length and head match the end of the run" if ended else ", run still open")
        + ", plugin unchanged"
    )
    return 0


def background_print(sessions):
    """The background commands launched untagged, and those the wind-down stopped: what to fix in the tags."""
    evs = [
        e
        for evs in sessions.values()
        for e in evs
        if e.get("event") in ("command_untagged", "command_stopped", "command_left", "command_timed_out")
    ]
    if not evs:
        return
    n = {}
    for e in evs:
        key = e["event"] + (f" {e['step']}" if e.get("step") else "") + (" unsure" if e.get("sure") is False else "")
        n[key] = n.get(key, 0) + 1
    print("\nBackground commands: " + ", ".join(f"{c} {key}" for key, c in sorted(n.items())))
    for e in evs[-15:]:
        what = e.get("step") or e["event"]
        extra = f" -> {e['tag']}" if e.get("step") == "guessed" else (f" [{e['tag']}]" if e.get("tag") else "")
        who = " (subagent)" if e.get("subagent") else (" (no tag guidance)" if e.get("guided") is False else "")
        print(
            f"  {datetime.fromtimestamp(e['at']):%y-%m-%d %H:%M}  {e['session'][:8]}  {what:<13}{extra}{who}  "
            f"{(e.get('command') or '')[:70]}"
        )


def plugin_id():
    """handover@<marketplace>, from where the plugin is installed, else from its data folder's name."""
    parts = os.path.dirname(os.path.abspath(__file__)).split(os.sep)
    if len(parts) >= 6 and parts[-5] == "cache":
        return f"{parts[-3]}@{parts[-4]}"
    name = os.path.basename(data_dir())
    return "handover@" + name[len("handover-") :] if name.startswith("handover-") else "handover"


def chezmoi_source(path):
    """The chezmoi source of `path` when chezmoi manages it, else None."""
    try:
        p = subprocess.run(["chezmoi", "source-path", path], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() or None if p.returncode == 0 else None


def cmd_config(args):
    """The config skill: each option with its default and current value, or new values saved."""
    pid = plugin_id()
    settings = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"), "settings.json")
    if args.set:
        try:
            values = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in json.loads(args.set).items()}
        except (ValueError, AttributeError) as e:
            print(f"handover: --set takes a JSON object of option values ({e})", file=sys.stderr)
            return 2
        p = subprocess.run(
            ["claude", "plugin", "configure", pid, "--values-stdin"],
            input=json.dumps(values),
            capture_output=True,
            text=True,
            check=False,
        )
        sys.stdout.write(p.stdout)
        sys.stderr.write(p.stderr)
        if p.returncode == 0:
            print(
                json.dumps(
                    {"saved": values, "settings": settings, "chezmoi_source": chezmoi_source(settings)},
                    ensure_ascii=False,
                )
            )
        return p.returncode
    p = subprocess.run(["claude", "plugin", "configure", pid, "--json"], capture_output=True, text=True, check=False)
    if p.returncode != 0:
        sys.stderr.write(p.stderr or p.stdout)
        return p.returncode
    info = json.loads(p.stdout)
    seen = read_json(os.path.join(data_dir(), "options.json"), {})
    options = []
    for key, schema in info.get("schema", {}).items():
        current = (info.get("inputs") or {}).get(key, "")
        options.append(
            {
                "key": key,
                **schema,
                "choices": (info.get("choices") or {}).get(key),
                "configured": key in (info.get("configured") or []),
                "current": current if key in (info.get("configured") or []) else None,
                "seen_by_hooks": seen.get(key),
            }
        )
    print(
        json.dumps(
            {"plugin": pid, "settings": settings, "chezmoi_source": chezmoi_source(settings), "options": options},
            indent=1,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_stats(args):
    reserve = config()["reserve"]
    sessions = {}
    with contextlib.suppress(OSError), open(metrics_path(), encoding="utf-8") as f:
        for line in f:
            with contextlib.suppress(ValueError, KeyError):
                e = json.loads(line)
                sessions.setdefault(e["session"], []).append(e)
    rows = [summarize(sid, c) for sid, evs in sessions.items() for c in cycles(evs)]
    rows.sort(key=lambda r: r["date"])
    # Where compaction fires: measured when compactions were recorded, estimated otherwise.
    observed = median(r["auto_compact_at"] for r in rows)
    for r in rows:
        point = observed or (r["compact_window"] - reserve if r["compact_window"] else None)
        r["margin_to_compaction"] = point - r["end_at"] if point and r["end_at"] and not r["auto_compact_at"] else None
    if args.audit:
        return audit_check(args.audit, sessions)
    chains = relay_chains(sessions)
    if args.json:
        print(json.dumps({"cycles": rows, "chains": chains, "afk": afk_runs(sessions)}, indent=1))
        return 0
    if not rows:
        print(f"No metrics yet in {metrics_path()}")
        return 0

    def k(n):
        return "-" if n is None else f"{n / 1000:.0f}K"

    def num(n):
        return "-" if n is None else str(n)

    cols = [
        ("date", lambda r: r["date"]),
        ("session", lambda r: r["session"][:8]),
        ("suggested", lambda r: k(r["suggested_at"])),
        ("cause", lambda r: r["cause"] or "-"),
        ("wind-down", lambda r: k(r["wind_down_at"])),
        ("notified", lambda r: k(r["notified_at"])),
        ("reply", lambda r: k(r["reply_at"])),
        ("+wind-down", lambda r: k(r["main_tokens_wind_down"])),
        ("ready", lambda r: k(r["ready_at"])),
        ("end", lambda r: r["end"] or "-"),
        ("end at", lambda r: k(r["end_at"])),
        ("+total", lambda r: k(r["main_tokens_after_wind_down"])),
        ("margin", lambda r: k(r["margin_to_compaction"])),
        ("write s", lambda r: num(r["writer_seconds"])),
        ("hold s", lambda r: num(r["hold_s"])),
        ("load wait s", lambda r: num(r["load_wait_s"])),
        ("writer in/out", lambda r: f"{k(r['writer_input_tokens'])}/{k(r['writer_output_tokens'])}"),
        ("$", lambda r: f"{r['writer_cost_usd']:.2f}"),
    ]
    table_print(cols, rows)
    ends = {}
    for r in rows:
        ends[r["end"] or "open"] = ends.get(r["end"] or "open", 0) + 1
    print(f"\n{len(rows)} cycles; ends: " + ", ".join(f"{n} {e}" for e, n in sorted(ends.items())))
    print(
        f"medians: wind-down {k(median(r['wind_down_at'] for r in rows))}, "
        f"+wind-down {k(median(r['main_tokens_wind_down'] for r in rows))}, "
        f"+total {k(median(r['main_tokens_after_wind_down'] for r in rows))}, "
        f"margin {k(median(r['margin_to_compaction'] for r in rows))}, "
        f"writer input {k(median(r['writer_input_tokens'] or None for r in rows))}, "
        f"writer {num(median(r['writer_seconds'] for r in rows))}s, "
        f"hold {num(median(r['hold_s'] for r in rows))}s, "
        f"load wait {num(median(r['load_wait_s'] for r in rows))}s"
    )
    print(
        f"auto-compaction point: {k(observed) + ' measured' if observed else 'estimated as autoCompactWindow - ' + k(reserve)}"
    )
    asked = [r for r in rows if r["requested_by"]]
    if asked:
        print(
            f"\nHandovers a session asked for ({len(asked)}; median at "
            f"{k(median(r['requested_at'] for r in asked))}, suggested from {k(asked[0]['suggest'])}, "
            f"trigger {k(asked[0]['trigger'])}):"
        )
        for r in asked:
            print(
                f"  {r['date']}  {r['session'][:8]}  {r['requested_by']:<6}  at {k(r['requested_at']):>4}  "
                f"{r['request_reason'] or '(no reason given)'}"
            )
    if chains:
        limit = config()["relay_limit"]
        print(f"\nRelay chains ({len(chains)}; limit {limit} handovers):")
        table_print(
            [
                ("date", lambda c: c["date"]),
                ("chain", lambda c: c["chain"]),
                ("start", lambda c: c["start"] or "-"),
                ("handovers", lambda c: f"{c['handovers']}/{limit}"),
                ("relays", lambda c: str(c["relays"])),
                ("mode", lambda c: ",".join(c["modes"]) or "-"),
                ("resumed", lambda c: str(c["resumed"])),
                ("relay s", lambda c: num(c["relay_s"])),
                ("handover at", lambda c: k(c["handover_at"])),
                ("stalls", lambda c: str(c["stalls"])),
                ("end", lambda c: c["end"]),
                ("min", lambda c: str(c["minutes"])),
                ("$", lambda c: f"{c['writer_cost_usd']:.2f}"),
            ],
            chains,
        )
        ends = {}
        for c in chains:
            ends[c["end"]] = ends.get(c["end"], 0) + 1
        print(
            "chain ends: "
            + ", ".join(f"{n} {e}" for e, n in sorted(ends.items()))
            + f"; median relay {num(median(c['relay_s'] for c in chains))}s"
            + f"; resume message from the reply in {sum(c['message_from_reply'] for c in chains)}"
            + f"/{sum(c['relays'] for c in chains)} relays"
        )
    background_print(sessions)
    runs = afk_runs(sessions)
    if runs:
        print(f"\nAFK runs ({len(runs)}):")
        table_print(
            [
                ("started", lambda r: r["date"]),
                ("run", lambda r: r["run"]),
                ("how", lambda r: r["how"] or "-"),
                ("until", lambda r: fmt_until(r["until"]) if r["until"] else "-"),
                ("sessions", lambda r: str(r["sessions"])),
                ("handovers", lambda r: str(r["handovers"])),
                ("sent back", lambda r: str(r["sent_back"])),
                ("yolo", lambda r: f"{r['yolo_only']}/{r['calls']}" if r["yolo"] else "-"),
                ("guarded", lambda r: str(r["guarded"]) if r["yolo"] else "-"),
                ("waits", lambda r: str(r["waits"])),
                ("denied", lambda r: str(r["denied"])),
                ("agent waits", lambda r: str(r["agent_waits"])),
                ("end", lambda r: r["end"]),
                ("hours", lambda r: str(r["hours"])),
                ("$", lambda r: f"{r['writer_cost_usd']:.2f}"),
            ],
            runs,
        )
        for r in runs:
            print(f"  {r['run']}  goal: {(r['goal'] or '-')[:100]}")
            if r["reason"]:
                print(f"  {' ' * len(r['run'])}  {r['end']}: {r['reason'][:100]}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", help="plugin data directory, for callers outside a hook")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook")
    sub.add_parser("guidance", help="SessionStart hook: the background-command tags, and the delegation guidance")
    w = sub.add_parser("await-timeout", help="watchdog of an [await] command the wind-down waits for")
    w.add_argument("--session", required=True)
    w.add_argument("--task", required=True)
    w.add_argument("--parent", type=int, required=True, help="the claude process that runs the command")
    w.add_argument("--seconds", type=int, required=True)
    w.add_argument("--command", required=True)
    k = sub.add_parser("wake-timeout", help="safety net of a kill that should wake the session for its last turn")
    k.add_argument("--session", required=True)
    k.add_argument("--transcript", required=True)
    k.add_argument("--offset", type=int, required=True, help="transcript size at the kill")
    k.add_argument("--seconds", type=int, required=True)
    g = sub.add_parser("write")
    g.add_argument("--session", required=True)
    g.add_argument("--transcript")
    g.add_argument("--focus")
    g.add_argument("--cause", help="what started the writer, recorded in the metrics")
    q = sub.add_parser("request")
    q.add_argument("--session", required=True)
    q.add_argument("--focus")
    q.add_argument(
        "--cause", default="model", help="who asked: model (the handover skill) or user (the trigger and relay skills)"
    )
    q.add_argument("--reason", help="why the session asked for a handover now, recorded in the metrics")
    q.add_argument(
        "--relay", action="store_true", help="hand over without the user, then keep relaying up to relay_limit"
    )
    s = sub.add_parser("status")
    s.add_argument("--session")
    m = sub.add_parser("stats")
    m.add_argument(
        "--json",
        action="store_true",
        help="the cycles, the relay chains and the AFK runs as JSON instead of the tables",
    )
    m.add_argument(
        "--audit", metavar="RUN", help="check an AFK run's audit log (hash chain, length at the end) and plugin hash"
    )
    sub.add_parser("statusline")
    c = sub.add_parser("config", help="the options with their default and current value, as JSON")
    c.add_argument(
        "--set", metavar="JSON", help="save these option values, a JSON object; options left out keep theirs"
    )
    r = sub.add_parser("relay-drive")
    r.add_argument("--session", required=True)
    r.add_argument("--pane", help="tmux pane to type /clear and the message into")
    r.add_argument("--message")
    r.add_argument("--kill", type=int, help="claude process to end, for the claude-relay loop to restart")
    a = sub.add_parser("afk")
    a.add_argument("--session", required=True)
    a.add_argument("--goal", help="what the run works toward, until it is met")
    a.add_argument("--until", help="deadline after which no new handover starts: 8, 8:30, tomorrow 8, +10h")
    a.add_argument("--off", action="store_true", help="turn AFK mode off in this session")
    y = sub.add_parser("yolo-settings")
    y.add_argument("--merge")
    u = sub.add_parser("until")
    u.add_argument("when", nargs="+")
    args = ap.parse_args()
    if args.data_dir:
        os.environ["CLAUDE_PLUGIN_DATA"] = args.data_dir
    return {
        "hook": cmd_hook,
        "write": cmd_write,
        "request": cmd_request,
        "status": cmd_status,
        "stats": cmd_stats,
        "statusline": cmd_statusline,
        "relay-drive": cmd_relay_drive,
        "afk": cmd_afk,
        "until": cmd_until,
        "guidance": cmd_guidance,
        "await-timeout": cmd_await_timeout,
        "wake-timeout": cmd_wake_timeout,
        "config": cmd_config,
        "yolo-settings": cmd_yolo_settings,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
