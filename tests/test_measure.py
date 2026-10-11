import subprocess
import sys
import textwrap

from agent_bench import results
from agent_bench.measure import ResourceSampler


def test_sampler_sees_cpu_and_memory_of_a_real_process():
    child = subprocess.Popen([sys.executable, "-c", textwrap.dedent("""
        import time
        blob = bytearray(60 * 1024 * 1024)      # ~60 MB resident
        for i in range(0, len(blob), 4096):
            blob[i] = 1
        end = time.time() + 1.2
        while time.time() < end:                 # burn CPU for ~1.2 s
            pass
    """)])
    s = ResourceSampler([child.pid], interval=0.1).start()
    child.wait(timeout=30)
    summary = s.stop()
    assert summary["cpu_seconds"] >= 0.6, summary
    assert summary["peak_tree_rss_mb"] >= 40, summary
    assert any(name.startswith("python") for name in summary["processes"]), summary["processes"]
    assert summary["samples"] >= 3


def test_sampler_on_an_idle_root_reports_zero_children_cpu_but_is_safe():
    child = subprocess.Popen(["sleep", "0.3"])
    s = ResourceSampler([child.pid], interval=0.05).start()
    child.wait()
    summary = s.stop()
    assert summary["cpu_seconds"] >= 0.0 and summary["samples"] >= 1


def _run(task, harness, procs):
    total = sum(v["cpu_seconds"] for v in procs.values())
    peak = max(v["peak_rss_mb"] for v in procs.values())
    return {"task": task, "harness": harness, "rep": 0, "attempt": 0, "pass": True, "wall_s": 1, "prompt_tokens": 0,
            "completion_tokens": 0, "chat_requests": 0, "timed_out": False, "http_errors": 0,
            "rate_limited": 0, "tests_tampered": False, "error": None,
            "resources": {"cpu_seconds": total, "peak_tree_rss_mb": peak, "samples": 3, "processes": procs}}


def test_process_table_averages_cpu_per_run_and_keeps_peak_memory():
    rows = [
        _run("T1", "omp", {"node": {"count": 2, "cpu_seconds": 10.0, "peak_rss_mb": 300.0}}),
        _run("T1", "omp", {"node": {"count": 2, "cpu_seconds": 20.0, "peak_rss_mb": 500.0}}),
        _run("T1", "pi", {"node": {"count": 1, "cpu_seconds": 4.0, "peak_rss_mb": 120.0}}),
    ]
    table = {(p["harness"], p["process"]): p for p in results.process_table(rows)}
    assert table[("omp", "node")]["mean_cpu_s"] == 15.0
    assert table[("omp", "node")]["peak_rss_mb"] == 500.0
    assert table[("omp", "node")]["runs"] == 2
    assert table[("pi", "node")]["mean_cpu_s"] == 4.0


def test_markdown_includes_resource_columns_and_process_table():
    rows = [_run("T1", "omp", {"node": {"count": 1, "cpu_seconds": 8.0, "peak_rss_mb": 250.0}})]
    md = results.markdown(rows)
    assert "mean CPU s" in md and "peak RSS MB" in md
    assert "Per process" in md and "| T1 | omp | node | 1 | 8.0 | 250.0 |" in md


def test_old_records_without_resources_still_summarise():
    rows = [{"task": "T1", "harness": "pi", "rep": 0, "attempt": 0, "pass": True, "wall_s": 5,
             "prompt_tokens": 1, "completion_tokens": 1, "chat_requests": 1, "timed_out": False,
             "http_errors": 0, "rate_limited": 0, "tests_tampered": False, "error": None}]
    assert results.summarise(rows)[0]["mean_cpu_s"] is None
    assert "Per process" not in results.markdown(rows)
