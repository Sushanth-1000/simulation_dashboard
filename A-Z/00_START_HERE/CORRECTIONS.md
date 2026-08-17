# Corrections proposed — 17 August 2026

> ## Review verdict — applied 17 August 2026
>
> Every entry below was **re-verified independently** before being applied: the
> committed state was linted from a fresh `git clone`, the `lateral_noise` arm was
> re-traced per tick and per axis, the register's strike-through state was counted,
> and the recovery test's fixture thresholds were read.
>
> | # | Verdict | Note |
> |---|---|---|
> | C1 | **APPLIED WITH AMENDMENT** | Confirmed, and **understated**: four files were unformatted, not two — see *Amendment 1* |
> | C2 | **APPLIED WITH AMENDMENT** | Both days' figures kept as dated ranges. The reproducible finding is the **maximum**, not the p99 |
> | C3 | **APPLIED WITH AMENDMENT** | Attribution confirmed exactly. The proposed replacement offered a *third* causal story; the cause is now marked `[OPEN]` instead — see *Amendment 2* |
> | C4 | **APPLIED** | As a dated range |
> | C5 | **APPLIED** | Narrowed as proposed |
> | C6 | **APPLIED** | |
> | C7 | **APPLIED** | `EVIDENCE.md` edited; both rows now carry a dated correction note |
> | C8 | **APPLIED** | Sharp catch. The test asserts the formula on its own thresholds (3/10/1 → 8) and never prints 91 |
> | C9 | **REJECTED** | The register does not say what this claims — see *Rejection* below |
> | C10 | **APPLIED** | As a dated range; the criterion tests the trend |
> | C11 | **APPLIED** | Both readings kept. The newer one is larger and strengthens the argument |
>
> ### Amendment 1 — C1 understates itself, and the prompt is why
>
> `ruff format --check` on a fresh clone of `453c558` names **four** files:
> `benchmarks/arms.py`, `benchmarks/tick_latency.py`, **`A-Z/08_INTERNAL_MECHANICS/README.md`
> and `A-Z/10_MATHEMATICS/README.md`**. `ruff format` is configured to format fenced
> code blocks in markdown, and `VERIFY_PROMPT.md` told the verifier to rsync with
> `--exclude 'A-Z/'` — **so the prompt's own instruction hid half of the finding it
> exists to catch.** The prompt now has a `STEP 0b` requiring the lint stages to run
> against a fresh clone.
>
> **The root cause of the red gate is worth naming.** `ruff format` was run in the
> WSL copy, a later rsync overwrote it from Windows, WSL was formatted again,
> `make check` was run **in WSL** and passed — and the commit came **from Windows**,
> where the files had never been formatted. The green gate that was reported was
> real and was not the gate on the committed state. Fixed by running `ruff` against
> the Windows tree directly; re-verified green at 3,065 passed + 3 xfailed.
>
> ### Amendment 2 — C3's fix replaced one unmeasured cause with another
>
> The attribution is confirmed to the digit: `RATE_LIMITED` moves throttle and brake
> by **exactly 0.000000** on all 122 ticks and steering by at most 11.977 mrad;
> `throttle 0, brake 1.0` is `SPEED_CAPPED`, on ticks 351–353; **tick 351, quoted by
> name as the limiter's work, is one of them.**
>
> But the proposed replacement text asserted that *"three hard speed-cap
> interventions and the policy's own response account for"* the deceleration, and
> that is not measured either. Applied instead as `[OPEN]` with three named
> candidates — a steering axis clipped on 122 of 200 ticks (which is where the
> *first*, abandoned hypothesis started), the three speed-cap brakes, and the
> policy's own response. **This arm has now had three explanations and two
> refutations; a fourth unmeasured one was not the right fix.**
>
> ### Rejection — C9
>
> C9 claims the register is 14 closed / 3 open with `OD-10` and `OD-15` among the
> open. Counted from `CREDIBILITY_MATRIX.md`:
>
> - **Struck through (17):** OD-1, 2, 4, 5, 6, **7**, **10**, 12, 13, 14, **15**, 16,
>   17, 18, 19, 20, 21
> - **Not struck (4):** OD-3, OD-8, OD-9, OD-11
>
> That is 16 closed + OD-7 reclassified + OD-9 partly closed + three open — **exactly
> what the matrix prose says and exactly what A-Z quotes.**
>
> The error's cause is instructive. `OD-10`'s status cell *opens* with *"Open, and
> less severe than this row first said"* and *ends* with *"Closed 15 August 2026 by
> ADR-0032"*; `OD-15`'s opens *"Partly closed 11 August"*. Reading the first words of
> a long narrative cell instead of its conclusion is the same trap the prompt warns
> about, arriving from the other direction. **Applying C9 would have made A-Z less
> accurate than its own cited source.**
>
> ### One thing left for a human
>
> The `lateral_noise` behaviour still wants a register row and probably an ADR, and
> the projector design question — *should a projector prefer the axis the violated
> bound lives on?* — is a design decision. Neither a verification pass nor a review
> pass should make it.

---


