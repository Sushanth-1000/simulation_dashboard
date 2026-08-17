# How to reproduce every number in this folder

One row per significant result: the figure, the exact command, and what to look
for in the output. If a command here does not produce the figure beside it, that
is a defect — report it the way you would a defect in the code. That has already
happened once: `E-152` cited a command that printed a different measurement
entirely, and it stood for a day because nobody ran it.

**Before anything else**

```bash
make artifacts-check
```

Must print *"twin, corpus and policy present; the vehicle drives"*. Presence is
not the check — **driving is**. `var/` is gitignored, so a fresh clone has no
artefacts at all; run `make artifacts` if this refuses. Order is load-bearing:
the corpus is generated *through* the twin and the policy is trained against
both.

Everything below runs in WSL2 Ubuntu (`wsl -d Ubuntu`), from `~/astra`, with
`uv run` in front of each command.

---

## 1 · The quality gate

| Figure | Command |
|---|---|
| 3,065 passed + 3 xfailed · 169 files under `mypy --strict` · 12 contracts, 0 broken · 97.47% coverage, per-file floor green | `make check` |

**What to look for.** The last line must read `quality gate: PASSED`. The three
`XFAIL`s are the NFR5 walls and are *supposed* to fail — if one flips to `XPASS`
the suite goes red on purpose, which is how a fix is forced to announce itself.

Individually: `make typecheck` prints the file count, `make contracts` prints
`12 kept, 0 broken`, `make coverage-floor` prints the per-file result.

---

## 2 · Which gates actually object

| Figure | Command |
|---|---|
| `STATISTICAL` 2800/0/0 · `PHYSICAL` 2651/**149**/0 · `DETERMINISTIC` 2800/0/0 | `python -m benchmarks.gate_census` |

**What to look for.** All 149 physical vetoes carry **one** reason code,
`LATERAL_JERK_EXCEEDS_LIMIT`. `ABSTAIN` is **zero for all three** — that is the
finding, not the veto count. The two silent gates are *judging every tick and
finding nothing*, which is different from being unable to judge.

---

## 3 · The conformal precondition (OD-8)

| Figure | Command |
|---|---|
| `URBAN_CLEAR` live 3.3648–3.4083 against a corpus of 3.8758–5.4312, **0.0% inside** | `python -m benchmarks.exchangeability` |

**What to look for.** The `NO OVERLAP` marker on `URBAN_CLEAR`, and
`DEGRADED_SENSOR` reported as `n=1 — too few to judge` rather than as a
percentage. That second row is the `E-161` guard: a fraction from one sample is
not a weaker measurement, it is a different kind of thing.

---

## 4 · The fault suite

| Figure | Command |
|---|---|
| control 0.017 m · `imu_dropout` 0.062 m · `position_bias` 0.017 m · `position_drift` 0.017 m · `speed_stuck` 0.024 m · `speed_bias` 0.059 m · `lateral_noise` 1.307 m | `python -m benchmarks.fault_study` |

**What to look for, in three places.**

The **deviation table** — `position_bias` and `position_drift` are now
indistinguishable from the control. Before ADR-0033 they ended 0.931 m and
2.025 m out.

The **escalation table** — `imu_dropout` reads `DEGRADED +5, LIMP +15, HALT —,
peak phi 40`. The counter reaches its HALT threshold and the machine does **not**
enter HALT, because ADR-0030's ceiling maps a `DEGRADED` stream to a maximum
posture of `LIMP`. `E-88` recorded *"HALT at +40"* and was correct on 11 August.

The **shadow-detector table** — the innovation signal is `silent` on all seven
arms, and `trust` raises a **FALSE ALARM on the control**.

---

## 5 · Redundancy — the strongest result in the project

| Figure | Command |
|---|---|
| single/clean **0.1034 m** · single/1 m bias **0.8387 m** · redundant/clean **0.0168 m** · redundant/1 m bias **0.0168 m**; peak estimator error **1.1805 m → 0.1323 m** | `python -m benchmarks.arms` |

