"""The relay handshake (D19): how a session handing over and the session the relay starts meet in the data folder.

    offer(key, sid, mode)        the session handing over offers its handover to the next session at `key`
    claim(key, sid)              the next session takes the offer: once, unless stale or its own
    confirm(prev, ok)            it says whether the handover of `prev` loaded
    await_confirmation(prev)     the relay's driver waits for that answer before it types the resume message, unless
                                 a later relay of `prev` supersedes it

`key` names the project and the pane (handover.py relay_key): the session the relay starts in a pane claims only the
offer made in that pane, so two chains of one project that hand over together never take each other's.

This module owns the file names, the staleness and the timeouts of the handshake, and writes each file atomically.
What the sessions do around it (loading the handover, typing into the terminal, the records) stays in handover.py.
"""

import contextlib
import os
import time

from store import data_dir, read_json, write_json

# An offer older than this is stale: no /clear followed it, so a later session must not take it.
OFFER_SECONDS = 300
# How long the claiming session waits for the writer of the handover it loads.
LOAD_SECONDS = 150
# How long the driver waits for the claim's answer: the new session's start, its wait for the writer, a margin.
CONFIRM_SECONDS = LOAD_SECONDS + 60


def offer_path(key):
    return os.path.join(data_dir(), "relay", f"{key}.json")


def confirmation_path(sid):
    return os.path.join(data_dir(), "relay", f"{sid}.loaded.json")


def offer(key, sid, mode, now=None):
    """Session `sid` hands over at `key`, relayed by `mode` (the terminal's name, or `loop`)."""
    write_json(offer_path(key), {"session": sid, "at": time.time() if now is None else now, "mode": mode})


def claim(key, sid, now=None):
    """The offer at `key`, taken by the starting session `sid`: {session, at, mode}, or None when there is
    none, it is stale, or `sid` made it. Taken once: of two sessions claiming together, one gets it."""
    path = offer_path(key)
    now = time.time() if now is None else now
    sweep(key, now)
    seen = read_json(path)
    if isinstance(seen, dict) and seen.get("session") == sid:
        # Its own offer waits for the next session, left in place: a claim moving it would hide it from that one.
        return None
    taken = f"{path}.{sid}.{os.getpid()}.claimed"
    try:
        # A rename moves the file once: the session whose rename fails lost the race. What it judges is the file it
        # moved, never one read before: another offer may have replaced it in between.
        os.rename(path, taken)
    except FileNotFoundError:
        return None
    pending = read_json(taken)
    valid = isinstance(pending, dict) and isinstance(pending.get("session"), str)
    at = pending.get("at") if valid else None
    if valid and pending["session"] == sid:
        # Its own offer, written after the look above: put back, unless a newer one is there.
        with contextlib.suppress(OSError):
            os.link(taken, path)
    with contextlib.suppress(OSError):
        os.remove(taken)
    if not valid or pending["session"] == sid or not isinstance(at, (int, float)) or now - at > OFFER_SECONDS:
        return None
    return pending


def sweep(key, now):
    """Removes what a claim that crashed between its rename and its remove left behind."""
    prefix = os.path.basename(offer_path(key)) + "."
    folder = os.path.dirname(offer_path(key))
    with contextlib.suppress(OSError):
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            if name.startswith(prefix) and name.endswith(".claimed") and now - os.path.getmtime(p) > OFFER_SECONDS:
                with contextlib.suppress(OSError):
                    os.remove(p)


def confirm(prev, ok):
    """The claiming session's answer to the driver of `prev`'s relay: whether `prev`'s handover loaded."""
    write_json(confirmation_path(prev), {"ok": bool(ok)})


def await_confirmation(prev, seconds=CONFIRM_SECONDS, clock=time.time, sleep=time.sleep, superseded=lambda: False):
    """Whether the session that claimed `prev`'s offer loaded its handover, waited for up to `seconds`: False when
    it says it did not, or no answer came in time; None once `superseded()`, the answer left to the newer driver.
    The answer is consumed."""
    path = confirmation_path(prev)
    deadline = clock() + seconds
    while not os.path.exists(path) and clock() < deadline:
        if superseded():
            return None
        sleep(1)
    if superseded():
        return None
    answer = read_json(path, {})
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)
    return isinstance(answer, dict) and answer.get("ok") is True
