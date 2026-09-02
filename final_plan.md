# final_plan.md — one week to a resubmittable manuscript

**Written** 31 August 2026
**Baseline** `3cda553` on `phase4-l5-twin-l7b-physical`
**Trigger** Q2 referee report on `ASTRA_Paper_v21`: **D — Reject and Resubmit**, 43/100.
**Goal of this week** Move the decision from *Reject and Resubmit* to *Major Revision* at a Q2
venue. Q1 is **not** reachable in a week and this plan does not pretend otherwise; §9 says why.

---

## 0 · Read this before anything else

### 0.1 · The cores and layers are already wired

The request that started this plan was "wire all the cores and the layers". They are wired.
`A-Z/28_CURRENT_STATUS` §28.2 records all nine layers as built, Core-A and Core-B are connected
through the one-way channel, and N-7 records **FB1 and FB4 as wired**.

What is unwired is **FB2** (twin adaptation) and **FB3** (trust recalibration). They have no callers
anywhere in `src/`, `training/` or `benchmarks/`:

```bash
grep -rn "\.consolidate(\|\.recalibrate(" src/ training/ benchmarks/   # returns nothing
```

### 0.2 · Wiring FB2 and FB3 as they stand would break the gates they feed

This is the part that conflicts with "follow the credibility matrix", so it is stated plainly.

| Loop | Measured in shadow | Consequence of wiring today |
|---|---|---|
| **FB2** | E-39: score against an FB2-adapted twin falls **1.1534 → 0.6962** over 100,000 ticks in one unchanging context, while the live score stays flat 1.1564 → 1.1560 | The statistical gate is disarmed. The monitor learns to agree with the component it monitors |
| **FB3** | E-40: veto rate converges to **5.02%** — `significance_epsilon` exactly | The gate stops being a detector and becomes a fixed-rate sampler |

`src/astra/layers/l3_trust/trust.py:219` says it in the source: *"It caused no harm because FB3 has
never been wired. It would have caused a great deal on the day it was."* The same docstring records
the root cause: the method writes gate-scale values (1.155–1.191) into a distribution of innovation
magnitudes (0.518–7.497 clear, 7.549–154.8 degraded), re-merging what P2.5 deliberately separated.

**The project rule these two failed is `no mechanism is given authority over a verdict until it has
run in shadow with none`.** Connecting them now would break that rule, contradict E-39 and E-40, and
invalidate §5.6 of the manuscript, which reports them as correctly withheld.

Day 5 therefore does the *useful* version of this request: fix the root causes, re-measure in
shadow, and wire **only if the shadow measurement changes**. If it does not change, the loops stay
out and the paper's §5.6 stands.

### 0.3 · The one thing that could invalidate the headline

`E-52` says the vehicle *"first crosses the ±1.75 m corridor at **+73**"*.
`E-46`, the row that produced the 4.199 m figure, says *"truth outside the ±1.75 m corridor on
**73 ticks**"* — a **count**, not a timestamp.

Both cannot be right. Over a 400-step run with the fault opening at step 200, a first crossing at
+73 that never recovers means ~127 ticks outside, not 73. **If E-52 read a count as a timestamp, the
68-step margin — the paper's single most-emphasised number — is wrong.** Day 1 settles this before
any other work is done.

---

## 1 · What the referee requires, and what each item costs

| # | Referee requirement | Needs a run? | Day |
|:--:|---|:--:|:--:|
| 1 | Multiple seeds and realizations | yes | 3 |
| 2 | Re-measure the flagship margin within one configuration (**C2**) | yes | 2 |
| 3 | Explain the 4.199 m > 1.707 m anomaly (**M1**) | no | 6 |
| 4 | Disclose seeds, thresholds, hyperparameters | no | 4 |
| 5 | Show the §5.8 refutations (**M4**) | maybe | 4 |
| 6 | Reconcile RQ1 wording with the trust-index result (**M3**) | no | 6 |
| 7 | External data, or an explicit narrow reframe | out of scope / reframe | 7 |
| 8 | m1–m5 and "ten constraints vs twelve contracts" | no | 6 |
| — | **+73 provenance** (found during review response, not in the report) | yes | 1 |

