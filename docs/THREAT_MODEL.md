# ASTRA — Security Threat Model

**Prepared** 10 August 2026
**Status** First edition. Design work only — nothing here has been tested by attack.
**Scope** The reference implementation in this repository, as it stands.

---

## What this document is, and what it is not

`ENGAGEMENT_DELIVERABLES.md` lists *"No security posture. No threat model, no
signed artefacts, no ISO/SAE 21434 work"* under what this team is **not**. This
document changes one word of that sentence and no others: there is now a threat
model. There are still no signed artefacts, no key management, and no 21434 work
products.

It is a **design artefact**, not a security assessment. Nothing in it has been
validated by attacking the system. Where a threat is marked as *demonstrated*,
that is because a **safety** measurement in `EVIDENCE.md` happens to establish
the mechanism — not because anyone attempted the attack.

The distinction matters and is the same one the credibility matrix draws
everywhere else: a mechanism shown by construction is weaker evidence than a
mechanism shown by measurement, and both are weaker than a mechanism shown by
someone trying to break it.

---

## 1 · The asymmetry this architecture rests on

ASTRA's entire proposition is stated in one sentence in `ARCHITECTURE.md`: an
**untrusted proposer** is constrained by a **trusted governance core**. Core-A
may be a learned policy, may be arbitrarily wrong, and may in principle be
adversarial; Core-B bounds what it can do.

That is a security posture, and **only half of it has ever been examined.**

The untrusted half is enforced hard: SI-3 gives any gate an unconditional veto,
SI-5 makes the core channel one-way as a *type error* rather than a convention,
SI-7 makes L9 the sole actuation authority, and ADR-0016 closed the one path by
which exploration could issue under a blocking verdict.

The trusted half is an **assumption with nothing behind it**. Core-B's integrity,
the sensor bus, the configuration, the calibration corpus, the twin weights and
the evidence log are all simply presumed honest. This document is the first
enumeration of what that presumption is worth.

> **The one-line summary for a reviewer.** ASTRA defends thoroughly against a
> proposer that is *wrong* and not at all against a platform that is
> *compromised*, and the second is the larger attack surface because everything
> the first defence relies on lives there.

---

## 2 · Assets, in the order an attacker would want them

| # | Asset | Why it is worth attacking | What protects it today |
|:--:|---|---|---|
| **A-1** | **The actuation path** — what the vehicle is commanded to do | Direct physical consequence. The only asset whose compromise hurts someone | L9 sole authority (SI-7), three gates, the fail-safe machine |
| **A-2** | **The state estimate** | Every gate and the proposer read it. Corrupting it defeats all of them at once | **Partial, since 11 Aug.** A channel that goes *quiet* is caught at the sensor boundary and stops the vehicle before the hazard (ADR-0024). A channel that *lies fluently* still defeats everything. See §5.1 |
| **A-3** | **The evidence log** | It is the certification argument. Forging it forges the safety case | Append-only by convention; integrity-checked; **not tamper-evident** |
| **A-4** | **The calibration corpus** | Sets the conformal quantile. Widen it and the statistical gate stops firing | SHA-256 digest recorded per run; the digest is not *verified* against anything at load |
| **A-5** | **The twin weights** | The reference two gates score against | Digest recorded per run, same limitation as A-4 |
| **A-6** | **The configuration** | Holds every threshold: ε, θ₁₂₃, corridor half-width, speed limits | SHA-256 (truncated) stamped on every decision record |
| **A-7** | **The ablation profile** | A run with gates disarmed produces evidence identical to a governed run's | Stamped per tick since audit schema v4 (ADR-0021) |

---

## 3 · Trust boundaries