Session ran **all 22** of the commands in `VERIFY_PROMPT.md`, plus three probes the
prompt asks the verifier to write. Gate: **RED** — `make check` fails at
`format-check`, the third of its eight stages, and again at `lint`. Every stage
after those two passes when run individually.

## Summary

Fifty-three quantitative claims were checked by running the code. **Forty-two
reproduced**, most of them to the last printed digit — the whole fault suite, the
whole ablation and comparison tables, `arms` to four decimals, the gate census to
the reason code, exchangeability to four decimals, whiteness digit-for-digit,
effectiveness, platform transfer, commissioning, degradation, the shadow monitor,
and every structural count. **Eleven did not.** The single most consequential finding
is that **`make check` does not pass on `HEAD`**: the two benchmarks added by the
last commit (`benchmarks/arms.py`, `benchmarks/tick_latency.py` in `83a7983`) were
never formatted or linted, so the gate stops before it runs a single test. Every
document in the folder states `quality gate: PASSED`. The second is that **the
`lateral_noise` mechanism is misattributed**: the rate limiter changes throttle and
brake by *exactly zero* on all 122 ticks it governs, and the `throttle 0, brake 1.0`
substitution the folder attributes to it belongs to the speed cap, on three ticks —
including tick 351, the tick quoted by name as the rate limiter's work. This is the
third explanation offered for that arm and the second to be refuted by measurement.

---

## Corrections

### C1 · The quality gate is red, and every document says it is green — WRONG

- **File** `A-Z/28_CURRENT_STATUS/README.md:63`
- **Says** *"**3,065 passed + 3 xfailed** in 80.15 s · `ruff` clean · `mypy --strict`
  **Success: no issues found in 169 source files** · `lint-imports`
  **12 kept, 0 broken** · coverage **97.47%**, per-file floor **every file at or
  above 80%** · `quality gate: PASSED`."*
- **Measured** `make check` **fails**, via `make check`. Stage order is
  `blobsize lockfile format-check lint typecheck contracts test coverage-floor`;
  it stops at `format-check` with *"2 files would be reformatted, 265 files already
  formatted"* — `benchmarks/arms.py` and `benchmarks/tick_latency.py`. Running the
  stages individually, `make lint` then fails too: `ISC004 Unparenthesized implicit
  string concatenation` at `benchmarks/tick_latency.py:173`, *"Found 1 error."*
- **The figures themselves all reproduce**, via `make typecheck`, `make contracts`,
  `make test`, `make coverage-floor`: **3065 passed, 3 xfailed in 78.20 s** ·
  *Success: no issues found in **169** source files* · **12 kept, 0 broken** ·
  coverage **97.4685%** · *per-file coverage floor: every file at or above 80%*.
- **Class** WRONG — not staleness. The tree is clean, both files are tracked, and
  both were committed in `83a7983`, so this is the committed state of the branch.
  `ruff clean` and `quality gate: PASSED` are false today.
- **Proposed text** *"**3,065 passed + 3 xfailed** in 78.20 s · `mypy --strict`
  **Success: no issues found in 169 source files** · `lint-imports`
  **12 kept, 0 broken** · coverage **97.47%**, per-file floor **every file at or
  above 80%**. **The gate as a whole is RED**: `benchmarks/arms.py` and
  `benchmarks/tick_latency.py`, both added in `83a7983`, fail `ruff format --check`,
  and the second fails `ruff check` with `ISC004`. Every stage after the two lint
  stages passes. `quality gate: PASSED` last held on 16 August 2026, before those
  two benchmarks landed."*
- **Same correction due at** `A-Z/00_START_HERE/README.md:145`
  (*"| `make check` | **3,065 passed + 3 xfailed** in 80.15 s; `quality gate: PASSED` |"*),
  `A-Z/00_START_HERE/REPRODUCE.md:30` and its *"The last line must read
  `quality gate: PASSED`"*, and `A-Z/28_CURRENT_STATUS/README.md:17`
  (*"| **Quality gate** | **green** | 3,065 passed + 3 xfailed, re-run 16 Aug |"*).

### C2 · The unstable latency tail does not reproduce — OVERSTATED

- **File** `A-Z/19_TRADEOFFS/README.md:26`
- **Says** *"| best run | 2.246 ms | 2.768 ms | 7.676 ms | **0** / 2000 |"* and
  *"| worst run | 2.173 ms | **10.460 ms** | 46.958 ms | **31** / 2000 |"*, and at
  line 30 *"**The median is stable across every run at about 2.2 ms — a fifth of the
  budget. The tail is not stable at all.** p99 ranged 2.768–10.460 ms, and the worst
  run's p99 was *itself over budget*."*
- **Measured** ten runs of 2,000 assembled ticks — two invocations of
  `python -m benchmarks.tick_latency`, five runs each, on an idle host:

  | invocation | p50 spread | p99 spread | max spread | breaches |
  |---|---|---|---|---|
  | 1 | 2.006 – 2.030 ms | **3.322 – 3.557 ms** | 3.682 – 49.684 ms | 0 – 1 / 2000 |
  | 2 | 2.184 – 2.392 ms | **3.630 – 6.225 ms** | 8.574 – 55.302 ms | 0 – 2 / 2000 |

  **Every one of the ten p99s sat inside the 10 ms budget**, and budget breaches
  ran 0 – 2 per 2,000, never 31. The tool's own summary line reads *"Every p99 sits
  inside the budget and at least one individual tick did not."*
