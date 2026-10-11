"""Resource measurement for one run: CPU time and memory of every process in the run's process trees.

A sampler thread walks /proc every INTERVAL seconds, starting from the root pids (the sandbox launcher and the
run's logging proxy) and following children. Per process it keeps the largest cumulative CPU time seen and the
largest resident memory seen; results are grouped by process name (node, omp, claude, python3, ...).

Limits, stated plainly: a process that starts and exits between two samples can be missed, so CPU totals are a
lower bound, and peak memory is sampled, not exact. Interval 0.5 s keeps the overhead negligible.
"""
from __future__ import annotations

import collections
import os
import threading

CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024
INTERVAL = 0.5


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _proc_info(pid: int):
    """(ppid, comm, cpu_ticks, rss_kb) for a live pid, or None if it has gone."""
    stat = _read(f"/proc/{pid}/stat")
    statm = _read(f"/proc/{pid}/statm")
    comm = _read(f"/proc/{pid}/comm")
    if stat is None or statm is None or comm is None:
        return None
    rp = stat.rfind(")")                       # comm may contain spaces and parentheses
    fields = stat[rp + 2:].split()
    ppid = int(fields[1])
    utime, stime = int(fields[11]), int(fields[12])
    rss_kb = int(statm.split()[1]) * PAGE_KB
    return ppid, comm.strip(), utime + stime, rss_kb


def _all_children() -> dict[int, list[int]]:
    children: dict[int, list[int]] = collections.defaultdict(list)
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        info = _proc_info(int(name))
        if info is not None:
            children[info[0]].append(int(name))
    return children


class ResourceSampler:
    def __init__(self, roots: list[int], interval: float = INTERVAL):
        self.roots = list(roots)
        self.interval = interval
        self.procs: dict[int, dict] = {}
        self.peak_tree_rss_kb = 0
        self.samples = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> "ResourceSampler":
        self._thread.start()
        return self

    def _loop(self):
        while not self._stop.wait(self.interval):
            self._sample()

    def _sample(self):
        children = _all_children()
        tree, stack = set(), list(self.roots)
        while stack:
            pid = stack.pop()
            if pid in tree:
                continue
            tree.add(pid)
            stack.extend(children.get(pid, []))
        tree_rss = 0
        for pid in tree:
            info = _proc_info(pid)
            if info is None:
                continue
            _, comm, ticks, rss = info
            rec = self.procs.setdefault(pid, {"name": comm, "cpu_ticks": 0, "peak_rss_kb": 0})
            rec["cpu_ticks"] = max(rec["cpu_ticks"], ticks)
            rec["peak_rss_kb"] = max(rec["peak_rss_kb"], rss)
            tree_rss += rss
        self.peak_tree_rss_kb = max(self.peak_tree_rss_kb, tree_rss)
        self.samples += 1

    def stop(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=5)
        self._sample()                          # one final sample catches processes still alive at exit
        return self.summary()

    def summary(self) -> dict:
        by_name: dict[str, dict] = {}
        for rec in self.procs.values():
            g = by_name.setdefault(rec["name"], {"count": 0, "cpu_seconds": 0.0, "peak_rss_mb": 0.0})
            g["count"] += 1
            g["cpu_seconds"] += rec["cpu_ticks"] / CLK_TCK
            g["peak_rss_mb"] = max(g["peak_rss_mb"], rec["peak_rss_kb"] / 1024)
        for g in by_name.values():
            g["cpu_seconds"] = round(g["cpu_seconds"], 2)
            g["peak_rss_mb"] = round(g["peak_rss_mb"], 1)
        return {"cpu_seconds": round(sum(v["cpu_seconds"] for v in by_name.values()), 2),
                "peak_tree_rss_mb": round(self.peak_tree_rss_kb / 1024, 1),
                "samples": self.samples,
                "processes": dict(sorted(by_name.items(), key=lambda kv: -kv[1]["cpu_seconds"]))}
