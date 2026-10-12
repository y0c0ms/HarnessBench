# Results

Four coding-agent harnesses on ten tasks (six coding tasks and four search-and-find tasks), the same model, and each harness's own defaults. Date: 2026-10-12.

## Setup

- **Harnesses:** Pi 1.1.0, OpenCode 1.18.32, omp 18.8.6, Claude Code 2.1.220 (the installed CLI versions). Codex CLI and DeepSeek Harness are queued and are not in these numbers.
- **Model:** `longcat-2.5-preview-free` (free tier), reached through one OpenAI-compatible gateway. Claude Code used the gateway's Anthropic-compatible route.
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
- **Protocol:** each run has a fresh workspace, a private HOME, its own logging proxy, and a sandbox whose only network path is that proxy. Up to 12 sessions ran at once across all harnesses. The time limit was 1500 s per run.
- **Pricing:** `$0.10` per million input tokens and `$0.60` per million output tokens. These are the rates assumed for the underlying model, not published prices. Cost uses `prompt_tokens` (which includes cached input, counted at the full input rate) and `completion_tokens`. Cache reads are not discounted. A harness that caches heavily is therefore overstated if cached input is cheaper.

### Data sets

| Set | Runs | Contents |
|---|---|---|
| Matrix | 72 | T4–T9, 3 reps per harness and task |
| Retry | 45 | 3 more reps for the 15 cells that had a failure or a large timing spread in the matrix |
| Gap | 36 | Extra reps to bring every T4–T9 cell to 6 valid runs |
| Search | 96 | S1–S4, 6 reps per harness and task |

- 249 records in total. 9 were infrastructure crashes and are excluded. All 9 are omp matrix runs that failed at startup, before any model request (`EDQUOT` on extracting the native addon). The rule: a run that is not passing, made zero chat requests, and ran under 10 s is infrastructure. No run was killed.
- 240 valid runs. **Every one of the 40 cells (10 tasks × 4 harnesses) has exactly 6 valid runs.**
- Source of the valid runs per cell: T4 to T9 combine matrix, retry, and gap runs; S1 to S4 are search runs only.

## Headline

- **T4 to T8 do not separate the harnesses.** All 120 valid runs for these five tasks passed.
- **T9 separates them.** omp 6/6, OpenCode 5/6, Pi 3/6, Claude Code 1/6.
- **S1 and S3 do not separate them.** Every run passed.
- **S2:** Pi passed 5/6, the other three 6/6.
- **S4 is not a valid measurement yet.** Every failure on S4 traces to a grader bug (see below). The raw pass counts are shown but should not be read as skill differences.
- **Cost:** Claude Code is the most expensive harness on every task, from $0.0207 to $0.0782 per run. The other three cost between $0.0054 and $0.0421 per run; Pi's S2 run is the highest of them.

## Pass rates and cost per task

Each cell shows passes out of 6 valid runs, and the mean cost per run in USD (see Pricing above).

| Task | Claude Code | omp | OpenCode | Pi |
|---|---|---|---|---|
| T4 | 6/6 · $0.0229 | 6/6 · $0.0125 | 6/6 · $0.0089 | 6/6 · $0.0108 |
| T5 | 6/6 · $0.0207 | 6/6 · $0.0098 | 6/6 · $0.0081 | 6/6 · $0.0054 |
| T6 | 6/6 · $0.0397 | 6/6 · $0.0137 | 6/6 · $0.0108 | 6/6 · $0.0092 |
| T7 | 6/6 · $0.0300 | 6/6 · $0.0089 | 6/6 · $0.0114 | 6/6 · $0.0147 |
| T8 | 6/6 · $0.0394 | 6/6 · $0.0186 | 6/6 · $0.0118 | 6/6 · $0.0162 |
| T9 | 1/6 · $0.0758 | 6/6 · $0.0335 | 5/6 · $0.0285 | 3/6 · $0.0276 |
| S1 | 6/6 · $0.0311 | 6/6 · $0.0121 | 6/6 · $0.0151 | 6/6 · $0.0081 |
| S2 | 6/6 · $0.0782 | 6/6 · $0.0321 | 6/6 · $0.0186 | 5/6 · $0.0421 |
| S3 | 6/6 · $0.0309 | 6/6 · $0.0094 | 6/6 · $0.0092 | 6/6 · $0.0068 |
| S4 (grader invalid) | 4/6 · $0.0634 | 3/6 · $0.0266 | 0/6 · $0.0097 | 3/6 · $0.0118 |

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

Across all 60 runs per harness: Claude Code 0.0432 $/run (53 passes), omp 0.0177 (57), OpenCode 0.0132 (53), Pi 0.0153 (53). The S4 pass counts are invalid, so these per-pass totals are indicative only.

## Time and tokens

Valid runs, 6 per cell. Wall time was measured at up to 12 concurrent sessions, so it includes contention; rank harnesses within a task, not across tasks.

