# ASTRA Dataset Selection

**Written** 31 August 2026 · **Basis** `ASTRA_RESEARCH_FREEZE.md`, `conference_master_plan.md` rev. 3
**Verification rule** Facts marked ✅ were confirmed against a primary source this session. Anything
unconfirmed is marked **UNKNOWN** and must be verified before commitment. Nothing is guessed.

> **The question every candidate must answer:** *what specific frozen ASTRA claim does this dataset
> let us defend that the simulator alone cannot?* If unclear, reject.

---

## 1 · Research Requirements

The frozen research question concerns **fault-information loss through an estimation pipeline**, not
perception. This eliminates most famous driving datasets before the search begins.

### R1 — Raw sensor evidence *(what L1 must ingest)*
Required: **IMU**, **GNSS/position**, **vehicle speed**, per-sample **timestamps**.
Not required: camera, LiDAR, radar. ASTRA governs *commands* from a 5-dimensional state; it has no
perception stack. A dataset offering only annotated boxes and tracks is useless here.

### R2 — Ground truth
Required: **ego pose** and **speed** at sufficient rate to serve as the clean reference and to score
a detection correct. Object-level ground truth is irrelevant.

### R3 — Fault relevance
Ideal: naturally occurring sensor faults **with labelled time and type**.
Acceptable: clean real logs supporting controlled injection, **provided the clean original is
retained as a paired reference**.

> **Synthetic corruption of real data is not equivalent to a natural fault.** It establishes
> behaviour under *real sensor noise and real command distributions* with a *known* perturbation. It
> does **not** establish real-world fault prevalence or detection rate. This distinction is carried
> through every claim below.

---

## 2 · Search Strategy

Primary sources preferred: official papers, official repositories, official dataset pages. Secondary
sources used only to discover candidates. Searched: automotive multimodal, low-level sensor,
localisation, adverse-weather, robotics fault/anomaly, and prognostics-and-health-management
categories.

---

## 3 · Candidate Pool

| # | Dataset | Category | First-pass |
|--:|---|---|---|
| 1 | **comma2k19** | low-level driving | **advance** |
| 2 | **ALFA** | UAV fault/anomaly | **advance (cross-domain)** |
| 3 | BASiC (Arducopter sensor failures) | UAV sensor failure | advance, UNKNOWN |
| 4 | Oxford RobotCar | localisation, longitudinal | advance |
| 5 | KITTI raw (OXTS) | multimodal + INS | advance |
| 6 | NCLT (Michigan) | long-term localisation | advance |
| 7 | Boreas | adverse weather | advance, UNKNOWN |
| 8 | 4Seasons | seasonal localisation | UNKNOWN |
| 9 | Malaga Urban | localisation | UNKNOWN |
| 10 | Rail positioning (Lucy 2018) | rail, IMU + dual GNSS | advance, cross-domain |
| 11 | EuRoC MAV | IMU + ground truth | cross-domain |
| 12 | TUM VI | visual-inertial | cross-domain |
| 13 | nuScenes | perception | **VETO 5** |
| 14 | Waymo Open | perception | **VETO 5** |
| 15 | Argoverse 2 | perception/forecasting | **VETO 5** |
| 16 | BDD100K | perception | **VETO 5** |
| 17 | A2D2 | perception | **VETO 5** |
| 18 | PandaSet | perception | **VETO 5** |
| 19 | DAIR-V2X | V2X perception | **VETO 5** |
| 20 | ONCE / SODA10M | perception pretraining | **VETO 5** |
| 21 | RADIATE | adverse-weather radar | **VETO 5** |
| 22 | DDAD | depth | **VETO 5** |
| 23 | Zenseact Open | perception | **VETO 5** |
| 24 | Automotive Faults Dataset (Zenodo) | OBD diagnostics | UNKNOWN, likely VETO 1 |
| 25 | Ford AV Dataset | multimodal | UNKNOWN |

**Eleven perception datasets vetoed under VETO 5.** They cannot support any frozen claim: ASTRA has
no perception stage, so there is no pipeline stage at which their labels enter. Their fame is
irrelevant.

---

## 4 · Credibility Matrix — verified entries only

