# 28 · Current status

Where the project stands as of **16 August 2026**. Written to be read by someone
deciding whether to trust it, so the uncomfortable numbers come first.

---

## 28.1 · The four numbers that matter most

| | | |
|---|---|---|
| **`[M-ext]` claims** | **0 of 30** | Nothing measured against an external reference |
| **Gates that ever veto** | **1 of 3** | Physical 149, statistical 0, deterministic 0 across 2,800 fault-suite ticks |
| **Register** | **3 open** of 21 | 16 closed, 1 reclassified, 1 partly closed |
| **Quality gate** | **green** | 3,042 tests + 3 strict xfail (`E-1`) |

**[INTERPRETATION]** Read together: the engineering discipline is in good shape
and the **evidence base is not**. A green gate over 166 files says the code does
what its tests say; it says nothing about whether the system works on a road.

---

## 28.2 · What exists and runs

### The nine layers — all built

| Layer | State |
|---|---|
| L1 sensing | Built. Three-channel median fusion, residual monitor, per-modality `StreamHealth` from freshness |
| L2 estimation | Built. UKF, packed symmetric covariance, no NumPy in the kernel. Sigma points redrawn after process noise (ADR-0032) |
| L3 trust | Built |
| L4 proposal *(Core-A)* | Built. Constrained PPO policy |
| L5 twin | Built. PINN, one head per context (ADR-0019) |
| L6 statistical gate | Built — **and cannot currently fire** (OD-8) |
| L7a deterministic gate | Built. **Zero vetoes** across the fault suite; `[OPEN]` |
| L7b physical gate | Built. Carries all 149 vetoes, on one reason code |
| L8 fail-safe | Built. Two counters, four postures, capability withdrawal axis, health-level ceiling, per-modality decay |
| L9 arbitration | Built. Sole actuation authority |

### Supporting machinery

- **Audit** — `DecisionRecord` per tick, hash-chained JSONL, **schema v10**
- **Config** — no defaults for safety thresholds (A-4), `extra="forbid"`, config
  hash on every row
- **Composition root** — accepts a platform rather than *being* one (ADR-0034)
- **Explainer** — `astra explain`, 95.2% covered after shipping at 10.3%
- **Dashboard** and interactive fault injection
- **Benchmarks** — fault study, degradation table, whiteness, exchangeability,
  gate census, ablation, ASTRA-vs-raw-Core-A
- **Artefact pipeline** — `make artifacts` and `make artifacts-check`, the latter
  **driving** the artefacts rather than checking they exist

### The quality gate, in detail

**3,042 tests + 3 strict xfail** · `ruff` + `mypy --strict` over **166 files** ·
**12 import contracts**, 0 broken · coverage **97.56%** with a **per-file floor at
80%** (`E-1`, `E-133`).

The floor sits far below the aggregate deliberately: its job is to catch a module
with *no* tests, not to chase branches. It exists because `astra explain` shipped
at 10.3% behind a green aggregate gate (`E-123`).

---

## 28.3 · The three open register rows

### OD-8 — the live loop is not exchangeable with its corpus · **the blocker**

Live scores at **1.156**, below the corpus **minimum** of 1.158; the whole
`HIGHWAY_CLEAR` distribution spans 1.158–1.189 over 1,000 samples. **Zero
overlap.**

Survived regeneration with the gap **widened**. The 0.089% veto rate is that
mismatch, not evidence the gate discriminates.

**Not fixable in-house** — the corpus and the loop are both things this project
wrote.

### OD-11 wall 3 — the process model cannot represent a differential-drive platform

Held as a **strict xfail**. L2 derives yaw rate from `a_lat / v` and refuses below
a minimum speed. *"Unlike walls 1, 2 and 4 it cannot be fixed by moving a
symbol."* Deferred by explicit decision.

### OD-11 wall 4 — the rename

Needs a genuine second **domain**, not a better car, plus a third regeneration.
Deferred by explicit decision.

### And one partly closed

**OD-9** — the common-cause estimate. One third closed: the health map now bypasses
L2 and cuts a frozen-IMU departure from 4.199 m to 0.167 m. The remaining two
thirds — a stream publishing fresh, well-formed, **wrong** values — is what
redundancy addresses for bias and does not address for slow drift.

---

## 28.4 · The evidence base, honestly

