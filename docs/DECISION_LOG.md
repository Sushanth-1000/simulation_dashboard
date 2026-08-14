# ASTRA — Decision Log

**What this is.** One entry per decision that could reasonably have gone another
way: what forced it, what the options were, what each would have cost, which was
taken, and what the choice gave up. It is the index a reviewer, an assessor or a
new engineer reads first.

**What it is not.** It does not restate the ADRs — each entry links to the
record that carries the full argument. It does not restate `EVIDENCE.md` — a
number lives in exactly one place, and that place is the evidence log. What lives
*here* and nowhere else is the **shape of the choice**: the alternatives, their
trade-offs, and why the rejected ones were rejected.

**Why it exists as a separate document.** Twenty-four ADRs are twenty-four
correct answers to twenty-four questions nobody remembers asking. Read in
sequence they do not tell you what kind of project this is. Read as a table they
do: **most of the hard calls here were forced by a measurement that contradicted
a document**, and the pattern is more persuasive than any single entry.

---

## How to read the columns

| Column | What it means |
|---|---|
| **Forced by** | The measurement, defect or contradiction that made a decision necessary. If this column says "design", the entry is weaker — it means nobody had run into the problem yet |
| **Alternatives** | Every option that was actually weighed, best rejected one first |
| **Why this one** | The discriminating argument — not the benefits, the *reason the others lose* |
| **Gave up** | What the choice cost. An entry with an empty cell here is a decision that has not been thought about hard enough |

---

## Part 1 · The decisions that shaped the architecture

### D-1 · Nine layers, consolidated numbering — [ADR-0001](adr/0001-consolidated-layer-numbering.md)

| | |
|---|---|
| **Forced by** | The source documents number the layers three different ways; the paper's Figure 1 labels **three different components "Layer 6"** |
| **Alternatives** | (a) Adopt the paper's numbering — rejected, it is internally inconsistent. (b) Number by execution order — rejected, L7a and L7b are concurrent. (c) Consolidated L1–L9, split L7 into a/b |
| **Why this one** | It is the only numbering in which every layer has exactly one number and every number has exactly one layer. `ASTRA_LAYER_COUNT = 9` is asserted against the enum by an architecture test, so it cannot drift without the build failing |
| **Gave up** | The paper and the implementation now disagree, and the paper is the one that must change (`PAPER_ADHERENCE.md` §2.7) |

### D-2 · SI units via `NewType`, converted only at boundaries — [ADR-0007](adr/0007-si-units-via-newtype.md)

| | |
|---|---|
| **Forced by** | Design. A speed cap in km/h and a speed in m/s are both `float` |
| **Alternatives** | (a) A units library (`pint`) — rejected, runtime cost on a 20 Hz hot path and a dependency in the kernel. (b) Naming conventions (`speed_mps`) — rejected, a convention is not a check. (c) `NewType` + explicit conversion helpers |
| **Why this one** | Zero runtime cost, and a mismatch is a **type error at build time** rather than a wrong number at run time |
| **Gave up** | Conversions must be written by hand, and `NewType` does not stop arithmetic between two different units — it stops *assignment*. The remaining gap is real |

### D-3 · Separation invariants as executable contracts — [ADR-0012](adr/0012-executable-separation-invariants.md)

| | |
|---|---|
| **Forced by** | Design, and it is the decision the whole safety argument rests on |
| **Alternatives** | (a) Document the invariants and review against them — rejected; **this is what "SI-6 is REVIEW-only" meant, and it stayed wrong in a document for four weeks after the code changed**. (b) Assert them in tests only — partly taken (SI-6, SI-8). (c) A catalogue where each invariant declares its own enforcement kind, and a test asserts the correspondence |
| **Why this one** | `is_mechanically_enforced` returns `False` for exactly `REVIEW`, and a test asserts that correspondence — so an invariant **cannot be quietly downgraded and keep claiming a guarantee** |
| **Gave up** | Nothing checks that the ten are the *right* ten |

### D-4 · One-way Core-A → Core-B channel as a type error — [ADR-0012](adr/0012-executable-separation-invariants.md), SI-5

