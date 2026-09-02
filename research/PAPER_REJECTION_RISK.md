# Rejection risk register — `ASTRA_Paper_Draft_v17`

**Subject** "Runtime governance of an untrusted learned controller using a layered
architecture with mechanically enforced architectural invariants" · Sushanth C., Tanay S. Huddar
**Prepared** 30 August 2026
**Assumed venue** IAES *International Journal of Artificial Intelligence* (IJ-AI) or a
comparable Scopus-indexed open-access journal, inferred from the manuscript template.
Items marked **[T]** escalate one level at an IEEE/Elsevier Transactions.

One row per reason a reviewer or editor can reject this manuscript. Written adversarially
on purpose: this is the case *against* the paper, not a balanced assessment. Cross-checked
against `EVIDENCE.md` and `CREDIBILITY_MATRIX.md`; where the repository contradicts or
confirms a claim, the row says so.

| Severity | Meaning |
|:--:|---|
| **BLOCK** | Sufficient on its own. Desk-reject, or reject after review |
| **MAJOR** | Forces major revision. Three or more together read as reject |
| **MINOR** | Will be raised; fix before submission |

---

## A · Claims against evidence

### A-1 · The paper's own results refute its central claim — **BLOCK**

The title, abstract and §3.1 sell three gates "built differently from one another on
purpose, so that a fault which defeats one of them is not expected to defeat the others."
Table 6 shows the statistical and deterministic gates issue **0 vetoes across 2,800 steps
and seven scenarios**, and that neutralising either **reproduces the governed row in every
cell**. §4.2 concedes the physical gate issued all 149 vetoes on a single reason code.

The reviewer's summary writes itself: *this is a one-gate architecture with a bounds
check.* You report it honestly, which does not change what it says. The three-gate
structure is the paper's novelty and the evidence does not support it.

### A-2 · The conformal gate is unsound as instantiated, and you prove it — **BLOCK**

§4.2 reports live non-conformity scores spanning 3.3648–3.4083 against a corpus of
3.8758–5.4312: **zero overlap**, live median 13% below the corpus minimum. Mondrian
class-conditional ICP's coverage guarantee requires exchangeability within the
conditioning class. You measure it violated. Therefore L6 carries no guarantee, and its
silence is not evidence of sound proposals — §4.2 says exactly this.

A paper cannot present as a pillar a mechanism it demonstrates is invalid. Either fix the
calibration or remove L6 from the contribution claim.

*Repo:* E-159, E-164. OD-8 is open and has been since August.

### A-3 · Governance makes one fault 8.8× worse, unexplained — **BLOCK**

Table 5, lateral noise: governed **1.307 m**, ungoverned **0.148 m**. §4.2 reports the
peak at 1.7179 m against a 1.75 m corridor — a **3.2 cm margin, single seed** — and states
"two earlier explanations of this run were refuted by measurement, so the mechanism is
recorded as open."

In a safety paper, an unresolved case where the safety system degrades safety is close to
disqualifying. Not because it happened, but because it is unresolved at submission. Also
note the internal tension: §4.1 says "the vehicle stays inside the corridor on every
scenario," which is true only by 1.8%.

### A-4 · The abstract's headline result is not the paper's contribution — **MAJOR**

The abstract leads with "median fusion of three position channels holds the peak estimator
error at 0.1323 m under an injected 1 m bias, against 1.1805 m for a single channel."
§4.1 then states: median voting across dissimilar channels is standard analytical
redundancy [23] and "no new technique is claimed here."

You have foregrounded a result you concede is not novel. The genuinely novel claim — the
health signal computed upstream of the estimator, the one safety input not downstream of
the common cause — is never quantified against a downstream alternative.

### A-5 · No efficacy claim survives, and §1 says so before the results — **BLOCK [T]**

"All measurements were taken in a simulation written by the authors, in which the plant,
the process model, the prediction model and the calibration corpus all derive from a
single kinematic bicycle model. Where these agree, they agree by construction... it does
not establish accuracy, and no false-positive or false-negative rate is reported for any
gate."

Correct, ethical, and strategically fatal. You have told the editor in the introduction
that the paper establishes no efficacy. `CREDIBILITY_MATRIX.md` agrees: **0 of 30 rows at
[M-ext]**, and section D's five central claims are `[NOT DONE]`.

### A-6 · The IMU-dropout result is not a result about the gates — **MAJOR**

