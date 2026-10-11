# Results

Four coding-agent harnesses on the same six tasks, the same model, and each harness's own defaults. Date: 2026-10-11.

## Setup

- **Harnesses:** Pi 1.1.0, OpenCode 1.18.32, omp 18.8.6, Claude Code 2.1.220 (the installed CLI versions).
- **Model:** `longcat-2.5-preview-free` (free tier), reached through one OpenAI-compatible gateway. Claude Code used the gateway's Anthropic-compatible route.
- **Sampling:** each harness's defaults. A probe on the wire confirmed that none of the four sent `temperature` or `top_p` in these runs.
- **Tasks:** six Python tasks, T4 to T9.
  - T4: expression evaluator with precedence, associativity, unary minus, and error cases.
  - T5: TTL cache with LRU eviction and an exact expiry boundary.
  - T6: CSV field parser and per-name totals report.
  - T7: invoice totals across several modules, with rounding and currency conversion.
  - T8: cron next-fire parser with steps, ranges, and day-of-month/day-of-week rules.
  - T9: line diff with a minimal edit script and unified hunks.
  - Each task has starter code, a test file the agent can see, and a reference solution. The tests fail on the starter and pass on the reference.
- **Grading:** pytest in the workspace after the tests are restored. A run passes if every test passes. Tampering with tests is recorded; none was detected.
- **Protocol:** each run has a fresh workspace, a private HOME, its own logging proxy, and a sandbox whose only network path is that proxy. Up to 12 sessions ran at once across all harnesses. The time limit was 1500 s per run.
- **Data sets:**
  - *Matrix:* 72 runs, 6 tasks × 4 harnesses × 3 repetitions.
  - *Retry:* 45 runs, 3 more repetitions for the 15 cells that had a failure or a large timing spread in the matrix.

## Headline

- **T4 to T8 do not separate the harnesses.** Every valid run passed.
- **T9 is the only task that separates them.** Claude Code passed 1 of 6, Pi 3 of 6, OpenCode 5 of 6, and omp 4 of 4.
- **The matrix's omp failures were infrastructure crashes, not agent failures.** An earlier report of mine said they were real rounding and cron-parsing bugs. That was wrong, and the correction is below.

## Pass rates

Valid runs only. Infrastructure crashes (see below) are excluded; the retry columns are separate samples.

| Task | Claude Code | omp | OpenCode | Pi |
|---|---|---|---|---|
| T4 | 6/6 | 5/5 | 3/3 | 6/6 |
| T5 | 3/3 | 5/5 | 3/3 | 3/3 |
| T6 | 6/6 | 5/5 | 3/3 | 6/6 |
| T7 | 6/6 | 4/4 | 3/3 | 3/3 |
| T8 | 3/3 | 4/4 | 3/3 | 6/6 |
| T9 | 1/6 | 4/4 | 5/6 | 3/6 |

## Time and tokens

Matrix runs, valid only, 3 repetitions per cell. Wall time was measured at 12 concurrent sessions, so it includes contention.

