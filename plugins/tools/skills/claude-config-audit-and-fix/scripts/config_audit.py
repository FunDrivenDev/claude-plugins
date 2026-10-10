#!/usr/bin/env python3
"""Inventory the always-loaded Claude Code context and apply config fixes.

Subcommands:
  inventory [--project P] [--days N]  JSON report on stdout
  probe [<dir>]                       what a new headless session in <dir> loads (default: empty dir)
  backup FILE [FILE ...]              copy each FILE to FILE.bak-YYMMDD, never overwriting
  override NAME on|name-only|user-invocable-only|off
                                      set skillOverrides[NAME] in the user settings ("on" removes it)

Ground truth for "what loads" is the attachment records of a session transcript:
`instructions` (CLAUDE.md and memory files), `skill_listing`, `hook_additional_context`.
Inventory reads the newest interactive transcript of the project, because a headless
session condenses the skill listing (verified 2026-09-26: 17k chars interactive vs
8k headless for the same config). Paths follow CLAUDE_CONFIG_DIR.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude").expanduser()
CLAUDE_JSON = CONFIG_DIR / ".claude.json" if (CONFIG_DIR / ".claude.json").exists() else HOME / ".claude.json"
USER_SETTINGS = CONFIG_DIR / "settings.json"
TRANSCRIPTS = CONFIG_DIR / "projects"
PLUGINS = CONFIG_DIR / "plugins"
INTERACTIVE = {"cli", "claude-desktop"}
EPHEMERAL_PREFIXES = (
    "/tmp",
    "/private/tmp",
    "/var/folders",
    "/private/var/folders",
    str(HOME / "Library" / "Application Support" / "Claude" / "scratch-workspaces"),
)
OVERRIDE_STATES = ("on", "name-only", "user-invocable-only", "off")


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def tilde(path):
    s = str(path)
    return "~" + s[len(str(HOME)) :] if s.startswith(str(HOME)) else s


def size(text):
    return {"chars": len(text), "words": len(text.split())}


def transcript_dir(project):
    return TRANSCRIPTS / re.sub(r"[^A-Za-z0-9]", "-", str(project))


def is_ephemeral(path):
    return path.startswith(EPHEMERAL_PREFIXES) or "/.claude/worktrees/" in path


def backup(path):
    """Copy path to path.bak-YYMMDD (or -2, -3...) and return the copy."""
    path = Path(path).expanduser()
    stem = f"{path}.bak-{datetime.now():%y%m%d}"
    dest, n = Path(stem), 2
    while dest.exists():
        dest, n = Path(f"{stem}-{n}"), n + 1
    shutil.copy2(path, dest)
    return dest


# --- session context -------------------------------------------------------


def attachments(transcript):
    """{type: [attachment, ...]} for the records a session loaded at start."""
    found = defaultdict(list)
    with open(transcript, errors="replace") as fh:
        for line in fh:
            if '"attachment"' not in line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            a = r.get("attachment") or {}
            if r.get("type") == "attachment" and a.get("type"):
                found[a["type"]].append(a)
    return found


def entrypoint(transcript):
    with open(transcript, errors="replace") as fh:
        for i, line in enumerate(fh):
            if i > 20:
                break
            try:
                ep = json.loads(line).get("entrypoint")
            except ValueError:
                continue
            if ep:
                return ep
    return None


def newest_interactive(project):
    """Newest interactive transcript for project, else the newest anywhere."""
    for pool in (transcript_dir(project).glob("*.jsonl"), TRANSCRIPTS.glob("*/*.jsonl")):
        for f in sorted(pool, key=lambda p: p.stat().st_mtime, reverse=True):
            if entrypoint(f) in INTERACTIVE and attachments(f).get("skill_listing"):
                return f
    return None


def split_listing(listing):
    """{skill name: its listing entry text} from a skill_listing attachment."""
    content, names = listing.get("content", ""), listing.get("names") or []
    starts = []
    for name in names:
        m = re.search(rf"(?m)^- {re.escape(name)}(?=:|$)", content)
        if m:
            starts.append((m.start(), name))
    starts.sort()
    entries = {}
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(content)
        entries[name] = content[pos:end].rstrip("\n")
    return entries


def session_context(transcript):
    att = attachments(transcript)
    files = [f for a in att.get("instructions", []) for f in a.get("files", [])]
    listing = (att.get("skill_listing") or [{}])[0]
    hooks = [
        {
            "hook": a.get("hookName"),
            **size("\n".join(a.get("content") or [])),
            "text": "\n".join(a.get("content") or []),
        }
        for a in att.get("hook_additional_context", [])
    ]
    return {
        "transcript": tilde(transcript),
        "instructions": [
            {
                "path": tilde(f["path"]),
                "type": f.get("type"),
                **size(f.get("content", "")),
                "chars_on_disk_now": len(Path(f["path"]).read_text(errors="replace"))
                if Path(f["path"]).is_file()
                else None,
            }
            for f in files
        ],
        "skill_listing": {"skills": len(listing.get("names") or []), **size(listing.get("content", ""))},
        "hook_context": hooks,
    }, split_listing(listing)


# --- skills ----------------------------------------------------------------


def frontmatter(skill_md):
    try:
        text = Path(skill_md).read_text(errors="replace")
    except OSError:
        return {}
    m = re.match(r"---\n(.*?)\n---", text, re.DOTALL)
    fm = {}
    for line in m.group(1).splitlines() if m else []:
        k, _, v = line.partition(":")
        if v and not k.startswith((" ", "\t")):
            fm[k.strip()] = v.strip().strip("'\"")
    return fm


def plugin_dirs():
    """[(plugin name, plugin id, install dir)] for installed and synced plugins."""
    dirs = []
    installed = load_json(PLUGINS / "installed_plugins.json", {}).get("plugins", {})
    for pid, installs in installed.items():
        if installs:
            dirs.append((pid.split("@")[0], pid, Path(installs[0]["installPath"])))
    for d in (PLUGINS / "synced").glob("*/*/"):
        name = d.name.split("~")[0]
        dirs.append((name, f"{name}@synced", d))
    return dirs


def skill_files(project):
    """{skill name: {source, path, owned, plugin}} for every skill with a SKILL.md."""
    found = {}

    def add(name, source, path, owned, plugin=None):
        found.setdefault(name, {"source": source, "path": tilde(path), "owned": owned, "plugin": plugin})

    for base, source in ((Path(project) / ".claude" / "skills", "project"), (CONFIG_DIR / "skills", "user")):
        for md in base.glob("*/SKILL.md"):
            add(frontmatter(md).get("name") or md.parent.name, source, md, True)
    for md in (CONFIG_DIR / "skills" / "synced").glob("*/*/SKILL.md"):
        add(f"anthropic-skills:{frontmatter(md).get('name') or md.parent.name}", "synced", md, False)
    for pname, pid, d in plugin_dirs():
        for md in (d / "skills").rglob("SKILL.md"):
            add(f"{pname}:{frontmatter(md).get('name') or md.parent.name}", "plugin", md, False, pid)
    return found


def skill_usage(days):
    """{skill: {model_calls, typed, last_used}} from Skill tool calls and typed slash commands."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    use = defaultdict(lambda: {"model_calls": 0, "typed": 0, "last_used": ""})
    first = ""
    for f in TRANSCRIPTS.rglob("*.jsonl"):
        with open(f, errors="replace") as fh:
            for line in fh:
                has_skill = '"Skill"' in line and '"tool_use"' in line
                has_cmd = "<command-name>" in line
                if not (has_skill or has_cmd):
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                ts = r.get("timestamp", "")
                if ts < cutoff:
                    continue
                first = min(first or ts, ts)
                if has_skill and r.get("type") == "assistant":
                    for c in (r.get("message") or {}).get("content") or []:
                        if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                            u = use[(c.get("input") or {}).get("skill", "")]
                            u["model_calls"] += 1
                            u["last_used"] = max(u["last_used"], ts)
                if has_cmd and r.get("type") == "user":
                    for name in re.findall(r"<command-name>/?([^<\s]+)</command-name>", line):
                        use[name]["typed"] += 1
                        use[name]["last_used"] = max(use[name]["last_used"], ts[:10])
    return use, first[:10]