| Marker | Count | What it means |
|---|---|---|
| `[M-ext]` | **0 of 30** | Measured against an external reference |
| `[M-syn]` | most | Measured, in an environment this project wrote |
| `[M-code]` | several | A property of the code, tested |
| `[E]` | several | Argued from evidence |
| `[NOT DONE]` | some | Claimed and not built |

**Three retractions stand on the record**, all from 15 August: `E-143` (a 7.35×
figure from a vehicle with every tick vetoed and speed zero), `E-145`/`E-146` (a
missing-artefact claim from a truncated `ls`), `E-161` (`100% inside` from one
sample). Each produced a **guard**, not a note.

**One withdrawn contribution:** EnbPI, the paper's stated method. No ensemble was
ever built; `ensemble_size` was deleted from the schema.

---

## 28.5 · Decisions and documents

**34 ADRs.** The most recent five, all from this month:

| | |
|---|---|
| 0030 | The health level caps how far the posture may escalate |
| 0031 | Decay measures the duty cycle — the counter cancels out |
| 0032 | Sigma points are redrawn after process noise is added |
| 0033 | Redundancy is the driven path, not a measurement beside it |
| 0034 | The composition root accepts a platform instead of being one |

**10 separation invariants**, each with a stated enforcement kind **asserted by a
test** — because SI-6 was documented as review-only for four weeks after the code
changed.

**10 assumptions**, each with what breaks if it is wrong.

**Threat model** — including T1′ (two coordinated liars invert the monitor) and T4
(a compromised process, explicitly out of scope).

**Paper adherence** — seven disagreements between the paper and the code
documented; six specified but unapplied, because the paper is not in this
repository.

---

## 28.6 · What was completed most recently

The work between 11 and 16 August, in order:

1. **Capability withdrawal** (ADR-0029) — a second axis; 21 tests; provably
   additive, all 2,958 pre-existing tests untouched
2. **Health-level ceiling** (ADR-0030) — a high-water mark bounding escalation
3. **Sensor decay** (ADR-0031) — per-modality EMA converging to a fault's duty
   cycle, reported in every audit row, driving nothing
4. **ADR-0032** — the sigma-point redraw. Fixed a real filter defect, made two
   strict xfails flip to XPASS, and cost lane-keeping performance because the old
   filter was over-confident
5. **ADR-0033** — redundancy on the driven path. Repaid ADR-0032's cost with
   margin
6. **ADR-0034** — the composition root's platform seam
7. **Four new benchmarks** — degradation, whiteness, exchangeability, gate census
8. **Paper hygiene and the threat model**
9. **`docs/CARLA_PLAN.md`** and `docs/DATA_SPLIT_PROTOCOL.md`
10. **This A–Z knowledge base** — 29 of 31 sections at the time of writing

Schema version moved **8 → 9 → 10** across that work, each step forced to be a
deliberate decision by a test that has now fired seven times.

---

## 28.7 · What is deliberately *not* done

Distinguish **not yet** from **decided against**:

| | Status |
|---|---|
| Hardware | **Never.** Out of scope by design |
| FB2 twin adaptation | **Refused**, with a measurement — score fell 40% in an unchanging context |
| FB3 corpus self-calibration | **Refused**, with a measurement — veto rate converges to ε regardless of whether anything is wrong |
| FB4 | Unbuilt |
| Per-gate override list in config | **Refused** — would turn *"which gate may be overruled"* into a value a deployment can edit |
| Weighting modalities | **Refused** — nobody can defend *"the camera is worth 0.4 of an IMU"* |
| Certification artefacts | Not yet. ISO 26262 work item |
| Latency measurement | **Not yet, and it should have been done first** |

---

## 28.8 · Honest summary in five sentences

The architecture is **complete and runs**, and its structural guarantees — the
trust boundary, the fail-closed merge, the refusal-not-repair rule, sole actuation
authority — are real and hold regardless of plant.

The **measurements are all internal**, and the plant, process model, twin and
corpus are the same bicycle model, so agreement between them is not evidence.

The statistical gate **cannot currently fire**, and the deterministic gate does not
fire either for reasons that are not yet understood, so one gate is carrying the
architecture.

The **engineering discipline is unusually strong** — executable invariants, a
schema pinned by a test, a per-file coverage floor, guards produced by every
retraction — and this is the part a company could use immediately.

The next step is not more internal work: it is **an environment this project did
not write**.

---

**Next:** `29_REMAINING_WORK/`.