**What to look for.** The two redundant rows agreeing **to four decimals** — the
biased vehicle and the healthy one are indistinguishable, which is a stronger
claim than *"the error got smaller"*. The tool says `INDISTINGUISHABLE` only when
they agree and `DIFFER` when they do not; it cannot report success by default.

**Read the estimator column, not the deviation column.** A fault can leave the
deviation small while the estimate is badly wrong — that is OD-9's shape, where
the proposer closes the loop on the corrupted number and drives *it* to zero.

> **This tool exists because `E-152` and `E-153` cited
> `python -m benchmarks.redundancy`, which does not produce these figures** — it
> prints the *shadow* residual monitor, a different measurement of a mechanism
> with no authority. Found on 16 August 2026 by running the cited command and not
> recognising the output.

The shadow monitor is still worth running for its own result:

```bash
python -m benchmarks.redundancy
```

The faulted channel's residual leaves every clean channel's band at **+41 ticks**
(IMU) and **+28** (GPS). Read the *other* channels' separation too — a run where
every channel separates is detecting the manoeuvre rather than the fault.

---

## 6 · What each gate is worth

| Figure | Command |
|---|---|
| `L6 off` and `L7a off` identical to governed in **every cell**; `L7b off` zeroes every veto and takes `lateral_noise` from 1.307 m to **0.138 m** | `python -m benchmarks.ablation` |

**What to look for.** Two tables — vetoes, then deviations. The `L7b off` row in
the deviation table is the uncomfortable one.

An ablation **neutralises** a gate, it never removes one (ADR-0021), so the
disarmed gate still runs and still writes a verdict. `summary.json` has an
`ablated_passes` field that is non-zero exactly where a gate was disarmed; a zero
there would mean the ablation did not happen.

---

## 7 · Governed against ungoverned

| Figure | Command |
|---|---|
| ASTRA better on every fault except `lateral_noise` — 1.307 m against raw Core-A's **0.148 m** | `python -m benchmarks.comparison` |

**What to look for.** `imu_dropout` at 0.062 m against 1.707 m — ASTRA is now
**27× better** on the fault `E-56` originally named as the one where it was
*worse*. The claim survived and moved faults.

---

## 8 · The `lateral_noise` mechanism

No benchmark prints this; it was traced by hand and the trace is worth repeating
if the behaviour changes. The measured facts:

| | vetoes | final m/s | final \|dev\| | peak \|dev\| | outside ±1.75 m |
|---|---|---|---|---|---|
| governed | 125 | 4.214 | 1.3073 m | **1.7179 m** | **0** |
| L7b disarmed | 0 | 6.870 | 0.1384 m | 0.5854 m | 0 |

Maximum \|issued − proposed\| by issued-command origin, after the fault opens:

| origin | ticks | throttle | brake | steer |
|---|--:|--:|--:|--:|
| `RATE_LIMITED` | 122 | **0.000000** | **0.000000** | 0.011977 |
| `PROPOSED` | 75 | 0.000000 | 0.000000 | 0.000000 |
| `SPEED_CAPPED` | 3 | 0.614747 | 0.791599 | 0.004285 |

**ADR-0017's rate limiter is a steering-axis limiter** — throttle and brake are
bit-identical to the proposal on all 122 ticks it governs. `throttle 0, brake 1.0`
belongs to the **speed cap**, on ticks 351, 352 and 353 only.

**To re-derive it:** drive the `lateral_noise` scenario from
`benchmarks.fault_study.SCENARIOS` with an observer, and read
`record.issued.origin` **together with** both command vectors per tick. Reading
the largest substitution without its origin is what produced two wrong
explanations of this arm — the delta and the origin must be read together.

**What this does *not* establish** is the cause of the 1.307 m. See §22 L9:
`[OPEN]`, with three candidates and none measured.

---

## 9 · Timing