def skills_report(project, entries, days, init_skills):
    files = skill_files(project)
    overrides = load_json(USER_SETTINGS, {}).get("skillOverrides", {})
    use, since = skill_usage(days)
    report = []
    for name in sorted(set(entries) | set(init_skills) | set(files)):
        info = files.get(name, {"source": "bundled", "path": None, "owned": False, "plugin": None})
        fm = frontmatter(Path(info["path"]).expanduser()) if info["path"] else {}
        entry = entries.get(name)
        report.append(
            {
                "name": name,
                **info,
                "in_listing": entry is not None,
                "listing_chars": len(entry or ""),
                "disable_model_invocation": fm.get("disable-model-invocation") == "true",
                "override": overrides.get(name),
                **use.get(name, {"model_calls": 0, "typed": 0, "last_used": ""}),
            }
        )
    return report, since


# --- projects and settings -------------------------------------------------


def known_projects():
    projects = load_json(CLAUDE_JSON, {}).get("projects", {})
    return sorted(p for p in projects if not is_ephemeral(p) and Path(p).is_dir())


def project_files(project):
    """Rule-bearing files a session in project loads, beyond the global CLAUDE.md."""
    root = Path(project)
    paths = [
        root / "CLAUDE.md",
        root / ".claude" / "CLAUDE.md",
        root / "CLAUDE.local.md",
        transcript_dir(project) / "memory" / "MEMORY.md",
    ]
    out = []
    for p in paths:
        if p.is_file():
            out.append({"path": tilde(p), **size(p.read_text(errors="replace"))})
    return out


