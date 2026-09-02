# Decision Log

Every meaningful decision gets an entry. The research direction is never silently modified.

---

```
DATE:          1 September 2026
EXPERIMENT:    Phase 5 opening
OBSERVATION:   E17 closed with heterogeneous observability and one well-posed absorption case.
               L6 was miscalibrated in both directions - unreachable on P1/P3, always tripped on P2.
DECISION:      Open Phase 5 with OD-8 calibration (E18) as the gate, not H7.
RATIONALE:     H7 asks whether a predicted monitor location gives better operational detection.
               That is unmeasurable while the monitor cannot fire. Calibration is upstream of the
               question H7 asks.
ALTERNATIVES   (a) Run H7 first using D_s as a proxy for detection - rejected: D_s is scale-free and
REJECTED:          cannot stand in for an operational outcome. That exact error was already made
                   once in this project and produced a withdrawn claim.
               (b) Proceed to comma2k19 - rejected: externally validating a phenomenon whose
                   operational consequence is untestable would be premature.
IMPACT ON      No claim changes. H7 status moves from "next" to "gated on E18".
CLAIMS:
NEXT ACTION:   Pre-register E18, then locate the exchangeability violation empirically.
```

---

```
DATE:          1 September 2026
EXPERIMENT:    E18 (diagnostic, before pre-registration was finalised)
OBSERVATION:   All three policies classify 199/200 ticks as URBAN_CLEAR. That context's legacy
               corpus spans 3.8776-5.4380; live scores span 2.56-4.46. Corpus context scales differ
               by two orders: HIGHWAY_CLEAR median 0.0888, URBAN_CLEAR 5.3199, DEGRADED_SENSOR
               0.1043.
DECISION:      Treat OD-8 as a calibration-set provenance problem, not a threshold-value problem.
               Recalibrate from clean runs generated under the same conditions as live operation.
RATIONALE:     Conformal validity requires exchangeability between calibration and test data.
               Changing the threshold value alone would paper over a distributional mismatch and
               would not be defensible as conformal prediction.
ALTERNATIVES   (a) Lower the quantile until the gate fires - rejected: that is tuning to a desired
REJECTED:          detection outcome and destroys the false-alarm guarantee.
               (b) Reclassify contexts so live maps to HIGHWAY_CLEAR - rejected: changes L3
                   behaviour to fix an L6 problem, and was not pre-registered.
IMPACT ON      None yet. "OD-8 currently calibrated" remains Not established.
CLAIMS:
NEXT ACTION:   Collect clean calibration scores on held-out seeds; freeze; then evaluate faults.
```

---

```
DATE:          1 September 2026
EXPERIMENT:    E18 Part 1
OBSERVATION:   Global calibration (q = 5.6449) gives 0.00 % clean false alarms on P1 and P3 and
               11.06 % on P2 - the original OD-8 pattern, reproduced. Policy-conditional
               calibration puts all three inside the pre-registered [2.5 %, 10 %] band
               (5.47 / 4.68 / 8.23 %) and exchangeability AUC falls to 0.515-0.537.
               P2's score drifts within a run: 4.1902 -> 5.3711, drift/SD = 1.28.
DECISION:      Select POLICY-CONDITIONAL per the pre-registered rule. Freeze thresholds at
               P1 3.7095, P2 5.9024, P3 3.4000. Record E18 Part 1 as PARTIAL.
RATIONALE:     The selection rule in protocol.md section F was written before any value was
               computed: prefer global unless its clean false-alarm rate leaves the band for at
               least one policy. It left the band for all three.
ALTERNATIVES   (a) Declare PASS and ignore the drift - rejected: C3 was pre-registered as a fail
REJECTED:          criterion and P2 fails it. Ignoring a criterion after seeing which policy trips
                   it is the failure mode this project has already been burned by.
               (b) Re-pre-register a drift criterion P2 would pass - rejected outright.
               (c) Drop P2 from the project - rejected: its non-stationarity is a finding, and
                   removing an inconvenient policy is not available.
IMPACT ON      "OD-8 currently calibrated" -> Established for P1 and P3; Not established for P2.
CLAIMS:        "L6 calibration and live scores are not exchangeable" -> Established (legacy corpus).
NEXT ACTION:   Evaluate all six faults at three severity levels against the frozen thresholds.
```

---

```
DATE:          1 September 2026
EXPERIMENT:    E18 Part 2 (design)
OBSERVATION:   Two of the six faults - speed_stuck (STUCK_AT) and imu_dropout (DROPOUT) - have no
               magnitude parameter. Their mechanism does not admit a severity scale.
DECISION:      Sweep three severity levels for the four parameterisable faults; run the other two at
               a single level and label them as such.
RATIONALE:     Inventing a severity axis for a fault that has none would be fabrication. Sweeping
               dropout *duration* would change the fault definition, which the research freeze
               forbids.
ALTERNATIVES   (a) Sweep dropout duration anyway - rejected: changes a fault definition.
REJECTED:      (b) Report all six as if three-level - rejected: false.
IMPACT ON      Severity results will cover four of six faults. Stated explicitly, not smoothed over.
CLAIMS:
NEXT ACTION:   Complete the sweep, then write final_decision.md with the E19 gate.
```