| Dataset | Raw sensors | Ground truth | Fault data | Injection possible | Sync | Vehicle state | Size | Licence | Access | Relevance |
|---|---|---|---|---|---|---|---|---|---|---|
| **comma2k19** | ✅ raw GNSS, 9-axis IMU, CAN, road camera | ✅ fused pose | **NO** | **YES** | UNKNOWN | ✅ via CAN | UNKNOWN | ✅ **MIT** | ✅ GitHub + HuggingFace | **HIGH** |
| **ALFA** | ✅ flight telemetry | ✅ | ✅ **labelled time + type** | n/a | UNKNOWN | ✅ | 66 min nominal + 13 min post-fault | UNKNOWN | ✅ CMU RI | **MEDIUM — cross-domain** |
| Oxford RobotCar | PARTIAL | UNKNOWN | NO | YES | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | MEDIUM |
| KITTI raw | PARTIAL (OXTS) | UNKNOWN | NO | YES | UNKNOWN | PARTIAL | UNKNOWN | UNKNOWN | UNKNOWN | MEDIUM |
| NCLT | UNKNOWN | UNKNOWN | NO | YES | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | MEDIUM |
| BASiC | UNKNOWN | UNKNOWN | ✅ claimed | n/a | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Boreas | UNKNOWN | UNKNOWN | NO | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

**Verified this session:** comma2k19 — 33 hours, 2,019 one-minute segments, CA I-280 San Jose→San
Francisco, ~20 km, road-facing camera + 9-axis IMU + **raw GNSS** + **CAN**, **MIT licence**.
ALFA — 47 autonomous flights, 23 engine failures, 24 control-surface faults across 7 types, 66 min
nominal + 13 min post-fault, **ground truth of fault time and type**, CMU Robotics Institute, IJRR.

---

## 5 · Fault Availability — the central finding

> **No public dataset of labelled real automotive sensor faults was located.**

The search returned fault *simulation* frameworks, patent literature, and unlabelled driving logs —
but no automotive analogue of ALFA. This is a **negative result about the field**, and it has two
consequences:

1. **Type A automotive evidence is unavailable.** ASTRA cannot obtain real labelled automotive
   sensor faults from public data, so **no detection-rate claim on real automotive faults is
   possible**, by anyone, with current public data.
2. **Controlled injection into real logs (Type B) is the only viable route**, and the paper must say
   why: not convenience, but the absence of a Type A alternative. Stating that turns a weakness into
   a documented constraint on the field.

### Type classification

| Dataset | Type | Reason |
|---|---|---|
| comma2k19 | **B — strong** | real low-level sensors, clean reference retained, injection well-defined |
| ALFA | **A — cross-domain** | real labelled faults, wrong platform |
| Oxford RobotCar, KITTI, NCLT | B | real sensors, no faults |
| Perception datasets | **E** | not suitable |

---

## 6 · Controlled Fault Injection Analysis — comma2k19

| Question | Answer |
|---|---|
| Which fault kinds? | **All five implemented kinds** — DROPOUT, BIAS, DRIFT, STUCK_AT, NOISE_BURST |
| Which channels? | position (from GNSS), speed (from CAN), lateral acceleration (from IMU) — matching `FaultChannel` exactly |
| At which level? | **raw measurement, before L1** — identical to the synthetic injection point |
| Before or after calibration? | **before** — the injector sits at the sensor boundary in both |
| Consistent across runs? | ✅ deterministic; the log is fixed, only the perturbation varies |
| Clean reference? | ✅ **the unmodified log is the paired control** — this is the key property |
| Reproducible? | ✅ segment id + fault spec + seed fully determines the run |

**The injection point matches the synthetic one exactly.** That is what makes the comparison
meaningful: the same injector, the same fault specs, different underlying sensor statistics.

---

## 7 · Sensor Pipeline Compatibility — which stages comma2k19 can reach

