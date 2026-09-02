# E17 — Failures and Invalid Runs

**1 September 2026**

---

## 1 · Execution failures

**None.** The 30-seed sweep completed 90/90 profiles (2,160 closed-loop runs of 400 ticks) in
12,708 s with **0 failures, 0 retries, 0 dropped seeds**. `results/E17_30SEED/logs/failures.json`
is `[]`.

No NaN, no Inf, no overflow was observed in the §5 verification subset (3 policies × 3 seeds ×
6 faults). All expected logs were produced.

## 2 · Invalid runs — scientific, not operational

Every run executed correctly. **Two of six faults are scientifically invalid because the injected
corruption never reached the pipeline.**

| fault | runs affected | reason | disposition |
|---|--:|---|---|
| `position_bias` | 90 (30 seeds × 3 policies) | ground-truth regeneration, ADR-0033 | **excluded from all conclusions** |
| `position_drift` | 90 | same | **excluded from all conclusions** |

**180 of 540 records (33.3 %) are excluded.**

## 3 · Disposition of the excluded data

The rows are **retained** in `results/E17_FINAL/*.csv` with `validity = INVALID` and
`invalid_reason` populated, and the raw JSON is retained under `results/E17_30SEED/raw/`.

They are not deleted. An audit that erases its contaminated rows cannot be checked, and the
contaminated rows are the evidence for the defect.

They must not be cited, plotted as results, or included in any aggregate. Documents carrying the old
conclusion have superseded-in-part banners pointing at `E17_INVALIDATION.md`.

## 4 · Superseded documents

| document | status |
|---|---|
| `E17_30SEED_RESULTS.md` | position rows superseded |
| `E17_STATISTICAL_ANALYSIS.md` | position rows superseded |
| `E17_FINAL_DECISION.md` | C1 verdict superseded |
| `E17_CORRECTED_DECISION.md` | position rows suspect — predates this audit |
| `E17_SECOND_POLICY_DECISION.md` | "policy-independent to three decimals" explained: no policy saw the fault |
| `E17_REGIME_ANALYSIS.md` | **stands** — computed on speed faults only |

## 5 · Defects found in this project's own measurement code

Three, all of the same shape — a statistic reading 0.5, or a fault appearing present, by construction:

1. **31 Aug — L1 health-count.** `T_L1` was the count of non-HEALTHY modalities; BIAS/DRIFT/STUCK_AT
   keep streams fresh by construction, so AUC was 0.500 by construction. Four of six `A(f)` values
   were artefacts.
2. **31 Aug — `lateral_noise` location statistic.** AUC on raw values cannot see a zero-mean variance
   fault. `D_L1` 0.504 → 0.995 once a rolling-dispersion statistic was used.
3. **1 Sep — position ground-truth regeneration.** This document.

A fourth, in the audit tooling itself, caught before it produced a conclusion:

4. **1 Sep — Control C measured end-to-end `D_s`** and returned "BYPASS NOT CONFIRMED". `D_s` is
   confounded by closed-loop compensation: the vehicle steers to null a position bias, so `D_L1`
   falls to 0.513 while the signal carries the full 1.0 m fault. Rewritten to measure boundary
   magnitudes, which confirmed the bypass.

**Standing rule, added to the pre-registration template:** a sweep must assert that the faulted arm
differs from the clean arm **at the delivered signal** before any result is believed, and fail the
run if it does not. A degenerate cell is an error, never a result.
