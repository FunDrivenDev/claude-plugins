"""The session's handover state: its lifecycle phase, its modes and its facts.

A session is in one phase at a time, in lifecycle order:

    working       no wind-down: the handover may be suggested, refreshed or kept fresh
    compacting    a compaction runs: its SessionStart brings the session back to working, a cancelled one ends
                  at the next activity
    winding_down  the wind-down started: the session finishes its tasks, held while agents, commands or a wake run,
                  then owes its closing reply once the handover was attempted at its stop (`reply_owed`)
    handed_over   the closing reply is written: the user runs /clear, or the relay starts
    relaying      the relay launched the next session
    halted        the relay stopped, for `halt_reason`: its limit, the AFK deadline, a failed relay, the AFK run's end

Orthogonal to the phase: the modes, `afk` (an AFK run, active or ended) and `relay` (the relay is on, its chain),
and the writer, an activity that runs in any phase (a refresh while working, the stop write while winding down), told
by its pid. Its result is a fact: `written`, `error`, `write_failed`.

The module owns the session's state file, `sessions/<sid>.json`: `read` and `locked` are its only ways in, and the
transitions below the only writers of its `phase` field, absent while working, and of `phase_before`, the phase
a compaction interrupted. A file an older plugin version wrote holds flags instead (`wind_down`, `closing_reply`,
`compacting`, `keep_fresh`): `read` and `locked` convert it (decision register
26-11-07-claude-plugins-architecture, D01-D05, D11-D16).
"""

import contextlib
import os
import re
import time

from store import data_dir, locked_json, read_json

WORKING = "working"
COMPACTING = "compacting"
WINDING_DOWN = "winding_down"
HANDED_OVER = "handed_over"
RELAYING = "relaying"
HALTED = "halted"
PHASES = (WORKING, COMPACTING, WINDING_DOWN, HANDED_OVER, RELAYING, HALTED)

# What SessionStart records in every session, the plugin's hooks having run there or not.
START_FIELDS = {"thresholds", "plugin_version"}
# The flags an older plugin version kept the phase in.
LEGACY = ("wind_down", "closing_reply", "compacting", "keep_fresh")
# A compaction's handover is loaded next to its summary, and the session starts over from it.
COMPACTED = (
    "phase",
    "phase_before",
    "wind_down_tokens",
    "cause",
    "suggested",
    "user_notified",
    "wind_down_sent",
    "reply_due",
    "reply_reminded",
    "held_since",
    "write_failed",
    "reply_offset",
    "written",
    "resume",
    "focus",
    "focus_at",
    "agents_refused",
    "refused_call",
    "refused_open",
)
# Due again at a handover asked for after an earlier one.
CLOSING = ("reply_due", "reply_reminded", "held_since", "reply_offset", "resume")
# The writer is stopped after this; past it and a margin, its pid may belong to another process.
WRITER_TIMEOUT = 600
# The thresholds recorded at SessionStart, by their name in the pane's view.
THRESHOLDS = {"suggest": "suggest_tokens", "warn_at": "warn_at_tokens", "trigger": "trigger_tokens"}


def path(sid):
    return os.path.join(data_dir(), "sessions", f"{sid}.json")


def read(sid):
    """The session's state, unlocked: a snapshot for a reader."""
    return converted(read_json(path(sid), {}))


@contextlib.contextmanager
def locked(sid):
    """The session's state, saved on exit; hooks and the writer never interleave."""
    with locked_json(path(sid)) as st:
        yield converted(st)


def tracked(sid):
    """Whether the session's state holds more than what SessionStart records."""
    return bool(set(read(sid)) - START_FIELDS)


def legacy_phase(st):
    """The phase an older plugin version's flags meant."""
    if st.get("wind_down") and not st.get("closing_reply"):
        # A handover asked for again after the relay's end: its Stop writes it.
        return WINDING_DOWN
    outcome = st.get("relay_outcome") or {}
    if outcome.get("at"):
        return RELAYING
    if outcome:
        return HALTED
    if st.get("closing_reply"):
        return HANDED_OVER
    return WINDING_DOWN if st.get("wind_down") else WORKING


def converted(st):
    """The state, its phase flags from an older plugin version turned into the `phase` field."""
    # Without them, the file is a new one, or an old one a compaction reset: working, its relay outcome a fact.
    if not any(k in st for k in LEGACY):
        return st
    meant, compacting = legacy_phase(st), st.get("compacting")
    for k in LEGACY:
        st.pop(k, None)
    if meant != WORKING:
        st["phase"] = meant
    if compacting:
        compaction_starts(st)
    return st