| | |
|---|---|
| **Forced by** | The paper's AXI4-Lite argument: a compromised Core-A must not be able to read a verdict |
| **Alternatives** | (a) A process boundary — rejected as out of scope for a Python prototype. (b) A convention plus review — rejected, see D-3. (c) A capability pair: `ProposalWriter` exposes no read method, enforced additionally by an import contract |
| **Why this one** | A violation does not compile. Twelve `lint-imports` contracts back it up at the module level |
| **Gave up** | It protects against *code* that reads a verdict, not against a compromised process outside the type system |

---

## Part 2 · The decisions forced by a measurement

**This is the substantial part.** Every entry below exists because something was
run and the result contradicted what a document said.

### D-5 · A gate that cannot judge abstains; no path overrides a veto — [ADR-0016](adr/0016-exploration-may-not-override-a-deterministic-veto.md)

| | |
|---|---|
| **Forced by** | **99,808 commands per 100,000 issued under a blocking verdict.** Bounded safe exploration was tested *before* the verdict, so in exploration the proposal was issued regardless of what the gates decided — and at the shipped operating point exploration was engaged almost always |
| **Alternatives** | (a) Keep the ordering, document it honestly — rejected: it makes the deterministic gate's authority conditional on a state the gate cannot observe, and with exploration permanently engaged *no* gate had authority over the actuators. (b) Swap the branches, no abstention — **strictly safer, and it deletes bounded safe exploration**, because an uncalibrated L6 vetoes every tick. Kept on record as the honest fallback. (c) Override only the STATISTICAL veto at issue time — the first draft; buys the same behaviour for a fifth of the effort and pays with a permanent exception to the unconditional veto. (d) A per-gate override list in configuration — rejected on sight: it turns "which gate may be overruled" into a value a deployment can edit. (e) Add `Verdict.ABSTAIN`, drop abstentions before the fail-closed merge, and test the verdict first |
| **Why this one** | The real defect was upstream of the ordering: **one condition had two owners.** "No profile covers this context" produced a veto from L6 and a narrowed envelope from L9, and the conflict was resolved by L9 ignoring L6. Abstention gives the condition one owner. The code already contained the argument — *"a gate that cannot make a statistical claim must not report that the proposal satisfied one"* — and it must not report that the proposal *violated* one either |
| **Gave up** | A command an uncalibrated L6 blocked before is now issued when L7a and L7b pass; **the verdict is no longer binary**, and two invariant statements had to be amended; audit schema 1 → 2; and abstention is a licence that must not spread — a gate abstaining because it was "uncertain" would be a fail-open mode wearing this record as cover |

### D-6 · A jerk veto yields the largest admissible step — [ADR-0017](adr/0017-rate-limited-approach-to-a-jerk-vetoed-proposal.md)

| | |
|---|---|
| **Forced by** | A veto latch: a vehicle 1 m off centre needs ~21 ticks to correct, every one of them vetoed on jerk, so the correction could never complete |
| **Alternatives** | (a) Raise the jerk limit — rejected, it is a comfort/safety bound, not a tuning knob. (b) Issue zero steering on a jerk veto — the previous behaviour, and it is what latched. (c) Project the proposal onto the largest step the bound permits, in the direction asked for |
| **Why this one** | The veto is not overridden — the proposal is *not* issued; a different command is, admissible under the refusing bound **by construction**. Verified live: 347 `RATE_LIMITED` ticks in a 20,000-tick soak |
| **Gave up** | It did not stop the departure, because there were two latches. The second — L6 vetoing every correction that would bring the vehicle back inside corpus coverage — is still open as P0.3 |

### D-7 · One twin head per context, not a consolidation penalty — [ADR-0019](adr/0019-one-twin-head-per-context.md)

| | |
|---|---|
| **Forced by** | **EWC was not selective at all.** Across λ from 0 to 10⁵ the ratio of forgetting to learning was constant to three significant figures. At λ=0 and λ=150, forgetting was 0.038972 and 0.038951 — identical to four decimals |
| **Alternatives** | (a) Tune λ higher — rejected by the measurement; the entry that proposed this guessed the penalty would bite around λ≈10¹² and it never bites. (b) Move the Fisher anchor to context boundaries ([ADR-0018](adr/0018-ewc-anchors-on-context-not-on-every-update.md)) — tried, and superseded in effect. (c) One output head per context |
| **Why this one** | It could not have worked: FB2 adapts a single 16→2 readout that both contexts use in full, so **there is no disjoint subspace for a Fisher-weighted penalty to protect**. EWC was a speed dial, not a consolidator. Per-context heads make forgetting structurally impossible — the test asserts `==`, not a tolerance |
| **Gave up** | Contexts no longer share representation, so nothing transfers between them. `ewc_lambda` and `adaptation_buffer` residue is still in comments and configuration |