```
  ┌─ untrusted ─────────┐   ┌─ TRUSTED BY ASSUMPTION ──────────────────────┐
  │                     │   │                                              │
  │  Core-A proposer    │──▶│  one-way channel ──▶ Core-B gates ──▶ L9 ──▶ actuators
  │  (learned policy)   │   │            ▲                                 │
  └─────────────────────┘   │            │                                 │
                            │      state estimate (L2)                     │
   ┌─ untrusted in the ─┐   │            ▲                                 │
   │  real world,       │──▶│      sensor bus (L1)                         │
   │  trusted here:     │   │                                              │
   │  sensors           │   │      config · corpus · twin · evidence log   │
   └────────────────────┘   └──────────────────────────────────────────────┘
```

**The boundary that is enforced** is the vertical one on the left. It is a type
error to cross it in the wrong direction.

**The boundary that is assumed** is everything inside the right-hand box. There
is no authentication on the sensor bus, no signature on any loaded artefact, and
no integrity chain over the evidence log.

---

## 4 · Adversary models

Tiered by capability, because the answers differ sharply between tiers.

| | Adversary | Capability | Realistic? |
|:--:|---|---|---|
| **T0** | **Wrong proposer** | Emits arbitrary commands. No other access | Yes — this is the *design* case, not an attack |
| **T1** | **Sensor-channel influencer** | Can perturb one sensor channel's values. No code execution | Yes. GPS spoofing, adversarial patches, a compromised sensor ECU, CAN injection |
| **T1'** | **Multi-channel influencer** | Can perturb **f of n** sensor channels simultaneously and consistently. No code execution | Yes, and more so since 15 August: redundancy is now the driven path, so the channels are a target that did not previously exist. One supplier, one bus, one firmware image or one physical environment reaches several channels at once |
| **T2** | **Artefact substituter** | Can replace a file on disk before start-up: corpus, twin, configuration | Yes, wherever an attacker reaches the filesystem or the supply chain |
| **T3** | **Evidence forger** | Can write to the audit log after the fact | Yes, and it is the quietest of the four |
| **T4** | **Platform-code executor** | Runs code inside Core-B | If reached, nothing in this architecture helps, and this document says so rather than pretending otherwise |

**T0 is handled.** The rest of this document is about T1–T3.

---

## 5 · Threats

### 5.1 · T1-A — Corrupt one sensor channel and every gate goes blind together

**Demonstrated, by safety measurement.** This is OD-9, and it is the most
important entry in this document.

Every Core-B gate reads L2's fast estimate, and the proposer closes the loop on
the same estimate — so the controller actively drives the corrupted number
toward the value the gates consider safe. Measured (E-46, E-48): 200 ticks of a
frozen IMU put the vehicle **4.199 m off a 1.75 m lane**, 73 ticks outside the
corridor, with a verdict trace **identical to the clean control's** and the
fail-safe machine NOMINAL on all 400 ticks. The corridor bound — added
specifically to catch a lane departure — read **0.023 m** throughout.

Worse, the fault does not stay in the channel it enters. A frozen position
reading is maximally self-consistent, so the filter grows confident in it and
pushes the inconsistency into the one state nothing observes: true heading
reached **0.0686 rad** against an estimate of **0.0017** (E-58).

**As a safety defect this is a common-cause failure. As a security finding it is
an attack primitive**: an adversary who can influence one sensor channel has a
measured path to loss of lane position that produces *clean evidence* the whole
way. Nothing raises, nothing degrades, and the audit log records a nominal run.

**What exists, since 11 August 2026:** L8 carries a **second counter** driven by
`StreamHealth`, which L1 computes at the sensor boundary before the filter
touches anything — the one input to the fail-safe machine upstream of the common
cause (ADR-0024). The dropout arm is closed by measurement: final deviation
**4.199 m → 0.167 m** over 400 ticks and **35.705 m → 0.170 m** over 800, with
DEGRADED at **+5 ticks**, LIMP at +15 and a commanded stop at **+40** against a
departure that begins at +73 (E-87, E-88, E-92). Zero false alarms on the
control.

