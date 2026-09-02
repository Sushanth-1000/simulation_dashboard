# research/ — the reference folder

Everything produced in the 31 August 2026 audit session. **Start here.**

Every quantitative statement in these documents was produced by **running the code**, not by reading
project documentation. Where a document and a measurement disagreed, the measurement is recorded and
the document is named.

---

## Read in this order

| # | File | What it is | Read it when |
|--:|---|---|---|
| 1 | **`conference_master_plan.md`** | The master roadmap. 34 sections: audit, credibility classification, contributions, hypotheses, experiment matrix, baselines, ablation, datasets, CARLA, industry demo, safety case, statistics, provenance, red team, gates, verdict | You want the whole picture, or the next action |
| 2 | **`REBASELINE_2026-08-31.md`** | Six benchmarks re-run against regenerated artefacts, with every delta against the published figures | You need a number for the paper |
| 3 | `conference.md` | Earlier 24-step IEEE plan. Superseded in scope by (1) but retains the venue analysis and figure plan | Venue selection, figure planning |
| 4 | `final_plan.md` | One-week plan written against the Q2 referee report | You want the short-horizon task list |
| 5 | `PAPER_REJECTION_RISK.md` | 44 rejection reasons for the journal manuscript, severity-ranked | Before touching the paper |

---

## The five things that matter most

1. **The committed policy did not drive.** `var/policy/synthetic.pt`, force-committed 9 August as
   *"the policy the measurements were actually taken with"*, predates three ADRs. Measured 31 Aug:
   200/200 ticks vetoed. All five checkpoints failed. Regenerated; the loop closes again.
   **Not yet committed — do this first.**

2. **13 findings reproduced on a freshly trained policy. Every absolute number moved.** The blind
   spot, OD-8, redundancy (to ~1%), health at +5, the ablation nulls — all held. Deviations, veto
   counts and the shadow-detector table all changed.

3. **The 27× claim is withdrawn.** IMU dropout re-measured at 0.089 m governed against 0.163 m
   ungoverned — **under 2×**, not 27×. It is in the manuscript's abstract.

4. **Table 4 is wrong, and the truth is better.** Innovation is silent on all seven arms, not firing
   at +84. Trust fires at +55 on position drift, not "none". Trust raises a **false alarm on the
   clean control**, reported as zero. So health is *specific* and trust is *indiscriminate* — a
   stronger placement argument than the paper makes.

5. **Two of three gates issue zero vetoes.** Complementarity is unestablished. L6 is structurally
   unable to fire (OD-8). `RAIN_NIGHT` is unreachable by the classifier, so one of three context
   classes can never be calibrated.

---

## Reproduce any of it

```bash
py -3.12 -m venv .venv
.venv/Scripts/pip install -e ".[estimation,learning]" pytest hypothesis import-linter
.venv/Scripts/python -m tools.check_artifacts     # must say "the vehicle drives"
.venv/Scripts/python -m benchmarks.fault_study
.venv/Scripts/python -m benchmarks.comparison
.venv/Scripts/python -m benchmarks.ablation
.venv/Scripts/python -m benchmarks.gate_census
.venv/Scripts/python -m benchmarks.exchangeability
.venv/Scripts/python -m benchmarks.arms
```

If `check_artifacts` refuses, run `make artifacts` — but note that trains a **new** policy, and
finding (2) above is the reason the figures will move again.

---

## Status at close of 31 August 2026

| | |
|---|---|
| Test suite | 3,063 passed · 2 failed · 1 skipped · 3 xfailed |
| Artefacts | regenerated, driving, **uncommitted** |
| `[M-ext]` rows | **0 of 30** |
| Open P0 publication blockers | **6** |
| IEEE readiness | 34 / 100 |
| Industry demo readiness | 58 / 100 |

**Next action:** commit the artefacts. Thirty seconds, and nothing else works without it.

## E17 30-seed sweep (1 Sep 2026)

- `E17_30SEED_RESULTS.md` — what was run and what came out
- `E17_STATISTICAL_ANALYSIS.md` — tests, effect sizes, multiplicity ledger
- `E17_REGIME_ANALYSIS.md` — **negative result**: the regime hypothesis is a Simpson's paradox
- `E17_FINAL_DECISION.md` — GO with the claim narrowed to position faults

Raw output, tables, figures and the pre-registration are under `results/E17_30SEED/`.

## Correction (1 Sep 2026)

- `E17_INVALIDATION.md` — **the position-fault headline is an artefact**; `FaultChannel.POSITION_Y` is inert against the driven sensing path. C1 NOT ESTABLISHED.

## Validation audit (1 Sep 2026)

- `E17_VALIDATION_REPORT.md` — full audit; verdict **E17 NEEDS MINOR FIXES**
- `E17_FAULT_INTEGRITY.md` — per-fault injection-path proof + 4 negative controls
- `E17_FAILURES_AND_INVALID_RUNS.md` — 0 execution failures; 180/540 records excluded

CSV artifacts in `results/E17_FINAL/`; integrity JSON in `results/E17_INTEGRITY/`.
