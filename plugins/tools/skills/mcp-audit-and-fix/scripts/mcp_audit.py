#!/usr/bin/env python3
"""Inventory MCP servers and their real usage, and apply scope changes.

Subcommands:
  inventory [--days N]        JSON report on stdout
  probe [<project>]           servers a session started in <project> loads (default: empty dir)
  copy NAME --from user|<project> --to user|<project> [<project> ...]
  deny NAME --where global|<project> [<project> ...]
  report-dir [--project P]    where the report goes: JSON {choice, path, default}
  set-report default|none|<path>

Paths follow CLAUDE_CONFIG_DIR, so a second account (e.g. work) audits its own config.
The report choice is saved in CLAUDE_PLUGIN_DATA when set, so it survives plugin updates.
Secrets in server configs (headers, env) never reach stdout.

Ground truth for "what loads" is the init event of a real headless session:
`claude mcp list` ignores settings-file deny lists, and `disabledMcpServers` in a
settings file has no effect (verified 2026-09-26). Only `deniedMcpServers` works
from settings files; `/mcp` toggles live in ~/.claude.json per project.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or HOME / ".claude").expanduser()
CLAUDE_JSON = CONFIG_DIR / ".claude.json" if (CONFIG_DIR / ".claude.json").exists() else HOME / ".claude.json"
USER_SETTINGS = CONFIG_DIR / "settings.json"
TRANSCRIPTS = CONFIG_DIR / "projects"
PLUGINS = CONFIG_DIR / "plugins"
# Installed as a plugin, the skill directory is replaced on every update: keep the saved
# choice in the plugin's persistent data dir. As a personal skill, keep it beside SKILL.md.
SKILL_CONFIG = (
    Path(os.environ["CLAUDE_PLUGIN_DATA"]) / "mcp-audit-and-fix.json"
    if os.environ.get("CLAUDE_PLUGIN_DATA")
    else Path(__file__).resolve().parent.parent / "config.json"
)
EPHEMERAL_PREFIXES = (
    "/tmp",
    "/private/tmp",
    "/var/folders",
    "/private/var/folders",
    str(HOME / "Library" / "Application Support" / "Claude" / "scratch-workspaces"),
)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def tool_prefix(server_name):
    """Server name as it appears in tool names: mcp__<prefix>__<tool>."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", server_name)


def project_root(cwd):
    """Fold worktrees back into the repo they belong to."""
    if not cwd:
        return None
    return cwd.split("/.claude/worktrees/")[0]


def is_ephemeral(path):
    return path.startswith(EPHEMERAL_PREFIXES)


def redact(config):
    if not isinstance(config, dict):
        return config
    out = dict(config)
    for key in ("headers", "env"):
        if isinstance(out.get(key), dict):
            out[key] = {k: "<redacted>" for k in out[key]}
    return out