| Task | Harness | Mean wall s | Mean prompt tok | Mean completion tok | Mean requests |
|---|---|---|---|---|---|
| T4 | Claude Code | 152 | 189,726 | 6,536 | 8.7 |
| T4 | omp | 137 | 94,777 | 5,095 | 9.0 |
| T4 | OpenCode | 116 | 55,446 | 5,531 | 6.8 |
| T4 | Pi | 190 | 55,586 | 8,752 | 8.7 |
| T5 | Claude Code | 100 | 183,169 | 4,028 | 8.7 |
| T5 | omp | 104 | 78,543 | 3,178 | 8.5 |
| T5 | OpenCode | 69 | 66,807 | 2,378 | 8.5 |
| T5 | Pi | 114 | 24,309 | 4,927 | 6.5 |
| T6 | Claude Code | 366 | 301,992 | 15,875 | 11.3 |
| T6 | omp | 132 | 110,634 | 4,401 | 10.8 |
| T6 | OpenCode | 96 | 83,662 | 4,051 | 9.5 |
| T6 | Pi | 173 | 48,312 | 7,298 | 10.3 |
| T7 | Claude Code | 268 | 224,796 | 12,586 | 9.3 |
| T7 | omp | 71 | 77,109 | 2,022 | 9.0 |
| T7 | OpenCode | 124 | 82,740 | 5,261 | 9.0 |
| T7 | Pi | 278 | 69,747 | 12,897 | 11.0 |
| T8 | Claude Code | 376 | 283,817 | 18,337 | 10.3 |
| T8 | omp | 275 | 114,305 | 12,028 | 8.5 |
| T8 | OpenCode | 142 | 80,308 | 6,294 | 8.3 |
| T8 | Pi | 383 | 50,818 | 18,537 | 7.8 |
| T9 | Claude Code | 1,449 | 207,638 | 91,680 | 9.2 |
| T9 | omp | 524 | 186,724 | 24,643 | 9.3 |
| T9 | OpenCode | 696 | 77,054 | 34,579 | 7.7 |
| T9 | Pi | 539 | 110,047 | 27,722 | 9.8 |
| S1 | Claude Code | 112 | 286,572 | 4,125 | 11.8 |
| S1 | omp | 86 | 105,523 | 2,551 | 10.8 |
| S1 | OpenCode | 89 | 133,472 | 2,926 | 13.0 |
| S1 | Pi | 80 | 64,169 | 2,768 | 12.3 |
| S2 | Claude Code | 391 | 689,626 | 15,478 | 21.8 |
| S2 | omp | 331 | 228,388 | 15,493 | 14.3 |
| S2 | OpenCode | 136 | 152,758 | 5,598 | 13.0 |
| S2 | Pi | 391 | 313,978 | 17,876 | 22.5 |
| S3 | Claude Code | 97 | 290,358 | 3,037 | 12.5 |
| S3 | omp | 74 | 81,352 | 2,062 | 9.5 |
| S3 | OpenCode | 57 | 81,792 | 1,632 | 10.0 |
| S3 | Pi | 76 | 55,951 | 1,963 | 14.5 |
| S4 | Claude Code | 311 | 558,129 | 12,564 | 18.0 |
| S4 | omp | 241 | 214,931 | 8,492 | 14.3 |
| S4 | OpenCode | 61 | 85,500 | 1,926 | 10.7 |
| S4 | Pi | 194 | 83,846 | 5,683 | 15.7 |

## Failures and invalid results

- **S4 grader bug (affects all 24 S4 runs).** `test_nothing_else_changed` fails when a `.pytest_cache` directory exists in the workspace. The agent's own pytest run creates that directory. Reproduced on one OpenCode S4 run: the same fixed workspace passes both tests with no cache and fails (`1 failed, 1 passed`) after one ordinary pytest run. Across the 24 S4 runs, all 14 failures have the full 8-line cache directory in their diff, and no run with that directory passed. In the diffs I inspected, the substantive change is the target record. S4 pass counts are therefore not a measure of skill, and the S4 row should be re-run after the grader ignores cache directories. The grader lives in the lab task folder, not in this repository.
- **Claude Code, T9:** 5 timeouts (3 matrix, 2 retry), all at the 1500 s limit, and the runs were still making requests (7 to 9 per run). Slow, not stuck.
- **Pi, T9:** 3 failures out of 6. Cause not investigated.
- **Pi, S2:** 1 failure out of 6. Not investigated.
- **OpenCode, T9:** 1 timeout in the matrix. Its retry runs all passed.
- **omp, 9 matrix runs:** startup crashes (`EDQUOT`), excluded from all rates above. All other omp runs passed on T4 to T9.

## Corrections

- I earlier said omp's T7 and T8 failures were a real rounding bug and a cron comma-list bug. That was wrong. Those messages came from crashed runs, where the agent never ran and the untouched starter code was tested. Every omp run that reached the provider passed.
- The previous version of this page showed omp T9 as 4/4. Two gap runs and the retry data bring it to 6/6, all passing.

## Limits

- **Six repetitions per cell.** A pass rate moves by one sixth per run, so differences of one or two runs are not meaningful.
- **Wall times are contended.** They were measured with up to 12 sessions in flight. Use them to rank harnesses on a task, not as absolute speed.
- **One free-tier model.** These results do not carry over to other models. The price figures are assumptions, not the model's published prices.
- **Harness defaults.** Each harness ran with its own defaults, so differences include each harness's own prompts and tools.
- **Token counts** come from the provider's usage fields. Prompt tokens include cached input. Claude Code's cache reads are counted at the full input rate in the cost figures.
- **Small tasks.** T4 to T8 saturate, so this is not a general coding benchmark.
- **No quality judge.** No judged scores are reported.

## Reproduce

```bash
.venv/bin/agent-bench validate -c bench.toml
.venv/bin/agent-bench run -c bench.toml --harness pi,opencode,omp,claude --reps 6 --max-sessions 12
.venv/bin/agent-bench report runs/<stamp>
```

The task folders are not part of this repository. They can be rebuilt from the descriptions above, and `validate` confirms that each one separates starter from reference.