| Figure | Command |
|---|---|
| Four-layer hot path p99 **0.442 ms** | `python benchmarks/latency.py` |
| **Full assembled tick**: p50 stable at ~2.2 ms; p99 **2.768–10.460 ms** across runs; max **7.7–61.1 ms**; **0–31** ticks per 2,000 over the 10 ms budget | `python -m benchmarks.tick_latency` |

**What to look for.** The `p99 spread` and `breaches` lines. **One run is not a
tail statistic** — the first single run of this measurement reported "one tick in
2,000 over budget", which turned out to be the best of five. The tool defaults to
five runs for that reason.

Every figure here is from an **idle host** with no simulator in the loop. Under
`stress-ng` the test suite runs about 2.6× slower, and nothing establishes what
the tick tail does under contention.

---

## 10 · Long-run stability

| Figure | Command |
|---|---|
| All ten criteria pass, verdict **STABLE**: deviation 0.0285 → 0.0287 m and `PROPOSED` on 99,958 ticks *(both exact across two days)*; resident **+0.1 to +0.2 MiB**, per-tick p99 **8.599 → 7.757 ms** (16 Aug) and **10.589 → 7.582 ms** (17 Aug) — the criterion tests the **trend**, ×0.72 against a ×1.5 budget, not the absolute | `python -m benchmarks.soak -n 100000 -o var/soak/verify` |

**What to look for.** Ten `[pass]` lines and `verdict: STABLE`. The header states
the limit honestly — the plant, twin and corpus share one set of equations, so
this measures whether the loop stays stable and **never whether the gates are
right**.

Takes several minutes. `-n 20000` gives the same shape faster.

---

## 11 · Degradation, capabilities and certification

| Figure | Command |
|---|---|
| 5 modalities, all critical, all HALT at φ 40, capabilities withdrawn per modality | `python -m benchmarks.degradation` |
| Only `urban_clear` **CERTIFIED**; `highway_clear`, `rain_night`, `degraded_sensor`, `tunnel` all **BOUNDED** | `python -m benchmarks.commissioning` |
| No platform HALTs; `sharp_steer` ends **53.756 m** off at LIMP | `python -m benchmarks.platform_transfer` |

**What to look for in the degradation table:** an `INERT` row — a modality whose
loss does nothing at all. There is none today, and one appearing is the *"we
added a sensor and forgot to wire its failure response"* bug made visible.

**In the commissioning certificate:** `BOUNDED` is a weaker certificate, **not a
failure** — it is what this architecture exists to do.

**In the platform table:** `sharp_steer` "passes" because the rule tests posture,
motion and speed cap and **not lane position**. 53.756 m is thirty lane-widths.
That is either a missing exit criterion or a platform this vehicle should refuse.

---

## 12 · The drift detectors

| Figure | Command |
|---|---|
| `position_drift` does **not** alarm and matches the control to every printed digit; `imu_dropout` reports **41 live ticks** | `python -m benchmarks.whiteness` |
| Sweep across nine slack values | `python -m benchmarks.whiteness --sweep` |
| The estimator reads **117.929** and **164.443** from the filtered estimate on platforms whose true `B` is 112 and 168 | `python -m benchmarks.effectiveness` |

**What to look for in the whiteness table:** the `n = N live ticks` line under
each arm. A tick counts as live only if a command reached the actuators **and**
the vehicle was moving; an arm whose fail-safe correctly stopped the vehicle is
live before the stop and dead after it.

> This benchmark refused to run at all until 16 August 2026. Its
> `StationaryVehicleError` guard — added after the `E-143` retraction — read the
> run's *final* speed, so once ADR-0024 and ADR-0030 gave the fail-safe a stopping
> response, it began refusing a run in which the safety mechanism had **worked**.

**In the effectiveness table:** `E-63` records *"140.000 on every platform"* and
that **no longer reproduces**. The conclusion still stands on the structural
argument; the evidence for it does not. Confirmed identical over two runs.

