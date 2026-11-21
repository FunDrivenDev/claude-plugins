#!/usr/bin/env python3
"""PreToolUse hook on the Agent and Bash tools.
- Agent: a catch-all subagent (no type, general-purpose, claude, fork) starts on a large context with every tool, so
  the plugin's typed read-only roles are named instead.
- Bash: the plugin's own agents (agent_type delegation:*) are read-only, so a command that writes (measure's
  bash_writes, the definition M2 uses) is caught, unless every write lands in a temporary folder (a `mktemp -d`
  one, $TMPDIR, /tmp, the session's own scratchpad, or a variable set from one): the agents' throwaway
  reproductions. A gh write is caught even there, and so is a push, unless its remote is a temporary path or a name
  this command line's clone or remote add set to one, with nothing in the line that can send it elsewhere. The main
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
# A temporary folder: /tmp, macOS's per-user /var/folders, $TMPDIR, the session's scratchpad; `mktemp -d` is rewritten
# to /tmp/mktemp before the check, and a variable set from a temporary path is one.
TEMP_ROOT = re.compile(r"^(?:/private)?/(?:tmp|var/folders)(?:/|$)")
# mktemp's arguments may hold quotes and variables, never a command of their own.
MKTEMP = re.compile(r"\$\(\s*mktemp\b(?:[^()`$]|\$(?!\())*\)|`\s*mktemp\b(?:[^()`$]|\$(?!\())*`")
FRESH = "/tmp/mktemp"  # what `mktemp -d` reads as: a folder just made, empty, in no repo
PWD = re.compile(r"\$\(\s*pwd(?:\s+-[LP])?\s*\)|`\s*pwd(?:\s+-[LP])?\s*`")
VAR = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
ASSIGN = re.compile(r"^(\w+)=(.*)$", re.DOTALL)
APPEND = re.compile(r"^(\w+)(?:\+=|\[)")
# What can change a variable or how it splits out of sight: IFS, sourced or evaluated code, a function, a trap. A
# command line holding one gets no variable tracked.
OPAQUE = re.compile(r"\bIFS\b|\bPWD\+?=|\w\s*\(\s*\)\s*\{|\bprintf\s+-\w*v")
OPAQUE_WORDS = {"source", ".", "eval", "builtin", "trap", "function", "alias", "read", "readonly", "exec", "mapfile"}
OPAQUE_WORDS |= {"readarray", "getopts", "declare", "local", "typeset"}
# What can send a push elsewhere, wherever it sits in the line (a git run through nice, sh -c, …).
REDIRECTS_PUSH = re.compile(
    r"\b(?:CDPATH|set-url|rename|insteadOf|pushInsteadOf|pushurl|pushDefault|gitdir|hooksPath|include(?:If)?|remote\.[\w-]+\.\w|branch\.\S+\.(?:remote|pushRemote|merge)|submodule|recurse)"
    r"|--(?:global|system|file)\b",
    re.IGNORECASE,
)
DECLARE = {"export", "local", "declare", "readonly", "typeset"}
SUBSHELL = {"|", "|&", "&", "("}
LITERAL_DOLLAR = "\x00"
SAFE_CONFIG = re.compile(
    r"^(?:(?:user|author|committer|commit|gpg|init|advice|color|tag|log|diff)\.\S+"
    r"|core\.(?:autocrlf|filemode|quotepath|editor|pager))$",
    re.IGNORECASE,
)
# The options of a push that keep it on the remote and the refs it names: any other one (--recurse-submodules,
# --repo, --exec, --no-verify, …) refuses it.
# The commands a line may hold beside a temporary push: none of them can rewrite a repo's remotes unseen (a write
# into .git, a hook or a config taints the line on its own).
PUSH_SAFE_COMMANDS = {"cd", "git", "echo", "printf", "cat", "ls", "mkdir", "touch", "rm", "rmdir", "true", "false"}
PUSH_SAFE_COMMANDS |= {":", "test", "[", "[[", "]]", "pwd", "grep", "head", "tail", "wc", "sleep"}
PUSH_SAFE_GIT_VERBS = {"init", "add", "commit", "status", "log", "diff", "show", "checkout", "switch", "branch", "tag"}
PUSH_SAFE_GIT_VERBS |= {"merge", "rebase", "reset", "rm", "mv", "restore", "stash", "rev-parse", "ls-files", "ls-tree"}
PUSH_SAFE_GIT_VERBS |= {"cat-file", "fetch", "pull", "cherry-pick", "revert", "describe", "merge-base", "config"}
PLAIN_PUSH_OPTIONS = re.compile(
    r"^(?:-[qufnvd]+|--(?:quiet|verbose|set-upstream|force|force-with-lease(?:=\S*)?|force-if-includes|tags|all"
    r"|follow-tags|atomic|dry-run|delete|porcelain|progress|no-progress|prune))$"
)
# Git's options before the verb that leave the repository and its remotes as -C and the folder give them.
GIT_PLAIN_OPTIONS = {"--no-pager", "-P", "--no-optional-locks", "--literal-pathspecs"}
# The options of git clone, remote and push that take the next word as their value.
GIT_VALUE_OPTIONS = {
    "clone": {"-b", "--branch", "-o", "--origin", "-c", "--config", "--depth", "-u", "--upload-pack", "-j", "--jobs"}
    | {"--reference", "--template", "--separate-git-dir", "--filter"},
    "remote": {"-t", "-m"},
    "push": {"-o", "--push-option", "--receive-pack", "--exec", "--repo"},
}
# A URL or an scp-like host:path: a remote that is no local path.
URL = re.compile(r"^(?!file://)[\w+.-]+://|^[^/]*:")
SEPARATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", "\n"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
PREFIXES = {"sudo", "env", "command", "nohup", "time", "then", "do", "else", "elif", "if", "while", "until", "!", "{"}
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


def temp_path(path, session=None):
    """Whether a path sits in a temporary folder, or in the session's own scratchpad, with no `..` to climb out."""
    path = os.path.expandvars(path)
    tmpdir = os.environ.get("TMPDIR", "").rstrip("/")
    inside = bool(TEMP_ROOT.match(path)) or bool(tmpdir and (path == tmpdir or path.startswith(tmpdir + "/")))
    if session and not inside:
        # Claude Code's scratchpad, <its temp folder>/claude-<uid>/<project>/<session id>/scratchpad, the temp folder
        # being CLAUDE_CODE_TMPDIR, else TMPDIR or /tmp: the session ID keeps every other session's out.
        roots = {os.environ.get("CLAUDE_CODE_TMPDIR", "").rstrip("/"), tmpdir, "/tmp", "/private/tmp"} - {""}
        tail = rf"/claude-{os.getuid()}/[^/]+/{re.escape(session)}/scratchpad(?:/|$)"
        inside = any(re.match(re.escape(r) + tail, path) for r in roots)
    return inside and ".." not in path.split("/")


