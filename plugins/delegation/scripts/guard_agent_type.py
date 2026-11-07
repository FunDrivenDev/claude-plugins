#!/usr/bin/env python3
"""PreToolUse hook on the Agent and Bash tools.
- Agent: a catch-all subagent (no type, general-purpose, claude, fork) starts on a large context with every tool, so
  the plugin's typed read-only roles are named instead.
- Bash: the plugin's own agents (agent_type delegation:*) are read-only, so a command that writes (measure's
  bash_writes, the definition M2 uses) is caught, unless every write lands in a temporary folder (a `mktemp -d`
  one, $TMPDIR, /tmp): the agents' throwaway reproductions. A push or a gh write is caught even there. The main
  session's commands (no agent_type) and other agents' are never touched.

Mode, from DELEGATION_GUARD_MODE (a session's override), else the plugin's guard_mode option (the hook environment,
then settings.json), else off. An invalid override is ignored with a one-line warning on stderr (exit 0: Claude Code
shows it in verbose mode only, and the call is decided by the option); an invalid option is off; a settings.json that
cannot be read, or whose level on the way to the option is not an object, sets no option, with the same kind of
warning:
- off: nothing happens;
- log: the call goes through, and a would-block event is appended to <plugin data>/guard-agent-type.jsonl;
- block: the call is refused with what to do instead, and the refusal is logged.
An event holds the time, the decision, the tool, the agent type and, for an Agent call, the skill running in the
current turn, nothing else. Any error before the decision lets the call through: the hook never blocks by mistake."""

import datetime as dt
import json
import os
import pathlib
import re
import shlex
import sys

try:  # measure's bash_writes, the definition of a write M2 counts; without it the Bash guard lets every call through
    import measure
except Exception:  # noqa: BLE001
    measure = None

CATCH_ALL = {"", "general-purpose", "claude", "fork"}
MODES = {"off", "log", "block"}
TAIL_BYTES = 2_000_000
REASON = """Subagent refused: {type} is a catch-all type, with a large starting context and every tool.
Delegate read-only, result-only work to a typed agent: Explore (locate code), delegation:investigator (diagnosis), \
delegation:reviewer (findings at file:line), delegation:researcher (web or docs), delegation:skeptic (objections to \
a plan), claude-code-guide (Claude Code), or another plugin's read-only agent.
Writing (edits, tests, commits) stays in this session: do it here."""
BASH_REASON = """Bash write refused: {type} is read-only, and this command changes a file, the repo or a remote.
Run a throwaway reproduction in a fresh folder: d=$(mktemp -d) && cd "$d" && ..., removed before you report.
Anything else goes into your report (under Repro or Verify) for the main session to run."""
# A temporary folder: /tmp, macOS's per-user /var/folders, $TMPDIR; `mktemp -d` and the variables set from it are
# rewritten to /tmp/mktemp before the check.
TEMP_ROOT = re.compile(r"^(?:/private)?/(?:tmp|var/folders)(?:/|$)")
MKTEMP = re.compile(r"\$\(\s*mktemp\b[^)]*\)|`\s*mktemp\b[^`]*`")
SEPARATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", "\n"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
PREFIXES = {"sudo", "env", "command", "nohup", "time", "then", "do", "else", "if", "while", "until", "!", "{"}
FILE_COMMANDS = {"mv", "rm", "rmdir", "mkdir", "touch", "truncate", "tee"}
MODE_COMMANDS = {"chmod", "chown"}
COPY_COMMANDS = {"cp", "install", "ln"}
PUSH = re.compile(r"\bgit\b(?:\s+(?:-[Cc]\s+\S+|--\S+))*\s+push\b|\bgh\s+(?:pr|issue|release|api)\b")


def data_dir():
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        return pathlib.Path(data)
    return config_dir() / "plugins" / "data" / "delegation-fundrivendev"


def config_dir():
    return pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude")


