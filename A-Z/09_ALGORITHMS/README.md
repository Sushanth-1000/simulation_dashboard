# 09 · Algorithms

Each algorithm answered twelve ways, per the brief: *what problem · why needed ·
what without it · theory · mathematics · implementation here · inputs · outputs ·
assumptions · failure modes · alternatives · why selected.*

**Prerequisite:** `10_MATHEMATICS/`. This section uses that vocabulary without
re-deriving it.

---

# A1 · The Unscented Kalman Filter

### 1 · Problem it solves

Turn noisy, partial, differently-timed sensor readings into one coherent estimate
of vehicle state — **with a defensible uncertainty attached**.

### 2 · Why it is needed

Every layer above L2 reasons about state, not readings. And L6 divides by the
filter's uncertainty, so a filter that produced only a point estimate would leave
the statistical gate with no denominator.

### 3 · Without it

Each gate would consume raw sensor readings and reconcile them itself. Three
reconciliations, three disagreements, and SI-1 (sensor opacity) gone.

### 4 · Theory

See `10_MATHEMATICS` §10.3–10.4. Predict-update, with sigma points instead of a
Jacobian.

### 5 · Mathematics

Given in `10_MATHEMATICS` §10.4, verbatim from the source.

### 6 · Implementation here

`src/astra/layers/l2_estimation/unscented.py` — **first-party**, ~200 lines,
NumPy only.

**Dual-rate:** a fast filter at 20 Hz over `[px, py, v, ψ, a_lat]`, and a slow
filter over `[road_friction, tyre_wear, sensor_health]`.

**The deliberately-unimproved detail** **[FACT]**: the gain is computed as
`Pxz @ inv(S)` — inverting explicitly — rather than `np.linalg.solve`, which
would be better conditioned.

> That is on purpose. Replacing a library **and** improving its numerics in the
> same change makes any difference in the results unattributable to either — and
> this filter's outputs are what `EVIDENCE.md` rests on, down to veto counts that
> are threshold crossings and can flip on the last bit.

### 7 · Inputs
A `FusedSensorFrame`; `Q`, `R` from configuration; the last issued command (FB1).

### 8 · Outputs
`FastStateEstimate` — mean and covariance — plus an `InnovationRecord`.

### 9 · Assumptions

- Noise is **additive and Gaussian**
- The process model describes the platform — **a bicycle model**, which is
  **OD-11 wall 3** and cannot be fixed by moving a symbol
- Measurements are **independent** given the state — which redundancy makes
  approximately true and correlated sensor failure breaks

### 10 · Failure modes

| Mode | What happens |
|---|---|
| Covariance loses positive-definiteness | Cholesky raises → `SafetyPathError` → **VETO**. Deliberately uncaught |
| A **self-consistent lie** | The filter grows *confident* in it; the error is pushed into an unobserved state. True heading 0.0686 rad, estimate 0.0017 (`E-58`) |
| No measurement | Predicts without correcting; covariance grows. **Correct behaviour**, and it makes L6 more permissive |
| Model mismatch | Systematic bias in the estimate; no internal signal |

### 11 · Alternatives considered

| Alternative | Why not |
|---|---|
| **EKF** | Requires hand-derived Jacobians; first-order only |
| **Particle filter** | Handles arbitrary distributions; far more expensive, and the 20 Hz budget is 10 ms |
| **FilterPy's UKF** | **Used, then removed** — unmaintained since 2018, inside the safety path where ISO 26262 wants a qualification argument, and dragging scipy → matplotlib → pillow for two classes |
| **Complementary filter** | Cheap; **no covariance**, so L6 loses its denominator |

### 12 · Why selected

Accuracy of a particle filter's neighbourhood at a Kalman filter's cost, no
Jacobians, and — decisively — **it produces the covariance the rest of the
pipeline consumes**.

---

# A2 · Mondrian Inductive Conformal Prediction

### 1 · Problem

Decide whether a proposal is unusual **for this kind of situation**, with a
guarantee that does not depend on any model being correct.

### 2 · Why needed

Every other uncertainty method asks the model to grade itself (§2.2 of the
problem section). Conformal grades against **recorded reality**.

### 3 · Without it

The gate would need a hand-tuned threshold on the departure, and there would be
no argument for the number beyond *"it seemed about right"*.

### 4 · Theory

