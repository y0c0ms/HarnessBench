# agent-bench

Run the same coding tasks through several agent harnesses against **one model and one set of model settings**,
then compare pass rate, time, tokens, requests, and an optional judge score.

- **Provider-agnostic.** Point it at any OpenAI-compatible endpoint (and optionally an Anthropic-compatible one).
  No provider, host, or model is built in.
- **Harnesses are plugins.** The core ships no agent adapters. Each harness is one file in `harnesses/`; a tick list
  at start chooses which to run.
- **Your tasks, in a folder.** Each task is a directory: instructions, starter files, checker tests, and an optional
  reference solution that proves the task is solvable.
- **Isolated runs.** Every run gets a fresh workspace, a private HOME, its own logging proxy, and a bubblewrap sandbox
  whose only network path is that proxy. The provider key never enters a harness.
- **Live display.** One row per selected harness with its icon, a progress bar, and pass/fail counts, then what is running.
- **Optional judge.** Any LLM endpoint can grade each change against the task text (1–5), alongside the tests.

> Tested on one Linux workstation (Fedora, bubblewrap 0.11) against one OpenAI-compatible gateway with 4 harnesses at
> up to 12 concurrent sessions. Results: [RESULTS.md](RESULTS.md). Limits: see below.

## Requirements

- Linux with `bwrap` (bubblewrap). The sandbox is what makes runs isolated; there is no unsandboxed model mode.
- Python 3.11+.
- The harness executables you want to run, on `PATH` or set under `[binaries]` in the config.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/agent-bench init my-bench          # bench.toml, tasks/title-case, harnesses/_template.py
$EDITOR my-bench/bench.toml                  # [provider] model, openai_base_url, api_key_env
export AGB_PROVIDER_KEY=...                  # the key, from the environment only
.venv/bin/agent-bench harnesses -c my-bench/bench.toml   # which plugins are runnable
.venv/bin/agent-bench validate -c my-bench/bench.toml    # tests must fail on starter, pass on reference
.venv/bin/agent-bench run -c my-bench/bench.toml         # tick list, then the live display
.venv/bin/agent-bench report my-bench/runs/<stamp>       # summary table for a run
```

`run` options: `--harness pi,omp` skips the tick list, `--task a,b`, `--reps N`, `--max-sessions N`,
`--retry-failed N`, `--judge` / `--no-judge`, `--ascii`, `--no-tui`.

On a terminal, `run` first shows the **tick list**: every plugin in the harness folder, with `[unavailable]` and the
reason for any that cannot run (missing executable, or no Anthropic endpoint for Claude Code). Type numbers to toggle,
`a` for all, `n` for none, Enter to start. Pre-selection comes from `[run] harnesses` if set, otherwise all runnable ones.

## Harnesses (plugins)

A harness is one Python file in `harnesses/` (path set by `harness_dir`). The file defines `HARNESS`, an instance
of a `Harness` subclass, that says:

- which executable to find, and its API protocol (`openai`, `anthropic`, or none)
- which config files to write into the run's private HOME, pointing at the proxy with a dummy key
- the environment and command line to launch it with

Start from `harnesses/_template.py`: copy it to `harnesses/<name>.py`, rename the class and `name`, fill in the three
methods, and it appears in the tick list. No other change is needed. A file starting with `_` is ignored.

Adding a new harness later (for example Codex or DeepSeek) is therefore one new file. Plugin names must be unique;
a clash is reported at start-up.

The four adapters used for the published results are not in this repository. Keep your own in `harnesses/`; the
`.gitignore` excludes them, so commit them only if you want them public.

## Your tasks

```
tasks/<name>/
  TASK.md        instructions the agent reads (required)
  starter/       files copied into the agent's workspace (required)
  tests/         checker files, copied in and restored before grading (required)
  reference/     known-good solution; used only by `validate`, never shown to agents (recommended)
  task.toml      optional: description, timeout_s, rubric (a file in the task folder)