The fault the paper foregrounds (Fig 2, the "row of most interest") is caught by the
health counter, not by any gate. §4.1 concedes "no gate detects the fault" and that the
18 vetoes are "a reaction to the remediation rather than a detection of its cause." What
remains is: a stale-frame watchdog fired at +5 steps. That is a standard mechanism. The
paper's strongest fault-handling result is therefore its least novel one.

### A-7 · One abstract claim does not discriminate — **MINOR**

"Lane deviation remains within the 1.75 m corridor on every fault" is true of the
ungoverned runs too, on five of six faults (Table 5). The claim separates nothing.

---

## B · Experimental design

### B-1 · n = 1 — **BLOCK [T]**

§4.3: "The results are single-seed per scenario, with reproducibility established by
re-running rather than by sampling across seeds." Every table is a point estimate with no
spread. Table 2's 0.017 vs 0.024 m, Table 5's 0.017 vs 0.055 m — nothing there is
distinguishable from seed noise, and the paper offers no way to tell.

This is the cheapest item on the register to fix and one of the most damaging to leave.
20–30 seeds, median and IQR, in every table.

### B-2 · No baseline from prior art — **BLOCK**

Six pages of related work — Simplex [5], L1Simplex [6], sandboxing [7], Neural Simplex
[8], black-box Simplex [9], REDriver [11], shielding [14], CBF [15][16], conformal OOD
[18][19] — and the only comparison is against *ungoverned*. Ungoverned is an ablation, not
a baseline.

The venue's own published work does better: the comparator paper in IJ-AI 13(4) compares
against four named published methods on a public dataset. You have a synthetic plant you
fully control and could implement a Simplex switch against in a day. There is no defensible
answer to "why didn't you?"

### B-3 · Six hand-chosen faults, no fault model — **MAJOR**

No taxonomy, no coverage argument, no justification for the selection, no reference to a
published fault classification (ISO 26262 Part 5 fault models, or the FDI literature). Your
own matrix says it: "six hand-chosen faults are not a population drawn from anything."

### B-4 · A declared benchmark reports no results — **MAJOR**

§3.4 declares four benchmarks and describes the fourth: "A shadow benchmark runs a
candidate mechanism with no authority over any verdict." §4 never reports it. This is your
E-51–E-53 shadow detector study — health at +5 ticks against a departure at +73, innovation
at +84, Trust Index catching both, zero false alarms on the control — and it is one of the
better results you have. Report it or delete the sentence. A methods/results mismatch reads
as carelessness and invites a closer look at everything else.

### B-5 · The ten stability criteria are never stated — **MAJOR**

Abstract and §5 both claim "all ten study-defined stability criteria" pass over 100,000
steps. Three are hinted in §4.1 (drift in mean deviation, memory growth, per-step cost).
The other seven appear nowhere. Unfalsifiable as written, and §4.1's own hedge — "these are
acceptance limits chosen for this study rather than established standards... not a formal
stability analysis in the control-theoretic sense" — invites the question of why the word
"stability" is used at all.

### B-6 · The proposer is never characterised — **MAJOR**

PPO on a Lagrangian relaxation of a CMDP, PID Lagrangian dual updates, Stable-Baselines3 —
and then nothing. No reward function, no hyperparameters, no training curves, no
statement of how well the ungoverned policy drives. Every governance benefit in Table 5 is
measured against an unquantified baseline controller. A reviewer will ask whether the gains
come from good governance or a weak proposer, and the paper cannot answer.

*Repo:* this is not a hypothetical concern. `SOAK_REPORT.md` records a period in which the
trained policy brought the vehicle to a complete stop inside its own training environment,
with no part of ASTRA involved.

### B-7 · 400 steps is 20 seconds — **MAJOR**

The fault study runs 400 control steps at 20 Hz. Every headline fault result in Table 2 is
a 20-second episode with the fault open for 10 seconds. The 100,000-step run is nominal
only. There is no long-horizon faulted run anywhere in the paper.

### B-8 · Fault injection only at the sensor boundary — **MINOR**

§3.4 states faults are injected "at the sensor boundary and never inside the core." Sound
methodology, but it means the paper says nothing about the failure mode the architecture is
nominally built for: a compromised or badly-behaved Core-A. The one-way channel, the trust
isolation, and SI-4, SI-5 and SI-10 are all defences against a threat that is never
exercised.

### B-9 · The control run is not clean — **MINOR**

Table 2 records 1 veto and a 0.365 m initial offset on the no-fault control. §4.1 explains
it as a startup transient present in every run. Fair, but it means the "clean control"
against which every fault is compared is itself in a transient for part of the window, and
the paper never shows the transient has settled by step 200 when the faults open.

---

## C · Novelty and positioning

