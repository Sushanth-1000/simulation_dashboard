# E18-R2 — Limitations

## Statistical

- **The per-run criterion is a threshold on a continuous quantity.** A run at 2.4 % and one at 2.6 %
  are counted differently while being materially identical. The band was frozen in advance and is
  applied as written; the counts should not be read as more precise than they are.
- **n = 30 runs.** 13/30 has a Wilson 95 % interval of roughly [26 %, 61 %], which excludes the 80 %
  the PASS criterion implies — the decision is not marginal — but the point estimate is not precise.
- **Effective sample size is estimated, not measured directly.** It is inferred from the ratio of
  observed to binomial variance, which assumes the only departure from independence is serial
  dependence within a run. For P3, where the lag-1 autocorrelation is ~0, that assumption is clearly
  violated and the "2 effective ticks" figure should be read as *"almost all variance is between
  runs"* rather than as a literal count.
- **The ideal-monitor benchmark (29.2/30) assumes independent ticks at exactly 5 %.** It is an upper
  bound for orientation, not an achievable target for a correlated process.

## Scope

- **No new data.** R2 reuses E18's score files by design, which is a strength for attribution and a
  limitation for generality: it inherits every property of those runs, including any that are
  artefacts of the plant or the seeds.
- **Clean runs only.** No detection was measured. A PASS would have licensed only a statement about
  clean-behaviour control, and PARTIAL licenses less.
- **Three policies, one plant, simulation only.** `[M-syn]`; `[M-ext]` remains **0 of 30**.
- **One window definition.** Fixed by `_FAULT_FIRST`, not searched.

## Interpretive

- **R2 cannot distinguish "eps = 0.05 is too tight for this process" from "this process cannot be
  monitored per-tick at all".** Both are consistent with the observations. Repair B in
  `final_decision.md` is designed to separate them.
- **The early-window tail asymmetry from `E18_R1/analysis.md` is now partly explained** — the matched
  quantile came out lower, as predicted — but *why* the upper tail is heavier in ticks 0–199 while
  mean scores barely differ remains unresolved.
- **P2 is reported but not analysed.** It is included in the tables for the record only, per the
  standing instruction not to tune for it or claim it.
