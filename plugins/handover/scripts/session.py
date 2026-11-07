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

`phase()` computes the phase from the flags handover.py's transitions set; those transitions move here next, then
the phase is stored (decision register 26-11-07-claude-plugins-architecture, D01-D05, D11-D16).
"""

WORKING = "working"
COMPACTING = "compacting"
WINDING_DOWN = "winding_down"
HANDED_OVER = "handed_over"
RELAYING = "relaying"
HALTED = "halted"
PHASES = (WORKING, COMPACTING, WINDING_DOWN, HANDED_OVER, RELAYING, HALTED)


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