**No gate reads it, and that is deliberate.** A veto would not have helped: L9's
fallback controller reads the same corrupted estimate, so refusing the proposal
exchanges one command computed from a lie for another. **You cannot veto your
way out of a lying sensor** — the remedy had to be a change of posture driven by
a signal that is not downstream of L2.

**Residual, and it is most of the primitive.** `StreamHealth` is computed from
*staleness*, so the mitigation covers only an adversary who makes a channel go
**quiet**. An adversary who makes a channel **lie fluently** — a constant
offset, a slow ramp, a value frozen at its last good reading — leaves the stream
perfectly fresh and the integrity counter at **zero**. The slow drift still ends
**2.025 m** out (E-90). The only remaining candidate is **sensor redundancy with
a cross-check**, which the reference plant cannot express because it publishes
one ground truth to all five modalities.

**And the mitigation adds a surface of its own.** An adversary who can silence
one channel can now drive the vehicle to a controlled halt in **two seconds**.
That is a denial-of-service trade taken deliberately against a loss-of-lane-
position hazard, and it is the right trade — a stopped vehicle in a known state
beats a moving one twenty lane-widths out — but it is a trade and it belongs in
this document rather than in a footnote. It also means the integrity thresholds
are an availability/safety operating point, which is part of why they carry no
default (A-4).

### 5.1b · T1' — Compromise two of three channels and the monitor blames the honest one

**Opened 15 August 2026, when [ADR-0033](adr/0033-redundancy-is-the-driven-path-not-a-measurement-beside-it.md)
made redundancy the driven path.** Until then the vehicle ran on one channel and
this adversary had nothing extra to attack. The defence created the surface, which
is the ordinary way surfaces appear.

**The bound is not a matter of opinion.** Median fusion of `n` channels tolerates
`f` faults with **n ≥ 2f+1** when the faults are *crash* faults — a channel that
goes silent or obviously wrong. It requires **n ≥ 3f+1** when they are
*Byzantine*: coordinated, consistent, and free to say whatever is most damaging.
The shipped configuration is **n = 3**. So:

| adversary | tolerated today |
|---|--:|
| one channel crashes or drifts randomly | **1** |
| one channel lies coherently, two honest | **1** |
| **two channels lie coherently and agree** | **0** |

**Two of three is not a degraded case, it is an inversion.** With two compromised
channels agreeing, *the median is the lie*. `training/redundant.py`'s residual
monitor computes each channel's disagreement with the median and flags the
largest — so it flags the **honest** channel, calls it `FAULTED`, and reports it
by name. The system does not merely fail to detect the attack; it produces
confident, specific, wrong attribution, and writes it into the evidence log.

That is the worst failure shape this document contains, because every other entry
here degrades toward silence and this one degrades toward a **false positive that
looks like a successful detection**.

**Correlation is what makes f = 2 reachable.** The bound assumes independent
compromise; nothing about three channels on one vehicle is independent. A shared
supplier, a shared bus, a shared firmware image, a shared power rail, or simply
*the same fog* reaches several at once. `DEFAULT_CHANNEL_SIGMAS` deliberately
gives the three unequal noise — identical sensors share a failure mode — but
unequal noise is not independent compromise.

**And the availability side got cheaper.** Every shipped profile sets
`integrity_tolerated_faults = 0`, so **one** unhealthy channel is already enough
to drive the integrity counter to its ceiling and halt the vehicle in two
seconds. An attacker who can silence a single channel — jam a GPS, blind a
lidar — now has a two-second denial of service that did not exist when the
vehicle drove from one sensor and simply carried on. Same trade as §5.1, one
step larger.

**What would change the answer**, in order of cost: raise `n` to 4 so that
`n ≥ 3f+1` holds at f = 1 and a single Byzantine channel is survivable; source
the channels so their compromise is genuinely uncorrelated; and give the monitor
a tie-break that does not assume the majority is honest — a physical plausibility
bound per channel, which is the only thing here that does not depend on a vote.