def phase(st):
    """The session's phase."""
    return st.get("phase") or WORKING


def settled(st):
    """The phase, or in a compaction the phase it interrupted, and comes back to when cancelled."""
    p = phase(st)
    return st.get("phase_before") or WORKING if p == COMPACTING else p


def wound_down(st):
    """Whether the wind-down started, in this phase or the one a compaction interrupted: past it, the session
    starts no new task."""
    return settled(st) != WORKING


def replied(st):
    """Whether the closing reply is written: handed over, relaying, or halted."""
    return settled(st) in (HANDED_OVER, RELAYING, HALTED)


def reply_owed(st):
    """Whether a winding-down session owes its closing reply: the handover was attempted at its stop."""
    if phase(st) != WINDING_DOWN:
        return False
    # Written while the Stop hook holds the session: the hook sets reply_due a moment later.
    held, written = st.get("held_since"), st.get("written") or {}
    return bool(st.get("reply_due") or held and written.get("ok") and written.get("at", 0) >= held)


def halt_reason(st):
    """Why the relay stopped, in a halted session: "afk", "deadline", "limit" or "failed"; None otherwise."""
    outcome = st.get("relay_outcome") or {}
    if phase(st) != HALTED:
        return None
    if outcome.get("afk"):
        return "afk"
    if outcome.get("limit"):
        return "deadline" if outcome.get("deadline") else "limit"
    return "failed"


def writing(st, now=None):
    """Whether the writer runs (D12): started within its timeout and a margin, its pid alive."""
    r = st.get("writer")
    if not r:
        return False
    if (now or time.time()) - r.get("since", 0) > WRITER_TIMEOUT + 60:
        return False
    try:
        os.kill(r["pid"], 0)
    except (OSError, KeyError, TypeError):
        return False
    return True


def handing_over(st):
    """Whether the session's handover is due: winding down or past it, or kept fresh for a compaction."""
    return phase(st) != WORKING


# Transitions: each takes the state, held under `locked`, and changes it.


def enter(st, p):
    """The session moves to phase `p`; in a compaction, once the compaction is over or cancelled."""
    key = "phase_before" if phase(st) == COMPACTING else "phase"
    if p == WORKING:
        st.pop(key, None)
    else:
        st[key] = p


def started(st, thresholds, version):
    """SessionStart: the thresholds and plugin version the session runs with, recorded once. A compaction or a
    resume starts the same session again: its thresholds stay."""
    st.setdefault("thresholds", thresholds)
    st.setdefault("plugin_version", version)


def wind_down(st, cause, tokens):
    """The wind-down starts: the session starts no new task and finishes those in progress. False when it is
    winding down already. Asked for during a compaction, it outlives a cancelled one."""
    if wound_down(st):
        return False
    st.update(wind_down_tokens=tokens, cause=cause)
    enter(st, WINDING_DOWN)
    return True


def requested(st):
    """A handover asked for: the session knows only the handover and its closing reply are left, due again
    after an earlier handover."""
    st["user_notified"] = st["wind_down_sent"] = True
    for k in CLOSING:
        st.pop(k, None)
    if replied(st):
        # Past the closing reply, the relay's end included: the handover and the reply are due again, and an
        # earlier refusal no longer overrules a block.
        st.pop("refused_open", None)
        enter(st, WINDING_DOWN)


def compaction_starts(st):
    if phase(st) != COMPACTING:
        before = phase(st)
        st["phase"] = COMPACTING
        if before != WORKING:
            st["phase_before"] = before


def active(st):
    """The session works again: a compaction it was in is over, or was cancelled, back to the phase before it."""
    if phase(st) == COMPACTING:
        st.pop("phase")
        before = st.pop("phase_before", None)
        if before:
            st["phase"] = before


def compacted(st):
    """After a compaction: the session starts over from a small context, to wind down and be told again."""
    for k in COMPACTED:
        st.pop(k, None)


def held(st, at=None):
    """The Stop hook holds the session while it writes the handover."""
    st["held_since"] = at or time.time()


def reply_asked(st, failed):
    """The handover was attempted at the stop: the session owes its closing reply."""
    st["reply_due"] = True
    st["write_failed"] = failed