Rank the new score against a calibration population; flag it if it exceeds the
⌈(n+1)(1−ε)⌉-th smallest. Distribution-free. **Mondrian** = one population per
context class.

### 5 · Mathematics

`10_MATHEMATICS` §10.5–10.6, including the two quantile subtleties.

### 6 · Implementation

`l3_trust/quantile.py`, `mondrian.py`, `corpus.py`; the gate in
`l6_statistical_gate/gate.py`.

The corpus is generated offline by `training/generate_calibration.py`, targets
**1,000 samples per class**, and carries its own provenance: a twin-weights
digest, a config hash and a seed — so a corpus can be checked against the system
that produced it.

### 7 · Inputs
Proposal, twin prediction, `P_f` at the control dimension, context class, corpus.

### 8 · Outputs
PASS, VETO, or ABSTAIN (uncalibrated class) with a reason code.

### 9 · Assumptions

- **Exchangeability** — the whole guarantee. **Currently violated** (`OD-8`)
- The context classifier assigns the right class — **`RAIN_NIGHT` is undecidable**
- ≥ ⌈(1−ε)/ε⌉ calibration samples exist, else the threshold is correctly `∞`

### 10 · Failure modes — all three measured

| Mode | Measured |
|---|---|
| Corpus describes an **older system** | Closing FB1 drove the veto rate 59.8% → 99.8% with no policy change |
| Corpus built from the **wrong source** | Threshold moved 1.18 → 2.43; the shipped value had been less than half what the system produced (`E-20`) |
| **Nothing changed and it went stale anyway** | Live 1.156 vs corpus minimum 1.158 (`E-41`); re-measured 15 Aug as **zero overlap** (`E-159`) |
| **Silent when wrong** | Scores below the threshold ⇒ **0 vetoes**, which looks healthy (`E-162`) |

### 11 · Alternatives

