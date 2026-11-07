"""The plugin's data folder and the JSON files in it, shared by handover.py and session.py."""

import contextlib
import fcntl
import json
import os


def data_dir():
    """The plugin's data folder; outside a hook, derived from where the plugin is installed."""
    d = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    if d and not d.startswith("${"):
        return d
    # <plugins>/cache/<marketplace>/<plugin>/<version>/scripts -> <plugins>/data/<plugin>-<marketplace>
    parts = os.path.dirname(os.path.abspath(__file__)).split(os.sep)
    if len(parts) >= 6 and parts[-5] == "cache":
        return os.sep.join(parts[:-5] + ["data", f"{parts[-3]}-{parts[-4]}"])
    return os.path.expanduser("~/.claude/plugins/data/handover-inline")


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, path)


@contextlib.contextmanager
def locked_json(path):
    """A JSON file, saved on exit; the processes that share it never interleave."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        obj = read_json(path, {})
        yield obj
        write_json(path, obj)