---

```
DATE:          1 September 2026
EXPERIMENT:    E18 finalisation
OBSERVATION:   Changing the unit of analysis from tick to run overturned the earlier reading.
               Pooled false-alarm rates (P1 5.47 %, P3 8.16 %, P2 4.67 %) all looked acceptable.
               Per run: P1 21/30 in band, P3 4/30, P2 0/30. P3 is bimodal - median 1.00 %, upper
               quartile 12.56 %. P2 never alarms in the median run.
DECISION:      Record E18 as PARTIAL with P1 VALID, P3 CONDITIONAL, P2 INVALID. Narrow the E19 gate
               from two policies to one.
RATIONALE:     The run is the unit at which an operational monitor is experienced, and is the unit
               this project has insisted on elsewhere. A pooled rate averages across runs that
               never alarm and runs that alarm constantly - which is the same defect OD-8 had in
               the first place, one level up.
ALTERNATIVES   (a) Keep the pooled reading and call P1+P3 valid - rejected: it is the exact error
REJECTED:          section 10 of the brief warns against, and we had already made it once.
               (b) Re-pre-register a per-run criterion P3 would pass - rejected outright.
               (c) Drop P2 and P3 from the record - rejected: their failure modes are findings.
IMPACT ON      "OD-8 provides operational monitoring under specified policy constraints" -> allowed
CLAIMS:        for P1 only. "OD-8 is calibrated for P3" -> Not established.
NEXT ACTION:   Either enter E19 on P1 alone with the single-policy limitation pre-registered, or
               run E18-R1 (windowed calibration) first to try to recover P3.
```

---

```
DATE:          1 September 2026
EXPERIMENT:    E18, section 13 test
OBSERVATION:   D_L1 correlates NEGATIVELY with operational detection: Spearman rho = -0.480,
               p = 0.0088, n = 28 cells. D_L6 vs detection is not significant (+0.291, p = 0.137).
               17 of 28 cells disagree between D_L6 >= 0.9 and detection >= 0.9.
DECISION:      Record as an established methodological boundary. Do NOT change E19's planned
               predictor before testing it.
RATIONALE:     E19's pre-registered prediction is derived from D_s. E18 now predicts that this will
               fail, and possibly fail in the anti-correlated direction. Changing the predictor
               before running the test would be fitting the hypothesis to data we already hold.
               A falsified pre-registered prediction is a real result.
ALTERNATIVES   (a) Redesign H7 around a better predictor now - rejected: untested, and it would
REJECTED:          destroy the value of the pre-registration.
IMPACT ON      "D_s does not predict operational detection" -> Established.
CLAIMS:        "Higher D_L1 associates with lower detection" -> Supported, as an association.
NEXT ACTION:   Carry the warning into E19's protocol explicitly.
```

---

```
DATE:          1 September 2026
EXPERIMENT:    E18-R1
OBSERVATION:   Run-local calibration removed the targeted mechanism - corr(run baseline, run FAR)
               went from +0.909 to -0.469 on P3 - but P3 reached only 9/30 runs in band, below the
               frozen 12/30 floor. Per-run threshold SD (0.0135-0.0251) is comparable to the entire
               threshold headroom (0.0170-0.0235). The P1 positive control did not improve (3/30).
DECISION:      Record FAIL-P3. Do not run the faulted evaluation.
RATIONALE:     The criterion was frozen before the run. The faulted evaluation is scoped to showing
               a *recovered* monitor stays operational; P3 was not recovered, so detection numbers
               from an uncalibrated monitor would be exactly the category of result this project has
               already withdrawn twice. ~90 minutes of compute deliberately not spent.
ALTERNATIVES   (a) Try a shorter window - rejected: that is the window search section 6 forbids.
REJECTED:      (b) Raise eps until P3 passes - rejected: tuning to a desired outcome.
               (c) Report 9/30 as CONDITIONAL - rejected: the frozen floor is 12.
IMPACT ON      "Run-local calibration recovers P3" -> Rejected.
CLAIMS:        "P3 bimodality is a per-run baseline offset" -> Established.
NEXT ACTION:   E18-R2, matched-window pooled calibration.
```

---