| Stage | Record field | Reachable? | Why |
|---|---|:--:|---|
| L1 sensing | `frame_health` | ✅ | raw IMU/GNSS/CAN with timestamps |
| L2a innovation | `fast_innovation` | ✅ | UKF runs on real measurements |
| L2b state | `fast_state` | ✅ | filtered estimate |
| L3 trust | `trust` | ✅ | derived from innovation |
| L4 proposal | `proposal` | ✅ | **the logged openpilot command is the proposal** |
| L5 prediction | `prediction` | ❌ | the twin was trained on synthetic kinematics; running it on real data measures **twin transfer error**, not fault discriminability. Confounded |
| L6/L7a/L7b | `gate_verdicts` | ⚠️ PARTIAL | gates execute, but thresholds and the conformal corpus were calibrated synthetically |
| L8 fail-safe | `failsafe` | ⚠️ PARTIAL | driven by upstream signals that are themselves partial |
| L9 arbitration | `issued` | ❌ | open-loop replay; no actuation, no consequence |

**Five of nine stages cleanly reachable.** Crucially, **L1 → L2a → L2b → L3 spans the claimed
collapse point**, which is where C1 lives.

---

## 8–9 · Ground Truth, Temporal Integrity, Calibration

**Ground truth:** fused pose, adequate as the clean reference for a paired design. **No fault
labels** — the injected fault *is* the ground truth, which is exactly why injection is needed.

**Temporal integrity — UNKNOWN and blocking.** Timestamp precision, inter-sensor synchronisation,
dropped-frame rate and clock drift are **not verified**. ASTRA's L1 classifies staleness against a
50 ms budget, so **timestamp quality directly determines whether L1's health signal is meaningful on
this data.** This is the single most important unverified property and it is the first item in the
go/no-go gate.

**Calibration — UNKNOWN.** Sensor-to-vehicle transforms not confirmed. Impact: moderate. ASTRA needs
position, speed and lateral acceleration in a consistent frame; a missing extrinsic would bias the
fused position and inflate L2 residuals, confounding `D_L2`.

---

## 10 · Licensing and Access

**comma2k19 — MIT ✅.** Commercial use permitted, redistribution permitted, derived data permitted,
no publication restriction, no registration barrier. Hosted on GitHub and HuggingFace.
**This is the strongest licence of any candidate and it also permits the industry demonstration.**

**ALFA** — licence UNKNOWN; from CMU Robotics Institute, published in IJRR. Verify before use.

---

## 11 · Windows 11 / 8 GB GPU Feasibility

| Requirement | Assessment |
|---|---|
| GPU | **None needed.** Replay is CPU-only; no perception model runs |
| VRAM | not a constraint |
| Storage | **UNKNOWN — must verify.** Camera data dominates and is **not needed**; if segments can be fetched without video, the footprint drops sharply |
| Windows compatibility | HuggingFace access is platform-neutral; no Linux-only toolchain identified |
| Preprocessing | numpy only — already installed |
| Runtime | replay of 2,019 one-minute segments at 20 Hz is CPU-bound and parallelisable |

**Mitigation if storage is prohibitive:** use a **stratified subset of segments** with the sampling
rule declared in advance. A subset is scientifically acceptable; a subset chosen after seeing results
is not.

---

## 12 · Reproducibility

Stable versioned hosting ✅ · official paper ✅ · MIT licence ✅ · fixed segment identifiers ✅.
Another researcher can obtain identical bytes. **Reproducibility is the strongest property of this
candidate after its licence.**

---

## 13 · Claim-to-Dataset Mapping

| Frozen claim | comma2k19 | ALFA | Note |
|---|:--:|:--:|---|
| **C1** discriminability collapses at a stage | ✅ **partial** | ⚠️ | L1→L3 covers the claimed collapse point |
| **C2** `D_s`, `R_s` computable | ✅ **partial** | ⚠️ | 5 of 9 stages |
| **C2** `A(f)` estimable | ⚠️ **partial only** | ❌ | see §22 |
| **C3** `A(f)` predicts placement | ❌ | ❌ | needs all stages incl. gates |
| **H8** MDS placement-dependent | ✅ | ❌ | severity sweep transfers |
| Real sensor-noise FP rate | ✅ **yes — the headline** | ❌ | the one thing only real data gives |
| OD-8 persists on a real corpus | ✅ | ❌ | recalibrate from real scores |
| Detection rate on real faults | ❌ | ✅ but aerial | no Type A automotive exists |
| Closed-loop consequence | ❌ | ❌ | CARLA only, `[M-sim]` |

---

## 14–15 · Ranked Scores and Top 5

