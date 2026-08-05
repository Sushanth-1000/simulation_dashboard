# ASTRA — Forward Work Plan

**Prepared** 1 August 2026, 22:58 IST
**Baseline commit** `833ce4d`
**Purpose** A pick-up-and-start plan for a fresh session. Every phase states what to
do, which files it touches, how to know it is finished, and the traps already
paid for.

**Ordering principle:** everything that needs no GPU and no simulator comes
first. CARLA and GPU work is Phase 7, deliberately last, because none of Phases
1–6 is blocked by it.

---

## Phase 0 — Orientation (read this first in a new session)

### Where the project stands

All ten layers exist, are composed by a tick loop, and run end to end. A trained
PPO policy drives the pipeline. FB1 is closed. The gate is green.

```
mypy --strict     Success: no issues found in 139 source files
lint-imports      Contracts: 12 kept, 0 broken
pytest            2513 passed  ·  coverage 97.97%
```

**The limitation that governs everything:** the twin, the calibration corpus and
the trained policy all descend from the same kinematic bicycle model. The
generator and the judge agree by construction, so **no false-positive or
false-negative rate exists and none can exist** until Phase 7. Every number
produced before then demonstrates that the machinery works, not that the gates
catch what they claim to catch.

### Environment — this matters, read it

**The quality gate cannot run on the Windows host.** Smart App Control blocks the
unsigned native extensions in `torch`, `mypy` and `grimp`. Use WSL2.

```bash
# in WSL2 Ubuntu
cd /path/to/astra
uv sync --all-groups --all-extras --python 3.12
uv run python -m compileall -q .venv/lib/python3.12/site-packages   # see trap 2
make check
```

`ruff` alone does work on Windows, so formatting can be applied there:

```powershell
python -m ruff format . ; python -m ruff check .
```

### Traps already paid for — do not rediscover these

| # | Trap |
|:--:|---|
| 1 | **Regenerate `uv.lock` on the machine you commit from.** It went stale twice; both times a training run found it, not the test suite. CI now runs `uv lock --check` |
| 2 | **FilterPy's docstrings emit `SyntaxWarning`**, which `filterwarnings = ["error"]` promotes to a `SyntaxError`. Whether it fires depends on whether the installer byte-compiled. `pip` does, `uv sync` does not |
| 3 | **Tests need full annotations** — `-> None` *and* typed parameters. Partial annotation is an "incomplete def" under `--strict` |
| 4 | **No function-local imports** (`PLC0415`). Hoist to module level |
| 5 | **`ProfileId` names must be 3–48 char `[a-z][a-z0-9_]` slugs.** `"a"` fails |
| 6 | **`critical_failures ≤ deployments`** and **`expires_at > certified_at`** are contract-enforced |
| 7 | **A `frozen=True, slots=True` dataclass raises `TypeError`, not `AttributeError`**, for an unknown attribute |
| 8 | **`InnovationRecord` validates finiteness at construction** — do not add redundant NaN guards downstream |
| 9 | **Closing a feedback loop invalidates the calibration corpus.** FB1 moved the placeholder veto rate 59.8% → 99.8% with no policy change. Regenerate the corpus after every loop |

---

## Phase 1 — Non-code, time-critical (do first, costs nothing)

### 1.1 The paper's validation section

**This is the only genuinely time-critical item in the project and it is not an
engineering task.**

§5 of the submitted survey describes a 21-minute CARLA drive across seven phases,
with specific observations (47 evidence tuples, gates firing in a stated order).
None of it was run. The paper was written before the prototype and the tense
slipped from *will* to *did*.

**Action:** raise it with Dr. Chaitra as the supervising author. The framing does
not need to be technical:

> *"We've been building the prototype and found that the validation section of the
> submitted paper describes experiments we hadn't actually run at the time. We've
> now built and composed all ten layers and want to correct it. What's the right
> way to handle this with the venue?"*

**Why it cannot wait:** correction, withdrawal and revised submission are all
routine before a reviewer attempts to reproduce the work, and difficult after.