### C-1 · "Mechanically enforced" will not survive scrutiny — **MAJOR**

Title, abstract, §2.1 and §3.3 all lean on it. §4.3 then concedes: "The implementation is
Python, so these are not compile-time guarantees in the sense a systems reviewer may
expect." Table 1 lists two invariants enforced **by test**, which is not enforcement — it is
a check on the cases you thought of. Five are import-linter and mypy contracts, which are CI
conventions in a dynamically typed language.

The word in your title is the most attackable phrase in the paper.

### C-2 · These are not invariants — **MAJOR [T]**

An invariant is a predicate that holds over all reachable states. Table 1's entries are
architectural rules ("no layer above L2 reads a raw sensor payload"). There is no state
space, no reachability argument, no formal statement, no proof. A formal-methods reviewer
will object to the term and to the paper's implicit borrowing of its authority.

### C-3 · One equation, no formalism — **MAJOR [T]**

Eq (1) is the merge rule and is the only numbered equation in the paper. For a manuscript
about a governance architecture with "invariants" in the title, there is no formal statement
or proof of any property — not even the obvious one, that fail-closed aggregation implies no
command reaches the actuator without a non-empty participating set of PASS verdicts.

### C-4 · The novel placement claim is not compared to standard practice — **MAJOR**

Health computed before the estimator is the real contribution. It is adjacent to established
automotive practice — input plausibility checks and sensor-validity monitoring as ISO 26262
safety mechanisms, AUTOSAR E2E protection, and classical FDI beyond Isermann [23]. None of
that literature is engaged. A domain reviewer will say the novelty is already common
practice, and the paper gives them no answer.

### C-5 · The nine layers are a decomposition, not a result — **MINOR**

Nothing in the evaluation tests the *nine-ness*. No ablation removes a layer; no argument
shows nine is necessary or sufficient. The layer count is in the title, the abstract and the
conclusion, and is never load-bearing.

### C-6 · Graduated degradation is not new either — **MINOR**

Two-axis degradation (posture × capability) is presented as a departure from "a single
severity ladder." Capability-based degradation is standard in automotive functional safety
(degraded modes with function-level withdrawal) and in avionics. Not cited.

---

## D · Reproducibility and compliance

### D-1 · Nothing in the paper is checkable by anyone — **BLOCK [T]**

Three compounding facts: (i) the code is withheld — "not presently public pending patent
consideration, so the results are internally rerunnable rather than externally
reproducible"; (ii) the plant is synthetic, self-authored, and also withheld; (iii) there is
no parameter table.

ε, θ₁, θ₂, θ_halt, the per-context quantile levels, the jerk limit, the speed and lateral
acceleration bounds, the friction margin, the UKF process and measurement noise beyond the
three position sigmas, the PPO hyperparameters, the reward, the constraint budgets, and the
capability-to-modality map — none are given. A reader cannot reimplement or check a single
number. Elsevier and IEEE data-availability policies make this an editorial-desk issue, not
only a reviewer one.

### D-2 · No algorithm boxes — **MAJOR**

The merge rule, the two-axis degradation machine, the arbitration policy and the health
computation are all described in prose only. For a systems paper this is the minimum
expected apparatus.

### D-3 · "169 source files" overstates the implementation — **MINOR**

`src/` holds 83 Python files; `tests/` holds 86. 169 is the sum. Accurate, but a reader
takes "static checking over 169 source files" as implementation size. Say "83 implementation
and 86 test files."

### D-4 · Test count and coverage are not research results — **MINOR**

"3,065 tests and 3 strict expected-failure tests, static checking over 169 source files, and
97.47% statement coverage" sits in §3.4 as though it were evidence. §4.3 then argues against
its evidential value — correctly, citing your own D-0. Move it to a reproducibility note.
Separately, I could not corroborate 3,065/97.47% from the repo docs (`PENDING.md` records
2,618 tests at 97.89%), so confirm the figures are current before submission.

### D-5 · Patent-pending status may conflict with an open-access licence — **MINOR**

IJ-AI publishes under CC BY-SA. Check that publishing an architectural description under a
share-alike licence is compatible with the intended filing, and that the filing is in place
*before* submission rather than after. This is a question for your institution, not a
reviewer objection, but it can stop a submission cold.

---

## E · Technical objections a specialist will raise

### E-1 · The non-conformity score is normalised by the filter's own uncertainty — **MAJOR**

