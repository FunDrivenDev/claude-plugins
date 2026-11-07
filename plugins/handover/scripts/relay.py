"""The relay handshake (D19): how a session handing over and the session the relay starts meet in the data folder.

    offer(key, sid, mode)        the session handing over offers its handover to the next session in project `key`
    claim(key, sid)              the next session takes the offer: once, unless stale or its own
    confirm(prev, ok)            it says whether the handover of `prev` loaded
    await_confirmation(prev)     the relay's driver waits for that answer before it types the resume message

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
    """Session `sid` hands over in project `key`, relayed by `mode` (the terminal's name, or `loop`)."""
    write_json(offer_path(key), {"session": sid, "at": time.time() if now is None else now, "mode": mode})


def claim(key, sid, now=None):
    """The offer of project `key`, taken by the starting session `sid`: {session, at, mode}, or None when there is
    none, it is stale, or `sid` made it. Taken once: of two sessions claiming together, one gets it."""
    path = offer_path(key)
    pending = read_json(path)
    if not isinstance(pending, dict) or not isinstance(pending.get("session"), str):
        return None
    at = pending.get("at")
    now = time.time() if now is None else now
    if pending["session"] == sid or not isinstance(at, (int, float)) or now - at > OFFER_SECONDS:
        return None
    taken = f"{path}.{sid}.{os.getpid()}.claimed"
    try:
        # A rename moves the file once: the session whose rename fails lost the race.
        os.rename(path, taken)
    except FileNotFoundError:
        return None
    os.remove(taken)
    return pending


def confirm(prev, ok):
    """The claiming session's answer to the driver of `prev`'s relay: whether `prev`'s handover loaded."""
    write_json(confirmation_path(prev), {"ok": bool(ok)})


def await_confirmation(prev, seconds=CONFIRM_SECONDS, clock=time.time, sleep=time.sleep):
    """Whether the session that claimed `prev`'s offer loaded its handover, waited for up to `seconds`: False when
    it says it did not, or no answer came in time. The answer is consumed."""
    path = confirmation_path(prev)
    deadline = clock() + seconds
    while not os.path.exists(path) and clock() < deadline:
        sleep(1)
    answer = read_json(path, {})
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)
    return isinstance(answer, dict) and answer.get("ok") is True