**Not measured.** No two-channel attack has been run. The bound above is
arithmetic and the attribution inversion is read off the monitor's own rule; both
are arguments, and this document's own standard is that an argument is weaker
than a measurement. Running it is the obvious next fault-study arm.

### 5.2 · T1-B — Neutralise one gate and almost all veto authority goes with it

**Demonstrated, by ablation.** E-59: disarming **L7b** takes the veto count to
**zero on six of seven scenarios**. L6 contributes **one veto in 2,800 ticks**;
L7a contributes **zero, everywhere**.

**Sharper as of 15 August 2026, on a rebuilt baseline (E-162 – E-164).** A census
over the same 2,800 ticks: `STATISTICAL` **VETO 0**, `DETERMINISTIC` **VETO 0**,
`PHYSICAL` **VETO 149** — all 149 on the single reason code
`LATERAL_JERK_EXCEEDS_LIMIT`. `ABSTAIN` is **zero for all three**: the two silent
gates judge every tick and find nothing to object to, rather than declining to
judge. And L6's silence has a cause an attacker does not need to create — its
scores sit entirely below the corpus quantile (OD-8), so it *cannot* veto.

For this adversary that is the whole picture: **there is one gate to neutralise,
not three**, and one of the other two is already neutralised by a defect.

The architecture's security story is *three structurally independent gates*. The
measured concentration is very far from uniform: on this traffic, one gate
produces essentially all observable veto activity. An attacker choosing a single
target has an obvious one.

**The honest qualification, which the matrix row D-10 also carries:** a gate that
did not fire on the traffic it was shown has been shown to be *untested by that
traffic*, not useless. L7a vetoed once in roughly 500,000 nominal ticks (N-9).
This is a finding about where authority concentrates on these seven scenarios,
not a proof that two gates are decorative.

### 5.3 · T2 — Substitute the corpus, the twin or the configuration

The statistical gate's threshold is the corpus's 1−ε quantile. **Widen the
corpus and the gate stops firing**, with every downstream metric continuing to
look healthy — the same signature as OD-7, arrived at from outside rather than
from a feedback loop.

**What exists:** a SHA-256 digest of the corpus and a digest of the twin weights
are *recorded* in the run's evidence, and the configuration's digest is stamped
on every decision record. `CalibrationProfile` computes a checksum over exactly
the fields its authority rests on and compares it with `hmac.compare_digest`.

**What does not exist:** any of those digests being **checked against an
expected value at load**. Recording what you loaded is provenance. Refusing to
load something unexpected is integrity, and this system has the first and not
the second. An attacker who swaps the corpus gets a run whose evidence faithfully
records the digest of the attacker's corpus.

**What would close it:** a signed manifest of expected digests, verified at
assembly, with the run refusing to start on a mismatch. That needs key
management, which does not exist.

### 5.4 · T3 — Forge the evidence

`EVIDENCE.md` N-10 states it plainly: the log is **integrity-checked, not
tamper-evident**. Records are append-only JSONL with a schema version and a
per-record configuration hash. Nothing chains one record to the next, so a record
can be altered, removed or inserted without any other record disagreeing.

**Why this is the quietest attack in the document:** the evidence log is what a
certification argument is made of. An adversary who can rewrite it does not need
to touch the vehicle at all — they change what the vehicle is *recorded* to have
done. Every other threat here has a physical signature somewhere; this one does
not.

**What would close it:** a hash chain over records — each carrying the digest of
its predecessor — so that any alteration breaks every subsequent link. That is
cheap and needs no key management. **Signing** the chain root, which is what
makes it attributable rather than merely self-consistent, does need keys.

### 5.5 · T2/T3 — Run an ablated pipeline and present its evidence as governed

**Closed, 9 August 2026**, and recorded here because it was open until then.