§3.1: the score is the distance between proposed command and twin output, "divided by the
estimator's own standard deviation in lateral acceleration." This makes the acceptance band
a function of filter tuning. It is almost certainly the mechanism behind A-2: change the UKF
covariance and the whole score distribution moves — which is what happened when the corpus
was regenerated (E-159 records the gap *widening* from 0.2% to 13% after the covariance
correction). The paper presents the normalisation without discussing this coupling.

### E-2 · The common-cause argument is incomplete — **MAJOR**

§3.2 and Fig 1 correctly identify that every gate reads L2 and that health is the one input
that does not. But health is computed from *frame freshness* only. A sensor that reports
fresh, plausible, wrong values — the position drift in Table 2 — defeats health and the
estimator together. Table 2 shows this (drift produces 1 veto and 0 steps outside nominal,
identical to the control), and §4.3 does not draw the conclusion: the common-cause fix
covers staleness, not corruption.

### E-3 · 2f+1 is asserted without matching the fault model — **MINOR**

§4.1's redundancy argument ("limiting the influence of f such channels requires 2f+1 of
them") assumes at most one corrupted channel and no collusion, which the paper states. But
the three channels share a plant, a timebase and an injection harness. The independence that
2f+1 requires is asserted, not shown.

### E-4 · Latency reporting is not a real-time argument — **MAJOR [T]**

Median 3.0–7.7 ms, p99 9.4–11.2 ms, **slowest single step 14.1–140.4 ms**, 11–76 steps per
2,000 over the 10 ms software budget, 0–1 per 2,000 over the 50 ms period. The paper
concedes these are "strongly host-sensitive and reported as a characterisation rather than
as a bound," measured on an idle host, with no WCET analysis and no load testing.

A 140 ms worst case against a 50 ms deadline is a 2.8× overrun. For a system whose entire
purpose is intercepting commands before they reach an actuator, "at least 99.95% of steps
met the deadline" is a statement that 1 step in 2,000 did not. Python is never discussed as
a deployment vehicle.

### E-5 · 20 Hz is low and unjustified — **MINOR**

For lane-keeping, 20 Hz will be questioned by vehicle-control reviewers. The 50 ms period
and the 10 ms internal budget are both asserted without derivation.

### E-6 · Table 4 is degenerate and its claim is circular — **MINOR**

Five rows; four columns identical (yes / Terminal / 40). §4.1 says the table "is a
measurement of the machine rather than a document kept beside it, so the two cannot drift
apart" — but a table produced by driving the machine cannot disconfirm the machine. It shows
the map is non-empty, and nothing more.

### E-7 · Steps-outside-nominal is reported without a cost — **MINOR**

Table 2's IMU dropout spends 195 of 400 steps outside nominal and the paper treats this as
success. Nearly half the run in a degraded posture is an availability cost that is never
weighed against the safety benefit — and D-8 in your own matrix warns that availability
figures are "quotable only next to D-7."

---

## F · Related work and references

### F-1 · Related work is a list, not a synthesis — **MAJOR**

Fifteen consecutive paragraphs of "Author et al. [n] did X; limitation Y." Thorough and
unusable. A comparison table — method / what it monitors / where the monitor sits relative
to the state estimator / response granularity / what it assumes — would compress three pages
to one and make the placement argument land structurally instead of rhetorically. This is
also the single highest-leverage edit in the paper.

### F-2 · Cited-but-never-discussed references — **MINOR**

[10] (ASTM F3269-21) appears only inside the range "[5]-[10]" and is never discussed. [20]
(Hendrycks & Gimpel) appears only in "[18]-[21]" and is never discussed, which is
conspicuous in a paper about OOD detection.

### F-3 · Missing literature — **MINOR**

Beyond C-4: no simplex-with-conformal work, no runtime-monitoring-for-autonomy survey past
2021 [21], nothing on voting/fusion architectures in automotive, no ISO 26262 Part 5 fault
models, and nothing on assurance cases (GSN) despite the paper being an assurance argument.

### F-4 · Some references lack DOIs — **MINOR**

[17], [20], [32], [33], [36]. Venue-dependent, but IAES checks.

---

## G · Presentation

### G-1 · Only two figures in eleven pages — **MAJOR**

Fig 1 is a block diagram; Fig 2 is one scenario. The exchangeability violation — your most
striking single result — is delivered as four numbers in a prose sentence. Two overlaid
histograms showing zero overlap would be the most persuasive image in the paper. The
noise-burst failure is not plotted at all. Neither is the 100,000-step run.

### G-2 · Tables 2, 5 and 6 overlap heavily — **MINOR**

