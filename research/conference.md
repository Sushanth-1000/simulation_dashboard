# conference.md — ASTRA to IEEE international conference

**Written** 31 August 2026
**Baseline** `3cda553` on `phase4-l5-twin-l7b-physical`, plus artefacts regenerated 31 Aug
**Status of this document** Execution plan. Every figure in Step 1 was **measured by running the
code on 31 August 2026**, not read from documentation.

> **Prior art on this manuscript.** A strict Q2 referee report on `ASTRA_Paper_v21` returned
> **43/100, D — Reject and Resubmit**, with four critical issues: single-seed evidence, a
> cross-configuration flagship metric, novelty below threshold, and self-referential validity.
> This plan assumes that report is correct.

---

## STEP 1 — AUDIT OF ACTUAL CURRENT STATE

Measured 31 August 2026 in a fresh Python 3.12 venv (torch 2.13.0, numpy 2.5.1, SB3 2.9.0).

| Area | Current status | Evidence (measured) | Quality | Missing work |
|---|---|---|---|---|
| **Research question** | Stated, five RQs, all answerable | manuscript §1.2 | Good | RQ1 wording vs trust-index result |
| **Novelty** | Explicitly disclaimed by the authors | "a better monitor is not proposed" | **Weak** | Reframe around measurement instruments |
| **Methodology** | Sound; positive-control ablation is above average | `benchmarks/ablation.py`, `ablated_passes` | Good | — |
| **Dataset** | **None.** No external data anywhere | `grep read_csv\|np.load\|h5py src/ training/` → empty | **Absent** | Acquire real logs |
| **Implementation** | 10 layer modules, 21,631 src LOC, 29,343 test LOC, all wired in `assembly.py`, all populate the decision record | per-layer test runs; audit record inspection | **Strong** | — |
| **Baselines** | Ungoverned Core-A only | `benchmarks/comparison.py` | **Weak** | Simplex, CBF |
| **Ablation** | 4 profiles × 7 scenarios, with positive control | `benchmarks.ablation` re-run 31 Aug | **Strong** | Seeds |
| **Statistics** | n = 1 per scenario. No dispersion | manuscript §4 | **Weak** | 30 seeds |
| **Generalization** | Zero. `[M-ext]` = 0 of 30 | `CREDIBILITY_MATRIX.md` scoreboard | **Absent** | External data |
| **Failure analysis** | Two negative results reported honestly | §5.4, §5.8 | Moderate | Systematic taxonomy |
| **CARLA** | **Not run.** `CARLA.md` is a forward handover | `find var -iname "*carla*"` → empty | **Absent** | Week 2+ |
| **Reproducibility** | **Was broken; fixed today.** Committed policy (9 Aug) predated 3 ADRs and did not drive; all 5 checkpoints failed. Regenerated 31 Aug | `tools.check_artifacts` before/after | Recovering | Commit artefacts |
| **Paper** | 15 pp, 38 refs, IJ-AI format | `ASTRA_Paper_v18.tex` | Good prose, stale numbers | Re-measure all tables |

### 1.1 · Test suite, measured

```
3,063 passed · 2 failed · 1 skipped · 3 xfailed
```

The 3 xfails are the deliberate NFR5 domain-independence walls. The **skip** is
`test_layering.py` — *import-linter is not installed* — so the manuscript's "twelve contracts,
0 broken" claim is **currently unverified**. The 2 failures are guard thresholds baselined to the
retired policy.

### 1.2 · Benchmarks re-run 31 August, against regenerated artefacts

| Benchmark | Result |
|---|---|
| `check_artifacts` | *"the vehicle drives"* (was: 200/200 ticks vetoed) |
| `fault_study` | control 0.142 m / 2 vetoes; `imu_dropout` 0.089 m / 85 / 195 outside nominal |
| `comparison` | ASTRA **worse than raw Core-A on 4 of 7** scenarios |
| `gate_census` | STATISTICAL 2800/0/0 · PHYSICAL 2558/**242**/0 · DETERMINISTIC 2800/0/0 |
| `exchangeability` | **OD-8 STANDS.** `URBAN_CLEAR` 0.0% inside, no overlap |
| `arms` | single/bias 1.1655 m → redundant/bias 0.1338 m, arms indistinguishable to 4 dp |
| `ablation` | L6-off ≡ governed; L7a-off ≡ governed; L7b-off zeroes vetoes |