### D-8 · FB2 estimates control effectiveness rather than regressing on commands — [ADR-0020](adr/0020-fb2-estimates-control-effectiveness.md)

| | |
|---|---|
| **Forced by** | FB2 as specified would **disarm the statistical gate**: its only labels are the proposer's own commands, so the twin regresses onto the thing it exists to be independent of. Measured in shadow, the non-conformity score fell **40%** in a context where nothing changed, monotonically, still falling |
| **Alternatives** | (a) Wire FB2 as specified — refused. (b) Wire it with a divergence guard — rejected, the guard would be calibrated against the drift it is meant to stop. (c) Leave FB2 unwired and say so — acceptable, and weaker. (d) Replace the *target*: estimate the platform's control effectiveness `B` from executed outcomes |
| **Why this one** | A target of **measured physics** cannot drift toward the proposer the way a target of the proposer's commands must |
| **Gave up** | The reasoning is sound and it is not evidence, so it too went through the shadow harness — and there it reported **140.000 on every platform**, including plants whose true `B` was 112 and 168, because it was being fed the *filtered estimate*. Fed the raw measured response it tracks to within 1.7%. **It is still not wired**, and this entry is a decision about what FB2 should be, not a closed loop |

### D-9 · An ablation neutralises a gate; it never removes one — [ADR-0021](adr/0021-ablation-neutralises-a-gate-it-never-removes-one.md)

| | |
|---|---|
| **Forced by** | The need for a Phase 4 ablation study, and the risk it creates: an ablation produces evidence that looks *exactly* like a governed run's |
| **Alternatives** | (a) Make the gate constructor parameters optional — rejected: a pipeline with no gate becomes constructible, permanently, so that a study can run once. (b) A configuration flag read at the gate — rejected, it is a safety threshold a deployment can flip. (c) Keep the parameters required and supply a **transparent subtype** that runs, writes a verdict, and cannot block |
| **Why this one** | A pipeline with no gate stays unconstructible, and the profile is **stamped into every decision record** — because a certification artefact describing a system that was not running is the failure this exists to prevent. Positive control: disarmed gates still write a verdict, 0 of 2,800 in every governed row, 2,800 of 2,800 in every disarmed row |
| **Gave up** | More machinery than a flag, and `ABLATION_ENVIRONMENTS` restricts it to development and simulation — which is a guard a deployment could in principle edit |

### D-10 · Faults are injected at the sensor boundary — [ADR-0022](adr/0022-faults-are-injected-at-the-sensor-boundary.md)

| | |
|---|---|
| **Forced by** | Design, and it is the decision that made every later finding possible |
| **Alternatives** | (a) Corrupt the state estimate directly — rejected: it tests the gates against a fault no sensor can produce, and skips the estimator, which is the component that turns out to matter most. (b) Corrupt the command — rejected, that is an actuator fault and a different threat. (c) Corrupt the published sensor payload, before L1 |
| **Why this one** | It is where a real fault enters, so the whole pipeline is under test rather than the half below the injection point. `FaultSpec` refuses an inert configuration, and `peak_absolute_error` is **measured, not requested** |
| **Gave up** | Nothing measurable. The injector is bit-identical to no injector when nothing is active, pinned by whole-trace equality rather than a tolerance — which is what makes a two-arm comparison possible at all |

### D-11 · The OOD counter freezes during bounded exploration — [ADR-0023](adr/0023-the-ood-counter-freezes-during-bounded-exploration.md)