---

## 13 · Concurrency

| Figure | Command |
|---|---|
| 6/6 full-suite and 15/15 threaded passes under `stress-ng`, 32 workers; **NO FLAKE OBSERVED**. Full suite median **238.8 s** under load against ~91 s clean | `python -m benchmarks.flake_hunt --repeats 6 --focus-repeats 15` |

**What to look for.** Three outcomes are counted, not two: `pass`, `fail` and
**`hang`**. The harness exists because a concurrency test once *hung* under
12-way load rather than failing, which is the worst failure mode a test has. A
single `hang` means the timeouts did not close the hole.

Its own verdict states the limit correctly: *absence of evidence over this many
runs, not proof of absence.*

---

## 14 · Structural claims — read, not run

| Claim | Where to look |
|---|---|
| The proposer has no way to read a verdict | `ProposalWriter` in `src/astra/runtime/channels.py` — `send` and a `pending` property, no read method |
| Empty verdict set ⇒ VETO, and **all-abstain ⇒ VETO too** | `Verdict.merge` in `src/astra/kernel/enums.py` — abstentions are stripped *before* the fold |
| Audit schema version | `AUDIT_SCHEMA_VERSION` in `src/astra/kernel/constants.py` — **10** |
| Three strict xfails, all NFR5 walls | `tests/architecture/test_domain_independence.py` |
| Recovery bounded at 91 ticks = 4.6 s | **Derived, not printed**: `θ_halt − θ_degraded + hysteresis` = 100 − 10 + 1 from `config/environments/simulation.toml`, at 20 Hz. The *property* — that the bound exists and equals that expression — is asserted by `pytest tests/unit/test_l8_failsafe.py -k recovery_is_bounded`, which runs on its own fixture thresholds (3 / 10 / 1, so a bound of 8) and never prints 91 |
| 34 ADRs · 10 SIs · 10 assumptions · 30 credibility rows · 21 register rows | `docs/adr/`, `docs/SEPARATION_INVARIANTS.md`, `docs/ASSUMPTIONS.md`, `docs/CREDIBILITY_MATRIX.md` |

---

## 15 · The evidence archive

`envelope` reads an audit log and reports where the vehicle repeatedly drove
outside anything certified:

```bash
python -m benchmarks.envelope <path-to-events.jsonl>
```

**It refuses the *historical* logs in `var/`** — schema **v1** and **v2** against
a **v7** minimum, v7 being the version that began recording the arbitration
signature (OD-14).

**It does not refuse the logs written since schema 10 landed.**
`var/soak/verify-100k`, `verify-20k` and `verify` — all produced by the
verification soak runs themselves — read cleanly and report *"no exploration
episodes"* on a clean drive. *An earlier draft of this section said it refuses
every log in `var/`; that stopped being true the moment this verification wrote
its own.*

The refusal that remains is the finding, and the third appearance of one shape:
**the archive that predates the arbitration signature cannot be mined
retrospectively, and no amount of new logging fixes the old logs.** See §22 `L13`.

---

## Two things this file cannot give you

**Historical figures whose defect is closed.** OD-1's 2,883 m, OD-5's 1,508,
OD-6's 99,808/100,000, OD-4's 2.9 × 10⁶ m, FB2's 40%, FB3's 5.02%. These are
traceable to `docs/CREDIBILITY_MATRIX.md` and are **history, not current
behaviour**. The system they describe no longer exists.

**Every `[INTERPRETATION]`.** Those are arguments. Running code says nothing
about whether they are right, and they should be argued with rather than
reproduced.

---

**Related:** [`VERIFY_PROMPT.md`](VERIFY_PROMPT.md) turns this list into a
self-contained prompt for a fresh session, with the environment quirks and the
traps that have already cost time. That session writes its findings to
`CORRECTIONS.md` and edits nothing — use this file when you want one number, and
that one when you want the whole sweep audited.
