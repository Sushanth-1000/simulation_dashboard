# Learning Path

The folders are numbered for reference, not for reading. This is the order that
works, because it follows **what depends on what**.

---

## The principle

> Read the *history* before the *architecture*.

Almost every part of the current design exists because something specific went
wrong and was measured. Read section 05 first and it looks like an arbitrary pile
of nine layers. Read 02–04 first and each layer arrives as the answer to a
question you have already seen asked.

---

## Stage 1 — Why this exists at all

**Read:** `01_PROBLEM_AND_MOTIVATION/`

Do not skip this even if you know autonomous systems. The specific failure mode
ASTRA targets — *structurally healthy, semantically wrong* — is narrower than
"AI safety" and the whole design follows from that narrowness.

**You are ready to move on when you can say** why lockstep redundancy, a
hypervisor and an HSM all miss this failure mode, in one sentence each.

---

## Stage 2 — How it got here

**Read, in order:** `02_PROJECT_HISTORY/` → `03_TIMELINE/` → `04_ARCHITECTURE_EVOLUTION/`

The single highest-value stage. Section 04 is where the design becomes
*inevitable* rather than arbitrary: old architecture → problem discovered →
decision → new architecture, repeatedly.

**Ready when** you can name three things the architecture does *because a
measurement contradicted a document*.

---

## Stage 3 — What it is now

**Read:** `05_CURRENT_ARCHITECTURE/` → `06_COMPONENTS/` → `07_DATA_FLOW/`

05 gives the shape, 06 goes component by component, 07 traces a tick end to end.

**Read 07 with 06 open.** Data flow is where components stop being boxes.

**Ready when** you can trace a sensor reading to an actuator command and name
every transformation on the way.

---

## Stage 4 — How it actually works

**Read:** `10_MATHEMATICS/` → `09_ALGORITHMS/` → `08_INTERNAL_MECHANICS/` → `23_RUNTIME_BEHAVIOR/`

**Mathematics comes first here, deliberately.** Section 10 starts from what a
probability distribution is and builds to the unscented transform; 09 then uses
that vocabulary without re-explaining it.

If you already know Kalman filtering and conformal prediction, skim 10 and start
at 09. If you do not, 10 is written for you and 09 will be unreadable without it.

**Ready when** you can explain what the covariance matrix `P` *means* physically,
and why the unscented transform exists at all.

---

## Stage 5 — What can go wrong

**Read:** `11_UNCERTAINTY_AND_ERROR/` → `12_SAFETY_AND_RELIABILITY/`

The difference between *"the system works"* and *"the system can be trusted to
work safely"* lives here.

**Ready when** you can explain how a false negative arises — mechanically, not in
principle.

---

## Stage 6 — What is actually known

**Read:** `13_TESTING_AND_VALIDATION/` → `14_SIMULATION/` → `15_EXPERIMENTS/`

The critical distinction: **proven** vs **experimentally demonstrated** vs
**assumed** vs **not yet validated**. Getting this wrong is how people end up
believing a prototype has properties it has never been shown to have.

**Ready when** you can say what `[M-syn]` licenses and what it does not.

---

## Stage 7 — What was tried and failed

**Read:** `16_FAILED_APPROACHES/` → `18_CHALLENGE_LOG/` → `17_DECISION_LOG/`

**Failures before decisions**, on purpose. The decisions only make sense once you
know what they were chosen *against*, and several were forced by a refutation.

**Ready when** you can explain why FB2 and FB3 were built, measured, and then
deliberately not wired.

---

## Stage 8 — Judgement

**Read:** `19_TRADEOFFS/` → `20_ALTERNATIVES/` → `21_BENEFITS/` → `22_LIMITATIONS/`

Where you form your own view. By now you know enough to disagree usefully.

---

## Stage 9 — Where it stands

**Read:** `28_CURRENT_STATUS/` → `29_REMAINING_WORK/` → `27_RESEARCH_QUESTIONS/`

Honest assessment: done / needs validation / partial / not built / open research
/ major risks / next steps.

---

## Stage 10 — Check yourself

**Read:** `26_INTERVIEW_QUESTIONS/` → `25_FAQ/` → `30_MASTER_A_TO_Z_DOCUMENT/`

The questions are graded 1–8 and are written to make you explain *why*, not
recall *what*. If you cannot answer at a level, the section that fixes it is
named.

**Read 30 last.** It is the whole story as a narrative, and it lands properly
only when you already know the pieces it connects.

---

## Reference, not reading

`24_GLOSSARY/` — keep it open throughout rather than reading it through.

---

## Three shortcuts, if you are in a hurry

| You have | Read |
|---|---|
| **1 hour** | `00_START_HERE/Executive_Overview` → `30_MASTER` → `28_CURRENT_STATUS` |
| **1 day** | Stages 1, 2, 3, 9 — the why, the history, the shape, the state |
| **1 week** | All ten stages in order |

The one-hour path gives you a *map*. It does not give you a mental model, and you
will not be able to challenge a decision from it.

---

## How to read critically

This project's own conventions are worth borrowing while you read it:

1. **Every number should have a source.** If a claim has no `E-n`, ask why.
2. **Distinguish the measurement from the conclusion.** Most retractions here
   came from arithmetic that was right and a configuration that was meaningless.
3. **Look for what a claim does *not* license.** The credibility matrix has a
   column for exactly this, and it is usually the most informative one.
4. **Silence is not evidence.** A gate that never fires might be well-tuned, or
   broken, or measuring the wrong thing — and the project has an example of each.