Full deltas against the published figures are in `docs/REBASELINE_2026-08-31.md`.

---

## STEP 2 — WHAT ASTRA ACTUALLY CONTRIBUTES

### 2.1 · Classification of every claimed contribution

| Claim | Class | Evidence |
|---|---|---|
| Estimator-absorbed faults are invisible to gates downstream of the estimator | **STRONG SCIENTIFIC** | 4 of 6 faults produce veto counts identical to control; reproduced on an independently trained policy |
| Upstream freshness signal is *specific* where downstream signals are not | **STRONG SCIENTIFIC** | health fires only on the one fault it can observe, 0 false alarms; trust fires on all 7 arms incl. a FALSE ALARM on the clean control |
| Shadow evaluation before wiring catches self-disarming loops | **MODERATE** | FB2 40% score collapse; FB3 → ε. Both withheld |
| Conformal exchangeability fails on a deployed loop | **MODERATE** | OD-8, zero overlap, re-confirmed 31 Aug |
| Positive-control ablation distinguishes a real null from a broken ablation | **MODERATE** (methodological) | `ablated_passes` 0/2,800 vs 2,800/2,800 |
| Per-intervention vs per-tick rates differ ~600× | **MODERATE** (reporting) | 4.97% vs 0.008% |
| Nine-layer architecture | **ENGINEERING** | every layer standard technique |
| Median fusion limits single-channel bias | **APPLICATION** | standard analytical redundancy; authors claim no novelty |
| Three gates are complementary | **UNSUPPORTED** | 2 of 3 issue zero vetoes |
| 27× improvement on IMU dropout | **UNSUPPORTED — withdrawn** | re-measured 0.089 vs 0.163 m, under 2× |
| Governance improves on 6 of 7 faults | **CONTRADICTED** | worse on 4 of 7 |
| Real-time operation | **UNSUPPORTED** | max 140.4 ms vs 50 ms period; no WCET |

### 2.2 · The four defensible contributions for an IEEE paper

**C1 — The observability constraint, demonstrated by fault injection.**
Four of six injected sensor faults produce verdicts indistinguishable from a clean control, on two
independently trained policies. Evidence: `fault_study`, both epochs.

**C2 — Placement determines specificity, not just latency.**
The upstream signal fires on exactly the fault it can observe and never on a clean run. The
downstream trust index fires on all seven arms *including the control*. This is the strongest
version of the placement argument and the current manuscript does not make it.

**C3 — Four instruments for detecting silent monitor failure.** Shadow-before-wiring;
positive-control ablation; measuring the conformal precondition rather than assuming it;
per-intervention vs per-tick reporting. Each caught a real defect in this system.

**C4 — Reproducibility as a measured property.** A committed artefact three ADRs stale produced a
non-driving loop; regeneration moved every absolute figure while leaving 13 structural findings
intact. That is a directly measured demonstration of why single-seed architectural claims fail.

---

## STEP 3 — REVIEWER RED TEAM

### Reviewer A — AI/ML

**Likely score: 2–3 / 6.**
Strongest criticism: *"No new method is proposed and the authors say so. The learned controller is
stock PPO with a PID-Lagrangian wrapper; the twin is a small PINN; the gate is textbook Mondrian
ICP. What is evaluated is an integration."*
Weakest part: novelty.
Likely rejection reason: incremental contribution.
Evidence required: reframe on C2/C3, which are methodological rather than architectural.

### Reviewer B — Autonomous driving / robotics

**Likely score: 2 / 6.**
Strongest criticism: *"Everything is measured on a kinematic bicycle plant the authors wrote. There
is no vehicle, no log, no simulator, no sensor model beyond additive Gaussian noise. A 1 m position
bias on a synthetic channel is not a sensor fault."*
Weakest part: external validity — `[M-ext]` = 0 of 30.
Likely rejection reason: no real-world or third-party evidence.
Evidence required: comma2k19 replay **or** CARLA closed loop. Non-negotiable for this reviewer.

### Reviewer C — Experimental methodology