### 1.2 Two claims that must be corrected regardless

`docs/changes.md` (in the survey-paper folder) specifies both edits precisely.

- **Table 1's `1.25 µs`** sits unmarked in a WCRT column beside measured figures
  from implemented systems. It is an analytical AbsInt aiT budget for RTL that
  does not exist, and it excludes L1, L2, L3, L4, L5 and L9. §3's own inclusion
  criterion excludes "back-of-envelope estimates" — the ASTRA row is one.
- **Table 1's `D(D)`** presents ASIL-D(D) as an awarded rating beside real ones.
  It is a design target; an ASIL is the outcome of an assessed safety case.

Also fix, while there: the layer numbering (§4.5.2 calls the ICP gate "Layer 5",
Figure 1 calls it "Layer 6", and three components are labelled "Layer 6"),
`\cite{altman1999}` attached to PPO instead of Schulman, `\cite{kirkpatrick2017}`
doing double duty for both EWC and the PINN, and two uncited references.

### 1.3 Documentation sync

`docs/PROJECT_STATE_AND_ROADMAP.md` still reports counts that have moved.

**Exit:** contract count, certification-field count and layer statuses match
reality. Delete or mark `docs/1144_2026-07-31_Sushanth_status.md` as superseded
by the 20:30 ledger.

---

## Phase 2 — Stability foundations

Nothing here needs new capability. It establishes whether what exists is sound.

### 2.1 Long-duration soak run — DONE, 1 Aug 2026. See [`SOAK_REPORT.md`](SOAK_REPORT.md)

> **Verdict: not stable, in either configuration.** Memory, latency, availability
> and evidence integrity all hold over 100,000 ticks — four real results.
>
> *Cold path dormant* (how every run before this was configured): the vehicle
> leaves the lane at ~tick 900 and never returns, 2.9 km out by tick 100,000,
> every tick vetoed, FSM in HALT. The deterministic placeholder fails the same
> way sooner through a different gate, so it is a property of the loop.
>
> *Cold path engaged*: the departure is replaced by a full stop at ~tick 400 that
> lasts the remaining 99,600 ticks. `SAFE_EXPLORATION` is the outcome of all
> 100,000 arbitrations **in both an open-road and a tunnel context** — no seed
> profile is reachable at τ = 0.70 — and the proposal is issued despite a
> blocking verdict on 99.8% of ticks.
>
> **The policy was also broken, and fixing it did not fix the above.** The
> checkpoint stopped the vehicle inside its *own* training environment by step
> 250 of 500. Cause: the action-rate penalty was applied to throttle and brake
> as well as steering, making a constant longitudinal command optimal — and the
> constant PPO starts from maps to half throttle and half brake, −2.5 m/s².
> Fixed (steering only, 786k timesteps); the policy now holds 13.0 m/s and the
> lane to 0.033 m, and three tests assert it. **The lane departure is unchanged.**
>
> **F1a, the real finding:** the fallback commands zero steering, so `a_current`
> goes to zero; L7b then permits at most 0.4 m/s² of lateral acceleration from
> rest; every useful correction exceeds that and is vetoed; the fallback governs
> again. The escape requires a ramp, and a proposal only moves `a_current` if it
> is executed, which it is not while vetoed. **No proposer can escape it.**
> Three policies confirm. This wants an ADR — see the report's closing list.

**The longest run in the project's history is 400 ticks — 8 seconds of simulated
time.** Nobody knows whether the closed loop is stable over minutes.

**Do:** run `training/closed_loop.py` for 100,000+ ticks overnight on CPU.
Instrument and plot: veto rate over time, mean lane deviation, dual-variable
trajectories, twin weights digest changes, resident memory, per-tick p50/p99.