| | |
|---|---|
| **Forced by** | **The architecture's distinguishing sentence was false.** On a platform the twin was never fitted to, L8 counted the vetoes L9 had already responded to and drove the vehicle to a terminal HALT — weak acceleration at t398, weak brakes at t404, both at 0.00 m/s under an arbitrator still reporting `SAFE_EXPLORATION` |
| **Alternatives** | (a) Exempt L6 and L7b vetoes from the counter — rejected, `machine.py`'s own docstring forbids it: *"which gate vetoed is evidence for the log, not an input to the escalation policy"*. An escalation policy that weights gates differently is one that can be tuned to ignore the gate that keeps firing. (b) Raise `ood_threshold_halt` when exploring — rejected: it converts a structural contradiction into a tuning parameter whose only defensible value is "longer than the longest tunnel", which nobody knows. (c) Make HALT recoverable — rejected, and it is the tempting one: **a recoverable HALT is a LIMP with a frightening name**. (d) Fix OD-12 alone and file OD-13 — rejected on the measurement, see below. (e) Freeze the counter on *posture*, and route the exploration speed cap through the projector |
| **Why this one** | Conditioning on posture — a boolean the arbitrator already publishes on every record — keeps every gate's contribution identical and puts the exception where an auditor sees it on the tick it applied. **SI-3 is untouched**: what is suspended is escalation to a terminal posture, never a gate's authority to block |
| **Gave up** | A sustained fault arising *during* exploration would not escalate the posture either. Recorded as an accepted risk with an explicit instruction — *whoever closes OD-9 must revisit this record* — and **D-12 is that revisit** |

### D-11b · Why OD-13 was fixed in the same change

| | |
|---|---|
| **Forced by** | The control arm: before halting, the weak-braking platform reached **23.43 m/s** against a calibrated 14.27, with **zero** ticks marked `SPEED_CAPPED`. The envelope computed a speed cap and `restricted_space` turned it into narrowed *channel* bounds, which limit throttle per tick and bound speed not at all |
| **Alternatives** | (a) Ship the counter freeze alone — **this is the one worth recording.** It would have replaced "stops unnecessarily" with "accelerates without bound", and been reported as a fix. The halt was the only thing arresting the acceleration. (b) Enforce the cap in L7a — rejected: L7a is a *veto* gate, so every tick above the cap would fall back rather than be clamped, which is OD-12 by another route. (c) Route the cap through the projector seam P2.1 built for the fail-safe cap |
| **Why this one** | The projector *alters* a command, which is what an envelope means, and `SPEED_CAPPED` keeps meaning **a command the cap altered** rather than a cap that existed |
| **Gave up** | The exploration cap and the fail-safe cap are indistinguishable in `CommandOrigin`. A third origin was considered and rejected — the cause is already on the same record in `arbitration.outcome`, and an enum that grows a member per cause stops being a classification |

### D-12 · Sensor integrity is a second counter, not a fourth gate — [ADR-0024](adr/0024-sensor-integrity-is-a-second-counter-not-a-fourth-gate.md)

**The most consequential decision in this log, and the one whose reasoning
transfers furthest.**

| | |
|---|---|
| **Forced by** | **OD-9.** Every Core-B gate reads L2's fast estimate and the proposer closes its loop on the same estimate, so a corrupted reading is *actively driven* toward the value the gates consider safe. A 200-tick IMU dropout put the vehicle **4.199 m off a 1.75 m lane** with the corridor bound reading **0.023 m** and a verdict trace **identical to the clean control's** |
| **Alternatives** | (a) **A fourth Core-B gate vetoing on stream health** — the obvious answer, and it does not work: L9's fallback controller reads the same corrupted estimate, so a veto exchanges one command computed from a lie for another. It also raises `CORE_B_GATE_COUNT`, which three architecture tests assert. (b) **Feed stream health into the existing OOD counter** — cheapest, and rejected three times over: it conflates two conditions in one integer so an auditor cannot tell which fired; it inherits thresholds that are too slow (HALT at 100 against a departure at 73); and **it would freeze during exploration**, which is exactly the risk D-11 accepted. (c) **Gate on the innovation sequence** — the *principled* candidate, and **refuted by measurement**: a 1 cm/tick drift against a 0.1 m sigma never leaves the filter's expected band, so it is silent on precisely the fault it was most wanted for. (d) **Gate on estimate uncertainty `trace(P_f)`** — rejected before it was built and written down so nobody tries it twice: a frozen reading is maximally *self-consistent*, so the filter grows **more** confident, not less. (e) **Reduce the Trust Index** — it already responds at the same +5 latency and it changed nothing, because nothing acts on trust alone; wiring it further would make the Trust Index no longer a conformal quantity and invalidate E-12's coverage arithmetic. (f) **Escalate only on a modality that has published at least once** — rejected: it silently tolerates a sensor **dead at boot**, the worst of the three to tolerate. (g) **Sensor redundancy and a cross-check** — *not rejected, deferred*: the only general answer, and unmeasurable on a plant that publishes one ground truth to all five modalities. (h) A second counter in L8, driven by `StreamHealth` |
| **Why this one** | One sentence decides it: **you cannot veto your way out of a lying sensor.** Everything downstream of L2 is compromised together, so a remedy has to read something that is not — and `StreamHealth` is computed at the sensor boundary before the filter touches anything. What the vehicle needs is not a refusal but a change of *posture*, and L8 already owns converting sustained evidence into a graduated one. **It also shrinks D-11's accepted risk**, because the integrity counter deliberately does *not* freeze during exploration: a narrowed envelope is a response to the world being unfamiliar and says nothing about whether the sensors are honest |
| **Gave up** | **Two thirds of OD-9, and the row stays open.** `StreamHealth` is computed from staleness, so `BIAS`, `DRIFT` and `STUCK_AT` — which keep the stream perfectly fresh — are invisible; the slow drift still ends 2.025 m out with the counter at 0. **No gate sees the fault even now**, so D-3's independence claim is no less contradicted. One unhealthy channel escalates, which over-fires on a platform with a different sensor set. And it creates a denial-of-service surface: an adversary who can silence one channel can stop the vehicle in two seconds — the right trade against a loss-of-lane-position hazard, but a trade |

