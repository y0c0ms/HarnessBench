"""Sandbox for one harness run (Linux, requires bubblewrap).

What the harness gets:
  - its own network namespace: no route to the internet, the provider, or any host port
  - one exit: a relay on 127.0.0.1:RELAY_PORT that forwards only to the run's logging proxy socket
  - read-only system paths and read-only install paths for the harness binary
  - a private HOME and workspace: the only writable places
  - a private /tmp, and the real home directory replaced by an empty read-only directory
It cannot see the task's reference files, other runs, or the user's real configuration.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys

RELAY_PORT = 18080
IO_DIR = "/io"                  # inside the sandbox: the directory holding proxy.sock
RELAY_PATH = "/tmp/agb-relay.py"   # inside the private /tmp tmpfs (the read-only /opt cannot host it)

RO_SYSTEM = ["/usr", "/lib", "/lib64", "/bin", "/sbin", "/opt", "/snap",
             "/etc/alternatives", "/etc/ssl", "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d",
             "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/passwd", "/etc/group",
             "/etc/localtime", "/etc/fonts", "/etc/pki", "/etc/profile.d", "/etc/crypto-policies"]


def available() -> bool:
    return shutil.which("bwrap") is not None


def install_roots(binary: str) -> list[str]:
    """Directories the harness needs read-only to run. For node-based installs this is the enclosing
    node_modules tree (so dependencies resolve); otherwise the directory of the real executable."""
    real = pathlib.Path(os.path.realpath(binary))
    parts = real.parts
    roots = []
    if "node_modules" in parts:
        idx = len(parts) - 1 - list(reversed(parts)).index("node_modules")
        roots.append(str(pathlib.Path(*parts[: idx + 1])))
    roots.append(str(real.parent))
    return list(dict.fromkeys(roots))


def bwrap_argv(run_dir: pathlib.Path, io_dir: pathlib.Path, ro_paths: list[str],
               real_home: str, argv: list[str]) -> list[str]:
    """Build the bwrap command. run_dir holds home/ and ws/; io_dir holds proxy.sock."""
    run_dir = run_dir.resolve()
    home, ws = run_dir / "home", run_dir / "ws"
    relay_src = pathlib.Path(__file__).resolve().parent / "relay.py"
    py_dirs = sorted({str(pathlib.Path(sys.executable).parent), str(pathlib.Path(os.path.realpath(sys.executable)).parent)})
    args = ["bwrap", "--die-with-parent", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--unshare-net",
            "--new-session", "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp", "--tmpfs", "/run", "--tmpfs", "/var/tmp",
            "--tmpfs", real_home, "--perms", "0555", "--dir", real_home]
    for p in RO_SYSTEM:
        if os.path.exists(p):
            args += ["--ro-bind", p, p]
    for p in py_dirs + ro_paths:
        if os.path.exists(p):
            args += ["--ro-bind", p, p]
    args += ["--ro-bind", str(relay_src), RELAY_PATH]
    args += ["--bind", str(home), str(home), "--bind", str(ws), str(ws), "--bind", str(io_dir), IO_DIR]
    args += ["--chdir", str(ws)]
    return args + argv