def wrote(st, failed):
    """The handover was written again at the session's last stop, or that write failed."""
    st["write_failed"] = failed


def reply_written(st, resume=None):
    """The closing reply is written, with the message it gives the next session to start on, when it has one."""
    if resume:
        st["resume"] = resume
    enter(st, HANDED_OVER)


def relayed(st, n, mode):
    st["relay_outcome"] = {"at": time.time(), "n": n, "mode": mode}
    enter(st, RELAYING)


def halted(st, reason, n, afk=None):
    """The relay stops: "limit", "deadline", "failed", or "afk", the AFK run's end, `afk` being how it ended."""
    if reason == "afk":
        st["relay_outcome"] = {"afk": afk, "n": n}
    elif reason == "failed":
        st["relay_outcome"] = {"failed": True, "n": n}
    else:
        st["relay_outcome"] = {"limit": True, "n": n, **({"deadline": True} if reason == "deadline" else {})}
    enter(st, HALTED)


# The session-mods pane's view (D18): the pane runs `handover.py state --session <sid> --json` and only renders it.


def title(text):
    """A handover's title: its front matter's `summary`, else its `# Handover:` heading."""
    front = re.match(r"---\n(.*?)\n---", text, re.DOTALL)
    summary = front and re.search(r"^summary:\s*[\"']?(.+?)[\"']?\s*$", front.group(1), re.MULTILINE)
    if summary:
        return summary.group(1)
    heading = re.search(r"^#\s*Hand(?:over|off):\s*(.+)$", text, re.MULTILINE)
    return heading.group(1).strip() or None if heading else None


def document(path):
    """A handover document as the pane lists it: its title, line count and last change (epoch s), each None when
    unread; None without a path."""
    if not path or not isinstance(path, str):
        return None
    try:
        # As `wc -l` and `head` count: only "\n" ends a line, and a byte that is not UTF-8 leaves the rest readable.
        with open(path, encoding="utf-8", errors="replace", newline="") as f:
            text = f.read()
        modified = int(os.path.getmtime(path))
    except (OSError, ValueError):
        return {"path": path, "title": None, "lines": None, "modified_at": None}
    head = "\n".join(text.split("\n")[:40]).replace("\r\n", "\n")
    return {"path": path, "title": title(head), "lines": text.count("\n"), "modified_at": modified}


def recorded_thresholds(st, resolved):
    """(thresholds, why unknown, pending): the thresholds the session recorded at its start, never a default; the
    suggest and trigger points `resolved` now gives otherwise, which apply from the next session."""
    saved = st.get("thresholds")
    if not isinstance(saved, dict):
        why = (
            "this session's handover state records no thresholds: its handover plugin is older than 0.20.0, which "
            "records them at session start"
        )
        return None, why, None
    bad = [
        v for v in THRESHOLDS.values() if not isinstance(saved.get(v), (int, float)) or isinstance(saved.get(v), bool)
    ]
    if bad:
        version = f" (handover {st['plugin_version']})" if isinstance(st.get("plugin_version"), str) else ""
        return (
            None,
            f"in this session's handover state{version}, not a number: thresholds." + ", thresholds.".join(bad),
            None,
        )
    th = {k: saved[v] for k, v in THRESHOLDS.items()}
    pending = {
        k: resolved[THRESHOLDS[k]]
        for k in ("suggest", "trigger")
        if isinstance((resolved or {}).get(THRESHOLDS[k]), int) and resolved[THRESHOLDS[k]] != th[k]
    }
    return th, None, pending or None


def view(st, on, resolved, went_on=False):
    """The session's handover state for the session-mods pane: `on` (its hooks run in the session), the phase, the
    pid-checked writer, its error as the status line cuts it, the written and loaded handovers, the thresholds and
    the resume message. `resolved` holds the thresholds the options give now, None when they do not resolve;
    `went_on`, whether anything came in after the closing reply: its resume message may then be stale."""
    error = st.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    th, why, pending = recorded_thresholds(st, resolved)
    return {
        "on": on,
        "phase": phase(st),
        "wound_down": wound_down(st),
        "writing": writing(st),
        "error": message[:60] if isinstance(message, str) and message else None,
        "written": document(st.get("path")) if (st.get("written") or {}).get("ok") else None,
        "loaded": document(st.get("loaded_from")),
        "thresholds": th,
        "thresholds_error": why,
        "pending": pending,
        "resume": None if went_on else st.get("resume"),
    }