def literal_dollars(text):
    """The text with each `$` that names no variable (in single quotes, or escaped) replaced by LITERAL_DOLLAR."""
    out, quote, i = [], None, 0
    while i < len(text):
        c = text[i]
        if quote != "'" and c == "\\" and i + 1 < len(text):
            out.append(c + (LITERAL_DOLLAR if text[i + 1] == "$" else text[i + 1]))
            i += 2
            continue
        if c in "'\"" and quote in (None, c):
            quote = None if quote else c
        out.append(LITERAL_DOLLAR if c == "$" and quote == "'" else c)
        i += 1
    return "".join(out)


def segments(command):
    """The simple commands of a command line, as token lists, its heredoc bodies and quotes resolved; `mktemp -d` reads
    /tmp/mktemp (a plain `mktemp`, /tmp/mktemp-file) and `pwd` reads $PWD, which bash_writes_outside_temp expands.
    Each comes with whether it runs in the shell itself, so that a variable it sets lasts (not in a pipeline, a
    subshell or the background), and the separator before it."""
    bare = measure.HEREDOC.sub(lambda m: m.group(3) + "\n", command)
    bare = MKTEMP.sub(lambda m: FRESH if re.search(r"\s-\w*d|--directory", m.group(0)) else FRESH + "-file", bare)
    bare = PWD.sub("$PWD", bare)
    # A `$` in single quotes or escaped names no variable: hide it from bash_writes_outside_temp's expansion.
    bare = literal_dollars(bare)
    lex = shlex.shlex(bare, posix=True, punctuation_chars="();<>|&\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    seg, before, depth = [], None, 0
    for tok in lex:
        if tok in SEPARATORS:
            if seg:
                yield seg, depth == 0 and before not in SUBSHELL and tok not in SUBSHELL, before
            seg, before = [], tok
            depth += {"(": 1, ")": -1}.get(tok, 0)
        else:
            seg.append(tok)
    if seg:
        yield seg, depth == 0 and before not in SUBSHELL, before


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


class Shell:
    """What a command line has set so far, read in order: the folder it runs in when that is a temporary one, the
    variables that hold a temporary path, and the remotes (repo folder, name) that point into a temporary folder.
    A push passes only from a repo the line made itself (git init or a clone of a temporary path, into a folder
    that was not there), and a remote added with a real URL taints the line. Anything that can send a push elsewhere (git config, a remote renamed or removed, a GIT_ variable, a link, a
    write into a .git folder or a hook) taints the line: no push in it is a temporary write after that."""

    def __init__(self, cwd, session):
        self.session = session
        self.here = os.path.normpath(cwd) if cwd and self.temp(cwd) else None
        # The other folders the line may run in by now, a cd having failed or run in a subshell; None: a real one.
        self.alts = set()
        tmpdir = os.environ.get("TMPDIR", "").rstrip("/")
        self.vars = {"TMPDIR": tmpdir} if tmpdir and self.temp(tmpdir) else {}
        self.chain = set()  # the repos made since the last separator other than &&: a cd into one surely succeeds
        self.remotes = {}  # repo folder made by this command line: the names of its remotes, all temporary
        self.tainted = False
        self.split = False  # no variable is tracked: something in the line may change one or how it splits

    def temp(self, path):
        return temp_path(path, self.session)

    def expand(self, tok):
        """The word with the variables known to hold a temporary path (and $PWD in one) replaced; others stay."""
        known = dict(self.vars, **({"PWD": self.here} if self.here and not self.split else {}))
        return VAR.sub(lambda m: known.get(m.group(1) or m.group(2), m.group(0)), tok)

    def resolve(self, path):
        """The temporary folder a path names, from the one the command runs in when it is relative, else None."""
        if not path or "$" in path:  # a variable not known to hold a temporary path
            return None
        if not path.startswith(("/", "~", "$")):
            if not self.here or ".." in path.split("/"):
                return None
            path = self.here + "/" + path
        return os.path.normpath(path) if self.temp(path) else None

    def assign(self, words, lasting):
        """A segment of assignments only: each name now holds its temporary path, or no longer holds one. One that
        does not last (a pipeline, a subshell) marks nothing."""
        for w in words:
            m = ASSIGN.match(w)
            if m:
                self.tainted |= m.group(1).startswith("GIT_")
                value = self.resolve(self.expand(m.group(2))) if m.group(2).startswith(("/", "$", "~")) else None
                # An unquoted use splits a value with a blank into several paths.
                if value and lasting and not self.split and not re.search(r"\s", value):
                    self.vars[m.group(1)] = value
                else:
                    self.vars.pop(m.group(1), None)

    def forget(self, seg):
        """Any other segment that names a variable (for, read, printf -v, unset, local -x, …) may set it: it no
        longer holds a temporary path. A GIT_ variable or a link taints the line."""
        for t in seg:
            m = ASSIGN.match(t) or APPEND.match(t)
            name = m.group(1) if m else t
            self.vars.pop(name, None)
            self.tainted |= name.startswith("GIT_")
        words = [t for t in seg if t not in PREFIXES and not ASSIGN.match(t)]
        self.tainted |= bool(words) and os.path.basename(words[0]) == "ln"
        # A command off this list may rewrite a repo's remotes out of sight (cp -R, tar, a script): no temporary push.
        self.tainted |= bool(words) and os.path.basename(words[0]) not in PUSH_SAFE_COMMANDS
        # A git run by another command (nice, timeout, sh -c '…') is out of sight: it may redirect a remote.
        self.tainted |= any(re.search(r"(?:^|[\s/])git\b", t) for t in words[1:])
        if words[:1] in (["source"], ["."], ["eval"]):  # sets what it likes
            self.vars = {}
            self.split = self.tainted = True

    def wrote(self, path):
        """A write into a .git folder, a bare repo's config or a hook can send a push elsewhere: it taints the line."""
        parts = path.split("/")
        self.tainted |= ".git" in parts or "hooks" in parts or parts[-1] in ("config", ".gitconfig")

    def cd(self, words, lasting):
        dest = next((a for a in words[1:] if not a.startswith("-")), "")
        cdpath = "CDPATH" in os.environ or any("CDPATH" in w for w in words)
        to = None if cdpath and not dest.startswith("/") else self.resolve(dest)
        if not lasting:  # a subshell's cd: what follows in it runs there
            self.alts.add(to)
            return
        # Only a cd into a fresh mktemp folder, the scratchpad, a folder on disk or one made in an unbroken && chain
        # surely succeeds. Any other may fail and leave the line anywhere: where it was, or where a cd function
        # (zoxide) jumps for a name it does not find.
        scratch = to and self.temp(to) and to.endswith("/scratchpad")
        sure = to and (to == FRESH or os.path.isdir(to) or scratch or to in self.chain)
        if not sure:
            self.alts.add(None)
        self.here = to

    def git_push_is_temp(self, words, seg):
        """A git clone, remote add or set-url is recorded; a git push is a temporary write when its remote is a
        temporary path, or a name a clone or a remote add set to one in this command line, and nothing in the line
        can send it elsewhere. None: not one of those."""
        repo, i, plain = self.here, 1, True
        while i < len(words) and words[i].startswith("-"):
            if words[i] == "-C" and i + 1 < len(words):
                repo, i = self.within(repo, words[i + 1]), i + 2
            else:
                plain &= words[i] in GIT_PLAIN_OPTIONS  # -c, --git-dir, --work-tree, --exec-path, …
                i += 2 if words[i] == "-c" else 1
        plain &= not any(ASSIGN.match(t) for t in seg)  # GIT_DIR=… git push
        verb = words[i] if i < len(words) else ""
        if verb == "config":
            # Only an identity or a display setting leaves the remotes alone.
            rest = words[i + 1 :]
            self.tainted |= not rest or rest[0].startswith("-") or not SAFE_CONFIG.match(rest[0])
            return None
        if verb == "remote" and not (len(words) > i + 1 and words[i + 1] in ("add", "set-url")):
            self.tainted |= len(words) > i + 1 and words[i + 1] not in ("-v", "show", "get-url")
            return None
        if verb not in GIT_VALUE_OPTIONS:
            self.tainted |= verb not in PUSH_SAFE_GIT_VERBS
            if verb == "init":
                rest = words[i + 1 :]
                args = positional(rest, set())
                folder = self.within(repo, args[0]) if args else repo
                self.tainted |= any("template" in o or "separate" in o for o in rest)
                self.made(folder, set())
            return None
        rest = words[i + 1 :]
        args = positional(rest, GIT_VALUE_OPTIONS[verb])
        if verb == "clone" and args:
            name = option(rest, ("-o", "--origin")) or "origin"
            dest = args[1] if len(args) > 1 else os.path.basename(args[0].rstrip("/")).removesuffix(".git")
            odd = ("-c", "--config", "--template", "--bare", "--mirror", "--separate-git-dir", "--reference")
            # A clone of a real URL, or an odd one, may carry a real remote anywhere.
            self.tainted |= not plain or any(o.startswith(odd) for o in rest) or not self.local(repo, args[0])
            self.made(self.within(repo, dest), {name})
            return None
        if verb == "remote":
            options = [o for o in rest[1:] if o.startswith("-")]
            names = self.remotes.get(repo)
            fails = names is None or (args[1] in names) == (args[0] == "add") if len(args) >= 3 else True
            # Out of a repo the line made, with a real URL, an option, or a name that fails (add: taken; set-url: none).
            if not plain or options or fails or not self.local(repo, args[2]):
                self.tainted = True
            else:
                names.add(args[1])
            return None
        if self.tainted or not plain or any(o.startswith("-") and not PLAIN_PUSH_OPTIONS.match(o) for o in rest):
            return False
        # Each folder the push may run in must be a repo the line made, or a fresh mktemp one (no repo: it fails).
        main = self.pushes_to_temp(self.repo_of(words, self.here), args, fresh=False)
        return main and all(self.pushes_to_temp(self.repo_of(words, here), args) for here in self.alts)

    def repo_of(self, words, here):
        """The repo folder a git command acts on, run from here (None: a real one)."""
        repo, i = here, 1
        while i < len(words) and words[i].startswith("-"):
            if words[i] == "-C" and i + 1 < len(words):
                repo, i = self.within(repo, words[i + 1]), i + 2
            else:
                i += 2 if words[i] == "-c" else 1
        return repo

    def pushes_to_temp(self, repo, args, fresh=True):
        """Whether a push from repo stays temporary; fresh: a fresh mktemp folder, in no repo, makes it fail."""
        if fresh and repo == FRESH and FRESH not in self.remotes:
            return True
        names = self.remotes.get(repo)
        if names is None:  # a repo made before this line: its remotes and upstreams are out of sight
            return False
        if not args or args[0] in names:  # with no remote, the upstream: one of its remotes, all temporary
            return True
        return args[0].startswith(("/", "./", "file://")) and bool(self.local(repo, args[0]))

    def made(self, folder, names):
        """A repo this line makes: a folder out of sight, in a .git, already made or already on disk taints it."""
        if not folder or ".git" in folder.split("/") or folder in self.remotes or os.path.lexists(folder):
            self.tainted = True
        if folder:
            self.remotes[folder] = names
            self.chain.add(folder)

    def local(self, repo, url):
        """The temporary folder a remote's URL names, from the repo folder, else None (a URL, a path elsewhere)."""
        return None if URL.match(url) else self.within(repo, url.removeprefix("file://"))

    def within(self, repo, path):
        """resolve, from the repo folder rather than the one the command runs in."""
        here, self.here = self.here, repo
        try:
            return self.resolve(path)
        finally:
            self.here = here


def positional(args, value_options):
    """The arguments of a git verb that are not options or their values."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in value_options:
            skip = True
        elif not a.startswith("-"):
            out.append(a)
    return out


def option(args, names):
    for i, a in enumerate(args[:-1]):
        if a in names:
            return args[i + 1]
    return None


def bash_writes_outside_temp(command, cwd, session=None):
    """Whether a command writes, per measure's bash_writes, somewhere other than a temporary folder."""
    if not measure.bash_writes(command):
        return False
    sh = Shell(cwd, session)
    first = [
        next((t for t in seg if t not in PREFIXES and not ASSIGN.match(t) and not t.startswith("-")), "")
        for seg, _, _ in segments(command)
    ]
    sh.split = bool(OPAQUE.search(command)) or any(w in OPAQUE_WORDS for w in first)
    # A command substitution (beyond mktemp and pwd) runs out of sight: it may rewrite a remote.
    sh.tainted = bool(
        REDIRECTS_PUSH.search(command) or re.search(r"\$\(|`|[<>]\(", PWD.sub("", MKTEMP.sub("", command)))
    )
    for seg, lasting, before in segments(command):
        if before not in (None, "&&"):  # a step after it runs even when one before failed
            sh.chain.clear()
        seg = [sh.expand(t) for t in seg]
        words = [t for t in seg if not ASSIGN.match(t) and t not in PREFIXES]
        if not words or (len(words) == 1 and words[0] in DECLARE):
            sh.assign(seg, lasting)
        else:
            sh.forget(seg)
        if words[:1] == ["cd"]:
            sh.cd(words, lasting)
            continue
        if words[:1] == ["git"]:
            pushed = sh.git_push_is_temp(words, seg)
            if pushed is False:
                return True
            if pushed:
                continue
        out = targets(seg, measure.bash_writes)
        if out is None:
            return True
        for t in out:
            where = sh.resolve(t)
            if not where:
                return True
            sh.wrote(where)
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
                str((payload.get("tool_input") or {}).get("command") or ""),
                payload.get("cwd"),
                str(payload.get("session_id") or "") or None,
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
