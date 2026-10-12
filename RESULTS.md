# Results

Six coding-agent harnesses on ten tasks (six coding tasks and four search-and-find tasks), the same model, and each harness's own defaults. Date: 2026-10-12.

## Setup

- **Harnesses:** Pi 1.1.0, OpenCode 1.18.32, omp 18.8.6, Claude Code 2.1.220 (the installed CLI versions), DeepSeek Harness (`deepseek-harness-sdk` 0.1.5rc1, a pre-release, driven through its Python SDK), Codex CLI 0.162.1 (through a local Responses-to-SSE proxy that calls the upstream non-streaming and re-emits its output unchanged).
- **Model:** `longcat-2.5-preview-free` (free tier), reached through one OpenAI-compatible gateway. Claude Code used the gateway's Anthropic-compatible route. DeepSeek and the other harnesses used the gateway's chat-completions route.
- **Sampling:** each harness's defaults. A probe on the wire confirmed that none of the four sent `temperature` or `top_p` in these runs.
- **Coding tasks, T4 to T9:**
  - T4: expression evaluator with precedence, associativity, unary minus, and error cases.
  - T5: TTL cache with LRU eviction and an exact expiry boundary.
  - T6: CSV field parser and per-name totals report.
  - T7: invoice totals across several modules, with rounding and currency conversion.
  - T8: cron next-fire parser with steps, ranges, and day-of-month/day-of-week rules.
  - T9: line diff with a minimal edit script and unified hunks.
- **Search tasks, S1 to S4:** each is a small workspace with a bug or a lookup, generated deterministically.
  - S1: config precedence. The answer is the value that wins after all override layers; four decoy values are planted.
  - S2: log hunt across rotated, gzipped logs. The answer is the earliest event by timestamp; the naive first match is wrong.
  - S3: a moved module. The import must be fixed in the caller.
  - S4: find one record by exact id, with near-miss ids (`acct-77410`, `acct-7714`, `acct-7741-old`) and change only that record.
  - Every task has starter code, a test file the agent can see, and a reference solution. The tests fail on the starter and pass on the reference.
- **Grading:** pytest in the workspace after the tests are restored. A run passes if every test passes. Tampering with tests is recorded; none was detected.
- **Protocol:** each run has a fresh workspace, a private HOME, its own logging proxy, and a sandbox whose only network path is that proxy. Up to 12 sessions ran at once across all harnesses; a shared slot queue enforces the cap across processes. The time limit was 1500 s per run.
- **Pricing:** `$0.10` per million input tokens and `$0.60` per million output tokens. These are the rates assumed for the underlying model, not published prices. Cost uses `prompt_tokens` (which includes cached input, counted at the full input rate) and `completion_tokens`. Cache reads are not discounted. A harness that caches heavily is therefore overstated if cached input is cheaper.

### Data sets

| Set | Runs | Contents |
|---|---|---|
| Matrix | 72 | T4–T9, 3 reps per harness and task (four original harnesses) |
| Retry | 45 | 3 more reps for the 15 cells that had a failure or a large timing spread in the matrix |
| Gap | 36 | Extra reps to bring every T4–T9 cell to 6 valid runs (four original harnesses) |
| Search | 96 | S1–S4, 6 reps per harness and task (four original harnesses) |
| DeepSeek | 60 | T4–T9 and S1–S4, 6 reps per task (queue run `20261012-010900`) |
| Codex | 60 | T4–T9 and S1–S4, 6 reps per task (queue run `20261012-182402`; T9 rep 5 from rerun `20261012-192342`) |

- The valid-run rule: a run that is not passing, made zero model requests, and ran under 10 s is infrastructure. Gateway errors on Codex are also excluded. No run was killed.
- Four original harnesses: 240 valid runs, 9 infrastructure crashes excluded (all omp matrix runs that failed at startup, `EDQUOT` on the native addon). **Every cell has exactly 6 valid runs.**
- DeepSeek: 60 valid runs, no infrastructure failures. **Every DeepSeek cell has exactly 6 valid runs.**

## Headline