**Likely score: 3–4 / 6.** The most sympathetic of the three.
Strongest criticism: *"n = 1. And the artefacts committed for reproduction do not run."*
Weakest part: statistics and reproducibility.
Likely rejection reason: claims exceed the evidence design.
Evidence required: 30 seeds with dispersion; committed working artefacts; disclosed seeds and
thresholds.

---

## STEP 4 — REJECTION-RISK MATRIX

| Risk | Prob. | Severity | Current evidence | Required fix | Priority |
|---|---|---|---|---|---|
| No external validation | **95%** | Fatal | `[M-ext]` 0/30 | comma2k19 replay | **P0** |
| n = 1 | **90%** | Fatal | manuscript §4 | 30 seeds, median + IQR | **P0** |
| Novelty disclaimed | **85%** | Fatal | §1.1, §5.3 | Reframe on C2/C3 | **P0** |
| No prior-art baseline | **80%** | Major | comparison = ungoverned only | Simplex | **P0** |
| Artefacts not committed / stale | 70% | Major | check failed 31 Aug | commit regenerated | **P0** |
| Published numbers now wrong | **100%** | Major | REBASELINE doc | re-measure all tables | **P0** |
| Gate complementarity unestablished | 100% | Major | 0/0/242 | report as negative | P1 |
| Timing exceeds period | 60% | Major | max 140.4 ms | state as characterisation | P1 |
| Contracts claim unverified | 50% | Important | test skipped | install import-linter | P2 |
| Seeds/thresholds undisclosed | 70% | Important | Declarations | parameter appendix | P2 |
| Two guard tests failing | 40% | Important | 2 failed | re-baseline | P2 |

**No P0 may remain open at submission.** Six are currently open.

---

## STEP 5 — RESEARCH QUESTION

### Current
*"Does monitor placement impose an observability constraint?"*

### Problems
Not falsifiable as stated — "constraint" has no threshold. Contradicted in part by the authors' own
Table 4 (a downstream signal fired at the same step). Scoped to one plant, one policy, six faults.

### Recommended

> **In a layered runtime-governance architecture, does a monitor's position relative to state
> estimation determine which sensor faults it can detect and how specifically it detects them —
> measured as (a) detection rate across a fault suite, (b) detection latency relative to hazard
> onset, and (c) false-alarm rate on fault-free operation?**

### Why stronger
Three measurable quantities instead of a metaphor. Includes **specificity**, which is where the
measured evidence is strongest and where the current manuscript is silent. Falsifiable: if a
downstream monitor matches the upstream one on all three, the claim fails.

### How falsified
Run every candidate signal on all seven arms across ≥30 seeds. If any downstream signal achieves
equal or better detection rate, equal or better latency, **and** zero false alarms on the control,
the hypothesis is refuted. Measured 31 Aug on n=1, the trust index fails the third condition.

---

## STEP 6 — NOVELTY STRATEGY

| Existing work | What it does | Limitation | ASTRA difference | Evidence needed |
|---|---|---|---|---|
| Simplex / L1Simplex | switches to a verified baseline on a state predicate | decision module reads the estimate | health path bypasses the estimator | side-by-side on the same fault suite |
| Sandboxing / Neural / black-box Simplex | reachability or simulation-certified switching | same estimate dependency | as above | as above |
| Runtime verification (REDriver) | STL monitor over vehicle state | fidelity bounded by state fidelity | measures that bound rather than assuming it | fault suite where the state is corrupted |
| Shielding / CBF | corrects actions against a certificate | certificate stated over model state | corrupted estimate certifies the wrong system | demonstrate on a corrupted-estimate fault |
| Conformal OOD (Cai; CODiT) | detects distribution shift in inputs | assumes exchangeability | **measures** exchangeability on a deployed loop | OD-8 (have it) |
| FDI / van Wyk | residuals after the filter | absorbed faults yield in-band residuals | the observation this work acts on | already cited |

**Defensible novelty statement:**

> The contribution is not a new monitor. It is the experimental separation of *evidence paths* in a
> runtime-governance architecture, and the measurement of what each path can observe — including
> four instruments that detect silent monitor failure, each of which located a real defect in the
> system under study.

**Not defensible:** "nine-layer architecture", "three independent gates" (ablation refutes),
"first to combine X and Y".

