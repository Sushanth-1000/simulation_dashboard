# E18-R1 - Limitations

## Statistical

- **`n_r` is about 200 autocorrelated ticks.** The finite-sample conformal guarantee assumes
  exchangeable draws; ticks within a run are not. The effective sample size is well below 200, which
  is the direct cause of the threshold variance that sank R1.
- **The 191st of 200 order statistics is close to the sample maximum.** At `eps = 0.05` with
  `n = 200`, the estimator is inherently conservative. A larger `eps` or a smaller window would each
  change this, and **neither was tried**, because trying them would be the window search section 6 of
  the brief forbids.
- **n = 30 runs per policy.** Run-level counts have wide binomial uncertainty; 9/30 has a Wilson 95 %
  interval of roughly [16 %, 47 %], comfortably below the 80 % the PASS criterion implies, so the
  decision is not close - but the estimate itself is not precise.

## Scope

- **Two policies.** P1 and P3 only; P2 excluded by design.
- **One plant model, simulation only.** `[M-syn]`; `[M-ext]` remains **0 of 30**.
- **Clean runs only.** No detection claim is made or implied by R1.
- **One window definition.** By design. R1 tests one pre-registered procedure, not the space of
  windowed procedures. A different window might succeed; that would be E18-R2 or later, not a
  reinterpretation of R1.

## Interpretive

- **The startup-tail asymmetry is unexplained.** FAR is 10-14 % over ticks 0-199 and 0.8-2.7 % over
  ticks 200-399 while mean scores barely differ, so the difference lies in the upper tail. The
  mechanism is not established, and it is directly relevant to whether E18-R2 will work.
- **"In band" is a threshold on a continuous quantity.** A run at 2.4 % and a run at 2.6 % are
  counted differently while being materially identical. The criterion was frozen in advance and is
  applied as written, but the counts should not be read as more precise than they are.
- **R1 cannot distinguish "windowing is the wrong idea" from "this window is too short".** It tests
  one instantiation. The failure is attributed to estimation variance because the threshold SD is
  measured and is comparable to the headroom - but that is an inference, not a controlled comparison.
