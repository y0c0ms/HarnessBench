import io
import textwrap
import types

from rich.console import Console

from agent_bench import cli
from agent_bench.runner import Job, State
from agent_bench.tui import render


def _text(renderable, width=110):
    buf = io.StringIO()
    Console(file=buf, width=width, force_terminal=False, color_system=None).print(renderable)
    return buf.getvalue()


def _meta():
    return {"pi": types.SimpleNamespace(label="Pi", icon_emoji="π", icon_ascii="pi"),
            "omp": types.SimpleNamespace(label="omp", icon_emoji="Ω", icon_ascii="omp"),
            "claude": types.SimpleNamespace(label="Claude Code", icon_emoji="✶", icon_ascii="cc")}


def test_tui_shows_one_row_per_harness_with_icons_and_progress():
    jobs = [Job(0, "pi", "t", 0), Job(1, "pi", "t", 1), Job(2, "omp", "t", 0), Job(3, "claude", "t", 0)]
    st = State(jobs, meta=_meta())
    st.begin(jobs[1])
    st.end(jobs[0], {"pass": True, "wall_s": 3.2, "error": None})
    out = _text(render(st, cap=4, mode="emoji"))
    assert "π Pi" in out and "Ω omp" in out and "✶ Claude Code" in out
    assert "1/2" in out and "✔1" in out
    assert "running" in out and "t rep1" in out
    assert "PASS" in out
    assert "cap 4" in out


def test_tui_ascii_mode_has_no_emoji():
    jobs = [Job(0, "pi", "t", 0)]
    out = _text(render(State(jobs, meta=_meta()), cap=1, mode="ascii"))
    assert "π" not in out and "pi Pi" in out


def test_tui_falls_back_to_harness_name_without_metadata():
    out = _text(render(State([Job(0, "codex", "t", 0)]), cap=1))
    assert "codex" in out


def test_init_writes_config_example_task_and_harness_folder(tmp_path):
    assert cli.main(["init", str(tmp_path)]) == 0
    assert (tmp_path / "bench.toml").exists()
    assert (tmp_path / "tasks" / "title-case" / "reference" / "textutil.py").exists()
    assert (tmp_path / "harnesses" / "_template.py").exists()
    assert cli.main(["init", str(tmp_path)]) == 1


def test_validate_command_on_example(tmp_path, capsys):
    cli.main(["init", str(tmp_path)])
    rc = cli.main(["validate", "-c", str(tmp_path / "bench.toml")])
    assert rc == 0 and "1/1 tasks valid" in capsys.readouterr().out


def test_harnesses_command_reports_status(tmp_path, capsys):
    cli.main(["init", str(tmp_path)])
    cli.main(["harnesses", "-c", str(tmp_path / "bench.toml")])
    out = capsys.readouterr().out
    assert "oracle" in out and "built-in" in out and "sandbox (bubblewrap)" in out


def test_run_without_selection_on_a_pipe_is_a_clear_error(tmp_path, capsys):
    cli.main(["init", str(tmp_path)])
    rc = cli.main(["run", "-c", str(tmp_path / "bench.toml")])
    out = capsys.readouterr().out
    assert rc == 2 and "no harnesses selected" in out


def test_config_error_is_reported_not_raised(tmp_path, capsys):
    bad = tmp_path / "bench.toml"
    bad.write_text(textwrap.dedent("""
        [provider]
        openai_base_url = "https://x/v1"
    """))
    rc = cli.main(["validate", "-c", str(bad)])
    assert rc == 2 and "config error" in capsys.readouterr().out