Same seven scenarios, overlapping metrics, three tables. Merge into one wide table with
governed / ungoverned / per-ablation columns. Table 6's rows 1–3 are byte-identical and row
4 is all zeros — true and important, but as a table it invites "why is this a table?" The
abstention count, which is what actually distinguishes the result from an uninformative
null, is discussed in prose and never tabulated.

### G-3 · Figure 2 is hard to read — **MINOR**

Greyscale, dual y-axis, four annotation callouts, and a lower panel whose veto triangles
will be illegible at print size. The step-function panel labels four states but only two are
ever entered.

### G-4 · The abstract ends on negative results — **MAJOR**

Its last two sentences are "Two of the three gates issue no vetoes, and the exchangeability
precondition of the statistical gate is measured to be violated." Editors triage on
abstracts. Whatever the body says, the abstract must state what the work *provides* before
it states what it does not.

### G-5 · Register and phrasing — **MINOR**

Several non-idiomatic constructions: "The functionality of the research is given as: i)",
"This research paper is in the following format", "Section 3 gives the explanation of the
three gates", "provides the results and discussion of the research method." These are IAES
house style, inherited from the template, and should be **kept** for that venue — but they
will read as awkward at any other, so they are a venue-lock.

### G-6 · The title is long and overclaims — **MINOR**

Nineteen words, two of which (C-1, C-2) the paper cannot support.

---

## H · Cross-document and process risk

### H-1 · The companion survey draft contradicts this one — **BLOCK**

`astra survey (2).pdf` — four authors, same system, one shared author — states a CARLA
validation as completed work ("The prototype runs a single 21-minute autonomous drive
through CARLA Town04"), reports a hardware WCET of 1.25 µs at 500 MHz, and presents FB1–FB4
as implemented. None of that has happened: `CARLA.md` is a handover for a run not yet
performed, no hardware exists, and `CREDIBILITY_MATRIX.md` records that FB2 and FB3 were
measured in shadow, found to break the gates they feed, and never connected.

If both documents circulate, anyone who reads them together sees a direct contradiction
about what was validated. **This is the highest-consequence item on the register**, because
unlike everything else here it is not a quality judgement — it is a factual conflict, and it
attaches to v17 by association even though v17 is the honest one. Resolve the survey draft
before v17 goes anywhere.

### H-2 · AI-assistance declaration — **MINOR**

Present and honest. Check IJ-AI's required wording; some venues specify a form of words, and
some require it in the cover letter rather than the manuscript.

### H-3 · Authorship — **MINOR**

"Both authors contributed to the architecture, implementation, evaluation and manuscript" is
undifferentiated and increasingly non-compliant with CRediT-style requirements. Note also
that the survey draft has four authors plus a named guide; if that work overlaps, the
authorship difference will need explaining.

---

## The ten that matter

Ranked by probability of ending the submission.

| # | Item | Fix cost |
|:--:|---|---|
| 1 | **H-1** Survey draft states unperformed CARLA work as completed | Days — non-negotiable |
| 2 | **A-1** Two of three gates contribute nothing; ablation confirms it | Reframe, or fix L6 |
| 3 | **A-2** Conformal gate's precondition measurably violated | Weeks — recalibrate |
| 4 | **A-3** Governance 8.8× worse on lateral noise, cause unknown | Days — root-cause |
| 5 | **B-2** No prior-art baseline | 2–3 days — implement Simplex |
| 6 | **B-1** Single seed everywhere | Hours — rerun with 30 seeds |
| 7 | **A-5** Wholly self-referential; no efficacy claim survives | Weeks — CARLA |
| 8 | **D-1** No code, no plant, no parameters — nothing checkable | Days — parameter appendix |
| 9 | **C-1/C-2** "Mechanically enforced invariants" overclaims | Hours — retitle, restate |
| 10 | **E-4** 140 ms worst case against a 50 ms deadline | Days — measure under load |

Items 4, 5, 6, 8 and 9 together are roughly a week, and move the paper from *reject* to
*major revision* at this venue. Items 2, 3 and 7 are what move it to *accept* — and they are
the same three things `CREDIBILITY_MATRIX.md` has been saying for a month.

---

## What this register is not

It does not say the work is bad. The engineering discipline in this repository is well above
what the target venue typically publishes, the defect register is genuinely unusual, and
§4.3's willingness to report three findings that run against the architecture is the best
thing in the manuscript.

The problem is a mismatch: **Transactions-grade honesty attached to Transactions-grade
claims, with neither the external validation nor the baselines that either would require.**
Lower the claims or raise the evidence. The current draft does neither, and a reviewer will
read the gap as overclaiming even though the body is scrupulous.