### D-12b · Analytical redundancy, tried and refuted

**Kept because a log of only successful decisions is a brochure, and because the
refutation is worth more than the attempt would have been.**

| | |
|---|---|
| **Forced by** | OD-9's remaining two thirds. A self-consistent lie is invisible to every mechanism in the system; the general answer is a second sensor, and the reference plant cannot express one |
| **Alternatives** | (a) Wait for Phase 7 and real redundancy — still the fallback. (b) **Build a second estimate from the issued commands**, propagated through the process model: commands are not measurements, so the two should share no channel |
| **Why it was tried** | It costs microseconds, needs no hardware, and the failure mode is checkable in advance — which is exactly the profile the shadow convention exists to exploit |
| **Why it failed** | **FB1 feeds the issued command into the filter's prediction step**, so the two estimates share the process model *and* the command input and differ only by the measurement correction. The residual measures "how far the measurement pulled the filter", which under a slow drift is exactly the drift rate — and the propagation's own uncorrected error accumulates 2.2x to 4.0x faster than that. **Refuted by the feedback loop that exists to mitigate the very defect it was built to attack**, and FB1 is load-bearing and not removable |
| **Gave up** | Nothing shipped, so nothing was given up but the time. The cost of *not* shadowing it would have been a monitor whose false-alarm rate exceeded its detection rate, wired into a fail-safe machine |
| **What it bought** | A quantitative bound rather than an intuition — 0.022–0.040 m of residual per tick of window against a 0.010 m/tick fault — and it identified the surviving candidate: a **cross-channel** check that does not integrate and does not pass through FB1 |

### D-12c · A commissioning certificate reports three verdicts, not two

| | |
|---|---|
| **Forced by** | OD-11. NFR5 claims a second platform costs only an adapter, and measured against a warehouse AGV that is **partly false**. "Which contexts does this platform actually work in" is the question that finding leaves open, and nothing answered it — the four seeded profiles were an assumption nobody had checked a vehicle against |
| **Alternatives** | (a) **Binary certified / not certified** — rejected, and this is the whole design decision: it reports `BOUNDED` as a *failure*, when bounded safe exploration is the behaviour the architecture exists to have. A vehicle that drives safely inside a narrowed envelope in an uncalibrated context has not failed; it has a weaker certificate. (b) A continuous fitness score — rejected: an integrator needs a decision, and a score defers it back to them. (c) Add a fourth `MARGINAL` verdict — rejected on the second platform's evidence; a majority-hold rule inside `BOUNDED` carries the same information without diluting a three-way answer. (d) **CERTIFIED / BOUNDED / UNFIT**, with the reason phrase on every row including the passes |
| **Why this one** | It mirrors what the architecture actually does. A certificate that could not express *"safe here, not calibrated here"* would be describing a different system |
| **Gave up** | Three verdicts need a hold threshold, and any threshold is arguable. It is set at a bare majority and deliberately not tuned finer — a value chosen to make a particular platform pass would be fitted to that platform |
| **What it found immediately** | On the calibrated platform, **three of the four seeded profiles are unreachable** — not because the road conditions differ but because `ego_speed` is *measured*, and this policy realises 0.28 against `HIGHWAY_CLEAR`'s centroid of 0.80. On a weak-braking platform, **all four**. E-82 had recorded this as a tuning trap; the certificate makes it a reported column |
| **What it got wrong first** | The verdict asked only whether a profile had *ever* matched, and reported a platform that spent **360 of 400 ticks in exploration** as CERTIFIED. Found by running a second platform rather than by review — the same instrument that found OD-12 and OD-13 |