Four of the nine need the benchmark suite to execute. That is what Day 0 is for.

---

## 2 · Day 0 (half day) — make the benchmarks runnable

Nothing in Days 1–3 is possible until `astra` imports. There is currently no virtual environment in
the tree and the default interpreter is Python 3.14, for which the ML extras may have no wheels.
Python 3.12 — the project's declared floor and the version the manuscript reports — is installed.

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/pip install -e ".[estimation,learning]"
.venv/Scripts/python -c "import astra, numpy, torch; print('ok')"
```

Then confirm the tree is green before changing anything, so that every later measurement has a
known-good starting point:

```bash
.venv/Scripts/python -m pytest -q          # expect 3,065 passed + 3 xfailed
make check                                 # full gate as CI runs it
```

**Exit criterion.** `astra` imports, the suite is green, and `python -m benchmarks.fault_study`
produces output.

**If the install fails.** Fall back to Days 4, 6 and 7 only — the five text-only items. Say so in
the cover letter rather than leaving items 1 and 2 silently unaddressed.

---

## 3 · Day 1 — settle the +73 provenance

The highest-value hour of the week. Everything downstream of the headline depends on it.

```bash
.venv/Scripts/python -m benchmarks.fault_study --scenario imu_dropout --output var/paper/d1
```

From the per-step record, extract two distinct quantities and label them separately:

1. **First crossing step** — the first control step at which `|true lateral deviation| > 1.75`.
2. **Total steps outside** — the count of steps satisfying that predicate.

**Then:**

- If first crossing is at **+73** → E-52 is correct, the 68-step margin stands, record the count
  separately so the two are never confused again.
- If the count is 73 and the first crossing is elsewhere → **E-52 is wrong**. Correct the evidence
  log, recompute the margin, and update the abstract, §5.2, Figure 3, the discussion and the
  conclusion with the true figure. Do not preserve 68 steps if the measurement does not support it.

**Deliverable.** A new evidence row recording both quantities, and a decision on whether the
manuscript's headline number survives.

---

## 4 · Day 2 — the flagship margin inside one build (referee item 2, C2)

The referee's sharpest methodological finding: `+5` is measured on the current build, `+73` on a
9 August build. The margin subtracts an event in one software version from an event in another.

**The clean experiment.** Disable the health path on the *current* build and measure the corridor
crossing there. One variable, one configuration, current code.

```bash
.venv/Scripts/python -m benchmarks.fault_study \
    --scenario imu_dropout --disable-health-path --output var/paper/d2-nohealth
.venv/Scripts/python -m benchmarks.fault_study \
    --scenario imu_dropout --output var/paper/d2-health
```

If no such flag exists, add one. It must disable **only** the L1→L8 health path, leaving redundancy,
the estimator and all three gates untouched — otherwise it reproduces the C2 defect in a new form.

**Deliverable.** A single-configuration margin. Report it as the headline and demote the
cross-build 4.199 m figure to a historical note. If the within-build margin is smaller, **report the
smaller number.**

---

## 5 · Day 3 — seeds (referee item 1)

The referee: *"Without this, the observability framing has no empirical support beyond an anecdote."*

```bash
for s in $(seq 1 30); do
  .venv/Scripts/python -m benchmarks.fault_study --seed $s --output var/paper/seeds/$s
