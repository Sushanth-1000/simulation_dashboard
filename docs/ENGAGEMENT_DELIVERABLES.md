# Engagement Deliverables

**Purpose** What a company receives in each of the two ways this team can engage, stated as
concrete artefacts rather than value propositions.

**Rule** Nothing on either list may be offered before the evidence supporting it exists in
[`CREDIBILITY_MATRIX.md`](CREDIBILITY_MATRIX.md). Prerequisites are named explicitly.

---

# Case 1 · Collaboration

**The trade in one line:** they supply logged data; we supply an independent measurement of
what a three-gate runtime monitor would have done with it. We never touch their controller.

## What the company provides

| Item | Detail |
|---|---|
| Logged **(state, command)** pairs | *N* hours from nominal operation — the signals the bus already records |
| Nothing else | No labels. No incident data. No model weights. No controller access. No engineering time beyond the log export |

An NDA, and a named technical contact for two or three questions about signal semantics and
units. That is the entire ask.

## What the company receives

### D0 · Credibility Matrix on public data — *delivered before anything is asked for*

The full claim-by-claim table, measured on 33 hours of real highway driving (comma2k19) and
reference trajectory data (highD), with every row marked for evidence provenance and every
open defect listed.

**This is the door-opener and it costs them nothing.** It also demonstrates the one thing that
matters in a safety conversation: that we report what we found. The register currently holds
**nine defects, five of them closed and re-measured**, every one found by this project rather
than reported to it — and two of the nine are cases where the evidence log confidently
recorded something that had not happened.

> **Prerequisite:** row D-1 must be at **[M-ext]**. Until the comma2k19 evidence run is
> complete, this deliverable does not exist and must not be promised.

### D1 · Veto-Rate Report on their data — *the core deliverable*

For every logged command, what an independent three-gate monitor would have decided:

- **Headline false-positive rate** — % of real commands vetoed on operation that completed safely
- **Per-gate attribution** — which of statistical / physical / deterministic fired, with stable reason codes
- **Per-context breakdown** — Mondrian class-conditional, with per-class calibration counts and any class too thin to support a threshold, named rather than averaged away
- **The disagreement set** — every command where the gates disagreed with each other, which is where anything interesting lives
- **Latency profile** — per-tick p50/p99 on their data volume

*Indicative: 3–5 weeks from receipt of clean logs.*

### D2 · Layer Ablation Report

Each of the nine layers switched off in turn and re-measured on their data. Output: what each
check is actually worth, in FP rate and in compute.

Most organisations accrete safety checks over years and never decompose them. This is the
deliverable that most often surprises the recipient.

*Indicative: 2–3 weeks after D1.*

### D3 · Evidence and Audit Pack

A sample corpus of structured decision records from their data — gate verdicts, reason codes,
calibration corpus SHA-256, twin weights digest, correlation IDs — shaped for record-keeping
obligations of the EU AI Act Article 12 kind, plus a note on what would and would not satisfy
an assessor.

*Indicative: 1–2 weeks, concurrent with D2.*

### D4 · Integration Assessment

A written assessment of how ASTRA would sit against their stack: the adapter surface required,
where their controller attaches at the L4 port, the tick-budget implications, which of the nine
layers are domain-neutral and which need their physical constants, and an honest list of what
would have to be true before any of it is deployable.

*Indicative: 1 week, concurrent with D2.*

### D5 · Negative-result commitment

Whatever the numbers say is what gets reported, including *"your controller is well-behaved and
we vetoed 0.3% of commands."* A clean result is a usable input to their safety case and is
delivered with the same weight as a dramatic one.

## Explicitly out of scope

Stated up front, because it is what makes the rest credible.

- **Not a deployment.** Python reference implementation; no hard-real-time guarantee on an ECU
- **No certification support.** No ISO 26262 work products, no ASIL decomposition, no safety manual
- **No security posture.** No threat model, no signed artefacts, no ISO/SAE 21434 work
- **No controller work.** We do not replace, retrain, tune, or read their policy
- **No hardware-in-the-loop.** Never run against real hardware

## Why the risk is low for them

- The ask is a log export, not an engineering commitment
- Nothing touches production, and nothing touches the control stack
- The output is an internal measurement they cannot currently generate at any price
- If the result is uninteresting, they have lost a log dump

---

# Case 2 · Project Internship

**The trade in one line:** four engineers who have already built and debugged a
safety-critical system, rather than four who need to be taught what one is.

## What we bring on day one

| Capability | Evidence in the repository |
|---|---|
| Safety-critical architecture under enforced constraints | `mypy --strict` clean over **146** files, **2,729** tests at **97.99%** coverage, 12 import-linter contracts kept, 10/10 separation invariants mechanically enforced with zero left to code review |
| Architectural properties as **compile-time** guarantees | SI-5 enforced as a capability pair — the one-way core channel is a type error, not a convention |
| Applied statistical ML, done correctly | Inductive conformal prediction with the ⌈(n+1)(1−ε)⌉ index and an honest `math.inf` rather than a clamp; Mondrian class-conditional calibration; MMD covariate-shift detection |
| Estimation and control | Dual-rate UKF with van der Merwe sigma points and fail-closed numerics; PPO under PID-Lagrangian constraints |
| Measurement discipline | 100,000-tick soaks that found eight defects; **three published numbers retracted** after they proved to be artefacts rather than results; a quantile Monte-Carlo'd rather than tuned when coverage looked wrong; every date in the evidence pack re-derived from `git log` after the stamps were found to have frozen |
| Counterfactual measurement of unwired mechanisms | Two dormant feedback loops run **in shadow** — adapting real state, read by nothing, changing no verdict — and both were found to break the gate they feed *before* either was connected. One collapses the non-conformity score 40%; the other pins the veto rate to ε by construction |
| Reproducibility engineering | Byte-identical replay spine; SHA-256 provenance on every calibration artefact; injected clock, no wall-clock reads anywhere |
| Fault injection with recorded ground truth | Five sensor-fault kinds at the adapter boundary, each against a clean control at the same seed. A specification that *could not inject* is refused at construction, and each episode reports the error it **measured** rather than the one it was configured with — so an injector that had silently become a no-op fails a named test instead of reporting that the gates are fine |