### D-12d · The vehicle proposes calibration *work*, never a calibration — [ADR-0025](adr/0025-the-vehicle-proposes-calibration-work-never-a-calibration.md)

| | |
|---|---|
| **Forced by** | The commissioning certificate: **four of five contexts come back `BOUNDED`**, meaning the vehicle drove for hundreds of ticks accumulating evidence about a context nobody calibrated for, and discarded all of it. A fleet doing that for a year discards the most valuable dataset anyone could have about where their coverage is missing |
| **Alternatives** | (a) **Propose a full profile, quantile table included** - rejected, and it is why this record exists: a table fitted to the vehicle's own exploration is **FB3 by another name**, pinning the veto rate to epsilon by construction (E-40), and every metric keeps looking healthy while the gate degenerates. (b) **Propose a profile inheriting the nearest one's quantile table** - rejected: it asserts, on no evidence, that an uncalibrated context has its neighbour's non-conformity distribution, the assumption OD-8 already found violated. (c) **Auto-approve after enough evidence** - rejected, and it must *stay* rejected: it is the obvious next request and it converts a human gate into a threshold. A system that certifies itself from its own data will certify anything. (d) **Run it inside L9** - rejected on three counts: a learning mechanism on the hot path against SI-8, a fleet of one, and runtime standing the shadow convention says it has not earned. (e) **Cluster across runs first** - deferred, not rejected; unmeasurable on one vehicle. (f) An **offline reader of the audit log** that emits a *calibration request* |
| **Why this one** | A request carries only what the vehicle can honestly claim to know: centroid, spread, safety record, nearest profile, and a pointer to the ticks. **No quantile table, no coverage level, no certification dates.** Being offline satisfies the shadow convention *structurally*: there is no wire to cut because none was laid. And it is how a fleet actually works, vehicles uploading evidence and a backend proposing |
| **Gave up** | **It proposes work, not capability.** Nothing improves until a human runs a calibration, so anyone measuring "contexts certified per week" finds it does nothing alone. That is the design. Three filter thresholds that are arguable and untuned, because there is no population to tune against. Coherence checked per component, not jointly, so a diagonal drift through signature space would pass. And a forged log is a forged request, the same residual the threat model already carries |
| **What it exposed** | **OD-14.** The arbitration record carried the outcome and the trust score but *not the signature RCM decided on*, so the log could say `SAFE_EXPLORATION` and not say what context that was. Found by trying to **use** the evidence rather than by reviewing it, a fifth distinct instrument, and it is the third instance of one shape after `fast_innovation` and `previous_digest`: a quantity the pipeline computes, consumes, and archives nowhere |

---

## Part 3 · Decisions about how the project works

### D-13 · No mechanism gets authority until it has run with none

**The standing convention, and the one that has paid for itself most often.**

| | |
|---|---|
| **Forced by** | FB2 and FB3. Both were specified as live loops, both would have broken the gate they feed, and **neither would have shown up as an error** — FB2 collapses the non-conformity score while every metric continues to look healthy; FB3 pins the veto rate to ε *by construction*, because ε of any distribution lies above its own 1−ε quantile |
| **Alternatives** | (a) Wire and monitor — rejected: both failure modes are invisible to monitoring, which is the whole point. (b) Wire behind a feature flag — rejected, a flag defaulting to on is wired. (c) Run it as a pure function of the decision record, changing no verdict, and diff it against the live system |
| **Why this one** | A mechanism that cannot change a verdict **cannot flatter itself**. It has since caught three things: FB2, FB3, and — in the other direction — that P2.7's principled candidate was silent on the fault it was built for |
| **Gave up** | Every mechanism costs a measurement before it costs an implementation. That is the intended price |