- **T4 to T8 separate little.** Every valid run of the four original harnesses passed (120 runs), and DeepSeek passed 29 of 30.
- **T9 separates them.** omp 6/6, OpenCode 5/6, Pi 3/6, DeepSeek 3/6, Claude Code 1/6.
- **S1 and S3 separate little.** Every run of all five harnesses passed.
- **S2:** Pi passed 5/6; every other harness passed 6/6, including DeepSeek.
- **S4 is not a valid measurement yet.** The failures trace to a grader bug (see below), which affects every harness. The raw pass counts are shown but should not be read as skill differences.
- **Cost:** DeepSeek is the most expensive harness on five tasks (T4, T5, T6, T8, S2), Claude Code on the other five. Its highest single cell is S2 at $0.1133 per run. Claude Code's highest is S2 at $0.0782.
- **Codex CLI: 48 of 60 passes.** Strongest on T4–T7 and S1/S3 (6/6 each); weakest on S4 (1/6, grader-invalid) and S2 (4/6, the most requests per run: 28.7). Its T9 is 3/6, the same as DeepSeek.

## Pass rates and cost per task

Each cell shows passes out of 6 valid runs, and the mean cost per run in USD (see Pricing above).

| Task | Claude Code | omp | OpenCode | Pi | DeepSeek | Codex |
|---|---|---|---|---|---|---|
| T4 | 6/6 · $0.0229 | 6/6 · $0.0125 | 6/6 · $0.0089 | 6/6 · $0.0108 | 6/6 · $0.0315 | 6/6 · $0.0131 |
| T5 | 6/6 · $0.0207 | 6/6 · $0.0098 | 6/6 · $0.0081 | 6/6 · $0.0054 | 6/6 · $0.0540 | 6/6 · $0.0142 |
| T6 | 6/6 · $0.0397 | 6/6 · $0.0137 | 6/6 · $0.0108 | 6/6 · $0.0092 | 5/6 · $0.0628 | 6/6 · $0.0155 |
| T7 | 6/6 · $0.0300 | 6/6 · $0.0089 | 6/6 · $0.0114 | 6/6 · $0.0147 | 6/6 · $0.0174 | 6/6 · $0.0117 |
| T8 | 6/6 · $0.0394 | 6/6 · $0.0186 | 6/6 · $0.0118 | 6/6 · $0.0162 | 6/6 · $0.0653 | 4/6 · $0.0253 |
| T9 | 1/6 · $0.0758 | 6/6 · $0.0335 | 5/6 · $0.0285 | 3/6 · $0.0276 | 3/6 · $0.0733 | 3/6 · $0.0198 |
| S1 | 6/6 · $0.0311 | 6/6 · $0.0121 | 6/6 · $0.0151 | 6/6 · $0.0081 | 6/6 · $0.0111 | 6/6 · $0.0162 |
| S2 | 6/6 · $0.0782 | 6/6 · $0.0321 | 6/6 · $0.0186 | 5/6 · $0.0421 | 6/6 · $0.1133 | 4/6 · $0.0844 |
| S3 | 6/6 · $0.0309 | 6/6 · $0.0094 | 6/6 · $0.0092 | 6/6 · $0.0068 | 6/6 · $0.0232 | 6/6 · $0.0118 |
| S4 (grader invalid) | 4/6 · $0.0634 | 3/6 · $0.0266 | 0/6 · $0.0097 | 3/6 · $0.0118 | 4/6 · $0.0306 | 1/6 · $0.0153 |

### Cost per harness

Mean cost per valid run, and cost per passed run. The cost per pass is total cost divided by passes, so a harness that fails a lot pays more per success.

| Harness | Group | Runs | Passes | Mean $/run | Total $ | $/pass |
|---|---|---|---|---|---|---|
| Claude Code | T4–T8 | 30 | 30 | 0.0306 | 0.92 | 0.0306 |
| Claude Code | T9 | 6 | 1 | 0.0758 | 0.45 | 0.4546 |
| Claude Code | S1–S4 | 24 | 22 | 0.0509 | 1.22 | 0.0555 |
| omp | T4–T8 | 30 | 30 | 0.0127 | 0.38 | 0.0127 |
| omp | T9 | 6 | 6 | 0.0335 | 0.20 | 0.0335 |
| omp | S1–S4 | 24 | 21 | 0.0200 | 0.48 | 0.0229 |
| OpenCode | T4–T8 | 30 | 30 | 0.0102 | 0.31 | 0.0102 |
| OpenCode | T9 | 6 | 5 | 0.0285 | 0.17 | 0.0341 |
| OpenCode | S1–S4 | 24 | 18 | 0.0132 | 0.32 | 0.0175 |
| Pi | T4–T8 | 30 | 30 | 0.0113 | 0.34 | 0.0113 |
| Pi | T9 | 6 | 3 | 0.0276 | 0.17 | 0.0553 |
| Pi | S1–S4 | 24 | 20 | 0.0172 | 0.41 | 0.0206 |
| DeepSeek | T4–T8 | 30 | 29 | 0.0462 | 1.39 | 0.0478 |
| DeepSeek | T9 | 6 | 3 | 0.0733 | 0.44 | 0.1466 |
| DeepSeek | S1–S4 | 24 | 22 | 0.0446 | 1.07 | 0.0486 |