def command_path(command):
    """The script a hook or statusLine command runs, when it names one."""
    first = os.path.expandvars(command.strip().split()[0]) if command.strip() else ""
    first = os.path.expanduser(first)
    return first if "/" in first else None


def settings_scopes():
    """{scope: [settings files]}: "user", then one scope per project."""
    user = [USER_SETTINGS, CONFIG_DIR / "settings.local.json"]
    scopes = {"user": user}
    for p in known_projects():
        # In $HOME, the project's .claude/ is the user config itself.
        scopes[tilde(p)] = [
            f
            for f in (Path(p) / ".claude" / "settings.json", Path(p) / ".claude" / "settings.local.json")
            if f.resolve() not in {u.resolve() for u in user}
        ]
    return {k: [f for f in fs if f.is_file()] for k, fs in scopes.items()}


def permission_rules(files):
    """{rule: {kind: [files]}} for allow/deny/ask rules across files."""
    rules = defaultdict(lambda: defaultdict(list))
    for f in files:
        for kind in ("allow", "deny", "ask"):
            for rule in ((load_json(f, {}) or {}).get("permissions") or {}).get(kind, []):
                rules[rule][kind].append(tilde(f))
    return rules


def settings_checks():
    """Broken hook and statusLine scripts, permission conflicts and duplicates, old backups.

    Permissions are compared within what one session sees: the user scope plus one project.
    """
    findings = []
    scopes = settings_scopes()
    for f in (f for fs in scopes.values() for f in fs):
        s = load_json(f, {}) or {}
        for event, groups in (s.get("hooks") or {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    path = command_path(h.get("command", ""))
                    if path and not Path(path).exists():
                        findings.append(
                            {"kind": "missing-hook-script", "file": tilde(f), "event": event, "command": h["command"]}
                        )
                    elif path and not os.access(path, os.X_OK):
                        findings.append(
                            {"kind": "hook-not-executable", "file": tilde(f), "event": event, "command": h["command"]}
                        )
        status = (s.get("statusLine") or {}).get("command", "")
        path = command_path(status)
        if path and not Path(path).exists():
            findings.append({"kind": "missing-statusline-script", "file": tilde(f), "command": status})
    seen = set()
    for scope, files in scopes.items():
        for rule, kinds in permission_rules(scopes["user"] + (files if scope != "user" else [])).items():
            key = (rule, tuple(sorted((k, tuple(v)) for k, v in kinds.items())))
            if key in seen:
                continue
            seen.add(key)
            if len(kinds) > 1:
                findings.append({"kind": "permission-conflict", "rule": rule, "in": dict(kinds)})
            for kind, fs in kinds.items():
                if len(fs) > 1:
                    findings.append({"kind": "permission-duplicate", "rule": rule, "list": kind, "files": fs})
    now = time.time()
    stale = [p for p in CONFIG_DIR.glob("*.bak*")] + [p for p in CONFIG_DIR.glob("*/*.bak*")]
    stale += list((CONFIG_DIR / "skills" / ".trash").glob("*"))
    for p in sorted(stale):
        if "plugins" not in p.parts:
            findings.append(
                {"kind": "stale-backup", "path": tilde(p), "age_days": int((now - p.stat().st_mtime) // 86400)}
            )
    return findings


# --- subcommands -----------------------------------------------------------


def run_headless(cwd):
    """(init event, transcript path) of a one-turn headless session in cwd."""
    out = subprocess.run(
        ["claude", "-p", "hi", "--max-turns", "1", "--model", "haiku", "--output-format", "stream-json", "--verbose"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=cwd,
        check=False,
    ).stdout
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("subtype") == "init":
            t = transcript_dir(os.path.realpath(cwd)) / f"{d['session_id']}.jsonl"
            return d, t
    sys.exit("probe failed: no init event")


def inventory(args):
    project = os.path.realpath(args.project)
    transcript = newest_interactive(project)
    if not transcript:
        sys.exit("no interactive transcript with a skill listing found")
    session, entries = session_context(transcript)
    loaded = {Path(i["path"].replace("~", str(HOME), 1)) for i in session["instructions"]}
    skills, since = skills_report(project, entries, args.days, [])
    projects = {}
    for p in known_projects():
        files = [f for f in project_files(p) if Path(f["path"].replace("~", str(HOME), 1)) not in loaded]
        if files:
            projects[tilde(p)] = files
    json.dump(
        {
            "session": session,
            "usage_window": {"days": args.days, "first_record": since},
            "skills": skills,
            "other_projects": projects,
            "settings": settings_checks(),
        },
        sys.stdout,
        indent=2,
        ensure_ascii=False,
    )
    print()


def probe(args):
    with tempfile.TemporaryDirectory() as empty:
        cwd = args.dir or empty
        init, transcript = run_headless(cwd)
        for _ in range(20):
            if transcript.exists():
                break
            time.sleep(0.5)
        session, entries = session_context(transcript) if transcript.exists() else ({}, {})
    session.pop("transcript", None)
    json.dump(
        {"init_skills": init.get("skills", []), "listed_skills": sorted(entries), **session},
        sys.stdout,
        indent=2,
        ensure_ascii=False,
    )
    print()


def backup_cmd(args):
    for f in args.files:
        print(f"{f} -> {tilde(backup(f))}")


def override(args):
    settings = load_json(USER_SETTINGS)
    if settings is None:
        sys.exit(f"cannot read {USER_SETTINGS}")
    backup(USER_SETTINGS)
    ov = settings.setdefault("skillOverrides", {})
    if args.state == "on":
        ov.pop(args.name, None)
    else:
        ov[args.name] = args.state
    if not ov:
        settings.pop("skillOverrides")
    write_json(USER_SETTINGS, settings)
    print(json.dumps({"skillOverrides": settings.get("skillOverrides", {})}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("inventory")
    p.add_argument("--project", default=os.getcwd())
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(fn=inventory)
    p = sub.add_parser("probe")
    p.add_argument("dir", nargs="?")
    p.set_defaults(fn=probe)
    p = sub.add_parser("backup")
    p.add_argument("files", nargs="+")
    p.set_defaults(fn=backup_cmd)
    p = sub.add_parser("override")
    p.add_argument("name")
    p.add_argument("state", choices=OVERRIDE_STATES)
    p.set_defaults(fn=override)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
