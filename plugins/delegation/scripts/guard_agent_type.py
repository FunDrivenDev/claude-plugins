#!/usr/bin/env python3
"""PreToolUse hook on the Agent tool: a catch-all subagent (no type, general-purpose, claude, fork) starts on a large
context with every tool, so the plugin's typed read-only roles are named instead.

Mode, from DELEGATION_GUARD_MODE (a session's override), else the plugin's guard_mode option (the hook environment,
then settings.json), else off:
- off: nothing happens;
- log: the call goes through, and a would-block event is appended to <plugin data>/guard-agent-type.jsonl;
- block: the call is refused with the roles to pick, and the refusal is logged.
An event holds the time, the decision, the agent type and the skill running in the current turn, nothing else. Any
error lets the call through: the hook never blocks by mistake."""

import datetime as dt
import json
import os
import pathlib
import re
import sys

CATCH_ALL = {"", "general-purpose", "claude", "fork"}
MODES = {"off", "log", "block"}
TAIL_BYTES = 2_000_000
REASON = """Subagent refused: {type} is a catch-all type, with a large starting context and every tool.
Delegate read-only, result-only work to a typed agent: Explore (locate code), delegation:investigator (diagnosis), \
delegation:reviewer (findings at file:line), delegation:researcher (web or docs), delegation:skeptic (objections to \
a plan), claude-code-guide (Claude Code), or another plugin's read-only agent.
Writing (edits, tests, commits) stays in this session: do it here."""


def data_dir():
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        return pathlib.Path(data)
    return config_dir() / "plugins" / "data" / "delegation-fundrivendev"


def config_dir():
    return pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude")


def mode():
    for v in (os.environ.get("DELEGATION_GUARD_MODE"), os.environ.get("CLAUDE_PLUGIN_OPTION_GUARD_MODE")):
        if v and v.strip():
            return normal(v)
    try:
        configs = json.loads((config_dir() / "settings.json").read_text()).get("pluginConfigs") or {}
    except (OSError, ValueError):
        configs = {}
    name = data_dir().name
    key = "delegation@" + name.removeprefix("delegation-") if name.startswith("delegation-") else None
    for k, v in configs.items():
        if k == key or (key is None and k.startswith("delegation@")):
            return normal(str((v.get("options") or {}).get("guard_mode") or "off"))
    return "off"


def normal(v):
    v = v.strip().lower()
    return v if v in MODES else "off"


def current_skill(transcript):
    """The skill invoked since the session's last prompt (a Skill call or a slash command), else None."""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - TAIL_BYTES))
            lines = f.read().decode(errors="replace").splitlines()
    except (OSError, TypeError):
        return None
    skill = None
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("isMeta") or r.get("isSidechain"):
            continue
        content = (r.get("message") or {}).get("content")
        if r.get("type") == "user":
            text = content if isinstance(content, str) else None
            if isinstance(content, list):
                if any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                    continue
                text = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            if text is not None:
                m = re.search(r"<command-name>/?([^<\s]+)</command-name>", text)
                skill = m.group(1) if m else None
        elif r.get("type") == "assistant" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                    skill = (c.get("input") or {}).get("skill") or skill
    return skill


def log(decision, agent_type, skill):
    try:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event = {"ts": ts, "decision": decision, "agent_type": agent_type, "skill": skill}
        with open(d / "guard-agent-type.jsonl", "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:  # noqa: BLE001 - a failed log never changes the decision
        print(f"guard-agent-type: the event was not logged: {e}", file=sys.stderr)


def main():
    m = mode()
    if m == "off":
        return 0
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") not in ("Agent", "Task"):
        return 0
    agent_type = str((payload.get("tool_input") or {}).get("subagent_type") or "").strip()
    if agent_type not in CATCH_ALL:
        return 0
    if m == "block":
        reason = REASON.format(type=agent_type or "no subagent_type")
        out = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}
        print(json.dumps({"hookSpecificOutput": out}), flush=True)
    # The decision is out before the log, which may fail without changing it.
    log("would-block" if m == "log" else "block", agent_type, current_skill(payload.get("transcript_path")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
