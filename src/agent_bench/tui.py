"""Live progress display. One row per selected harness at the top (icon, progress bar, pass/fail counts), then the
runs in flight, then the most recent results. Reads a State snapshot; never touches the runs themselves."""
from __future__ import annotations

import time

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .runner import State

BAR = 24


def _meta(state: State, name: str):
    """(label, icon) for a harness. Falls back to the name if the harness object was not supplied."""
    h = state.meta.get(name)
    if h is None:
        return name, "•", "*"
    return h.label, h.icon_emoji, h.icon_ascii


def _label(state: State, name: str, mode: str) -> str:
    label, emoji, ascii_icon = _meta(state, name)
    return f"{emoji if mode == 'emoji' else ascii_icon} {label}"


def render(state: State, cap: int, mode: str = "emoji"):
    snap = state.snapshot()
    now = time.time()
    elapsed = int(now - snap["started"])
    head = Text.assemble(("agent-bench", "bold"), f"  {snap['done']}/{snap['total']} done",
                         f"  ·  {len(snap['running'])} running (cap {cap})",
                         f"  ·  {snap['passed']} passed",
                         f"  ·  {elapsed // 60:02d}:{elapsed % 60:02d}")

    rows = Table.grid(padding=(0, 2))
    rows.add_column(width=16)
    rows.add_column(width=BAR + 2)
    rows.add_column()
    for name, s in snap["per"].items():
        frac = s["done"] / s["total"] if s["total"] else 0
        filled = int(frac * BAR)
        bar = Text("█" * filled + "░" * (BAR - filled), style="green" if s["failed"] == 0 else "yellow")
        counts = Text.assemble((f"{s['done']}/{s['total']}", "bold"), "  ",
                               (f"✔{s['passed']}", "green"), " ",
                               (f"✘{s['failed']}", "red" if s["failed"] else "dim"),
                               (f"  err {s['errors']}" if s["errors"] else ""))
        rows.add_row(Text(_label(state, name, mode), style="bold"), bar, counts)

    running = Table.grid(padding=(0, 2))
    running.add_column(width=16)
    running.add_column()
    running.add_column(justify="right")
    if snap["running"]:
        for info in sorted(snap["running"].values(), key=lambda i: (i["harness"], i["task"], i["rep"])):
            t = int(now - info["t"])
            running.add_row(Text(_label(state, info["harness"], mode)),
                            f"{info['task']} rep{info['rep']}", f"{t // 60:02d}:{t % 60:02d}")
    else:
        running.add_row(Text("idle", style="dim"), "", "")

    recent = Table.grid(padding=(0, 2))
    recent.add_column(width=16)
    recent.add_column()
    recent.add_column()
    for r in snap["recent"]:
        recent.add_row(Text(_label(state, r["harness"], mode)),
                       f"{r['task']} rep{r['rep']} {r['wall_s']}s",
                       Text("PASS", style="green") if r["pass"] else Text("FAIL", style="red"))

    return Panel(Group(head, Text(""), rows, Text(""), Text("running", style="bold"), running,
                       Text(""), Text("recent", style="bold"), recent),
                 border_style="cyan", title="harness benchmark")


class Display:
    def __init__(self, state: State, cap: int, mode: str = "emoji"):
        self.state, self.cap, self.mode = state, cap, mode
        self.live = Live(render(state, cap, mode), refresh_per_second=4, transient=False)

    def __enter__(self):
        self.live.__enter__()
        return self

    def __exit__(self, *exc):
        self.live.update(render(self.state, self.cap, self.mode))
        self.live.__exit__(*exc)
        return False

    def tick(self):
        self.live.update(render(self.state, self.cap, self.mode))
