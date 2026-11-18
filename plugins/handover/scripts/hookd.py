"""The hook daemon: handover.py imported once, a fork per hot hook event (docs/how-it-works.md, The hook daemon).

`hookd-client` posts each PreToolUse, PostToolUse, SubagentStart and SubagentStop event to the daemon's Unix
socket: the session's environment (`env -0`, with the client's parent pid and cwd), a NUL, then the hook's
input. A forked child takes that environment, cwd and input, runs `cmd_hook` and answers with its stdout.
The other events stay a cold `handover.py hook`, which starts the daemon when it does not answer.
"""

import contextlib
import fcntl
import glob
import io
import os
import socket
import socketserver
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler

from store import data_dir

# A daemon with no event for this long exits; the next cold hook starts another one.
IDLE_SECONDS = 3600
# The longest Unix socket path every system binds (sun_path is 104 bytes on macOS, with its NUL).
SOCKET_PATH_MAX = 103
# How often an idle daemon checks that its socket and its scripts are still the ones it serves.
POLL_SECONDS = 30


def paths(root):
    """The socket and lock of the daemon of the plugin at `root`, one per version: the name of the plugin's
    folder is its version in the plugin cache."""
    base = os.path.join(data_dir(), f"hookd-{os.path.basename(root)}")
    return f"{base}.sock", f"{base}.lock"


def answers(sock):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(sock)
        return True
    except OSError:
        return False
    finally:
        s.close()


def ensure(H):
    """Start the daemon, detached, unless it answers, HANDOVER_HOOKD=off, or its socket path is past the
    system's limit: a daemon that cannot bind would be started again on every hot event."""
    sock = paths(H.plugin_root())[0]
    if os.environ.get("HANDOVER_HOOKD") == "off" or len(os.fsencode(sock)) > SOCKET_PATH_MAX or answers(sock):
        return None
    return H.detach(["hookd"])


def scripts_stamp(root):
    # Regular files only: another python3 writing its bytecode to __pycache__ changes no code.
    files = [p for p in glob.glob(os.path.join(root, "scripts", "*")) if os.path.isfile(p)]
    return max((os.stat(p).st_mtime_ns for p in files), default=0)


def run_hook(H, body):
    """In the forked child: run `cmd_hook` as the cold hook would; (HTTP status, stdout)."""
    head, _, stdin = body.partition(b"\0\0")
    env = dict(kv.split("=", 1) for kv in head.decode(errors="surrogateescape").split("\0") if "=" in kv)
    with contextlib.suppress(ValueError):
        H.HOOK_PID = int(env.pop("HANDOVER_HOOK_PID", ""))
    cwd = env.pop("HANDOVER_HOOK_CWD", "")
    os.environ.clear()
    os.environ.update(env)
    if cwd:
        with contextlib.suppress(OSError):
            os.chdir(cwd)
    sys.stdin = io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            code = H.cmd_hook(None)
    except SystemExit as e:
        code = e.code
    except Exception:  # noqa: BLE001 - the client reports it as the cold hook's traceback would be
        return 500, (out.getvalue() + traceback.format_exc()).encode()
    return (200 if code in (0, None) else 500), out.getvalue().encode()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        status, out = run_hook(self.server.module, body)
        self.send_response(status)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
        self.wfile.flush()

    def log_message(self, *_args):
        pass


class Server(socketserver.ForkingMixIn, socketserver.UnixStreamServer):
    block_on_close = False

    def process_request(self, request, client_address):
        self.last = time.monotonic()
        super().process_request(request, client_address)


def serve(H, idle=IDLE_SECONDS, poll=POLL_SECONDS):
    """Serve until `idle` seconds without an event, or until the socket or the scripts change."""
    root = H.plugin_root()
    sock, lock = paths(root)
    os.makedirs(os.path.dirname(sock), exist_ok=True)
    with open(lock, "a") as held:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0  # another daemon of this version serves, or starts
        with contextlib.suppress(FileNotFoundError):
            os.unlink(sock)
        try:
            srv = Server(sock, Handler)
        except OSError:
            return 0  # a socket path past the system's limit, say: the hooks stay cold
        srv.module, srv.last, srv.timeout = H, time.monotonic(), min(poll, idle)
        inode, stamp = os.stat(sock).st_ino, scripts_stamp(root)
        try:
            while time.monotonic() - srv.last < idle:
                srv.handle_request()
                srv.collect_children()
                try:
                    if os.stat(sock).st_ino != inode:
                        return 0
                except OSError:
                    return 0
                if scripts_stamp(root) != stamp:
                    break
        finally:
            srv.server_close()
        with contextlib.suppress(OSError):
            if os.stat(sock).st_ino == inode:
                os.unlink(sock)
    return 0