done
```

Then rewrite Table 3 as **median [Q1, Q3] over 30 seeds** for every scenario.

**Rules for this table.**

- Report medians and interquartile ranges. **No** means, standard deviations, p-values, confidence
  intervals or significance tests — the referee praised the paper for refusing these and §13 of the
  report says keep that discipline.
- The lateral-noise degradation **must survive into the multi-seed table**. If it appears in some
  seeds and not others, that is a finding: report the proportion.
- If a headline result does not hold across seeds, **the headline changes.** That is the point of
  running them.

**Deliverable.** Table 3 with dispersion; §4's statistical-status paragraph rewritten from
"single deterministic realization" to what was actually run.

---

## 6 · Day 4 — reproducibility and the missing refutations (items 4, 5)

### 6.1 · Parameter appendix (item 4)

The referee calls the current position disqualifying: a single-seed result whose seed is not
disclosed cannot be reproduced even in principle. Extract from `config/`, the ADRs and
`src/astra/invariants/catalogue.py`:

- every gate threshold — ε, the L7a bounds on speed, lateral acceleration, friction margin and
  lateral position, the L7b jerk limit
- the fail-safe counters θ₁, θ₂, θ_halt and the per-modality decay
- the UKF process and measurement noise, and the three channel sigmas
- the PPO hyperparameters, reward and constraint budgets
- **the seed values behind every reported number**

Add as an appendix. This is compatible with withholding the source: parameters are not code.

### 6.2 · The §5.8 refutations (item 5)

The manuscript says two explanations of the lateral-noise degradation "were refuted by measurement"
without showing the measurement. Search the evidence log:

```bash
grep -n "lateral_noise" docs/EVIDENCE.md docs/DECISION_LOG.md
```

- If the refutations are recorded → write them into §5.8 with their numbers.
- If they are not → **delete the claim.** "Refuted by measurement" without the measurement is
  exactly the assertion-without-evidence pattern the rest of the paper avoids.

---

## 7 · Day 5 — FB2 and FB3, done properly

Not "wire them". The honest sequence:

**7.1 · Fix FB3's root cause.** `trust.py:219` documents it: the method is pointed at L3's
distribution while documenting L6's statistic, so wiring it would pour gate-scale values into a
distribution of innovation magnitudes. Fix the target, or split the method in two.

**7.2 · Fix FB2's root cause.** Its only training labels are the proposer's own commands
(`_consolidate`'s data term is `MSE(predicted, applied)`), which is why the score collapses by
construction. `train_twin.py` labels from physics instead. Either label FB2 from physics too, or
accept that FB2 cannot be safely wired.

**7.3 · Re-measure in shadow.** Same protocol as E-39 and E-40, 100,000 ticks, changing no verdict.

**7.4 · Decide on evidence.**

- Shadow behaviour now flat → wire, and record the fix and the new measurement.
- Shadow behaviour still degrades → **leave them out.** Record the second refutation. §5.6 of the
  manuscript becomes stronger, not weaker: a mechanism that fails a shadow test twice, after a
  targeted fix, is a better result than one that fails once.

**Do not wire on schedule pressure.** The rule that caught these two is the most defensible piece of
methodology in the paper.

---

## 8 · Day 6 — manuscript edits (items 3, 6, 8)

All text, no runs.

**8.1 · Item 3 — the 4.199 > 1.707 anomaly.** The answer is already established: E-46 is 9 August on
a **single-channel** build; ADR-0033 made three-channel median fusion the driven path afterwards. The
1.707 m ungoverned run has redundancy the 4.199 m run never had. It is not governance underperforming
no governance — it is two sensing architectures. Add to §5.2 and flag it in Table 3's caption.

**8.2 · Item 6 — RQ1 wording.** RQ1 asks about *downstream monitors*; the trust index is a downstream
monitor and it detected the dropout. Restate RQ1 in terms of **the mechanisms with veto authority**,
and state the gate-versus-shadow-signal distinction inside the RQ rather than only in §5.2.

**8.3 · Item 8 — the minor set.**

| Ref | Fix |
|---|---|
| m1 | 1.1534 vs 1.1564 are the *live* and *shadow* twin starting scores and are genuinely different — say so in Table 7's caption |
| m2 | 4.97% and 5.02% are two sample estimates either side of ε = 0.05; state that rather than calling them equal |
| m3 | The **ten separation invariants** (SI-1…SI-10) and the **twelve import-linter contracts** are different objects. The manuscript never says so. One sentence in §3.2 |
| m4 | Grammatical slip on p. 9: "because of the two downstream candidates matched it exactly" — insert "one" |
| m5 | Add the `+40` posture marker to Figure 3, or state in the caption why it is absent |

---

## 9 · Day 7 — scope decision, then final QC (item 7)

### 9.1 · The decision this week cannot avoid

The referee offers two routes and this week can only take the second:

- **Route A — external validation.** comma2k19 or CARLA. Two to three weeks minimum, and Day 0's
  environment work is a prerequisite. **Not achievable this week.**
- **Route B — narrow the scope explicitly.** Reframe as a single-environment methodology and
  negative-results study, and retitle to match. Achievable in a day.

**Take Route B this week and start Route A next week.** They are not exclusive: Route B is the
submittable paper now, Route A is what makes the *next* one Q1-eligible.

### 9.2 · The reframe that raises novelty

Novelty scored **3/10** because the paper disclaims new mechanisms. More seeds do not fix that. What
does is foregrounding the contribution currently buried in §5.4 and §5.6 — **four measurement
instruments, each of which found a real defect:**

1. **Shadow evaluation before wiring** — caught FB2's 40% collapse and FB3's convergence to ε
2. **Positive-control ablation** — the ablated-pass column, 0/2,800 against 2,800/2,800
3. **Measuring the conformal precondition** instead of assuming it — caught the zero-overlap
   separation
4. **Per-intervention against per-tick rates** — 4.97% versus 0.008%, differing by ~600×

Each is generalisable past this system, each is a positive result, and each is already supported by
data in hand. That is a stronger novelty claim than "placement matters", and it does not depend on
the single-seed evidence base.

### 9.3 · Final QC

Re-run the 25-point submission check on the manuscript, plus:

- [ ] every number in the paper traces to an evidence row **from the current build**
- [ ] no figure mixes configurations without saying so
- [ ] the lateral-noise degradation and the 0/0/149 ablation are still visible
- [ ] the conformal finding is still descriptive, not a formal test
- [ ] no hard-real-time or WCET claim
- [ ] title and abstract match the reduced scope
- [ ] a cover letter answering all eight referee items point by point, including any this week
      could not close

---

## 10 · What this week does not buy

State this in the cover letter rather than letting a reviewer find it.

| Not achieved | Why |
|---|---|
| External validation | Route A, two to three weeks |
| Q1 eligibility | Novelty is the binding constraint, and §9.2 is a partial answer at best |
| Gate complementarity | Would require faults that separate the gates; none in the current suite does |
| Real-world validity | Requires Route A |
| Hard real-time | Requires a different implementation and a different measurement method |

**Realistic outcome of a clean week:** Reject-and-Resubmit → **Major Revision**, with acceptance
probability at a Q2 venue moving from roughly 5–10% to roughly 35–45%.

---

## 11 · Order of operations, and the one rule

```
Day 0  environment                     gates everything
Day 1  +73 provenance                  may invalidate the headline — do it first
Day 2  single-build margin (C2)        the referee's sharpest finding
Day 3  30 seeds                        removes n=1
Day 4  parameters + refutations        removes the reproducibility objection
Day 5  FB2 / FB3 root cause            wire only if the evidence changes
Day 6  manuscript edits                items 3, 6, 8
Day 7  reframe + QC + cover letter     item 7, Route B
```

**The rule for the week:** if a measurement contradicts something the manuscript currently claims,
**the manuscript changes.** Days 1, 2 and 3 each have a realistic path to a worse number than the one
published. Reporting the worse number is what makes the rest of the paper worth believing, and the
referee report singles out exactly that discipline as the manuscript's strongest asset.