| Task | Harness | Valid runs | Mean wall s | Mean prompt tok | Mean completion tok | Mean requests |
|---|---|---|---|---|---|---|
| T4 | Claude Code | 3 | 156 | 181,161 | 6,710 | 8.3 |
| T4 | omp | 2 | 162 | 121,164 | 5,883 | 10.5 |
| T4 | OpenCode | 3 | 117 | 54,665 | 5,550 | 6.7 |
| T4 | Pi | 3 | 170 | 46,874 | 7,342 | 8.3 |
| T5 | Claude Code | 3 | 86 | 157,753 | 3,541 | 7.7 |
| T5 | omp | 2 | 84 | 64,236 | 2,085 | 7.5 |
| T5 | OpenCode | 3 | 64 | 64,163 | 2,059 | 8.3 |
| T5 | Pi | 3 | 107 | 20,898 | 4,675 | 5.7 |
| T6 | Claude Code | 3 | 453 | 368,299 | 19,414 | 12.7 |
| T6 | omp | 2 | 107 | 56,134 | 3,364 | 6.0 |
| T6 | OpenCode | 3 | 71 | 63,853 | 2,820 | 8.0 |
| T6 | Pi | 3 | 196 | 30,672 | 8,737 | 8.3 |
| T7 | Claude Code | 3 | 461 | 265,291 | 22,540 | 9.7 |
| T7 | omp | 1 | 64 | 86,024 | 1,632 | 10.0 |
| T7 | OpenCode | 3 | 188 | 94,788 | 8,462 | 9.0 |
| T7 | Pi | 3 | 501 | 112,952 | 24,335 | 12.0 |
| T8 | Claude Code | 3 | 326 | 249,172 | 15,986 | 9.3 |
| T8 | omp | 1 | 198 | 79,841 | 9,346 | 7.0 |
| T8 | OpenCode | 3 | 114 | 58,698 | 5,104 | 7.0 |
| T8 | Pi | 3 | 222 | 55,943 | 9,548 | 8.0 |
| T9 | Claude Code | 3 | 1,500 | 140,677 | 104,282 | 8.0 |
| T9 | omp | 1 | 622 | 220,502 | 30,881 | 10.0 |
| T9 | OpenCode | 3 | 1,091 | 74,263 | 53,825 | 8.0 |
| T9 | Pi | 3 | 514 | 54,756 | 27,244 | 7.0 |

Averages across all tasks by harness (valid matrix runs): Claude Code 497 s, 227K prompt tokens, 28.7K completion tokens; OpenCode 274 s, 68K, 13.0K; Pi 285 s, 54K, 13.6K; omp 177 s, 97K, 7.2K. These averages mix different task sets, because omp has one valid run each for T7 to T9. Compare per task instead.

## Failures

- **Claude Code, T9:** 3 timeouts in the matrix and 2 in the retry, all at the 1500 s limit. These runs were still making requests (7 to 9 per run), so they were slow rather than stuck.
- **Pi, T9:** 2 matrix failures and 1 retry failure. Each run ended with 4 tests failing after about 4 requests, and none timed out. I have not investigated the cause.
- **OpenCode, T9:** 1 timeout in the matrix. Its retry runs all passed.
- **omp, 9 matrix runs:** all failed at startup, before making any model request. The native addon could not be extracted because the temporary filesystem was full (`EDQUOT`). These runs are excluded from the pass rates above. All 15 omp retry runs passed. The runs now write to the work disk, so this failure should not recur.

## Corrections

- I earlier said omp's T7 and T8 failures were a real rounding bug and a cron comma-list bug. That was wrong. Those messages came from the crashed runs, where the agent never ran and the untouched starter code was tested. Every omp run that reached the provider passed.

## Limits

- **Three repetitions per cell.** A pass rate can only be 0, 1, 2, or 3 out of 3, so one run moves a rate by a third.
- **Wall times are contended.** They were measured with up to 12 sessions in flight. Use them to rank harnesses on a task, not as absolute speed.
- **One free-tier model.** These results do not carry over to other models.
- **Harness defaults.** Each harness ran with its own defaults, so differences include each harness's own prompts and tools.
- **Token counts** come from the provider's usage fields. Prompt tokens include cached input. Claude Code's cache reads are counted. The accounting was checked against the provider's raw usage on one request.
- **Small tasks.** T4 to T8 saturate, so this is not a general coding benchmark.
- **Mixed tool versions.** The matrix ran before the kill and resource-measurement features, and the retry ran before the viewer and settings changes. Resource figures are not part of these results.
- **No quality judge.** No judged scores are reported.

## Reproduce

```bash
.venv/bin/agent-bench validate -c bench.toml
.venv/bin/agent-bench run -c bench.toml --harness pi,opencode,omp,claude --reps 3 --max-sessions 12
.venv/bin/agent-bench report runs/<stamp>
```

The task folders for T4 to T9 are not part of this repository. They can be rebuilt from the descriptions above, and `validate` confirms that each one separates starter from reference.