---

## STEP 7 — DATASET STRATEGY

**Current: no dataset.** Verified — no `read_csv`, `np.load`, `h5py`, or any loader in `src/` or
`training/`. All data is generated by `SyntheticDrivingEnv`.

| Dataset | Purpose | Train | Val | Test | External | Claim validated |
|---|---|:--:|:--:|:--:|:--:|---|
| `SyntheticDrivingEnv` | mechanism isolation | ✓ | ✓ | ✓ | ✗ | C1 structural only |
| **comma2k19** | primary external | ✗ | ✓ | ✓ | **✓** | false-positive rate on real sensor noise; C1 on real logs |
| **ALFA** | labelled faults | ✗ | ✗ | ✓ | **✓** | false-negative rate — the only open source of ground-truth fault type *and* time |
| CARLA | closed-loop consequence | ✗ | ✗ | ✓ | ✓ | what happens *after* a veto — the one thing replay cannot give |

**Verify before committing:** licence terms, current download availability, and exact modality
coverage for each. Do not cite size or sensor figures from memory.

**Why replay is cheap here:** the logged commands *are* the proposals. No policy retraining is
required — replay each logged command through L1, L2 and the three gates and record the verdict.
Open-loop, so it yields detection rates but not consequence.

---

## STEP 8 — EXPERIMENTAL MASTER PLAN

### E1 — Main performance, multi-seed
RQ(a),(b),(c) · H: detection differs by placement · synthetic plant · 7 arms × **30 seeds** ·
metrics: detection rate, latency, false-alarm rate, final |dev| · median [Q1,Q3] · **Table 1** ·
supports C1, C2.

### E2 — Prior-art baseline
H: a Simplex switch on the same plant does not detect estimator-absorbed faults either ·
implement Simplex (verified fallback + state predicate) · same 7 arms, 30 seeds · same metrics ·
**Table 2** · closes the P0 baseline gap. **This is the single highest-value new experiment.**

### E3 — Ablation with positive control
Already implemented. Extend to 30 seeds. 4 profiles × 7 arms · report `ablated_passes` · **Table 3**.

### E4 — External validation, comma2k19
H: gates downstream of estimation exhibit the same blind spot on real logs · replay logged
openpilot commands · metrics: veto rate, false-positive rate · **Table 4** · moves `[M-ext]` off 0.

### E5 — Robustness / fault severity sweep
Sweep bias ∈ {0.1, 0.5, 1.0} m, dropout ∈ {0.25, 0.5, 1.0} s, drift ∈ {0.005, 0.02, 0.05} m/s ·
detection rate vs severity · **Figure 4** · establishes the detection floor.

### E6 — Failure analysis
See Step 13.

### E7 — Computational characterisation
Per-layer latency, median/p95/p99/max, ≥15 runs × 2,000 steps · **Table 5** · explicitly *not* a
WCET claim.

### E8 — CARLA controlled scenarios
Week 2+. See Step 14.

---

## STEP 9 — BASELINE REQUIREMENTS

| Tier | Baseline | Why required |
|---|---|---|
| Simple | Ungoverned Core-A | **have it** — establishes the fault is harmful |
| Established | **Simplex switch** | the canonical runtime-assurance architecture; without it "we compared to nothing from the literature" |
| Strong modern | **CBF safety filter** | tests whether a certificate on a corrupted estimate certifies the wrong system — directly on-thesis |
| SOTA | conformal OOD detector standalone | isolates whether the gate or its *placement* is doing the work |

Fairness: identical plant, identical seeds, identical fault injection point, identical metrics,
identical control period. Report each baseline's own tuning procedure.

---

## STEP 10 — ABLATION MATRIX

Axes: **H** upstream health path · **R** redundant sensing · **G6** statistical gate ·
**G7a** deterministic gate · **G7b** physical gate.