def mode():
    """The session's override if it is a mode, else the option's mode. An invalid override is ignored with a warning:
    a typo never turns block off. An invalid option is off."""
    option = option_mode()
    override = (os.environ.get("DELEGATION_GUARD_MODE") or "").strip()
    if not override:
        return option
    if override.lower() in MODES:
        return override.lower()
    print(
        f"guard-agent-type: DELEGATION_GUARD_MODE={override!r} is not off, log or block, so it is ignored; "
        f"the guard_mode option applies: {option}",
        file=sys.stderr,
    )
    return option


def option_mode():
    """The plugin's guard_mode option: the hook environment, then settings.json, else off."""
    v = os.environ.get("CLAUDE_PLUGIN_OPTION_GUARD_MODE")
    if v and v.strip():
        return normal(v)
    path = config_dir() / "settings.json"
    try:
        return settings_mode(path)
    except Malformed as e:
        print(f"guard-agent-type: {path}: {e}, so it sets no guard_mode option: off", file=sys.stderr)
        return "off"


class Malformed(Exception):
    """settings.json cannot be read, or a level on the way to the option is not an object."""


JSON_TYPES = {list: "an array", str: "a string", bool: "a boolean", int: "a number", float: "a number"}


def json_object(value, where):
    """value if it is an object, {} if it is null or absent, else Malformed."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise Malformed(f"{where} is {JSON_TYPES.get(type(value), 'another type')}, not an object")
    return value


def settings_mode(path):
    """The guard_mode option in settings.json's pluginConfigs: off when the file or a level is missing."""
    try:
        text = path.read_text()
    except FileNotFoundError:
        return "off"
    except OSError as e:
        raise Malformed(f"it cannot be read ({e.strerror or e})") from e
    try:
        settings = json.loads(text)
    except ValueError as e:
        raise Malformed("it is not valid JSON") from e
    configs = json_object(json_object(settings, "the file").get("pluginConfigs"), "pluginConfigs")
    name = data_dir().name
    key = "delegation@" + name.removeprefix("delegation-") if name.startswith("delegation-") else None
    for k, v in configs.items():
        if k == key or (key is None and k.startswith("delegation@")):
            entry = json_object(v, f"pluginConfigs[{k!r}]")
            options = json_object(entry.get("options"), f"pluginConfigs[{k!r}].options")
            return normal(str(options.get("guard_mode") or "off"))
    return "off"


def normal(v):
    v = v.strip().lower()
    return v if v in MODES else "off"


# User records that are not a prompt: a background agent's notice, a `!` command's echo, a local command's output,
# another session's message. They arrive mid-turn and keep the skill that runs.
NOT_A_PROMPT = ("<task-notification>", "<bash-", "<local-command-", "Another Claude session sent a message")


def current_skill(transcript):
    """The skill invoked since the session's last prompt (a Skill call or a slash command), else None.

    Only a typed prompt starts a new turn: a record with an `origin` or one of NOT_A_PROMPT does not."""
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
                if m:
                    skill = m.group(1)
                elif not (r.get("origin") or text.lstrip().startswith(NOT_A_PROMPT)):
                    skill = None
        elif r.get("type") == "assistant" and isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                    skill = (c.get("input") or {}).get("skill") or skill
    return skill


def temp_path(path):
    """Whether a path sits in a temporary folder, with no `..` to climb out of it."""
    path = os.path.expandvars(path)
    tmpdir = os.environ.get("TMPDIR", "").rstrip("/")
    inside = bool(TEMP_ROOT.match(path)) or bool(tmpdir and (path == tmpdir or path.startswith(tmpdir + "/")))
    return inside and ".." not in path.split("/")