**Watch for** exactly what RK-3 warns about — oscillation, slow drift,
feedback overcorrection — plus unbounded growth in any rolling window
(`MondrianCalibration`, `MmdShiftDetector`, the twin's Fisher history).

**Exit:** a plot of every metric over 100k ticks, and a written statement of
whether the loop is stable. If it is not, that is the most important finding
available right now and everything else waits.

**Files:** `training/closed_loop.py`, new `benchmarks/soak.py`

### 2.2 Evidence-pack scaffolding

**Do:** build `docs/EVIDENCE.md` as a living table — one row per claim the project
makes, with the run that produced it, the command to reproduce, and the date. Add
a section for claims explicitly **not** demonstrated.

**Why now rather than at the end:** it turns every subsequent phase into evidence
automatically instead of an archaeology exercise in month three. It is also the
artefact that most distinguishes a serious submission.

**Exit:** every number in `README.md` and both status documents traces to a row.

### 2.3 Close the residual test-quality gaps

- Confirm the L1 concurrency flake is genuinely fixed (it *hung* under 12-way
  load rather than failing; `RENDEZVOUS_TIMEOUT`/`JOIN_TIMEOUT` were added).
  Run the full suite 20× under `stress-ng` load.
- Add a **from-scratch frozen-install smoke test** to the local workflow, not
  only CI. Two lockfile defects reached commits because nothing exercised it.

---

## Phase 3 — Close the remaining feedback loops

The central claim is *closed-loop* governance and **one of four loops is wired**.
This phase takes it to four.

Bring them up **one at a time**, confirming stability before adding the next. The
roadmap is explicit that this does not compress.

### 3.1 FB2 — PINN online adaptation

The mechanism already exists in `src/astra/layers/l5_twin/twin.py`:
`adapt()`, `_consolidate()`, Fisher estimation, gradient clipping and
divergence rollback. It is **not connected to the tick loop**.

**Write the catastrophic-forgetting test first.** Not after. The test is:
highway accuracy must not degrade after adapting to rain. Without it you cannot
tell adaptation from destruction, and a confidently wrong twin produces
confidently wrong scores rather than errors.

**Known issue to resolve as part of this:** *EWC is inert at the configured λ.*
`development.toml` and `simulation.toml` set 100 and 150; the penalty only
measurably resists movement around λ≈10¹². Gradients are norm-clipped and
`(θ − θ_anchor)` is near zero right after re-anchoring, so the term is swamped by
the data and physics terms. **Either tune λ empirically until the forgetting test
passes, or rescale the penalty.** Do not ship a value that does nothing while the
configuration implies it does something.

**Expect the corpus to be invalidated** (trap 9). Regenerate after wiring.

**Exit:** forgetting test passes; corpus regenerated; per-class coverage back in
the 94.9–95.1% band; soak run repeated with FB2 on.

### 3.2 FB3 — online Mondrian requantilisation

`ConformalTrustModule.recalibrate()` exists and is tested. Wire executed outcomes
into it from the tick loop.

**Design point already settled:** `recalibrate()` deliberately ignores
`was_correct` when deciding whether to record a score. Filtering the calibration
set to outcomes that went well biases the quantile downward and produces a
guarantee about a distribution the vehicle does not drive in. **Do not "fix" this.**

**Exit:** quantiles track a deliberately shifted synthetic distribution; coverage
holds per class through the shift; corpus regenerated; soak repeated.

### 3.3 FB4 — plant synchronisation

Return the executed command to the synthetic plant so its internal state reflects
what happened rather than what was planned. Lowest risk of the four; bring up last.

Note this loop is prototype-only and has no counterpart in a real vehicle.

**Exit:** all four loops running together through a long soak without oscillation.

---

## Phase 4 — Prove the layers are worth their cost

### 4.1 Ablation study

**Do:** disable each layer in turn and measure. The `None` paths were preserved
deliberately for exactly this.

| Ablation | Question it answers |
|---|---|
| FB1 off | How fast does the state estimate drift under veto? |
| FB2 off | How far does the twin drift as conditions change? |
| FB3 off | How stale do the quantiles get? |
| L6 off (ICP only via L7a/L7b) | What does the statistical gate catch that the others do not? |
| L7a off | What does the deterministic shield catch alone? |
| L9 exploration disabled | Confirm the system halts — the behaviour ASTRA exists to avoid |

**Exit:** a table quantifying each layer's contribution. This converts *"we built
nine layers"* into *"here is what each layer is worth"*, which is the difference
between a description and a contribution.

### 4.2 The comparison harness

**The single most persuasive artefact available, and it needs no GPU.**

Two synchronised instances — full ASTRA and raw Core-A — driven from the same
seed against the same injected fault, side by side. One keeps moving; one does
not.

`drive_closed_loop` is already the substrate. Add fault injection (IMU
corruption, sensor dropout, a distribution shift the corpus has never seen) and
run both instances in lockstep.

**Exit:** a reproducible script producing a two-column result and a recorded run.

---

## Phase 5 — Make it visible

### 5.1 Dashboard

FastAPI + WebSocket backend, React + Recharts frontend, rendering the pipeline
diagram itself:

- Trust Index gauge
- **L6 and L7 as separately lit paths** — the visual proof of gate independence
- `P_f` visibly widening and narrowing the acceptance band
- FSM as a lit state diagram
- RCM's knowledge-base search, shadow execution, and a **"SAFE EXPLORATION
  ENGAGED"** banner
- Event ticker with independent-cause attribution

**Rule:** every number on screen must trace to a live `DecisionRecord`. Nothing
scripted, nothing interpolated.

### 5.2 Interactive fault injection

Let an audience press the button. It is a deliberate credibility move — a demo
where the observer chooses the fault cannot be staged.

**Also capture a pre-recorded fallback run** before any live demonstration.

---

## Phase 6 — Architectural hardening

Independent of each other; pick by available time.

### 6.1 Replace FilterPy

It was last released in **2018**, is unmaintained, sits inside the safety path,
and drags `scipy`, `matplotlib` and `pillow` into a dependency tree that ISO
26262 §8-12 will require a qualification argument for — one per package.

`stubs/filterpy/` already enumerates the exact surface depended on. It is small.
Writing your own scaled-unscented-transform UKF is roughly a weekend and removes
four packages from the safety case.

**Exit:** `filterpy` gone from `pyproject.toml`; UKF tracking accuracy unchanged
against the existing synthetic validation.

### 6.2 Test domain independence for real (assumption A-1)

**NFR5 is asserted, structurally defended, and never tested.** The claim is that a
new domain is supported by adding configuration, never by editing the core.

**Do:** add a genuinely non-automotive profile — a warehouse AGV, a two-channel
differential-drive robot — and get it through the pipeline **without touching
`src/astra/` outside adapters**. Your own assumptions register names this as the
real test.

**Exit:** either the claim is validated, or it is revealed to be
automotive-shaped. Both are valuable; the second is more so.

### 6.3 Resolve the L7a scope question

`src/astra/layers/l7_shield/shield.py:166` — `del proposal`. The Hard Safety
Shield does not evaluate the command it is given. It is a state monitor, not a
command gate.

This is a **decision, not a bug**. Two defensible answers:

- **Reactive by design**, with predictive admissibility owned by L7b. Then fix
  the docstring (line 146 claims the proposal is "carried into the verdict for
  attribution" — `GateVerdict` has no field for it) and the README sentence
  *"Every proposed command is validated three ways."*
- **It should be predictive.** Then it needs its own crude projection — **not the
  PINN**, which would collapse its independence from L5 and L7b — plus a
  `CommandProjector` seam supplied by the adapter, because turning a command into
  physics requires knowing which channel is steering, and NFR5 keeps that out of
  the core.

**Cost of deciding now: one conversation. Cost after Phase 5: the dashboard, the
tests and the ADRs all move with it.**

### 6.4 Security threat model

Currently **nothing exists**: no threat model, no signed artefacts, no key
management. The evidence log is integrity-checked but **not tamper-evident**.

Note the asymmetry worth writing down: the architecture assumes an untrusted
*proposer* on a *trusted platform*, and the second half of that has never been
examined.

Pure design work, no compute. Blocks every industrial conversation.

---

## Phase 7 — CARLA and GPU (last, and the highest-value single item)

Everything above is unblocked. This phase is last in *sequence* only — it remains
the highest-leverage thing on the roadmap, because it is the only work that
produces **non-self-referential** validation.

### 7.1 Close assumption A-8 — ten minutes, zero cost

Unverified since Phase 2: *"evidenced from published wheel metadata, not verified
by a run."*

```bash
pip install carla==0.9.16
python -c "import carla; c = carla.Client('localhost', 2000); c.set_timeout(10.0); print(c.get_server_version())"
```

The install half needs no GPU and runs on Colab free. **Do this before any other
Phase 7 work** — the entire adapter design rests on it.

### 7.2 Obtain a Linux GPU host

| Route | Cost | Notes |
|---|---|---|
| **DigitalOcean credit** (Student Pack) | **$200, already yours** | H100-class ≈ $3.4/hr → ~55 hrs. Redeem only when ready; credits have their own clock |
| **Azure for Students** | **$100, no card** | NC-series; GPU quota often needs a request |
| **Dual-boot own laptop** | **₹0, forever** | RTX 3050 6 GB. Save the BitLocker key first; check for Intel RST storage mode |
| **College GPU lab** | ₹0 | Ask. Frequently exists and is unused |

**Cost discipline at $3.4/hr:** do all setup on a $6/month CPU droplet, snapshot
it, spin a GPU droplet only for runs, destroy after. Billing alerts at $50/$150.
A forgotten droplet overnight is $27.

### 7.3 CARLA adapter

Attaches at the `MeasurementExtractor` seam — already the designated boundary,
and `.importlinter` already forbids `import carla` anywhere in the core.

**Settings:** `./CarlaUE4.sh -RenderOffScreen -quality-level=Low`. On 6 GB VRAM
this is necessary; on any GPU it makes latency measurements cleaner. **If you run
at Low, say so in the paper** — the FGSM scenario depends on camera imagery.

**Exit:** closes **RK-1b**; retires technical-debt item 1 (the UKF has met only
synthetic dynamics); enables real validation.

### 7.4 Retrain against CARLA

The twin, the calibration corpora and the PPO policy all need regenerating
against real simulated dynamics. **This is the step that produces the first
numbers the paper can honestly report as gate accuracy.**

Do not run CARLA and PPO training on the same GPU simultaneously — 6 GB will not
hold both. Sequence: rollout → save → stop CARLA → train → restart.

### 7.5 The seven-phase validation drive

Town04: highway → urban → rain/night → **tunnel (3.5)** → sensor fault →
adversarial FGSM → recovery. The vehicle never stops.

**The independence evidence lives here and nowhere else.** Validation Phase 5
(FGSM) is designed so that exactly one gate fires; Phase 4 (IMU corruption) so
that two fire for different reasons. Until those run, "three structurally
independent gates" is architecture rather than evidence.

**Report what happens, not what was predicted.** If two gates fire under FGSM, or
none do, that is the finding.

---

## Suggested order for a fresh session

1. **Phase 1.1** — the paper conversation. Not code, not deferrable.
2. **Phase 2.1** — the soak run. Start it; it runs overnight while you do
   something else. If the loop is unstable, everything else changes.
3. **Phase 3.1** — FB2, forgetting test first, and settle the λ question.
4. **Phase 4.2** — the comparison harness. Best value per hour for a demo.
5. **Phase 7.1** — the A-8 check, whenever you have ten idle minutes.

Phases 5 and 6 are parallelisable across the team; Phase 3 is not — the loops
must come up one at a time.

---

## Standing rules

- **Every metric must come from code that ran.** Nothing hardcoded to look good.
- **Regenerate the calibration corpus after closing any feedback loop.**
- **Run `make check` in WSL, not Windows.**
- **Write the test that would catch the failure before writing the feature** —
  it caught the EWC no-op, the divergence blow-up, and the open-loop jerk
  artefact.
- **State what a result does not license.** Every number produced before Phase 7
  is self-referential, and saying so is what makes the rest credible.
