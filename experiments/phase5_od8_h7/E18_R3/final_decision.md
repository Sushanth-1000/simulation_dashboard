# E18-R3 — Final Decision

**3 September 2026** · 60 clean runs × 3,400 ticks · frozen v3 thresholds, no recalibration
**Criterion frozen in `preregistration.md` before any long run was executed.**

---

# VERDICT: PASS-R3

**P1 reaches 30/30 runs in band at n = 3200.** The frozen criterion required ≥ 24/30.

**The limitation was precision, not dynamics.** The conformal score is usable — at a longer
evaluation window.

---

## 1 · Result

| policy | n=200 | n=400 | n=800 | n=1600 | n=3200 |
|---|:--:|:--:|:--:|:--:|:--:|
| **P1** | 12/30 | 16/30 | 21/30 | 29/30 | **30/30** |
| P3 | 2/30 | 4/30 | 6/30 | 6/30 | 5/30 |

P1 improves monotonically with window length and saturates at perfect coverage. The n = 200 column
reproduces E18-R2's result (13/30 there, 12/30 here — same design, sampling noise), which is the
internal consistency check the pre-registration required.

## 2 · The mechanism test

Fitting `log SD(FAR_r) = a + b·log n`:

| policy | SD@200 | SD@400 | SD@800 | SD@1600 | SD@3200 | slope b |
|---|--:|--:|--:|--:|--:|--:|
| P1 | 0.0696 | 0.0483 | 0.0328 | 0.0186 | 0.0086 | **−0.739** |
| P3 | 0.1892 | 0.1147 | 0.0606 | 0.0305 | 0.0152 | **−0.918** |

Both are steeper than the −0.5 an independent-tick monitor would give. **Per-run false-alarm
variability falls with window length, decisively.** H0 (dynamics-limited) is rejected for both
policies.

### An anomaly I cannot explain

**The slopes are steeper than binomial, and they should not be.** −0.5 is the independent-sampling
floor; correlated data should give a *shallower* slope, not a steeper one. This was not predicted and
is not a good sign on its own terms — an unexplained result in the favourable direction deserves more
suspicion than one in the unfavourable direction.

The most likely candidate is a measurement artefact rather than a property of the score: at n = 200
the per-run FAR is quantised to 0.5 % steps and bounded below at zero, which inflates its standard
deviation at the short windows and steepens the fitted slope. That is a hypothesis, not a finding.
**It should be checked before the slope is quoted anywhere**, because the PASS verdict does not
depend on it — the runs-in-band count is the frozen criterion and it is unambiguous.

## 3 · P3 — variance solved, bias exposed

P3's variance collapses just as hard (slope −0.918, SD 0.189 → 0.0152) and it still fails. The reason
is now visible and is **not** the reason it failed before:

**P3's median run FAR at n = 3200 is 1.16 %**, against a band floor of 2.5 %. Its per-run rate has
converged tightly — to the wrong value. **This is threshold bias, not instability.** More data simply
makes a mis-set threshold more precisely wrong.

The cause is straightforward: P3's v3 threshold was calibrated on ticks 200–399 of 400-tick runs. Over
3,400 ticks the score distribution is not identical, so that quantile sits slightly too high.

**This is a diagnosis, not a fix, and the fix is a new experiment.** Recalibrating P3 on the matched
long window is E18-R4. Doing it inside R3 would change two variables and destroy the result.

## 4 · Overdispersion persists

| policy | n=200 | n=400 | n=800 | n=1600 | n=3200 |
|---|:--:|:--:|:--:|:--:|:--:|
| P1 | 4.2× | 4.3× | 4.0× | 3.2× | **2.1×** |
| P3 | 9.2× | 9.8× | 9.3× | 8.1× | **6.7×** |

**Ticks are still not independent at n = 3200.** P1 gets into band despite 2.1× overdispersion
because the absolute SD (0.0086) is now small relative to the band width (0.075), not because the
correlation went away. That distinction matters: the monitor works by having enough data to overwhelm
the correlation, not by the correlation being absent.

## 5 · Confounder check — clean

The pre-registration required R3 to be reported INCONCLUSIVE if the long runs developed drift.

| policy | 1st half | 2nd half | drift | drift/SD | limit |
|---|--:|--:|--:|--:|:--:|
| P1 | 3.6883 | 3.6888 | +0.0005 | **0.05** | ≤ 1.0 ✓ |
| P3 | 3.3830 | 3.3827 | −0.0003 | **0.08** | ≤ 1.0 ✓ |

Neither policy drifts at 3,400 ticks. **R3 isolated its variable.** (P2, which does drift, was
excluded by design and remains untouched.)

## 6 · Is the window operationally realistic?

**Yes.** At the configured 20 Hz control rate:

| window | real time |
|---|---|
| 200 ticks | 10 s |
| 1600 ticks | 80 s |
| **3200 ticks** | **160 s — 2.7 minutes** |

The pre-registration warned that a window no real drive reaches would be "a negative result wearing a
positive result's clothes." **A monitor that needs under three minutes of driving to establish a
stable false-alarm rate is an ordinary engineering requirement, not a disqualifying one.**

## 7 · Decision

# PASS-R3 — precision-limited

**P1 now has a valid operational monitor:** 30/30 runs inside the target false-alarm band, at a
frozen threshold, on held-out clean seeds, at a realistic window length, with no drift confound.

This is the first unambiguous PASS in the E18 series, and it reverses the working assumption that
came out of R2. **The score was not unfit for purpose. It was being asked to decide on 10 seconds of
data.**

## 8 · What this does and does not license

**Licensed now:**

- *"OD-8 provides operationally stable clean-data behaviour on P1 at a 160-second evaluation window."*
- E19 / H7 is **unblocked for P1**.

**Not licensed:**

- Nothing about **detection**. R3 is a clean-data experiment; it measures false alarms only. Whether
  the longer window also detects faults is the immediate follow-up and is not assumed.
- Nothing about **P3 or P2**.
- The slope anomaly in §2 is unexplained and must not be quoted as a finding.

## 9 · Next, in order

1. **E18-R3b — detection at the long window.** Re-run the faulted evaluation at n = 3200 against the
   frozen threshold. A monitor with perfect false-alarm control and no detection is still useless,
   and E18 measured `speed_stuck` and `imu_dropout` as undetectable at any severity. **This is the
   experiment that decides whether the PASS is worth anything.**
2. **Phase 2 — monitorability.** Still nearly free, still able to delete a large part of the ASTRA
   2.0 proposal.
3. **E18-R4 — recalibrate P3** on the matched long window. Optional; only if two policies are wanted
   for E19.
4. **E19 / H7** — now genuinely reachable on P1.