Across all valid runs per harness: Claude Code 0.0432 $/run (53 passes of 60), omp 0.0177 (57 of 60), OpenCode 0.0132 (53 of 60), Pi 0.0153 (53 of 60), DeepSeek 0.0482 (54 of 60). The S4 pass counts are invalid, so these per-pass figures are indicative only.

## Time and tokens

Valid runs, 6 per cell. Wall time was measured at up to 12 concurrent sessions, so it includes contention; rank harnesses within a task, not across tasks.

| Task | Harness | Mean wall s | Mean prompt tok | Mean completion tok | Mean requests |
|---|---|---|---|---|---|
| T4 | Claude Code | 152 | 189,726 | 6,536 | 8.7 |
| T4 | omp | 137 | 94,777 | 5,095 | 9.0 |
| T4 | OpenCode | 116 | 55,446 | 5,531 | 6.8 |
| T4 | Pi | 190 | 55,586 | 8,752 | 8.7 |
| T4 | DeepSeek | 385 | 224,767 | 15,042 | 22.0 |
| T5 | Claude Code | 100 | 183,169 | 4,028 | 8.7 |
| T5 | omp | 104 | 78,543 | 3,178 | 8.5 |
| T5 | OpenCode | 69 | 66,807 | 2,378 | 8.5 |
| T5 | Pi | 114 | 24,309 | 4,927 | 6.5 |
| T5 | DeepSeek | 500 | 422,453 | 19,552 | 25.8 |
| T6 | Claude Code | 366 | 301,992 | 15,875 | 11.3 |
| T6 | omp | 132 | 110,634 | 4,401 | 10.8 |
| T6 | OpenCode | 96 | 83,662 | 4,051 | 9.5 |
| T6 | Pi | 173 | 48,312 | 7,298 | 10.3 |
| T6 | DeepSeek | 553 | 501,974 | 20,925 | 32.7 |
| T7 | Claude Code | 268 | 224,796 | 12,586 | 9.3 |
| T7 | omp | 71 | 77,109 | 2,022 | 9.0 |
| T7 | OpenCode | 124 | 82,740 | 5,261 | 9.0 |
| T7 | Pi | 278 | 69,747 | 12,897 | 11.0 |
| T7 | DeepSeek | 252 | 122,682 | 8,537 | 20.7 |
| T8 | Claude Code | 376 | 283,817 | 18,337 | 10.3 |
| T8 | omp | 275 | 114,305 | 12,028 | 8.5 |
| T8 | OpenCode | 142 | 80,308 | 6,294 | 8.3 |
| T8 | Pi | 383 | 50,818 | 18,537 | 7.8 |
| T8 | DeepSeek | 593 | 521,628 | 21,958 | 26.8 |
| T9 | Claude Code | 1,449 | 207,638 | 91,680 | 9.2 |
| T9 | omp | 524 | 186,724 | 24,643 | 9.3 |
| T9 | OpenCode | 696 | 77,054 | 34,579 | 7.7 |
| T9 | Pi | 539 | 110,047 | 27,722 | 9.8 |
| T9 | DeepSeek | 1,146 | 332,112 | 66,790 | 18.8 |
| S1 | Claude Code | 112 | 286,572 | 4,125 | 11.8 |
| S1 | omp | 86 | 105,523 | 2,551 | 10.8 |
| S1 | OpenCode | 89 | 133,472 | 2,926 | 13.0 |
| S1 | Pi | 80 | 64,169 | 2,768 | 12.3 |
| S1 | DeepSeek | 150 | 89,532 | 3,646 | 18.0 |
| S2 | Claude Code | 391 | 689,626 | 15,478 | 21.8 |
| S2 | omp | 331 | 228,388 | 15,493 | 14.3 |
| S2 | OpenCode | 136 | 152,758 | 5,598 | 13.0 |
| S2 | Pi | 391 | 313,978 | 17,876 | 22.5 |
| S2 | DeepSeek | 817 | 932,906 | 33,310 | 36.7 |
| S3 | Claude Code | 97 | 290,358 | 3,037 | 12.5 |
| S3 | omp | 74 | 81,352 | 2,062 | 9.5 |
| S3 | OpenCode | 57 | 81,792 | 1,632 | 10.0 |
| S3 | Pi | 76 | 55,951 | 1,963 | 14.5 |
| S3 | DeepSeek | 294 | 175,595 | 9,354 | 26.5 |
| S4 | Claude Code | 311 | 558,129 | 12,564 | 18.0 |
| S4 | omp | 241 | 214,931 | 8,492 | 14.3 |
| S4 | OpenCode | 61 | 85,500 | 1,926 | 10.7 |
| S4 | Pi | 194 | 83,846 | 5,683 | 15.7 |
| S4 | DeepSeek | 357 | 232,945 | 12,196 | 28.2 |