| Variant | H | R | G6 | G7a | G7b | Question answered |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Ungoverned | ✗ | ✗ | ✗ | ✗ | ✗ | is the fault harmful at all? |
| Gates only | ✗ | ✗ | ✓ | ✓ | ✓ | can downstream gates alone catch it? |
| + redundancy | ✗ | ✓ | ✓ | ✓ | ✓ | how much is fusion vs placement? |
| + health | ✓ | ✓ | ✓ | ✓ | ✓ | **the contribution** |
| Health only | ✓ | ✗ | ✗ | ✗ | ✗ | is the upstream signal sufficient alone? |
| − G6 | ✓ | ✓ | ✗ | ✓ | ✓ | is the statistical gate load-bearing? |
| − G7a | ✓ | ✓ | ✓ | ✗ | ✓ | is the deterministic gate load-bearing? |
| − G7b | ✓ | ✓ | ✓ | ✓ | ✗ | is the physical gate load-bearing? |

Rows 5 and 3 are new and are the two that separate *placement* from *fusion* — the objection a
reviewer will raise first. All ×30 seeds. Positive control on every disarmed row.

---

## STEP 11 — STATISTICAL VALIDATION PLAN

**Design.** 30 seeds per scenario per configuration. Paired across configurations — same seed, same
fault, same injection tick.

**Report.** Median and IQR. Paired comparisons via **Wilcoxon signed-rank** (non-Gaussian latency
distributions), effect size as paired rank-biserial correlation, and **Benjamini–Hochberg** at
q = 0.05 across the scenario family.

**Independence.** Seeds are independent; **control steps within a trajectory are not** and must
never be treated as replicates. State this explicitly.

**Forbidden.** Any statistic computed over ticks-within-a-run. Any mean over a bimodal detection
latency. Reporting a p-value without the effect size.

---

## STEP 12 — DATA LEAKAGE AUDIT

Synthetic phase — the real risk is **calibration leakage**, not train/test leakage:

- [ ] Calibration corpus generated from runs **disjoint** from evaluation runs
- [ ] Policy training seeds disjoint from evaluation seeds
- [ ] Gate thresholds fixed **before** the evaluation sweep; no post-hoc tuning
- [ ] Twin trained on data disjoint from the corpus it calibrates

External phase — split **by drive, never by tick**:

- [ ] comma2k19 split by chunk/route, not by frame
- [ ] No segment appears in two splits
- [ ] Split committed and hashed **before** any data is drawn
- [ ] Temporal ordering preserved; no future frames in calibration

`docs/DATA_SPLIT_PROTOCOL.md` already specifies this. Follow it; do not re-derive it.

---

## STEP 13 — FAILURE ANALYSIS

| Category | Collect | n | Metric | Visualisation |
|---|---|---:|---|---|
| Estimator-absorbed faults | all arms where veto count = control | ≥30 seeds × 4 arms | detection rate | per-arm detection bar |
| Slow self-consistent corruption | drift at 0.005 m/s | 30 | detection rate vs ramp rate | detection floor curve |
| False alarms | clean control, all signals | 30 | FP rate per signal | signal × arm heatmap |
| Governance cost | arms where ASTRA > ungoverned | currently **4 of 7** | Δ final \|dev\| | paired scatter |
| Intervention-induced degradation | lateral_noise | 30 | governed vs ungoverned | box plot across seeds |
| Gate silence | L6, L7a | 2,800+ ticks | veto and abstain counts | census table |

The paper must show **where ASTRA fails**. Currently that is: 4 of 7 scenarios where governance
costs, one gate structurally unable to fire, and a drift regime nothing detects.

---

## STEP 14 — CARLA PLAN

### What CARLA tests
Closed-loop consequence — *what happens after a veto*, which log replay cannot give. Sensor models
with real failure characteristics. Weather and lighting as genuine covariate shift.

### What CARLA cannot prove
Real-vehicle validity. It is still a simulator, and its plant is not the deployment plant. It does
**not** substitute for comma2k19: replay gives real sensor noise, CARLA gives consequence. Both are
needed and they answer different questions.

### Scenarios
Sensor dropout, position bias, gradual drift, frozen channel, speed bias, noise burst — the same six
faults, so results are comparable to the synthetic suite. Plus weather (clear/rain/night) as a
covariate-shift probe for OD-8.

### Prerequisite
Do **not** start CARLA until E1–E3 are complete on the synthetic plant with seeds. CARLA will not
fix an n = 1 problem; it will reproduce it more expensively.

---

## STEP 15 — REPRODUCIBILITY CHECKLIST