Weighted: relevance 25 · fidelity 20 · injection 15 · ground truth 10 · pipeline 10 · reproducibility
5 · licence 5 · statistics 5 · industry 5.

| Rank | Dataset | Score | Role |
|--:|---|--:|---|
| **1** | **comma2k19** | **79** | **Primary external validation** |
| 2 | Oxford RobotCar | 54 (UNKNOWN-limited) | Independent replication |
| 3 | ALFA | 48 | Fault-focused, cross-domain |
| 4 | Boreas | UNKNOWN | Adverse-condition candidate |
| 5 | KITTI raw | 46 | Backup |

comma2k19 is not first because it is well known. It is first because it is the **only verified
candidate carrying raw GNSS, a 9-axis IMU and the logged command stream under a permissive licence** —
and the logged command being the proposal is what removes the need to retrain anything.

---

## 16–17 · Primary and Secondary

**Primary — comma2k19.** Answers the question the simulator cannot: *do the monitors behave the same
way under real sensor noise and real command distributions?*

**Secondary — Oxford RobotCar, conditional on verification.** Justified **only** if it provides
independent evidence: different vehicle, different sensor suite, different geography, different
conditions. If it merely duplicates highway driving with similar sensors, **do not use it** — a
second dataset that repeats the first adds pages, not evidence.

**ALFA — supporting, cross-domain, strictly bounded.** It may support a claim about *fault-detection
method* under real labelled faults. **It may not be used as evidence that ASTRA works on road
vehicles.** Aerial actuator faults are not automotive sensor faults.

---

## 18 · Real-World Validation Protocol (E13)

**Input:** comma2k19 segments, stratified sample, sampling rule declared in advance.

**Design — paired, on identical trajectories:**
```
segment S  →  clean replay      →  D_s^clean
segment S  →  injected replay   →  D_s^faulted        same segment, same tick alignment
```
Pairing on the same real trajectory removes ordinary driving variability as a confound. This is the
strongest available design given no natural faults exist.

**Injection point:** raw measurement, before L1 — identical to synthetic.
**Fault classes:** all five kinds × three applicable channels.
**Severity:** the §15.1 ladder, unchanged, so synthetic and real are directly comparable.
**Stages measured:** L1, L2a, L2b, L3, L4. L5 and L9 excluded with reasons stated.
**Repetitions:** ≥ 30 segments per (fault, severity); segment is the unit of analysis.
**Controls:** the unmodified segment.
**Baselines:** ASTRA vs Simplex on identical replays.
**Statistics:** DeLong for paired AUC between adjacent stages; Wilson intervals for FP rate; BH
across stages.

**Expected:** if C1 is real, `D_L2 < D_L1` on real logs as it is on synthetic.
**Falsified if** `D_L2 ≈ D_L1` on real data while collapsing on synthetic — which would mean the
collapse is an artefact of the synthetic plant. **That is the result the paper most needs to test.**

---

## 19 · Statistical Validation

Unit: **the segment**, never the sample. comma2k19 segments are one minute at high rate — treating
samples as independent would be pseudoreplication of the worst kind.

Temporal autocorrelation within a segment is handled by the segment-level unit. Segments from the
same drive are **not** independent; block by drive, not by segment, where drive identity is
recoverable.

---

## 20 · Dataset Red-Team

**"Why is this real-world evidence if you inject the faults?"**
The *sensor statistics, command distribution and vehicle dynamics* are real; only the perturbation is
synthetic. The claim is scoped accordingly: behaviour of monitors under real sensor noise, not real
fault prevalence. **And no Type A automotive dataset exists** — §5 documents the search.

**"Are the faults real?"** No, and the paper says so in the same sentence it introduces them.

**"Enough ground truth?"** Fused pose only. Sufficient for a paired design, insufficient for
detection rate on natural faults — which is not claimed.

**"Is the pipeline representative?"** Partially. Five of nine stages. §7 states which and why.

**"Could the result be dataset-specific?"** Yes — hence the secondary dataset, conditional on it
being genuinely different.

**"Could the result be caused by the injection mechanism?"** The strongest attack. **Mitigation:**
the same injector runs on synthetic and real. If the collapse appears on synthetic but not real, the
injector is not the cause — the plant is.