## Failures and invalid results

- **Codex CLI:** 60 valid runs, no infrastructure exclusions. Its earlier failures (startup sandbox mount, gateway `function_call` errors) are in the excluded batches described below.
- **S4 grader bug (affects all 30 S4 runs of the five measured harnesses).** `test_nothing_else_changed` fails when a `.pytest_cache` directory exists in the workspace. The agent's own pytest run creates that directory. Reproduced on one OpenCode S4 run: the same fixed workspace passes both tests with no cache and fails (`1 failed, 1 passed`) after one ordinary pytest run. For the four original harnesses, all 14 failures have the full 8-line cache directory in their diff, and no run with that directory passed. DeepSeek's two S4 failures also have the cache directory in their diffs, and its passing runs do not. S4 pass counts are therefore not a measure of skill, and the S4 row should be re-run after the grader ignores cache directories. The grader lives in the lab task folder, not in this repository.
- **Claude Code, T9:** 5 timeouts (3 matrix, 2 retry), all at the 1500 s limit, and the runs were still making requests (7 to 9 per run). Slow, not stuck.
- **DeepSeek, T9:** 3 failures out of 6, all with real model requests. Cause not investigated.
- **DeepSeek, T6:** 1 failure out of 6. Not investigated.
- **Pi, T9:** 3 failures out of 6. Cause not investigated.
- **Pi, S2:** 1 failure out of 6. Not investigated.
- **OpenCode, T9:** 1 timeout in the matrix. Its retry runs all passed.
- **omp, 9 matrix runs:** startup crashes (`EDQUOT`), excluded from all rates above. All other omp runs passed on T4 to T9.

### Codex CLI: what changed

- **Earlier failure (fixed):** the gateway's streamed Responses route returned a tool-call turn as a stream `error` event. The proxy now calls the upstream non-streaming and re-emits the same response as SSE. Output items are the upstream's own; the proxy changes delivery, not content.
- **Excluded batches:** `20261012-010900` (60 runs, sandbox mount failure), `20261012-020546` (60 runs, gateway errors), `20261012-022154` (1 smoke run). Only `20261012-182402` and the T9 rerun `20261012-192342` count.
- **Concurrency:** the runner's pool and slot queue were checked with Codex against a local mock Responses endpoint.

## Corrections

- I earlier said omp's T7 and T8 failures were a real rounding bug and a cron comma-list bug. That was wrong. Those messages came from crashed runs, where the agent never ran and the untouched starter code was tested. Every omp run that reached the provider passed.
- The previous version of this page showed omp T9 as 4/4. Two gap runs and the retry data bring it to 6/6, all passing.
- The previous version said Claude Code was the most expensive harness on every task. DeepSeek's cost is higher on five tasks; the headline now says so.

## Limits

- **Six repetitions per cell.** A pass rate moves by one sixth per run, so differences of one or two runs are not meaningful.
- **Wall times are contended.** They were measured with up to 12 sessions in flight. Use them to rank harnesses on a task, not as absolute speed.
- **One free-tier model.** These results do not carry over to other models. The price figures are assumptions, not the model's published prices.
- **Harness defaults.** Each harness ran with its own defaults, so differences include each harness's own prompts and tools.
- **Token counts** come from the provider's usage fields. Prompt tokens include cached input. Claude Code's cache reads are counted at the full input rate in the cost figures.
- **DeepSeek Harness is a pre-release SDK.** Its runs use the SDK's own agent loop; the comparison measures that loop, not the upstream project's latest release.
- **Small tasks.** T4 to T8 saturate for most harnesses, so this is not a general coding benchmark.
- **No quality judge.** No judged scores are reported.

## Reproduce

```bash
.venv/bin/agent-bench validate -c bench.toml
.venv/bin/agent-bench run -c bench.toml --harness pi,opencode,omp,claude,deepseek,codex --reps 6 --max-sessions 12
.venv/bin/agent-bench report runs/<stamp>
```

The task folders are not part of this repository. They can be rebuilt from the descriptions above, and `validate` confirms that each one separates starter from reference.