- [x] Python 3.12; `uv.lock` pins numpy 2.5.1, torch 2.13.0, SB3 2.9.0
- [ ] **Commit the regenerated artefacts** — `var/policy/synthetic.pt`, `var/twin/synthetic.pt`, `var/calibration/synthetic.json`
- [ ] Disclose every seed behind every reported number
- [ ] Disclose gate thresholds: ε, θ₁/θ₂/θ_halt, jerk limit, speed and lateral-acceleration bounds, friction margin
- [ ] Disclose PPO hyperparameters, reward, constraint budgets
- [ ] Disclose channel sigmas (0.10 / 0.20 / 0.06 m) and UKF noise
- [ ] Install `import-linter` so the contracts claim is actually checked
- [ ] Re-baseline the 2 failing guard tests
- [ ] Record hardware, runtime, memory for every reported timing

**Release with the paper:** parameter appendix, seed list, per-episode result CSVs. Parameters are
not source code — this is compatible with withholding the implementation.

---

## STEP 16 — COMPUTATIONAL REQUIREMENTS

Measured 31 Aug on a general-purpose workstation, **CPU only**:

| Task | Measured / estimated |
|---|---|
| Twin training | ~2 min, CPU |
| Corpus generation | ~1 min, CPU |
| Policy training | ~10 min, CPU |
| Full test suite | 47 s |
| One fault-study sweep (7 arms) | ~1 min |
| **30-seed sweep across 4 configs** | **~2 h, CPU, parallelisable** |
| CARLA | **GPU required**, 8 GB VRAM is workable for a single ego with reduced sensor resolution |

Everything in E1–E3, E5, E7 runs on the existing CPU machine. The 8 GB VRAM constraint applies only
to CARLA, and is adequate if camera resolution is kept modest and LiDAR channel count reduced.

---

## STEP 17 — FIGURE AND TABLE PLAN

| # | Item | Source | Message |
|---|---|---|---|
| Fig 1 | Nine layers + trust boundary + health path | existing | where each monitor draws evidence |
| Fig 2 | Detection latency, all signals × all arms, 30 seeds | E1 | **health is specific; trust is not** |
| Fig 3 | Detection rate vs fault severity | E5 | where detection floors out |
| Fig 4 | Exchangeability, corpus vs live, overlaid | `exchangeability` | zero overlap in one image |
| Fig 5 | Paired scatter, ASTRA vs ungoverned per seed | E1 | governance cost, honestly |
| Tab 1 | Main results, median [IQR] | E1 | scale of the effect |
| Tab 2 | **ASTRA vs Simplex vs CBF vs ungoverned** | E2 | prior-art comparison |
| Tab 3 | Ablation with `ablated_passes` | E3 | which components are load-bearing |
| Tab 4 | comma2k19 replay | E4 | first `[M-ext]` row |

Figure 2 is the paper's centrepiece and does not currently exist.

---

## STEP 18 — PAPER STRUCTURE

IEEE conference format, typically 6–8 pages. Adapt on venue selection.

1. Title · 2. Abstract · 3. Introduction (with RQ) · 4. Related work, organised **by monitor
placement** · 5. Architecture · 6. Experimental setup (incl. statistical design) · 7. Main results ·
8. Baseline comparison · 9. Ablation · 10. External validation · 11. Failure analysis ·
12. Limitations · 13. Conclusion · 14. References

Related work organised by *where each method's monitor reads* is the structural argument. Do not
organise it chronologically.

---

## STEP 19 — CONFERENCE SELECTION