```

`validate` checks two things: the tests **fail** on `starter/` (otherwise the task proves nothing) and **pass** on
`reference/` (otherwise the task may be unsolvable). Tests edited by an agent are restored before grading and
reported as `tests_tampered`.

Put your tasks in any folder and point `[run] tasks_dir` at it. The instruction given to every agent is `[run] prompt`,
and the grader is `[run] grade_cmd` (default `python3 -m pytest -q`).

## Output

Each run writes to `runs/<stamp>/`:

- `results.jsonl`: one record per attempt (pass, pytest summary, wall time, requests, prompt/completion/cache tokens,
  HTTP errors, rate-limit hits, timeouts, test tampering, judge result, error)
- `summary.md` and `summary.json`: aggregates per task and harness
- `log.txt`: one line per finished job
- `runs/<cell>/`: `change.diff` (the agent's change against the starter), `harness.out`, `harness.err`,
  `capture/` (every request and the usage the proxy saw)

Tokens are summed from the provider's usage fields. Anthropic cache reads are added to the prompt total. Requests are
counted only when the proxy saw them, so a run that bypassed the proxy would show zero.

## Concurrency and limits

`[run] max_sessions` caps how many runs are in flight across all selected harnesses. Match it to your provider's
concurrent-session or rate limit. Each run has its own proxy, so token counts never mix between runs.

## Judge (optional)

```toml
[judge]
enabled = true
api = "openai"                 # or "anthropic"
base_url = "https://judge.example.com/v1"
model = "your-judge-model"
api_key_env = "AGB_JUDGE_KEY"
rubric = "rubric.md"           # optional; a built-in rubric is used otherwise
```

The judge sees the task text, the diff, and the test outcome, and returns `score` (1–5), `spec_faithful`,
`minimal_change`, and notes. Treat it as a second opinion: tests decide pass/fail, and the judge is itself a model
with its own errors.

## Security model

- The provider key is read from an environment variable and used only by the proxy process on the host.
- Harnesses get a dummy key. The proxy strips inbound auth headers and injects the real key upstream.
- Inside the sandbox: no network except a relay to the run's own proxy socket; the real home is replaced by an empty
  read-only directory; `/tmp` is private; only the run's workspace and HOME are writable.
- `tests/test_integration.py` checks these properties with real sandboxes.

## Limits

- Linux only (bubblewrap). No Windows or macOS sandbox.
- Harness adapters are plugins written against specific CLI versions; when a CLI changes, its plugin may need updating.
- Providers must serve `/v1/models` if a harness discovers models through it (omp does), and `/v1/chat/completions`.
  Claude Code needs an Anthropic-compatible `/v1/messages`; without one that harness is shown as unavailable.
- Model settings are the provider's defaults unless your config sets them. Not every harness exposes sampling controls,
  so the comparison is "each harness as shipped" on the same model.
- Wall time under concurrency measures contention as well as the harness. For timing comparisons use
  `--max-sessions 1`.
- Small tasks saturate quickly; use harder tasks to separate harnesses.

## Settings (general, applied to every harness that supports them)

One file, `settings.toml` next to `bench.toml`:

```toml
temperature = 0.2          # 0 to 2
top_p = 0.95               # 0 to 1
max_output_tokens = 4096   # whole number
```

Unset means "the harness's own default". A setting a harness does not support is not applied to it. Each adapter
declares what it applies (`settings_support`) and writes those values into its own config format.

Declared is not the same as working. `agent-bench check-settings -c bench.toml` sends one tiny probe per harness with
known values and inspects the request bodies the proxy recorded: a setting counts as applied only if the exact value
reached the provider. Results are saved next to the settings file. A harness that never reaches the provider is
reported as such, not as "not applied".

Every run records the values it used (`settings.json` in the run folder, and `settings` in each record), so results
stay comparable. Changing a setting changes what later runs measure: treat it as part of the experiment.

The settings screen (`agent-bench settings -c bench.toml`, or `s` in the viewer) lists each setting with its value on
the left and an icon for each harness that supports it on the right. `icon?` means declared but not yet confirmed.
Up and down select, Enter edits, `x` unsets, `b` goes back.

## Operator viewer

`agent-bench watch RUN_DIR` (add `-c bench.toml` to enable settings) is a separate process: it reads the run and writes
kill requests, so it does not change the run's results. Keys are listed in the screen. A kill is recorded as a killed
run: no grading, no judge, and it is excluded from pass rates and counted separately.

## Tests

```bash
.venv/bin/python -m pytest -q
```

Unit tests need no network. Integration tests use bubblewrap and a local mock provider, and are skipped if `bwrap`
is missing. Adapter-config tests run only if the matching plugin files are present in `harnesses/`.

## License

Not yet chosen.