An ablated run's records are *by construction* indistinguishable from a governed
run's — every field is identical, which is what an ablation is. Audit schema v4
stamps the profile on **every tick** (ADR-0021), so the evidence is
self-identifying, and `certification` is refused as an ablation environment
outright.

The residual is the version boundary itself: a **v3 reader parses a v4 record and
does not see the field**, so it reads an ablated run as a governed one. This is
the one schema transition in the project where an old reader is *dangerously*
wrong rather than merely poorer, and it is noted in
`astra/kernel/constants.py`.

### 5.6 · T4 — Code execution inside Core-B

Out of scope, and stated rather than hedged: **nothing in this architecture
helps.** Core-B's separation invariants constrain how the *code as written* may
be composed; they are not a sandbox. An adversary running code inside Core-B
owns the actuation path, the evidence log and every threshold.

The mitigations belong to the platform — secure boot, memory protection, a
hardware root of trust — and none of them is this project's work. A deployment
that cannot supply them does not get ASTRA's guarantees, whatever the layers say.

---

## 6 · The asymmetry, quantified

| Threat | Adversary | Status | Evidence |
|---|:--:|---|---|
| Wrong or hostile proposer | T0 | **Defended, measured** | E-11: 0 commands issued under a blocking verdict, from 99,808 per 100,000 before ADR-0016 |
| Sensor-channel corruption | T1 | **Undefended, demonstrated** | E-46, E-48, E-58 |
| Single-gate neutralisation | T1 | **Concentrated authority, measured** | E-59 |
| Artefact substitution | T2 | **Undefended** — provenance recorded, integrity unverified | — |
| Evidence forgery | T3 | **Undefended** | N-10 |
| Ablated run passed off as governed | T2/T3 | **Defended since 9 Aug** | E-62, ADR-0021 |
| Code execution in Core-B | T4 | **Out of scope by design** | — |

Read down the *status* column: the architecture is strongest exactly where it
was designed to be strong and absent everywhere else. That is not a criticism of
the design — it is what happens when a safety architecture has never had a
security review, and it is the reason this document exists.

---

## 7 · What must be true before any deployment

Ordered by cost, cheapest first. None is done.

1. **Hash-chain the evidence log.** No keys, no infrastructure, closes §5.4's
   silent-alteration case. The single best ratio in this document.
2. **Verify artefact digests at load** against a manifest, and refuse to start on
   a mismatch. Closes most of §5.3 without key management; signing the manifest
   is a later step.
3. **Wire the stream-health gate** (P2.7's option A, measured at 3.4 s of
   margin). Turns §5.1's worst case from *no reaction* into *a warning*.
4. **Require sensor redundancy and cross-check it.** The only candidate for
   §5.1's slow-drift case, unmeasurable on the current plant, and a genuine
   precondition on the integrator rather than something this repository can
   close.
5. **A platform security argument** — secure boot, memory protection, key
   storage. Not this project's work, and §5.6 is void without it.

---

## 8 · Explicitly out of scope

Stated up front, because it is what makes the rest credible.

- **No ISO/SAE 21434 work products.** No TARA in the standard's form, no
  cybersecurity goals, no CAL assignment.
- **No penetration testing.** Nothing here has been attacked. Every "demonstrated"
  in this document rests on a *safety* measurement that happens to establish the
  mechanism.
- **No cryptographic design.** Where this document says "signed", it names a
  requirement and not a scheme.
- **No supply-chain analysis**, beyond noting that FilterPy is unmaintained since
  2018 and sits inside the safety path (P4.3).
- **No privacy analysis.** Driving data is personal data in most jurisdictions
  and nothing here addresses that.

---

## Maintenance

This document cites `EVIDENCE.md` and never restates it, under the same rule the
credibility matrix follows: a number in two places will be wrong in one of them.

A threat whose status changes must be updated **in the same change** that alters
it, and the residual stated. A threat model that overstates what is defended is
worse than none, because it is the document a reviewer will trust.