def probe_servers(cwd=None):
    """[{name, status, source}] from the init event of a one-turn headless session."""
    with tempfile.TemporaryDirectory() as empty:
        try:
            out = subprocess.run(
                [
                    "claude",
                    "-p",
                    "hi",
                    "--max-turns",
                    "1",
                    "--model",
                    "haiku",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=cwd or empty,
                check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            sys.exit(f"probe failed: {e}")
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("subtype") == "init":
            return d.get("mcp_servers") or []
    sys.exit("probe failed: no init event")


def plugin_server_names():
    """{'plugin:<plugin>:<server>': plugin id} for installed and synced plugins."""
    dirs = []
    installed = load_json(PLUGINS / "installed_plugins.json", {}).get("plugins", {})
    for plugin_id, installs in installed.items():
        if installs:
            dirs.append((plugin_id.split("@")[0], plugin_id, Path(installs[0]["installPath"])))
    for d in (PLUGINS / "synced").glob("*/*/"):
        name = d.name.split("~")[0]
        dirs.append((name, f"{name}@synced", d))
    result = {}
    for pname, pid, path in dirs:
        servers = {}
        mcp_file = load_json(path / ".mcp.json", {})
        if isinstance(mcp_file, dict):
            servers.update(mcp_file.get("mcpServers", mcp_file))
        declared = load_json(path / ".claude-plugin" / "plugin.json", {}).get("mcpServers")
        if isinstance(declared, str):
            declared = load_json(path / declared, {})
            declared = declared.get("mcpServers", declared)
        if isinstance(declared, dict):
            servers.update(declared)
        for sname in servers:
            result[f"plugin:{pname}:{sname}"] = pid
    return result


def usage(days):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    calls = defaultdict(lambda: defaultdict(lambda: {"calls": 0, "recent_calls": 0, "last_used": ""}))
    for f in TRANSCRIPTS.rglob("*.jsonl"):
        try:
            lines = f.open(errors="replace")
        except OSError:
            continue
        with lines:
            for line in lines:
                if '"tool_use"' not in line or "mcp__" not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "assistant":
                    continue
                root = project_root(d.get("cwd"))
                ts = d.get("timestamp", "")
                for c in d.get("message", {}).get("content", []) or []:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    name = c.get("name", "")
                    if not name.startswith("mcp__"):
                        continue
                    entry = calls[name[5:].split("__")[0]][root]
                    entry["calls"] += 1
                    if ts and datetime.fromisoformat(ts.replace("Z", "+00:00")) >= cutoff:
                        entry["recent_calls"] += 1
                    entry["last_used"] = max(entry["last_used"], ts)
    return calls


def inventory(args):
    cj = load_json(CLAUDE_JSON, {})
    settings = load_json(USER_SETTINGS, {})
    projects = cj.get("projects", {})
    plugins = plugin_server_names()
    calls = usage(args.days)

    # claude.ai connectors occasionally miss the init event; union two probes.
    probed = {}
    for _ in range(2):
        for s in probe_servers():
            probed.setdefault(s["name"], s)
    servers = []
    for s in probed.values():
        name = s["name"]
        entry = {"name": name, "source": s.get("source"), "status": s.get("status"), "tool_prefix": tool_prefix(name)}
        if name in cj.get("mcpServers", {}):
            entry["config"] = redact(cj["mcpServers"][name])
        if name in plugins:
            entry["plugin"] = plugins[name]
        servers.append(entry)
    # Servers that exist only in some projects: local scope and .mcp.json.
    for path, p in projects.items():
        for name, cfg in (p.get("mcpServers") or {}).items():
            servers.append(
                {
                    "name": name,
                    "source": "local",
                    "project": path,
                    "config": redact(cfg),
                    "tool_prefix": tool_prefix(name),
                }
            )
        for name, cfg in (load_json(Path(path) / ".mcp.json", {}).get("mcpServers") or {}).items():
            servers.append(
                {
                    "name": name,
                    "source": "project",
                    "project": path,
                    "file": str(Path(path) / ".mcp.json"),
                    "config": redact(cfg),
                    "tool_prefix": tool_prefix(name),
                }
            )

    for s in servers:
        per_project = calls.get(s["tool_prefix"], {})
        s["usage"] = {
            "real_projects": {p: u for p, u in per_project.items() if p and not is_ephemeral(p) and Path(p).exists()},
            "ephemeral_or_gone": {
                p or "?": u for p, u in per_project.items() if not p or is_ephemeral(p) or not Path(p).exists()
            },
        }

    blocked = {
        "global_denied": settings.get("deniedMcpServers", []),
        "disable_claude_ai_connectors": settings.get("disableClaudeAiConnectors", False),
        "per_project": {},
    }
    for path in set(projects) | {p for u in calls.values() for p in u if p}:
        entry = {}
        toggled = projects.get(path, {}).get("disabledMcpServers")
        if toggled:
            entry["mcp_toggled_off"] = toggled
        for fname in ("settings.local.json", "settings.json"):
            denied = load_json(Path(path) / ".claude" / fname, {}).get("deniedMcpServers")
            if denied:
                entry[f"denied_in_{fname}"] = denied
        if entry:
            blocked["per_project"][path] = entry

    loaded_prefixes = {s["tool_prefix"] for s in servers}
    report = {
        "window_days": args.days,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "servers": servers,
        "blocked": blocked,
        "known_projects": sorted(p for p in projects if Path(p).exists() and not is_ephemeral(p)),
        "plugin_servers_not_loaded": sorted(n for n in plugins if tool_prefix(n) not in loaded_prefixes),
        "usage_of_unlisted_servers": sorted(set(calls) - loaded_prefixes),
    }
    json.dump(report, sys.stdout, indent=2)
    print()


def probe(args):
    for s in probe_servers(args.project):
        print(f"{s['name']}\t{s.get('status')}\t{s.get('source')}")


def copy(args):
    cj = load_json(CLAUDE_JSON, {})
    if args.source == "user":
        cfg = cj.get("mcpServers", {}).get(args.name)
    else:
        cfg = (cj.get("projects", {}).get(args.source, {}).get("mcpServers") or {}).get(args.name)
    if cfg is None:
        sys.exit(f"{args.name} not found in {args.source}")
    for target in args.to:
        scope, cwd = ("user", HOME) if target == "user" else ("local", target)
        r = subprocess.run(
            ["claude", "mcp", "add-json", args.name, json.dumps(cfg), "-s", scope],
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
        )
        print(f"{target}: {'ok' if r.returncode == 0 else 'FAILED'} {(r.stdout + r.stderr).strip()}")


def deny(args):
    for where in args.where:
        path = USER_SETTINGS if where == "global" else Path(where) / ".claude" / "settings.local.json"
        data = load_json(path, {})
        denied = data.setdefault("deniedMcpServers", [])
        if any(d.get("serverName") == args.name for d in denied if isinstance(d, dict)):
            print(f"{where}: already denied")
            continue
        denied.append({"serverName": args.name})
        write_json(path, data)
        note = ""
        if where != "global":
            r = subprocess.run(
                ["git", "check-ignore", "-q", ".claude/settings.local.json"],
                cwd=where,
                capture_output=True,
                check=False,
            )
            if r.returncode == 1:
                note = " (WARNING: .claude/settings.local.json is not gitignored)"
        print(f"{where}: denied{note}")


def claude_plans_dir(project):
    """Where Claude Code writes plans: `plansDirectory` by settings precedence, else <config>/plans."""
    project = Path(project).resolve()
    for path in (project / ".claude" / "settings.local.json", project / ".claude" / "settings.json", USER_SETTINGS):
        value = load_json(path, {}).get("plansDirectory")
        if value:
            value = Path(value).expanduser()
            return value if value.is_absolute() else project / value
    return CONFIG_DIR / "plans"


def report_dir(args):
    # Claude Code has no reports setting: default to a `reports` folder beside its plans folder.
    default = claude_plans_dir(args.project).parent / "reports"
    choice = load_json(SKILL_CONFIG, {}).get("report")
    if choice is None:
        path = None
    elif choice == "default":
        path = default
    elif choice == "none":
        path = None
    else:
        path = Path(choice)
    kind = choice if choice in (None, "default", "none") else "custom"
    json.dump({"choice": kind, "path": str(path) if path else None, "default": str(default)}, sys.stdout, indent=2)
    print()


def set_report(args):
    choice = args.choice
    if choice not in ("default", "none"):
        path = Path(choice).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        choice = str(path)
    write_json(SKILL_CONFIG, {"report": choice})
    print(f"report: {choice} (saved in {SKILL_CONFIG})")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--days", type=int, default=60)
    inv.set_defaults(func=inventory)
    pr = sub.add_parser("probe")
    pr.add_argument("project", nargs="?")
    pr.set_defaults(func=probe)
    cp = sub.add_parser("copy")
    cp.add_argument("name")
    cp.add_argument("--from", dest="source", required=True)
    cp.add_argument("--to", nargs="+", required=True)
    cp.set_defaults(func=copy)
    dn = sub.add_parser("deny")
    dn.add_argument("name")
    dn.add_argument("--where", nargs="+", required=True)
    dn.set_defaults(func=deny)
    rd = sub.add_parser("report-dir")
    rd.add_argument("--project", default=".")
    rd.set_defaults(func=report_dir)
    sr = sub.add_parser("set-report")
    sr.add_argument("choice", help="default | none | <path>")
    sr.set_defaults(func=set_report)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