### D-14 · Cite `EVIDENCE.md`, never restate it

| | |
|---|---|
| **Forced by** | Stale figures in three documents at once, and the 9 August date correction: every row was stamped `2 Aug`, and for most of them that was **provably impossible** — E-24 measures a fix committed on the 6th |
| **Alternatives** | (a) Restate figures where they are needed and sync them — this is what produced the staleness. (b) Generate the documents — over-engineering for a prototype. (c) One number, one place; every other document cites the `E-n` row |
| **Why this one** | A figure restated in two documents is a figure that will be stale in one of them |
| **Gave up** | Reading requires following a link. **And it does not fully work** — this session found `README.md` and `SEPARATION_INVARIANTS.md` both four weeks stale, in opposite directions |

### D-15 · Retract, do not refresh

| | |
|---|---|
| **Forced by** | `COMMERCIAL_ASSESSMENT.md` quoting "2,513 tests at 98% coverage" — correct on its date, wrong now |
| **Alternatives** | (a) Update the figures in place — rejected: a dated snapshot that is silently refreshed **stops being a snapshot**. (b) Delete the document. (c) Leave it, with its date as the caveat, and re-issue rather than edit |
| **Why this one** | The value of a dated assessment is that it says what was believed on that date |
| **Gave up** | Documents accumulate. The register carries the cost as a known-stale list rather than as invisible drift |

### D-16 · Strict xfail for a claim that is false

| | |
|---|---|
| **Forced by** | NFR5. Domain independence is claimed in `assembly.py`'s own docstring and is **partly false** — four walls, found by building a warehouse AGV and driving it at the pipeline |
| **Alternatives** | (a) Delete the claim — rejected, the claim is the goal. (b) File a ticket — rejected, tickets do not fail builds. (c) A test per wall, marked strict xfail |
| **Why this one** | **Making the claim true turns the suite red** and forces the documents to be rewritten on the same day. A strict xfail is a promise with a deadline enforced by a machine |
| **Gave up** | Five permanently-failing tests in the output, which needs explaining to anyone reading the gate for the first time |

### D-17 · Rewriting history to strip a 200 MB blob

| | |
|---|---|
| **Forced by** | A `str.replace("", new)` accident made `docs/PENDING.md` **210 MB** in two commits. GitHub refuses any pushed object over 100 MB, so the branch was **unpushable from 6 August and nothing found out until the 10th** — four days and thirty commits later |
| **Alternatives** | (a) Squash the history — rejected: the commit messages carry the reasoning for OD-9, the ablation result and the ADR-0020 refutation, and in this project that history is a deliverable. (b) Start a fresh branch — same objection. (c) `filter-branch` the two commits to carry their parent's copy of the file |
| **Why this one** | The rewrite is confined to unpushed commits, it is a fast-forward for the remote afterwards, and a backup tag makes it one command to undo. Nothing else in any commit changed and the working tree is byte-identical |
| **Gave up** | Twenty-six hashes moved, four citations had to be remapped, and hashes quoted *inside* commit messages are permanently stale. **The real fix was the guard**: `make blobsize` fails on any tracked file over 5 MB — a limit set just under the one that bites gives no warning |

---

## Part 4 · Challenges that were not decisions — the mistakes, and what they cost

**These are here because a log of only good decisions is a brochure.** Each is a
thing that went wrong in the work itself, what it cost, and what stops it
recurring.