> **Deadlines are not stated here because they could not be verified from official sources at the
> time of writing.** Confirm each on the official site before planning around it. See
> [IEEE ICPS 2027](https://icps2027.ieee-ies.org/), [ICCPS listing](http://www.wikicfp.com/cfp/program?id=1319).

| Venue | Scope match | Notes |
|---|---|---|
| **IEEE ICCPS** | **Strongest.** Runtime assurance for CPS is core scope | Competitive; expects real or high-fidelity evaluation |
| **IEEE ITSC** | Strong for the vehicle framing | Broad AV scope; more tolerant of simulation |
| **IEEE IV** | Good | Vehicle-centric; would want CARLA at minimum |
| **IEEE ICPS** | Moderate | Industrial CPS; less AV-specific |
| **IEEE DSN / SAFECOMP** | **Strong for the dependability framing** | Values negative results and measurement methodology — a good fit for C3/C4 |

**Recommendation:** target **ITSC or SAFECOMP** for the first submission with synthetic + comma2k19,
and hold **ICCPS** for after CARLA. SAFECOMP in particular rewards the "instruments for detecting
silent monitor failure" framing that plays to C3.

---

## STEP 20 — SUBMISSION COMPLIANCE

Verify each against the venue's current call — **do not assume last year's rules**:

- [ ] IEEE conference template, correct year
- [ ] Page limit and whether references count
- [ ] Double-blind? If so, remove repo URLs, institution, `ASTRA` if identifying
- [ ] Originality; no concurrent submission (**note: v18 is in preparation for a journal — resolve overlap before submitting**)
- [ ] Authorship: 4 authors + supervisor; CRediT statement
- [ ] AI-assistance declaration per the venue's current policy
- [ ] Supplementary material limits
- [ ] Copyright form; ORCID
- [ ] Plagiarism/CrossCheck threshold

**Flag:** the manuscript states the implementation is withheld pending patent consideration.
Confirm this does not conflict with any venue artefact-availability requirement, and confirm the
filing status before submitting.

---

## STEP 21 — EXECUTION ROADMAP

| Phase | Tasks | Depends on | Deliverable | Acceptance |
|---|---|---|---|---|
| **P0 Audit** | done 31 Aug | — | `REBASELINE_2026-08-31.md` | ✅ complete |
| **P1 Foundation** | commit artefacts; install import-linter; re-baseline 2 tests; parameter appendix | P0 | green gate | `make check` passes, contracts verified |
| **P2 Statistics** | 30-seed harness across 4 configs | P1 | seeded result CSVs | every table has median [IQR] |
| **P3 Baselines** | implement Simplex; then CBF | P1 | `benchmarks/baselines.py` | runs on same plant, same seeds |
| **P4 Main experiments** | E1, E3, E5, E7 | P2, P3 | Tables 1–3, Figs 2–3, 5 | all with dispersion |
| **P5 External** | comma2k19 acquisition, split, replay | P2 | Table 4 | ≥1 row at `[M-ext]` |
| **P6 CARLA** | environment, 6 scenarios, weather | P4 | Table 5 | scenarios reproducible |
| **P7 Failure analysis** | taxonomy per Step 13 | P4 | Fig 5 + taxonomy | every category populated |
| **P8 Paper** | rewrite around C1–C4 | P4, P5 | draft | every claim maps to a table |
| **P9 Red team** | re-run Step 3 against the draft | P8 | issue list | zero open P0 |
| **P10 Submit** | Step 20 checklist | P9 | submission | all boxes ticked |

**Blocking issues today:** artefacts uncommitted (P1); no baseline implementation (P3); no external
data (P5).

---

## STEP 22 — WEEK-BY-WEEK

| Week | Focus | Exit criterion |
|---|---|---|
| **1** *(current)* | Audit complete; artefacts regenerated; re-baseline documented | ✅ done — commit the artefacts |
| **2** | 30-seed harness; every table re-measured with dispersion | no figure in the paper is n = 1 |
| **3** | Simplex baseline implemented and run | Table 2 exists |
| **4** | comma2k19 acquired, split frozen, replay harness | first `[M-ext]` row |
| **5** | CBF baseline; severity sweep; failure taxonomy | Tables 2–3, Figs 3, 5 |
| **6** | CARLA environment + 6 scenarios | scenarios reproducible |
| **7** | CARLA results; weather covariate shift | Table 5 |
| **8** | Paper rewritten around C1–C4 | every claim maps to a table |
| **9** | Red team; compliance; submit | zero open P0 |

Nine weeks. Weeks 2–4 are the ones that change the decision; 6–7 are optional for a first
submission if the venue accepts replay-only external validation.

---

## STEP 23 — DEFINITION OF DONE

**Dataset** — downloaded · licence verified · integrity hashed · leakage checked per Step 12 ·
splits frozen and committed *before* any result.

**Model** — artefacts committed and `check_artifacts` passes · training reproducible from a stated
seed · baselines implemented and tuned by a documented procedure.

**Experiments** — E1–E5, E7 complete · every number has median [IQR] over ≥30 seeds · every claim
traces to a named table.

**CARLA** — scenarios scripted and reproducible · sensor configuration documented · results recorded
with seeds.

**Paper** — every claim supported by a table · no unsupported novelty claim · both negative results
retained · every reference verified against Crossref/DataCite.

---

## STEP 24 — PUBLICATION GATE

| Gate | Status today | To pass |
|---|---|---|
| 1 Scientific validity | ⚠️ partial | claims match re-measured evidence |
| 2 Novelty | ❌ **FAIL** | reframe on C2/C3 |
| 3 Dataset quality | ❌ **FAIL** | ≥1 external dataset |
| 4 Experimental rigor | ⚠️ partial | baselines implemented |
| 5 Statistical rigor | ❌ **FAIL** | 30 seeds |
| 6 Generalization | ❌ **FAIL** | `[M-ext]` > 0 |
| 7 CARLA | ❌ not started | optional for first submission |
| 8 Reproducibility | ⚠️ recovering | commit artefacts |
| 9 IEEE compliance | ⬜ not assessed | Step 20 |
| 10 Reviewer red team | ❌ **FAIL** | 6 open P0 |

**Submission permitted only at zero open P0. Currently six.**

---

## FINAL SCORECARD

| Category | /10 | Evidence | Required improvement |
|---|--:|---|---|
| Research question | 6 | 5 RQs, all answerable | make specificity explicit |
| Novelty | **3** | disclaimed by authors | reframe on C2/C3 |
| Methodology | 7 | positive-control ablation | — |
| Dataset | **1** | none exists | comma2k19 |
| Baselines | **2** | ungoverned only | Simplex, CBF |
| Ablation | 7 | 4 profiles, positive control | seeds |
| Statistics | **2** | n = 1 | 30 seeds |
| Generalization | **0** | `[M-ext]` 0/30 | external data |
| Robustness | 4 | 6 faults, 1 severity | severity sweep |
| CARLA | **0** | not started | Week 6–7 |
| Reproducibility | 5 | fixed today, uncommitted | commit + disclose |
| Writing | 8 | referee praised claim discipline | — |
| IEEE readiness | **3** | 6 open P0 | the above |

### CURRENT IEEE CONFERENCE READINESS: **34 / 100**

Readiness, not acceptance probability. Weeks 2–4 as scoped move this to roughly 65.

---

## NO-BS VERDICT

**Currently strong.** The implementation — 21,631 lines, all ten layers wired, every layer
populating the decision record, 3,063 tests passing. Claim discipline the referee explicitly
praised. Two structural findings that reproduced on an independently trained policy. The
positive-control ablation, which most papers omit.

**Currently weak.** No external data. n = 1. No prior-art baseline. Novelty disclaimed by the
authors themselves.

**What gets it rejected.** Any one of: no external validation; single-seed; no baseline; disclaimed
novelty. All four are live.

**Before experiments.** Commit the artefacts. Install import-linter. Re-baseline the two failing
guard tests. Nothing else can be trusted until `make check` is green.

**Before CARLA.** Finish the seeds. CARLA will not fix n = 1 — it will reproduce it at higher cost.

**Before writing.** Every table re-measured. The 27× claim withdrawn — it is now under 2×.

**Before submission.** Zero open P0.

**Single experiment with most value.** **The Simplex baseline.** Two to three days on the existing
plant, no new data, and it converts "we compared to nothing from the literature" into a table. It
also directly tests the thesis: if Simplex also misses the estimator-absorbed faults, the placement
claim generalises beyond this architecture.

**Single weakness most likely to cause rejection.** No external validation. `[M-ext]` = 0 of 30, and
the authors say so in the manuscript.

**Strongest defensible contribution.** C2 — placement determines *specificity*. Measured 31 Aug:
the upstream signal fires on exactly the one fault it can observe with zero false alarms; the
downstream trust index fires on all seven arms including the clean control. The current manuscript
reports this as a tie and is under-claiming a result it already has.

**Claim to remove.** The 27× improvement on IMU dropout. Re-measured at under 2×. It is in the
abstract and it is wrong.
