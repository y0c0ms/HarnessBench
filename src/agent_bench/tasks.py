"""Tasks are folders. Layout:

    <tasks_dir>/<name>/
        TASK.md        the instructions the agent reads (required)
        starter/       files copied into the agent's workspace (required)
        tests/         checker files, copied into the workspace and restored before grading (required)
        reference/     optional known-good solution, used only by `validate`, never shown to agents
        task.toml      optional: {description = "...", timeout_s = 900, rubric = "..."}
"""
from __future__ import annotations

import dataclasses
import pathlib
import shutil
import subprocess
import tempfile
import tomllib


class TaskError(ValueError):
    pass


@dataclasses.dataclass
class Task:
    name: str
    dir: pathlib.Path
    description: str
    timeout_s: int | None
    rubric: str | None

    @property
    def starter(self) -> pathlib.Path:
        return self.dir / "starter"

    @property
    def tests(self) -> pathlib.Path:
        return self.dir / "tests"

    @property
    def reference(self) -> pathlib.Path:
        return self.dir / "reference"


def discover(tasks_dir: pathlib.Path, only: list[str] | None = None) -> list[Task]:
    if not tasks_dir.is_dir():
        raise TaskError(f"tasks directory not found: {tasks_dir}")
    out = []
    for d in sorted(p for p in tasks_dir.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if only and d.name not in only:
            continue
        for required in ("TASK.md", "starter", "tests"):
            if not (d / required).exists():
                raise TaskError(f"{d}: missing '{required}'")
        meta = {}
        if (d / "task.toml").exists():
            meta = tomllib.loads((d / "task.toml").read_text())
        rubric = None
        if meta.get("rubric"):
            rubric = (d / meta["rubric"]).read_text()
        out.append(Task(name=d.name, dir=d,
                        description=meta.get("description", ""),
                        timeout_s=meta.get("timeout_s"),
                        rubric=rubric))
    if only:
        missing = set(only) - {t.name for t in out}
        if missing:
            raise TaskError(f"requested tasks not found: {sorted(missing)}")
    return out


def grade(task_dir_with_code: pathlib.Path, tests: pathlib.Path, cmd: list[str], timeout: int = 180):
    """Run the grader in a scratch copy: code from `task_dir_with_code`, tests from `tests`. Returns (passed, summary)."""
    with tempfile.TemporaryDirectory(prefix="agb-grade-") as tmp:
        ws = pathlib.Path(tmp) / "ws"
        shutil.copytree(task_dir_with_code, ws)
        for f in tests.rglob("*"):
            if f.is_file():
                target = ws / f.relative_to(tests)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(f, target)
        try:
            p = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "grader timed out"
        lines = (p.stdout + p.stderr).strip().splitlines()
        return p.returncode == 0, (lines[-1] if lines else f"exit {p.returncode}")


def validate(task: Task, grade_cmd: list[str]) -> dict:
    """The tests must FAIL on the starter (otherwise the task is trivially passed) and PASS on the reference."""
    starter_ok, starter_summary = grade(task.starter, task.tests, grade_cmd)
    report = {"task": task.name, "starter_fails": not starter_ok, "starter": starter_summary,
              "reference": None, "reference_passes": None, "ok": False}
    if task.reference.exists():
        ref_ok, ref_summary = grade(task.reference, task.tests, grade_cmd)
        report["reference"] = ref_summary
        report["reference_passes"] = ref_ok
        report["ok"] = (not starter_ok) and ref_ok
    else:
        report["ok"] = not starter_ok
        report["reference"] = "no reference/ folder (cannot prove the task is solvable)"
    return report