def segments(command):
    """The simple commands of a command line, as token lists, its heredoc bodies and quotes resolved."""
    bare = measure.HEREDOC.sub(lambda m: m.group(3) + "\n", command)
    names = set(re.findall(r"\b(\w+)=[\"']?(?:" + MKTEMP.pattern + ")", bare)) | {"TMPDIR"}
    bare = MKTEMP.sub("/tmp/mktemp", bare)
    for name in names:
        bare = re.sub(r"\$\{?" + name + r"\}?(?!\w)", "/tmp/mktemp", bare)
    lex = shlex.shlex(bare, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    seg = []
    for tok in lex:
        if tok in SEPARATORS:
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def targets(seg, writes):
    """What a simple command writes to: its paths, "." for the folder it runs in, or None for a remote."""
    out, args, skip = [], [], False
    for i, tok in enumerate(seg):
        if skip:
            skip = False
        elif tok in REDIRECTS or tok == ">&" and i + 1 < len(seg) and not seg[i + 1].isdigit():
            if i + 1 < len(seg) and not seg[i + 1].startswith("/dev/"):
                out.append(seg[i + 1])
            skip = True
        elif tok in ("<", "<<<", ">&", "<&"):
            skip = True
        else:
            args.append(tok)
    while args and (args[0] in PREFIXES or re.match(r"^\w+=", args[0])):
        args.pop(0)
    if not args:
        return out
    cmd, rest = os.path.basename(args[0]), [a for a in args[1:] if not a.startswith("-")]
    line = " ".join(args)
    if PUSH.search(line) and writes(shlex.join(args)):
        return None
    if cmd in FILE_COMMANDS:
        out += rest
    elif cmd in MODE_COMMANDS:
        out += rest[1:]
    elif cmd in COPY_COMMANDS:
        out += rest[-1:]
    elif cmd == "dd":
        out += [a[3:] for a in args if a.startswith("of=")]
    elif cmd == "git":
        if writes(shlex.join(args)):
            c = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "-C"]
            out += c or ["."]
    elif cmd in ("sed", "gsed", "perl") and any(re.match(r"^-[a-zA-Z]*i", a) for a in args[1:]):
        out += rest if any(a in ("-e", "-f") for a in args) else rest[1:]
    elif writes(shlex.join(args)) or writes(line):
        out.append(".")
    return out


def bash_writes_outside_temp(command, cwd):
    """Whether a command writes, per measure's bash_writes, somewhere other than a temporary folder."""
    if not measure.bash_writes(command):
        return False
    here = temp_path(cwd or "")
    for seg in segments(command):
        words = [t for t in seg if not re.match(r"^\w+=", t) and t not in PREFIXES]
        if words[:1] == ["cd"]:
            dest = next((a for a in words[1:] if not a.startswith("-")), "")
            here = temp_path(dest) or (here and not dest.startswith(("/", "~", "$")) and ".." not in dest.split("/"))
            continue
        out = targets(seg, measure.bash_writes)
        if out is None:
            return True
        for t in out:
            if temp_path(t):
                continue
            if here and not t.startswith(("/", "~", "$")) and ".." not in t.split("/"):
                continue
            return True
    return False


def log(decision, agent_type, skill, tool):
    try:
        d = data_dir()
        d.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event = {"ts": ts, "decision": decision, "tool": tool, "agent_type": agent_type, "skill": skill}
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
    if not isinstance(payload, dict):
        return 0
    tool = payload.get("tool_name")
    if tool in ("Agent", "Task"):
        agent_type = str((payload.get("tool_input") or {}).get("subagent_type") or "").strip()
        if agent_type not in CATCH_ALL:
            return 0
        reason = REASON.format(type=agent_type or "no subagent_type")
    elif tool == "Bash":
        agent_type = str(payload.get("agent_type") or "")
        if measure is None or not agent_type.startswith("delegation:"):
            return 0
        try:
            if not bash_writes_outside_temp(
                str((payload.get("tool_input") or {}).get("command") or ""), payload.get("cwd")
            ):
                return 0
        except Exception:  # noqa: BLE001 - an unreadable command never blocks by mistake
            return 0
        reason = BASH_REASON.format(type=agent_type)
    else:
        return 0
    if m == "block":
        out = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}
        print(json.dumps({"hookSpecificOutput": out}), flush=True)
    # The decision is out before the log, which may fail without changing it.
    skill = current_skill(payload.get("transcript_path")) if tool != "Bash" else None
    log("would-block" if m == "log" else "block", agent_type, skill, "Bash" if tool == "Bash" else "Agent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
