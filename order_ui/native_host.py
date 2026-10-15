"""Narrow Chrome native host: start the fixed local desk, never handle orders/keys."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

from .extension import EXTENSION_ORIGIN
from toss_fractional.auth import _TokenFileLock

HOST_NAME = "com.moa_invest.launcher"
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
MAX_MESSAGE = 1024
IDENTITY = {"app": "moa-invest", "launcherProtocol": 1}


def read_message(stream):
    header = stream.read(4)
    if len(header) != 4:
        raise ValueError("Missing message")
    size = struct.unpack("<I", header)[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("Invalid message size")
    raw = stream.read(size)
    if len(raw) != size:
        raise ValueError("Truncated message")
    message = json.loads(raw.decode("utf-8"))
    if message != {"action": "ensure-server"}:
        raise ValueError("Unsupported message")
    return message


def write_message(stream, message):
    raw = json.dumps(message, ensure_ascii=True).encode("utf-8")
    stream.write(struct.pack("<I", len(raw)) + raw)
    stream.flush()


def port_available():
    """Windows can time out, rather than refuse, a connection to an unused port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", 8765))
            return True
        except OSError:
            return False


def probe():
    """No proxy, redirect, account lookup, token issuance or credential read."""
    connection = http.client.HTTPConnection("127.0.0.1", 8765, timeout=0.6)
    try:
        connection.request("GET", "/api/launcher-status", headers={"X-Requested-With": "fractional-buy"})
        response = connection.getresponse()
        raw = response.read(MAX_MESSAGE + 1)
        if response.status == 200 and len(raw) <= MAX_MESSAGE and json.loads(raw) == IDENTITY:
            return "ready"
        return "occupied"
    except (OSError, ValueError, http.client.HTTPException):
        # Bind-check distinguishes a filtered unused port from a slow server.
        return "absent" if port_available() else "occupied"
    finally:
        connection.close()


def launch_server():
    if os.name != "nt":
        raise OSError("Windows launcher only")
    command = ([sys.executable, "--serve"] if getattr(sys, "frozen", False)
               else [sys.executable, "-m", "order_ui.server", "--env", str(ROOT / ".env")])
    return subprocess.Popen(
        command,
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True,
        # Never inherit the native host's lifetime/job or show a console window.
        # If breakaway is forbidden, fail instead of silently tying orders to Chrome.
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB,
    )


def ensure_server():
    with _TokenFileLock(ROOT / "data" / "native-launch.lock", timeout_seconds=12):
        state = probe()
        if state == "ready":
            return {"ok": True, "started": False}
        if state != "absent":
            return {"ok": False, "code": "port-busy"}
        child = launch_server()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if probe() == "ready":
                return {"ok": True, "started": True}
            if child.poll() is not None:
                break
            time.sleep(0.15)
        # Never kill an existing/new server: an order may already have started.
        return {"ok": False, "code": "start-failed"}


def main(argv=None, incoming=None, outgoing=None):
    args = sys.argv[1:] if argv is None else argv
    incoming = sys.stdin.buffer if incoming is None else incoming
    outgoing = sys.stdout.buffer if outgoing is None else outgoing
    # Chrome checks allowed_origins too. No arbitrary path, port or command input.
    if not args or args[0] != EXTENSION_ORIGIN + "/":
        return 1
    if os.name == "nt":
        import msvcrt
        for stream in (incoming, outgoing):
            if hasattr(stream, "fileno"):
                try:
                    msvcrt.setmode(stream.fileno(), os.O_BINARY)
                except (OSError, ValueError):
                    pass
    try:
        read_message(incoming)
        result = ensure_server()
    except Exception:
        # No exception text, local paths, environment or credentials over the pipe.
        result = {"ok": False, "code": "launcher-error"}
    write_message(outgoing, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