```
DATE:          1 September 2026
EXPERIMENT:    E18-R1 audit of E18
OBSERVATION:   E18 computed clean false-alarm rate over ticks 0-399 but detection over ticks
               200-399. On the matched window, P1 - the policy E18 certified - has median run FAR
               0.00 % and 4/30 runs in band, not 4.88 % and 21/30. FAR by range: P1 10.17 % early
               vs 0.78 % late; P3 13.58 % vs 2.73 %; P2 0.93 % vs 8.42 %.
DECISION:      Withdraw E18's "P1 VALID" verdict. Block E19. Require E18-R2 before any monitor-
               placement work.
RATIONALE:     A false-alarm rate is comparable to a detection rate only if both describe the same
               operating condition. E18/protocol.md section J did not name a tick range, so nothing
               forced the two to agree. The operationally correct window is the one where detection
               decisions are made.
ALTERNATIVES   (a) Keep whole-run FAR and proceed - rejected: it certifies a monitor on a window it
REJECTED:          does not operate in.
               (b) Treat it as a documentation inconsistency - rejected: it changes a verdict.
IMPACT ON      "OD-8 provides operational monitoring (P1 only)" -> WITHDRAWN.
CLAIMS:        "E18 measured FAR and detection on different windows" -> Established.
NEXT ACTION:   E18-R2. Add a standing rule: a FAR and a detection rate quoted together must share a
               tick range, named in the pre-registration.
```

---

```
DATE:          1 September 2026
EXPERIMENT:    E18-R2
OBSERVATION:   Matched-window pooled calibration gave P1 13/30 runs in band - the best of three
               schemes (v1 4/30, v2 3/30) - but below the frozen 24/30 bar. P3 fell to 2/30.
               Diagnostic: an ideal independent monitor would give 29.2/30. Observed per-run FAR
               overdispersion is 4.2x (P1) and 9.2x (P3) versus binomial. P1's alarm indicator has
               lag-1 autocorrelation +0.359 (clustering, ~11 effective ticks of 200); P3's is ~0
               with variance between runs (~2 effective ticks).
DECISION:      Record PARTIAL-R2. Close the E18 calibration series. Do not attempt a fourth
               calibration scheme. Do not proceed to E19.
RATIONALE:     Three schemes have now been tried. P1 and P3 fail for different, measured reasons,
               and each scheme that helps one aggravates the other. Both mechanisms are properties
               of the score process rather than of the threshold, so no further threshold or window
               choice can resolve them. Continuing to vary the calibration would be a search.
ALTERNATIVES   (a) Try a fourth window or a different eps - rejected: that is the search the brief
REJECTED:          forbids, and the diagnostic says it cannot work.
               (b) Report 13/30 as sufficient for a P1 pilot - rejected: 4.2x overdispersion means
                   a detection difference between monitor locations would not be attributable to
                   the location.
               (c) Lower the bar to 12/30 - rejected: the criterion was frozen.
IMPACT ON      "Matched-window calibration recovers P1" -> Rejected.
CLAIMS:        "OD-8 cannot deliver per-run-stable false alarms at eps=0.05 on 200-tick windows"
               -> Established. Mechanisms for P1 and P3 -> Established, and distinct.
NEXT ACTION:   Repair B - longer evaluation windows. A pure compute change, no new rule to
               pre-register, and it separates "not enough samples" from "wrong monitor" for both
               policies at once.
```

---

```
DATE:          3 September 2026
EXPERIMENT:    E18-R3
OBSERVATION:   Evaluation window was the binding variable. P1 runs in band: 12/30 at n=200 rising
               monotonically to 30/30 at n=3200. Scaling slope -0.739 (P1), -0.918 (P3); both
               steeper than the -0.5 independent-sampling floor. Drift/SD 0.05 and 0.08 - the
               confounder guard passed, so the design isolated its variable. n=3200 at 20 Hz is
               160 s of driving. P3 reached only 5/30, but its variance collapsed too: its median
               FAR converged to 1.16 %, below the 2.5 % floor - bias, not instability.
DECISION:      Record PASS-R3. Supersede the E18-R2 conclusion. Unblock E19 for P1 only, pending a
               detection check. Do not fix P3 inside R3.
RATIONALE:     The frozen criterion was P1 >= 24/30 at n=3200; the result is 30/30 and unambiguous.
               The R2 claim was not wrong, it was under-qualified: "cannot deliver per-run-stable
               false alarms" was true only on 200-tick windows, and that qualifier turned out to be
               load-bearing.
ALTERNATIVES   (a) Recalibrate P3 on the long window inside R3 - rejected: changes two variables
REJECTED:          and destroys the one-variable design. It is E18-R4.
               (b) Claim the monitor works - rejected: R3 measured clean data only. Detection is
                   untested and E18 found two faults undetectable at any severity.
               (c) Quote the steeper-than-binomial slope as a finding - rejected: unexplained, in
                   the favourable direction, and probably a quantisation artefact at short windows.
IMPACT ON      "OD-8 cannot deliver per-run-stable false alarms" -> SUPERSEDED.
CLAIMS:        "OD-8 is stable on P1 at a 160 s window" -> Established.
               "The P1 limitation was precision" -> Established.
               "P3's residual failure is threshold bias" -> Supported.
NEXT ACTION:   E18-R3b - faulted evaluation at n=3200 against the frozen threshold. A monitor with
               perfect false-alarm control and no detection is still useless.
```