The three rows that matter most are the last three, and they say the same thing from three
directions.

A fail-safe speed cap that reached no actuator survived 2,513 tests, 97.97% coverage, strict
typing and twelve architecture contracts. Every layer was individually correct; the composition
was not. A run sat in HALT — a commanded stop — holding 17.2 m/s while every audit row agreed
it had been capped. Our own soak found it, and it is fixed and pinned by a test that drives the
assembled pipeline into HALT and asserts the brake.

The second is the more transferable capability. Before connecting an online-adaptation loop we
ran it against state nothing reads and compared it against the live system tick by tick. It
would have driven the statistical gate's own score down 40% in a context where nothing changed
— disarming the gate while every metric continued to look healthy. A second loop, measured the
same way, would have pinned the veto rate to exactly the configured significance level whether
or not anything was wrong. **Neither was ever wired. Neither would have shown up as an error.**

That is the method rather than the anecdote: a mechanism that fails by making the evidence look
better is invisible to testing, and the way to catch it is to run it with no authority and
measure it against the thing it would have replaced.

The third is the one we would most want to be asked about, because it is the least flattering.
On 9 August we built a fault injector, ran its first fault, and it found a defect in our own
architecture within the hour. Ten seconds of frozen IMU put the vehicle **4.199 m off a 1.75 m
lane** — two and a half lane widths — and Core-B's verdict trace was **identical to the clean
run's**: same three vetoes, same reason codes, the fail-safe machine NOMINAL on all 400 ticks.
The cause is not a missing check. A lateral corridor bound exists and was added for exactly this
hazard. It reads the position estimate, the proposer closes the loop on that same estimate, and
so the controller drives the corrupted number to the value the monitor considers safe: over that
run the bound read **0.023 m** while the vehicle was 4.199 m out.

That is a common-cause failure between a monitor and the thing it monitors, it is written
down as OD-9 with the run that produced it, and it is the kind of finding a runtime-assurance
argument has to survive rather than avoid. We would rather bring it to a first meeting than
have it found in one.

## What we deliver during an internship

Scoped to what is genuinely transferable, not to ASTRA itself.

### For a team running a learned or autonomous controller

1. **A replay harness for your system** — record inputs, replay byte-identically, make a defect reproducible instead of anecdotal
2. **An independent runtime monitor prototype** at your actuation boundary, with a measured false-positive rate on your logs
3. **An ablation of your existing safety checks** — what each one is worth, measured
4. **Structured evidence logging** — auditable decision records with provenance, non-blocking on the control path

### For any team with an architecture worth protecting

5. **Architecture fitness tests** — import contracts and type-level enforcement that turn design rules into build failures rather than review comments
6. **A soak and stability harness** — long-duration runs with bounded-memory verification and latency-drift detection
7. **A fault-injection study** — faults injected at your adapter boundary with ground truth recorded per tick, each against a control run, answering *what do your existing checks actually catch* rather than *do they run*

### Always

8. **An honest defect register.** Whatever we find, written down, including what we cannot fix in the time available

## What we are not

- No production deployment experience
- No certification experience — no ISO 26262 or 21434 work products
- No hard-real-time systems work; the implementation is Python, and we know why that is a limitation
- No hardware or HIL experience
- Zero external validation of the safety claims to date — which is precisely what we are trying to fix

## Engagement shapes

- **Four together** — the fastest route to any of the deliverables above; the work parallelises and each of us owns a subsystem end to end
- **Individually** — each of us can defend a distinct area: architecture and invariants, estimation and filtering, conformal calibration and gating, or policy training and closed-loop evaluation

---

## Sequencing note

Case 1 should not be opened before row **D-1** in the credibility matrix reaches **[M-ext]**.

> **What may and may not be said about the false-positive rate.** These are two different
> numbers and conflating them is the easiest way to lose a technical audience.
>
> *Per tick*, the gate vetoes **ε** — 5% at the shipped significance level — and always will,
> because ε of any distribution lies above its own 1−ε quantile. That is the conformal
> guarantee working, not a defect, and it is not the number a fleet operator cares about.
>
> *Per intervention* is what they care about, because a veto runs the fallback controller for
> one tick and the posture does not degrade until the OOD counter crosses θ₁. Measured at the
> design point over 100,000 ticks: **0.008% of ticks outside NOMINAL** — two episodes in 83
> minutes of driving, 2 and 6 ticks, both self-recovering, LIMP and HALT never reached (E-42).
>
> **Both figures are quotable together and neither is quotable alone.** And both are
> **[M-syn]**: the plant, twin and corpus share one set of equations, so this shows the two
> rates are compatible, *not* that either holds on a real vehicle. That still needs comma2k19,
> and D-1 stays [NOT DONE] until it has it.

Before that point the conversation is *"lend us data so we can find out whether our gates
work."* After it, the conversation is *"here is a measured false-positive rate on 33 hours of
real driving — let us confirm it on your fleet."*

Same ask. Different meeting.

Case 2 has no such prerequisite and can be opened immediately, subject to whatever disclosure
the patent filing permits.