| Alternative | Why not |
|---|---|
| **EnbPI** (the paper's stated contribution) | **Never implemented.** Requires an ensemble that does not exist; `ensemble_size` was config nothing read, and was deleted 15 Aug |
| Fixed threshold | No guarantee, no argument for the number |
| Bayesian credible interval | Requires the model to be well-specified — the thing not assumable here |
| **Global (non-Mondrian) conformal** | Compares highway against urban; both mildly unusual, neither flagged |

### 12 · Why selected

The only method offering a coverage guarantee **without trusting the model**.
The honest caveat: that guarantee is currently unavailable because its
precondition is not met.

---

# A3 · The Physics-Informed Neural Twin

### 1 · Problem
Predict `(state, command) → next state`, so a gate can judge the **consequence**.

### 2 · Why needed
Converts *"does this command look sensible?"* into *"is what it does sensible?"*.

### 3 · Without it
L6 has nothing to compute a departure from, and L7b loses its divergence check.

### 4 · Theory
A network trained on transitions, with a **physics term** in the loss penalising
violation of the kinematic relations. The physics acts as a regulariser and pulls
predictions toward consistency where data is thin.

### 5 · Mathematics
`loss = data_loss + λ · physics_residual`. **[UNVERIFIED]** the exact residual
form was not read while writing this; see `l5_twin/network.py`.

### 6 · Implementation — and the architectural decision

**One output head per context class** (ADR-0019), sharing a trunk.

This *superseded in effect* ADR-0018's **elastic weight consolidation** — a
penalty discouraging movement of weights important to earlier contexts.

> Per-context heads make forgetting **structurally impossible** rather than
> penalised.

**[INTERPRETATION]** A recurring shape in this project: replace a *penalty that
discourages* a failure with a *structure that cannot express* it. The same move
appears in SI-5 (type error, not rule) and ADR-0029 (intersection, so withdrawal
cannot grant).

### 7 / 8 · Inputs and outputs
State, proposed command, context class → predicted next state.

### 9 · Assumptions
The training distribution covers deployment; contexts are correctly classified;
**the plant it learned is the plant it faces** — false against CARLA by design.

### 10 · Failure modes

- **Trained on the same bicycle plant as everything else** — generator and judge
  agree by construction
- **FB2 would have destroyed its independence**: its only labels are the
  proposer's commands, so the twin regresses onto the thing it exists to be
  independent of. Score fell **40%** in an unchanging context (`E-39`). Never wired
- **[FACT** — CARLA prediction P2**]** expected to be badly wrong against a
  simulator with suspension, tyre slip and drivetrain lag

### 11 · Alternatives
An analytical model (accurate only where the model is); a lookup table (no
generalisation); **EWC** (tried, superseded); no twin at all (loses two gates).

### 12 · Why selected
It generalises where an analytical model would not, and the physics term keeps it
honest where data is thin.

---

# A4 · Constrained PPO (the CMDP proposer)

### 1 · Problem
Learn a driving policy that maximises performance **subject to explicit budgets**.

### 2 · Why needed
It is the untrusted thing being governed.

### 3 · Without it
Nothing to govern — and the governance would be untested against a real
adversary.

### 4 · Theory
PPO improves a policy in small, clipped steps. The **constrained** variant keeps
cost budgets separate with Lagrange multipliers **adapted from the costs the
current policy actually realises**.

### 5 · Mathematics
Maximise `E[reward]` s.t. `E[cost_i] ≤ budget_i`, via the Lagrangian
`reward − Σ λ_i (cost_i − budget_i)` with `λ_i` adapted upward while violated.

### 6 · Implementation
`training/train_policy.py` — PPO via Stable-Baselines3, **48 rounds ×
16,384 steps**. Budgets: lane deviation 0.875 m, longitudinal acceleration
4 m/s², collision rate 0.

### 7 / 8 · Inputs and outputs
Observation → command vector. **Never an `IssuedCommand`** (SI-7).

### 9 · Assumptions
The training environment resembles deployment — **known false** in two ways
(§10).

### 10 · Failure modes

- **[FACT** — `E-155`**]** it trains against `SyntheticDrivingEnv` **directly**:
  no pipeline, no UKF, no sensor bus. It has only ever seen **ground truth** and
  is deployed against an **estimate**. **[OPEN]** — the cost is unmeasured
- **C-2** — the plant integrated **2.5× faster** than the controller
  (`step_seconds` 0.02 vs a 0.05 tick), and *the docstring said 0.05*. **Every
  policy trained before 5 August was invalidated**
- **C-3** — a reward term ~500× too small produced a policy that **stopped the
  vehicle** and collected the stationary reward

### 11 · Alternatives
Unconstrained RL with penalties (**C-3 is the measured failure of exactly this**);
classical MPC (needs a model good enough to optimise against — the thing not
assumable); a hand-written controller (would not be an untrusted proposer, and
would not test the governance).

### 12 · Why selected
Constraints stay legible as budgets a safety engineer can read, rather than
disappearing into a weighted sum.

---

# A5 · Median fusion with a residual monitor

### 1 · Problem
Detect and survive a channel that lies fluently.

### 2 · Why needed
`StreamHealth` is computed from **freshness** — a fresh, well-formed, wrong
reading is `HEALTHY` for ever. Four detectors built on a single chain all failed
(§A6).

### 3 · Without it
OD-9's bias and drift cases stay open. Before ADR-0033 the bus published **one
payload byte-identical to all five modalities** — five modalities carrying one
sensor.

### 4 · Theory
With three channels, the **median** is robust to one arbitrary value. Then
`residual_i = reading_i − median` **cancels the truth term exactly**, so the
statistic measures *disagreement between sensors* and nothing else.

### 5 · Mathematics
`median(a,b,c)` — outvote one liar. `residual = reading − median`.
Verified: readings at true positions 0.0 m and 7.5 m with the same noise draws
give residuals equal to **5e-17** — algebraically identical (`E-111`).

**That invariance is what the earlier candidates lacked** — cross-channel
consistency measured a *quantity*, so a large legitimate correction moved it and
it reported the manoeuvre as a fault (`E-106`).

### 6 · Implementation
`training/redundant.py`. Three channels, **deliberately unequal** noise —
IMU 0.10, GPS 0.20, LIDAR 0.06 — because *identical sigmas model identical
sensors, and identical sensors share a failure mode*. `RESIDUAL_LIMIT = 0.45 m`,
`PATIENCE = 10` ticks.

### 7 / 8 · Inputs and outputs
Three readings → a fused position, and a `StreamHealth` per channel — the first
real producer of `FAULTED` in the project's life (`E-114`).

### 9 · Assumptions
**At most one channel lies**; failures are **independent**; ≥3 channels exist.

### 10 · Failure modes — and the worst one in the threat model

`n ≥ 2f+1` for crash faults, **`n ≥ 3f+1` for Byzantine**. With `n = 3`, two
coordinated liars are tolerated **zero** times — and it is an **inversion**, not
a gap:

> With two compromised channels agreeing, **the median is the lie**, so the
> monitor flags the **honest** channel, names it, and writes it to the evidence
> log.

Every other entry in the threat model degrades toward *silence*; this one
degrades toward **a false positive that looks like a successful detection**
(threat `T1'`).

Also: `tolerated_faults = 0` in every shipped profile, so silencing **one**
channel is a two-second denial of service.

### 11 · Alternatives
Kalman-fuse all three (the liar's error enters the estimate weighted, not
excluded); mean instead of median (**one outlier moves the mean without bound**);
pairwise cross-checks (with two channels you know something is wrong, not which).

### 12 · Why selected
It **outvotes** rather than *averages*. Measured: a 1 m bias in one channel gives
a final deviation of **0.0168 m — the clean run's figure to four decimals**
(`E-153`).

---

# A6 · The five detectors that failed

Kept because they are evidence *for* redundancy.

| # | Detector | Measured result |
|---|---|---|
| 1 | **Innovation sequence** magnitude | 1 cm/tick against σ = 0.1 m is well inside the band; never leaves it (`E-53`) |
| 2 | **Innovation gate flag** (γ = 7.5) | Fires on **tick 0 of every arm including the control** — the plant's 1 m initial offset — and on nothing else (`E-105`) |
| 3 | **Analytical redundancy** from commands | The parity residual is **2.2×–4.0× larger than the fault**. FB1 feeds the command into the *prediction* step, so the two estimates were never independent (`E-94`, `E-95`) |
| 4 | **Cross-channel consistency** | Catches the bias at 4.14×; the drift at **0.99×** — indistinguishable from clean (`E-106`) |
| 5 | **Innovation whiteness / CUSUM** | Separates **1.03×** at every slack, while the bias separates 12.8–14.3× (`E-143`) |

**The shared root** **[FACT** — `E-107`**]**:

> A self-consistent lie slower than the sensor noise **cannot be distinguished
> from truth by any function of a single sensor chain.** Every quantity on the
> record is downstream of the same measurement, and no rearrangement of
> downstream quantities creates information that was never upstream.

**And detector 5 is the cautionary tale.** It initially reported **7.35×** and
`E-107` was retracted — on a run where the vehicle had **400 of 400 ticks vetoed
and a final speed of zero**. On a stationary all-vetoed vehicle the closed-loop
feedback E-107 describes does not exist, so the innovation keeps a bias a closed
loop would absorb. **The false signal was the mechanism's absence.**

**[INTERPRETATION]** Five refutations with one shared cause is a stronger result
than any single detector working would have been. It converts *"we could not find
a detector"* into *"no such detector exists in this class"* — and that is the
argument for a second sensor.

---

## You should know this before moving on

**The six algorithms**

| | Solves | Assumption that can break it |
|---|---|---|
| UKF | Fuse noisy readings, with uncertainty | Additive Gaussian noise; bicycle model |
| Mondrian ICP | Is this unusual for this context? | **Exchangeability — currently violated** |
| PINN twin | What will this command do? | Trained plant = deployed plant |
| Constrained PPO | Learn a policy within budgets | Training env resembles deployment — **false** |
| Median + residual | Survive and identify a liar | **At most one** liar; independent failures |
| — | — | — |

**Questions you should be able to answer**

1. Why does the UKF use sigma points rather than a Jacobian?
2. Why was the gain deliberately left as `inv(S)` rather than improved?
3. What single assumption does conformal prediction rest on, and is it met?
4. Why does `reading − median` measure sensor disagreement and nothing else?
5. Why is *two of three channels compromised* worse than *no redundancy at all*?
6. What do the five failed detectors have in common, and what does that prove?

**Misconception to avoid**

> *"The fifth detector nearly worked."*
>
> It appeared to, on a vehicle that never moved. Re-run on a driving vehicle it
> separates **1.03×** — indistinguishable from noise — while separating the bias
> 12.8×. The statistic works fine; the drift is invisible to it, and that was
> `E-107`'s point all along.

---

**Next:** `08_INTERNAL_MECHANICS/`.