**"Could it be calibration artefacts?"** Possible; calibration is UNKNOWN. **Mitigation:** compute
`D_s` on clean segments first; a non-trivial `D_s` between two clean replays would expose a
calibration or determinism problem before any fault is injected.

---

## 21 · GO / CONDITIONAL GO / NO-GO

### **CONDITIONAL GO** for comma2k19

**Satisfied ✅** — licence (MIT), access, raw sensors, clean paired reference, injection well-defined,
reproducibility, Windows/CPU feasibility, ≥ 1 frozen claim supported.

**Unverified — must clear before commitment:**

```
[ ] Timestamp precision and inter-sensor synchronisation   ← BLOCKING
[ ] Download size and whether video can be excluded         ← feasibility
[ ] Calibration / sensor-to-vehicle transforms              ← confounding
[ ] Drive identity recoverable for blocking                 ← statistics
```

**NO-GO trigger:** if timestamps are too coarse for a 50 ms staleness budget, **L1's health signal
cannot be evaluated on this data**, and comma2k19 supports only L2–L3. The claim then narrows to
"the collapse at the estimator persists on real data" — still valuable, but C1's upstream half is
unverifiable and the paper must say so.

---

## 22 · Can comma2k19 support `A(f)`? — mandatory answer

> **Partially, and the limitation must be stated explicitly in the paper.**

`A(f)` = the first stage where `D_s < 0.60`, defined over the full nine-stage pipeline. comma2k19
reaches five stages cleanly. Therefore:

- **If the collapse occurs at L2** — the hypothesis — `A(f)` is **estimable**, because L1, L2a, L2b
  and L3 are all reachable and the transition is inside the observable window.
- **If the collapse occurs later**, at L5 or a gate, `A(f)` is **not estimable** on this dataset.

**Required wording, to be used verbatim:**

> *comma2k19 validates fault discriminability across the sensing, estimation and trust stages. It
> does not span the full pipeline, so `A(f)` is estimated over a restricted stage set and is
> reported as a lower bound on the absorption point.*

Do not force the dataset beyond this.

---

## 23 · Evidence Separation

```
[M-syn]  synthetic plant   all 9 stages, full A(f), full C3
[M-ext]  comma2k19         5 stages, partial A(f), real sensor noise      ← the only external row
[M-sim]  CARLA             closed-loop consequence, not external validity
```

**Never combined into one validation number.** Three markers, three tables, three scopes.

---

## 24 · Final Recommendation

**Primary: comma2k19.** MIT-licensed, raw GNSS + 9-axis IMU + CAN, the logged command serves as the
proposal so nothing needs retraining, and the unmodified log is a paired control. **CONDITIONAL GO**
pending the four verifications in §21.

**Secondary: Oxford RobotCar**, only if verification shows it is genuinely different.

**Fault strategy: controlled injection**, because §5 establishes that no labelled automotive
sensor-fault dataset exists publicly. That absence is itself worth one sentence in the paper.

**Claims supported:** monitor FP rate under real sensor noise · whether the L1→L2 discriminability
collapse persists on real logs · whether OD-8 survives a real score distribution · partial `A(f)` as
a lower bound.

**Claims NOT supported:** detection rate on natural automotive faults · real-world fault prevalence ·
closed-loop consequence · intervention benefit · full `A(f)` · C3.

**Effort:** ~5 days — 1 verification, 1 acquisition, 2 replay harness, 1 analysis. CPU only.

**Risks:** timestamp quality (blocking) · storage · calibration unknowns · single-geography bias
(highway only, one corridor, one vehicle).

**Backup:** KITTI raw via OXTS if comma2k19 fails the gate. Weaker — shorter sequences, no logged
command stream — so the proposal slot would have to be reconstructed, which weakens the design.

**If both fail:** the paper narrows honestly to the simulated plant, and the title, abstract and
conclusion narrow with it. **CARLA is not a substitute.**

---

**Sources verified this session:** [comma2k19 paper](https://arxiv.org/abs/1812.05752) ·
[comma2k19 on HuggingFace](https://huggingface.co/datasets/commaai/comma2k19) ·
[ALFA paper](https://arxiv.org/abs/1907.06268) ·
[ALFA at CMU RI](https://publications.ri.cmu.edu/alfa-a-dataset-for-uav-fault-and-anomaly-detection)