- **Class** OVERSTATED — the *shape* of the claim survives and the headline number
  does not. The median is stable (2.006 – 2.392 ms) and isolated maxima still reach
  40 – 55 ms, so "met at the median, missed in the tail" holds. What does not hold
  is "p99 itself over budget" and "31 ticks per 2,000": neither recurred in ten runs.
- **Proposed text** *"**The median is stable and the tail is not.** Measured over
  ten runs on 17 August: p50 2.006–2.392 ms, p99 3.322–6.225 ms — **every p99 inside
  the 10 ms budget** — with isolated maxima reaching 49.684 and 55.302 ms and
  **0–2** ticks per 2,000 over budget. *On 16 August a five-run sweep recorded p99 up
  to 10.460 ms and 31 breaches in one run; that run has not recurred and the figure
  is kept as dated history.* The limitation is unchanged and is about the maximum,
  not the p99: a tick can still take twenty times the median, and **nothing notices**."*
- **Same correction due at** `A-Z/22_LIMITATIONS/README.md:228-238` (the five-run
  table and *"p99 varies by **3.8×** and in run 4 exceeded the budget outright.
  Budget violations ranged from **0 to 31 ticks per 2,000**"*),
  `A-Z/13_TESTING_AND_VALIDATION/README.md:125` (*"max 46.9 ms"*),
  `A-Z/28_CURRENT_STATUS/README.md:239` and `A-Z/29_REMAINING_WORK/README.md:116`,
  which both still carry the **superseded single-run** *"1 tick in 2,000 over
  budget"* that the second pass had already replaced with 0–31 — these two lines
  were listed as fixed in `README.md:233` but were not changed.

### C3 · The `lateral_noise` mechanism is attributed to the wrong component — WRONG

- **File** `A-Z/22_LIMITATIONS/README.md:163`
- **Says** *"**The mechanism, measured rather than guessed.** L7b vetoes
  `LATERAL_JERK_EXCEEDS_LIMIT` on **125 of 200** post-fault ticks. ADR-0017's rate
  limiter then substitutes the largest admissible command — and the projector
  realises that as **throttle 0, brake 1.0**"*, followed by
  *"tick 351   proposed  (throttle 0.6147, brake 0.2084, steer 0.0094) / issued
  (throttle 0.0000, brake 1.0000, steer 0.0137)"* and *"**The steering axis is
  barely touched.** The jerk bound is being satisfied by *slowing down*"*.
- **Measured** by driving `benchmarks.fault_study.SCENARIOS`' `lateral_noise` arm
  (400 ticks, fault at 200, seed 20260809, `var/policy/synthetic.pt`) with an
  observer, reading `record.issued.origin` and both command vectors per tick:

  | origin | ticks | max &#124;issued − proposed&#124; throttle | brake | steer |
  |---|---|---|---|---|
  | `RATE_LIMITED` | 122 | **0.000000** | **0.000000** | 0.011977 |
  | `SPEED_CAPPED` | 3 | 0.614747 | 0.791599 | 0.004285 |
  | `PROPOSED` | 75 | 0.000000 | 0.000000 | 0.000000 |

  **The rate limiter never touches throttle or brake — the delta is exactly zero on
  all 122 ticks.** It moves the steering axis alone, by at most 11.977 mrad. The
  `throttle 0, brake 1.0` substitution occurs on **three** ticks, every one of them
  `SPEED_CAPPED` — and **tick 351, the tick quoted by name as the rate limiter's
  work, is one of the three.**
- **Class** WRONG. The surrounding figures are all correct and reproduce exactly:
  125 post-fault vetoes (126 over the run, of which 1 precedes the fault), final
  1.3073 m, peak 1.7179 m, 0 ticks outside ±1.75 m, and speed falling 12.1821 →
  4.2137 m/s. Only the causal attribution is wrong.
- **Proposed text** *"**The mechanism, measured — and this is the second
  explanation of it to be refuted by measurement.** L7b vetoes
  `LATERAL_JERK_EXCEEDS_LIMIT` on **125 of 200** post-fault ticks. ADR-0017's rate
  limiter governs **122** of them, and on every one of those it moves **the steering
  axis alone** — at most 11.977 mrad — leaving throttle and brake **bit-identical to
  the proposal**. The `throttle 0, brake 1.0` substitution belongs to the **speed
  cap**, which fires on **three** ticks:*

  ```
  tick 351   origin    SPEED_CAPPED
             proposed  (throttle 0.6147, brake 0.2084, steer 0.0094)
             issued    (throttle 0.0000, brake 1.0000, steer 0.0137)
  ```

  *So the vehicle does decelerate from 12.2 to 4.2 m/s across the burst, but not
  because the jerk limiter brakes — it does not brake at all. Three hard speed-cap
  interventions and the policy's own response to a corrupted lateral signal account
  for it. **An earlier draft said the rate limiter satisfied the lateral bound
  longitudinally. It does not; it is a steering-axis limiter.***
- **Same correction due at** `A-Z/15_EXPERIMENTS/README.md:183-193`,
  `A-Z/00_START_HERE/README.md:288-293` (*"the rate limiter substitutes **throttle 0,
  brake 1.0** — the lateral bound is being satisfied *longitudinally*, by braking"*),
  `A-Z/00_START_HERE/REPRODUCE.md:160-166`, and `VERIFY_PROMPT.md:98-102`, whose
  expected result — *"the rate limiter substituting throttle 0 / brake 1.0"* — is
  itself the error and would propagate to the next verifying session.

### C4 · The four-layer hot path p99 does not reproduce — STALE

- **File** `A-Z/22_LIMITATIONS/README.md:223`
- **Says** *"| L1+L2+L7a+L8 in isolation (`benchmarks/latency.py`) | 0.160 ms |
  **0.442 ms** | 0.984 ms |"*
- **Measured** three runs of `python benchmarks/latency.py`: hot-path p50
  0.144 / 0.170 / 0.166 ms, **p99 0.245 / 0.222 / 0.207 ms**, max 0.513 / 0.573 /
  0.474 ms. The documented p99 is roughly **twice** every value measured, and the
  documented max is above all three.
- **Class** STALE — a host-variable software timing figure, measured on a different
  day. The claim it supports (the four-layer path is far cheaper than the full tick)
  is strengthened, not weakened.
- **Proposed text** *"| L1+L2+L7a+L8 in isolation (`benchmarks/latency.py`) |
  0.144–0.170 ms | **0.207–0.245 ms** | 0.474–0.573 ms | *(three runs, 17 Aug;
  0.442 ms p99 recorded 16 Aug)* |"*
- **Same correction due at** `A-Z/25_FAQ/README.md:222`,
  `A-Z/29_REMAINING_WORK/README.md:111`, `A-Z/00_START_HERE/README.md:155`,
  `A-Z/00_START_HERE/REPRODUCE.md:175`.

### C5 · `envelope` no longer refuses every log in `var/` — STALE

- **File** `A-Z/00_START_HERE/REPRODUCE.md:287`
- **Says** *"**It refuses every log in `var/`.** All retained logs are audit
  **schema v1** and it requires **v7 or later**"*
- **Measured** every retained log's first record, and `envelope` against three of
  them:

  | log | schema |
  |---|---|
  | `var/soak/coldpath-open`, `coldpath-tunnel`, `learned-100k`, `placeholder-100k` | v1 |
  | `var/soak/final-100k`, `thresholds-100k` | v2 |
  | **`var/soak/verify-100k`, `verify-20k`, `verify`** | **v10** |

  `python -m benchmarks.envelope var/soak/verify-100k/audit/run-closedloop0001/events.jsonl`
  **runs** and reports *"No exploration episodes in this log."* The v1 logs are
  still refused, with the documented message.
- **Class** STALE — the two `verify-*` logs were written by the 16 August
  verification session's own soak runs, under schema 10.
- **Proposed text** *"**It refuses the historical logs in `var/`,** which are audit
  schema v1 and v2 against the v7 minimum. It does **not** refuse the logs written
  since schema 10 landed: `var/soak/verify-100k`, `verify-20k` and `verify` all read
  cleanly and report *"no exploration episodes"*. The finding is narrower than it
  was and still holds where it matters — **the archive that predates the
  arbitration signature cannot be mined retrospectively**, and no amount of new
  logging fixes the old logs. See §22 `L13`."*
- **Same correction due at** `A-Z/00_START_HERE/README.md:322-323` (*"`envelope`
  runs, but **not against anything in this repository**"*) and
  `VERIFY_PROMPT.md:90-92`.

### C6 · The Executive Overview still carries the pre-correction gate figures — STALE

- **File** `A-Z/00_START_HERE/Executive_Overview.md:187`
- **Says** *"- 3,042 tests, 3 strict `xfail`, `mypy --strict` over 166 files, 12
  import contracts, 97.6% coverage with a per-file floor"*
- **Measured** **3,065** tests + 3 xfailed, **169** files, **97.47%** coverage, via
  `make test`, `make typecheck` and `make coverage-floor`.
- **Class** STALE — these are exactly the figures correction #1 of the 16 August
  pass replaced. That correction records *"Where fixed | 13, 25, 28"*; it missed the
  overview in its own directory, which is the first document the folder tells a
  reader to open.
- **Proposed text** *"- 3,065 tests, 3 strict `xfail`, `mypy --strict` over 169
  files, 12 import contracts, 97.47% coverage with a per-file floor"*
- **Note** the adjacent claim on line 190, *"164 evidence rows"*, **reproduces**:
  `EVIDENCE.md` holds 159 live rows plus the five struck-through retractions
  `E-139`–`E-142` and `E-144`, which is 164.

### C7 · `E-152` and `E-153` still cite commands that do not produce their figures — WRONG

- **File** `docs/EVIDENCE.md:264` *(outside `A-Z/`; reported, not edited)*
- **Says** `E-152` gives *"final deviation **0.1034 m → 0.0168 m**"* and cites
  **`python -m benchmarks.redundancy`**.
- **Measured** `python -m benchmarks.redundancy` prints the shadow residual monitor
  — *"drift on IMU: the faulted channel's residual left every clean channel's band
  at +41 ticks"* — and none of E-152's figures. **`python -m benchmarks.arms`** is
  the command that produces them, and it reproduces all four exactly:
  single/clean **0.1034**, single/1 m bias **0.8387**, redundant/clean **0.0168**,
  redundant/1 m bias **0.0168**, peak estimator error **1.1805 → 0.1323**.
- **`E-153` has the same defect in a different form.** It cites
  `pytest tests/integration/test_closed_loop_faults.py`, which passes (10 passed)
  but prints none of its figures — `1.1805`, `0.1323`, `0.8387` and `0.0168` appear
  in that file only as a **comment** at lines 202-206. The test asserts the
  *property* (`biased_mean - clean_mean == approx(0.0, abs=0.1)`), not the numbers.
- **Class** WRONG. This is the defect the 16 August pass found, recorded at
  `A-Z/00_START_HERE/README.md:191-196`, and **it has not been applied to
  `EVIDENCE.md`** — the folder documents the finding while the source row still
  carries the wrong command. `REPRODUCE.md:104-108` already says so.
- **Proposed text** for `E-152`'s command column: `python -m benchmarks.arms`.
  For `E-153`: `python -m benchmarks.arms` as the reproduction, keeping the pytest
  as the assertion that guards it.

### C8 · The recovery bound's cited command does not produce 91 — OVERSTATED

- **File** `A-Z/00_START_HERE/REPRODUCE.md:273`
- **Says** *"| Recovery bounded at 91 ticks = 4.6 s |
  `pytest tests/unit/test_l8_failsafe.py -k recovery_is_bounded` |"*
- **Measured** the test passes (`1 passed, 48 deselected`) but asserts
  `recovered == THETA_HALT - THETA_DEGRADED + HYSTERESIS` against its **own fixture
  thresholds**, `THETA_DEGRADED = 3`, `THETA_HALT = 10`, `HYSTERESIS = 1`
  (`tests/unit/test_l8_failsafe.py:25-55`) — a bound of **8 ticks**. The 91 comes
  from `config/environments/simulation.toml`: `ood_threshold_degraded = 10`,
  `ood_threshold_halt = 100`, so 100 − 10 + 1 = **91 ticks**, 4.55 s at 20 Hz.
- **Class** OVERSTATED — the number is right and the command does not produce it.
  The test asserts the *formula*; the deployment config supplies the values.
  `A-Z/13_TESTING_AND_VALIDATION/README.md:113` already states this correctly
  (*"Derived from the counter's ceiling"*), as does
  `A-Z/08_INTERNAL_MECHANICS/README.md:165`.
- **Proposed text** *"| Recovery bounded at 91 ticks = 4.6 s | **Derived**, not
  printed: `θ_halt − θ_degraded + hysteresis` = 100 − 10 + 1 from
  `config/environments/simulation.toml`, at 20 Hz. The *property* that the bound
  exists and equals that expression is asserted by
  `pytest tests/unit/test_l8_failsafe.py -k recovery_is_bounded`, on its own
  thresholds |"*
- **Same correction due at** `VERIFY_PROMPT.md:163` (*"asserted by a passing test"*).

### C9 · The register's status counts do not match the register — STALE

- **File** `A-Z/00_START_HERE/VERIFY_PROMPT.md:169`
- **Says** *"21 register rows (16 closed, 1 reclassified, 1 partly closed, 3 open)"*
- **Measured** 21 rows (`OD-1` … `OD-21`) in `docs/CREDIBILITY_MATRIX.md`, which is
  right, but the status column reads: **14 `Closed`** (OD-1, 2, 4, 5, 6, 12, 13, 14,
  16, 17, 18, 19, 20, 21) · **1 `Half closed`** (OD-3) · **1 `Still open`** (OD-8) ·
  **1 `Reclassified`** (OD-7) · **1 `Partly closed`** (OD-9) · **3 `Open`** (OD-10,
  OD-11, OD-15).
- **Class** STALE — the row count is correct; the breakdown collapses four distinct
  states into two.
- **Proposed text** *"21 register rows — 14 closed, 1 half closed, 1 partly closed,
  1 reclassified, 1 still open and 3 open"*
- **Same correction due at** `A-Z/02_PROJECT_HISTORY/README.md:242`, which reads
  *"closed, 3 open. 34 ADRs. 3,065 tests. 164 evidence rows."* — the ADR, test and
  evidence counts there all reproduce.

### C10 · The soak's timing and memory figures moved — STALE

- **File** `A-Z/00_START_HERE/REPRODUCE.md:193`
- **Says** *"All ten criteria pass, verdict **STABLE**: deviation 0.0285 → 0.0287 m,
  resident **+0.1 MiB**, `PROPOSED` on 99,958 ticks, per-tick p99 8.599 → 7.757 ms"*
- **Measured** via `python -m benchmarks.soak -n 100000 -o var/soak/verify`: all ten
  criteria pass, **verdict STABLE** ✓, deviation **0.0285 → 0.0287 m** ✓ (exact),
  **`PROPOSED` on 99,958 ticks** ✓ (exact), resident **+0.2 MiB** peak, per-tick p99
  **10.589 → 7.582 ms**.
- **Class** STALE — two of the four figures reproduce to the digit; the two
  host-variable ones moved. The criterion is a **trend** (×0.72 against a ×1.5
  budget), not an absolute, so the verdict is unaffected.
- **Proposed text** *"All ten criteria pass, verdict **STABLE**: deviation
  0.0285 → 0.0287 m, resident **+0.2 MiB**, `PROPOSED` on 99,958 ticks, per-tick p99
  **10.589 → 7.582 ms** (×0.72 against a ×1.5 budget). *16 August recorded
  8.599 → 7.757 ms and +0.1 MiB; the absolute p99 is host-variable and the trend is
  what the criterion tests.*"*

### C11 · The contention slowdown is larger than recorded — STALE

- **File** `A-Z/00_START_HERE/README.md:311`
- **Says** *"The full suite takes a median of **238.8 s under contention against
  90.81 s clean** — a 2.6× slowdown."*
- **Measured** via `python -m benchmarks.flake_hunt --repeats 6 --focus-repeats 15`:
  6/6 full-suite passes under `stress-ng` with **32 workers on 16 cores**, wall
  clock **min 249.2 s, median 276.2 s, max 307.0 s**; threaded tests 15/15, median
  3.8 s. Clean baseline this session was **78.20 s** (`make test`). That is a
  **3.5× slowdown**, not 2.6×.
- **Class** STALE — the verdict and both pass counts reproduce exactly; only the
  wall-clock figures moved, and they moved in the direction that makes the
  surrounding argument stronger.
- **Proposed text** *"The full suite takes a median of **276.2 s under contention
  against 78.2 s clean** — a **3.5×** slowdown (min 249.2 s, max 307.0 s; 238.8 s
  against 90.81 s on 16 August). The latency figures in this folder were measured on
  an *idle* machine, and nothing here establishes what the tick tail does under
  load."*
- **Same correction due at** `VERIFY_PROMPT.md:161-162`.

---

## Code defects

**Do not fix these in a verification session.** Recorded for a separate change.

1. **`benchmarks/arms.py` and `benchmarks/tick_latency.py` break the quality gate.**
   Both fail `ruff format --check`; `benchmarks/tick_latency.py:173` also fails
   `ruff check` with `ISC004 Unparenthesized implicit string concatenation in
   collection`. Both were committed in `83a7983` — the commit whose message is
   *"Make every headline number reproducible"* — and the tree is otherwise clean, so
   the branch has been red since that commit. The two files are exactly the two new
   tools the last pass added to make its numbers reproducible; they were run but the
   gate was not.

2. **`VERIFY_PROMPT.md` carries a wrong expected value into the next session.** Its
   *"THE ONE THING NO BENCHMARK PRINTS"* section tells the verifier to expect *"the
   rate limiter substituting throttle 0 / brake 1.0"*. That is the error corrected in
   C3. A prompt that states the expected answer will tend to get it confirmed, which
   is the failure mode the propose-don't-edit rule exists to prevent — and it did
   not prevent this one, because the wrong value is in the prompt rather than in the
   document under test.

---

## Reproduced exactly

Listed so this pass is auditable in both directions.

**The gate's own figures** (`make test`, `make typecheck`, `make contracts`,
`make coverage-floor`) — 3,065 passed + 3 xfailed · `mypy --strict` over **169**
source files · **12 kept, 0 broken** · coverage **97.4685%** · per-file floor
*every file at or above 80%*. Only the gate's *verdict* fails; see C1.

**`make artifacts-check`** — *"twin, corpus and policy present; the vehicle drives"*.

**`gate_census`** — `STATISTICAL` 2800/0/0 · `PHYSICAL` 2651/**149**/0, all
`LATERAL_JERK_EXCEEDS_LIMIT` · `DETERMINISTIC` 2800/0/0, and **zero abstentions on
all three**.

**`exchangeability`** — `URBAN_CLEAR` live **3.3648 – 3.4083** against corpus
**3.8758 – 5.4312**, **0.0% inside**, `NO OVERLAP`; `DEGRADED_SENSOR` reported
`n=1 — too few to judge`. To four decimals.

**`fault_study`** — every cell. control **0.017** · `imu_dropout` **0.062**
(`DEGRADED +5`, `LIMP +15`, **HALT never**, peak φ **40**) · `position_bias`
**0.017** · `position_drift` **0.017** · `speed_stuck` **0.024** · `speed_bias`
**0.059** · `lateral_noise` **1.307 m with 126 vetoes**. Shadow detectors:
innovation **silent on all seven arms**, `trust` raising a **FALSE ALARM on the
control**.

**`ablation`** — `L6 off` and `L7a off` **bit-identical to governed in every cell**
of both tables; `L7b off` zeroes every veto and takes `lateral_noise` from
**1.307 m to 0.138 m**.

**`comparison`** — ASTRA better on every fault except `lateral_noise`, where
ungoverned Core-A is **0.148 m** against ASTRA's **1.307 m**; `imu_dropout`
**0.062 m against 1.707 m**; `position_drift` 0.017 against **2.001 m**, 27 ticks out.

**`arms`** — single/clean **0.1034** · single/1 m bias **0.8387** · redundant/clean
**0.0168** · redundant/1 m bias **0.0168**; peak estimator error **1.1805 → 0.1323**;
verdict **INDISTINGUISHABLE**. The strongest claim in the folder, to four decimals.

**`redundancy`** — faulted channel leaves every clean band at **+41** (IMU) and
**+28** (GPS) ticks.

**`whiteness`** — `position_drift` does **not** alarm and is identical to the
control on **every printed digit** (`+0.005 / 3.35`, `+0.181 / 3.18`,
`−0.099 / 3.75`); `imu_dropout` **41 live ticks**, lateral-acceleration CUSUM
**77.63**, alarm `+2`; `lateral_noise` **888.92**, alarm `+1`.

**`whiteness --sweep`** — nine slack values, separation ratio **1.00× at every
one**, `no` throughout. `E-143`'s 1.03× is now exactly 1.00×.

**`effectiveness`** — from estimate **117.929** (true 112) and **164.443**
(true 168); from sensor **114.986** and **167.702**. `E-63`'s *"140.000 on every
platform"* **does not reproduce**, confirming the second pass's finding.

**`degradation`** — 5 modalities, all critical, all HALT at φ **40**, **no INERT row**.

**`platform_transfer`** — **no platform HALTs**; `sharp_steer` ends **53.756 m** off
at **LIMP**.

**`commissioning`** — only `urban_clear` **CERTIFIED**; `highway_clear`,
`rain_night`, `degraded_sensor`, `tunnel` all **BOUNDED**.

**`soak -n 100000`** — all ten criteria pass, **STABLE**; deviation
**0.0285 → 0.0287 m** and **`PROPOSED` on 99,958 ticks** both exact. (Two figures
moved; C10.)

**`flake_hunt`** — **6/6** full-suite and **15/15** threaded passes under
`stress-ng` with **32 workers on 16 cores**; verdict **NO FLAKE OBSERVED**, with the
tool stating its own limit correctly as *absence of evidence over this many runs,
not proof of absence*. Three outcomes are counted, not two: no `hang` occurred.
(The wall-clock figures moved; C11.)

**The two cited test runs** — `tests/integration/test_closed_loop_faults.py`
**10 passed**; `test_l8_failsafe.py -k recovery_is_bounded` **passed**.

**Structural claims, read rather than run** — `ProposalWriter`
(`src/astra/runtime/channels.py:80`) has `send` and a `pending` property and **no
read method**, with the docstring stating the absence is the enforcement of SI-5 ·
`Verdict.merge` (`src/astra/kernel/enums.py:185`) strips abstentions **before** the
fold, so all-abstain ⇒ **VETO** as well as empty ⇒ VETO · `AUDIT_SCHEMA_VERSION`
(`src/astra/kernel/constants.py:139`) = **10** · **3** strict xfails in
`tests/architecture/test_domain_independence.py`.

**Counts** — **34** ADRs · **10** SIs (SI-1 … SI-10) · **10** assumptions
(A-1 … A-10) · **30** credibility rows (7+6+4+10+3), **[M-ext] 0 of 30** ·
**164** evidence rows · **21** register rows. (The register's *status breakdown*
does not match; C9.)

**The `lateral_noise` figures** — 125 post-fault vetoes (126 over the run, 1 before
the fault) · final **1.3073 m** · peak **1.7179 m** · **0** ticks outside ±1.75 m ·
speed **12.1821 → 4.2137 m/s** · origins `RATE_LIMITED` **122**, `PROPOSED` 75,
`SPEED_CAPPED` 3. (Only the mechanism's attribution is wrong; C3.)

---

## Not verified this pass

- **`benchmarks.detectors`** — has no `main`; it is a library, and its output is the
  shadow-detector table inside `fault_study`, which was run and reproduced.
- **Historical figures whose defect is closed and which no command can produce
  today**: OD-1's 2,883 m, OD-5's 1,508, OD-6's 99,808 / 100,000, OD-4's
  2.9 × 10⁶ m, FB2's 40%, FB3's 5.02%. Traceable to `docs/CREDIBILITY_MATRIX.md` and
  **history, not current behaviour**.
- **Every `[INTERPRETATION]` in the folder.** These are arguments, not measurements;
  running code says nothing about whether they are right, and they are listed here
  neither as verified nor as findings.
- **Anything about behaviour under contention.** Every timing figure above is from
  an idle host with no simulator in the loop.

**Fraction actually verified.** This pass checked **53** quantitative claims by
running code, across 21 of the folder's 31 sections. The folder contains far more
claims than that — most of §§01–12 and §§16–27 is structural exposition,
`[INTERPRETATION]`, or narrative history that no command tests. **A fair estimate is
that a little over half the folder's checkable quantitative claims were re-measured
here, and none of its arguments were.** This is not a 100% verification and should
not be recorded as one.

---

## Expected-values table

Updated to what was measured on 17 August 2026, ready to replace the table in
`VERIFY_PROMPT.md` when these corrections are applied.

```
  gate                RED -- format-check and lint fail on benchmarks/arms.py and
                      benchmarks/tick_latency.py (committed unformatted in 83a7983).
                      Every later stage passes: 3,065 passed + 3 xfailed; mypy over
                      169 files; 12 contracts, 0 broken; coverage 97.47%; per-file
                      floor green
  gate census         STATISTICAL 2800/0/0 · PHYSICAL 2651/149/0, all
                      LATERAL_JERK_EXCEEDS_LIMIT · DETERMINISTIC 2800/0/0
  exchangeability     URBAN_CLEAR live 3.3648-3.4083 vs corpus 3.8758-5.4312,
                      0.0% inside; DEGRADED_SENSOR n=1, too few to judge
  fault study         control 0.017 m · imu_dropout 0.062 m (DEGRADED +5, LIMP +15,
                      HALT never, peak phi 40) · position_bias and position_drift
                      both 0.017 m · speed_stuck 0.024 m · speed_bias 0.059 m ·
                      lateral_noise 1.307 m with 126 vetoes
  ablation            L6 off and L7a off identical to governed in every cell;
                      L7b off zeroes every veto and takes lateral_noise
                      1.307 m -> 0.138 m
  comparison          ASTRA better on every fault except lateral_noise, where
                      ungoverned Core-A is 0.148 m against ASTRA's 1.307 m
  arms                single/clean 0.1034 · single/1 m bias 0.8387 ·
                      redundant/clean 0.0168 · redundant/1 m bias 0.0168;
                      peak estimator error 1.1805 -> 0.1323; INDISTINGUISHABLE
  redundancy          faulted channel leaves every clean band at +41 (IMU) and
                      +28 (GPS) ticks
  lateral_noise       125 of 200 post-fault ticks vetoed. RATE_LIMITED governs 122
    mechanism         of them and moves the STEERING AXIS ONLY -- throttle and brake
                      deltas are exactly 0.000000, max steer delta 11.977 mrad.
                      throttle 0 / brake 1.0 belongs to SPEED_CAPPED, on 3 ticks,
                      one of which is tick 351
  whiteness           position_drift does NOT alarm and matches the control to every
                      printed digit; imu_dropout reports 41 live ticks; sweep gives
                      ratio 1.00x at all nine slack values
  effectiveness       from estimate 117.929 (true 112) and 164.443 (true 168);
                      from sensor 114.986 and 167.702. E-63's "140.000 on every
                      platform" does NOT reproduce
  degradation         5 modalities, all critical, all HALT at phi 40, no INERT row
  platform transfer   no platform HALTs; sharp_steer ends 53.756 m off at LIMP
  commissioning       only urban_clear CERTIFIED; four contexts BOUNDED
  latency subset      four-layer hot path p99 0.207-0.245 ms over three runs
                      (p50 0.144-0.170, max 0.474-0.573)
  tick_latency        over TEN runs: p50 2.006-2.392 ms; p99 3.322-6.225 ms, EVERY
                      p99 INSIDE the 10 ms budget; max 3.682-55.302 ms; 0-2 ticks
                      per 2,000 over budget. 16 Aug's p99 10.460 and 31 breaches
                      did not recur
  soak 100k           all ten criteria pass, STABLE, resident +0.2 MiB,
                      deviation 0.0285 -> 0.0287 m, PROPOSED on 99,958 ticks,
                      p99 10.589 -> 7.582 ms (x0.72 against a x1.5 budget)
  flake_hunt          6/6 full-suite and 15/15 threaded passes under stress-ng
                      with 32 workers on 16 cores; NO FLAKE OBSERVED. Full suite
                      median 276.2 s under load (min 249.2, max 307.0) against
                      78.2 s clean -- a 3.5x slowdown
  recovery bound      91 ticks = 4.6 s, DERIVED from simulation.toml (100-10+1) at
                      20 Hz. The cited test asserts the formula on its own
                      thresholds (3/10/1 -> 8), not the figure 91
  envelope            REFUSES the v1 and v2 logs; RUNS on var/soak/verify-100k,
                      verify-20k and verify, which are schema v10, reporting
                      "no exploration episodes"
  structural          ProposalWriter has send + a pending property, no read
                      method · Verdict.merge strips abstentions first, so
                      all-abstain => VETO as well as empty => VETO ·
                      AUDIT_SCHEMA_VERSION = 10 · 3 strict xfails
  counts              34 ADRs · 10 SIs · 10 assumptions · 30 credibility rows,
                      [M-ext] 0 of 30 · 164 evidence rows · 21 register rows
                      (14 closed, 1 half closed, 1 partly closed, 1 reclassified,
                      1 still open, 3 open)
```