| | Challenge | Cost | What stops it now |
|:--:|---|---|---|
| **C-1** | **`str.replace("", new)` on a 63 KB file.** Python inserts the replacement between every character | 210 MB blob, an unpushable branch for four days, a history rewrite | `make blobsize`, which scans the filesystem rather than `git ls-files` — the first version passed vacuously |
| **C-2** | **The plant integrated 2.5× faster than the controller.** `step_seconds` was 0.02 while the tick period was 0.05, and the docstring said 0.05 | **Every policy trained before 5 August was invalidated**, and L7b was 2.5× more permissive than configured, so the proposer's steering fitted inside slack that did not exist | The value is documented against `1 / fast_rate_hz` with the full history in its own docstring |
| **C-3** | **A reward term ~500× too small.** `action_rate_weight` was 6.0 against a task reward capping at 2.0; a step at exactly L7b's jerk limit cost one part in ten thousand | A policy that **stopped the vehicle** and collected centring reward for the rest of every episode — and ran a whole 100,000-tick soak without the defect being visible, because nothing measured speed | The weight is derived from L7b's bound rather than chosen, and the derivation is in the docstring |
| **C-4** | **ADR-0020's measurement went wrong four times in a row**, all on tick pairing between the command, the plant's truth and the sensor reading | Read the effectiveness 12–18% low and looked entirely plausible while doing it | The tick timeline is written out explicitly in `benchmarks/effectiveness.py`'s module docstring |
| **C-5** | **Cold-path context tuned by intuition inverted the result.** A signature that *looks* like clear highway sat in permanent `SAFE_EXPLORATION`, because component 2 is ego-speed/legal-limit — 0.375 against a centroid of 0.8 | The tunnel demo would have shown exploration against a baseline that was already exploring | The tuning is measured and recorded as E-82, and the failure is kept in the row |
| **C-6** | **Overstating OD-10 as "22×"** — that is the per-channel algebraic bound, not the realised effect | A register row that overstated what was broken. Realised: 1.53× on the bottom half, **1.23× in the tail**, 1.024× on the largest single distance | The row was corrected with a dagger rather than edited, and E-71 carries the measurement. *A register that overstates what is broken loses trust as fast as one that understates it* |
| **C-7** | **`--delete-excluded` on an rsync wiped `~/astra/var`** — the trained twin, the calibration corpus and the policy | Restored from tracked Windows copies; would have cost a retrain otherwise | Named in the environment notes; the artefacts are tracked |
| **C-8** | **A snapshot's `speed_cap` of `None` rendered as `0.0`** would have shown *commanded stop* on every healthy tick | Caught by running the dashboard, not by a test — every fixture had set a cap | E-79, and `test_every_field_is_declared_as_record_or_simulator` fails if a field is added without declaring its source |
| **C-9** | **Two integration tests asserted a defect**, and fixing the defect broke them | Correct behaviour, and it must not be papered over: one of them said in its own comment *"pinned so that a future change which fixes it fails here and has to say so"* | It fired, and this log entry is part of the saying-so. The tests were rewritten to assert the new truth **and** to keep pinning the half that is still broken |
| **C-10** | **An integration rig published one sensor modality of five.** Harmless while nothing read stream health; a vehicle with four dead sensors once L8 did | Two tests failed on a change that was working correctly | The rig now publishes every modality, as the closed-loop harness and a real vehicle do, and the old behaviour is pinned by a test that asserts a one-modality vehicle **does not stay NOMINAL** |

---

## The pattern, stated once

Read the **Forced by** column top to bottom. Eleven of the seventeen decisions
were forced by a measurement that contradicted a document, and **not one of them
was caught by the test suite, `mypy --strict`, or the twelve import contracts** —
all of which were green throughout.

Four of them share one shape, and it is the shape worth naming:

> **The composition is correct at every layer and wrong as a whole.**

- **OD-4** — every layer handled `position_y` correctly; nothing observed it.
- **OD-6** — L6's veto and L9's envelope were each right; they answered the same
  question and disagreed.
- **OD-12** — L8's counting and L9's exploration were each right; they owned the
  same condition and the terminal answer won.
- **OD-9** — every gate reads the state estimate, which is correct; all three
  therefore fail together when it lies.

That is the argument for this architecture and it is also the argument against
trusting it: a system assembled from correct parts needs **runtime evidence**,
because static verification of the parts cannot see the composition. Every entry
in Part 2 is a case where the evidence found something the verification could
not.

---

## Related

- [`adr/`](adr/) — the full argument behind each entry in Parts 1 and 2
- [`EVIDENCE.md`](EVIDENCE.md) — every number, and the command that reproduces it
- [`CREDIBILITY_MATRIX.md`](CREDIBILITY_MATRIX.md) — the open-defect register, and what each claim does *not* license
- [`PENDING.md`](PENDING.md) — what is left, ordered by what unblocks the most work
- [`ASSUMPTIONS.md`](ASSUMPTIONS.md) — A-1 … A-10, what breaks if each is wrong
