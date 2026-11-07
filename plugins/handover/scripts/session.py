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
transitions below the only writers of the flags `phase()` computes the phase from. The phase is stored next
(decision register 26-11-07-claude-plugins-architecture, D01-D05, D11-D16).
"""

import os
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
# A compaction's handover is loaded next to its summary, and the session starts over from it.
COMPACTED = (
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
    "reply_offset",
    "written",
    "compacting",
)
# Due again at a handover asked for after an earlier one.
CLOSING = ("closing_reply", "reply_due", "reply_reminded", "held_since", "reply_offset")


def path(sid):
    return os.path.join(data_dir(), "sessions", f"{sid}.json")


def read(sid):
    """The session's state, unlocked: a snapshot for a reader."""
    return read_json(path(sid), {})


def locked(sid):
    """The session's state, saved on exit; hooks and the writer never interleave."""
    return locked_json(path(sid))


def tracked(sid):
    """Whether the session's state holds more than what SessionStart records."""
    return bool(set(read(sid)) - START_FIELDS)


def phase(st):
    """The session's phase, from its state."""
    if st.get("compacting"):
        return COMPACTING
    outcome = st.get("relay_outcome") or {}
    if outcome.get("at"):
        return RELAYING
    if outcome:
        return HALTED
    if st.get("closing_reply"):
        return HANDED_OVER
    return WINDING_DOWN if st.get("wind_down") else WORKING


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
    if not outcome or outcome.get("at"):
        return None
    if outcome.get("afk"):
        return "afk"
    if outcome.get("limit"):
        return "deadline" if outcome.get("deadline") else "limit"
    return "failed"


def handing_over(st):
    """Whether the session's handover is due: winding down or past it, or kept fresh for a compaction."""
    return bool(st.get("wind_down") or st.get("compacting"))


# Transitions: each takes the state, held under `locked`, and changes it.


def started(st, thresholds, version):
    """SessionStart: the thresholds and plugin version the session runs with, recorded once. A compaction or a
    resume starts the same session again: its thresholds stay."""
    st.setdefault("thresholds", thresholds)
    st.setdefault("plugin_version", version)


def wind_down(st, cause, tokens):
    """The wind-down starts: the session starts no new task and finishes those in progress. False when it is
    winding down already, or compacting, whose handover is loaded next to the summary instead."""
    if handing_over(st):
        return False
    st.update(wind_down=True, wind_down_tokens=tokens, cause=cause)
    return True


def requested(st):
    """A handover asked for: the session knows only the handover and its closing reply are left, due again
    after an earlier handover."""
    st["user_notified"] = st["wind_down_sent"] = True
    for k in CLOSING:
        st.pop(k, None)


def compaction_starts(st):
    st["compacting"] = True


def active(st):
    """The session works again: a compaction it was in is over, or was cancelled, back to the phase before it."""
    st.pop("compacting", None)
    st.pop("keep_fresh", None)


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


def reply_written(st):
    st["closing_reply"] = True


def relayed(st, n, mode):
    st["relay_outcome"] = {"at": time.time(), "n": n, "mode": mode}


def halted(st, reason, n, afk=None):
    """The relay stops: "limit", "deadline", "failed", or "afk", the AFK run's end, `afk` being how it ended."""
    if reason == "afk":
        st["relay_outcome"] = {"afk": afk, "n": n}
    elif reason == "failed":
        st["relay_outcome"] = {"failed": True, "n": n}
    else:
        st["relay_outcome"] = {"limit": True, "n": n, **({"deadline": True} if reason == "deadline" else {})}
