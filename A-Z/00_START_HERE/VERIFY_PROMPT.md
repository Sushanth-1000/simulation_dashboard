# The re-verification prompt

Paste the block below into a fresh session to re-verify this folder from scratch.
It is written to be self-contained: it carries the environment quirks, the exact
commands, the expected values, and the traps that have already cost time.

**Re-run it whenever** the code changes, an ADR lands, or more than a week has
passed. Two ADRs once moved a headline safety number with nothing announcing it,
which is the whole reason this file exists.

---

```
Re-verify the A-Z folder in this repository by RUNNING the code, not by reading
the documents the claims came from. Correct anything that does not reproduce.

THE RULE
Every quantitative claim in A-Z/ must trace to a command you ran in this session.
If a number cannot be reproduced, say so explicitly and either mark it historical
with its date or withdraw it. Never quote a figure from EVIDENCE.md,
CREDIBILITY_MATRIX.md or any A-Z section as verification of itself — those are
what you are checking. Record corrections visibly in the document rather than
silently overwriting, in the house style: state what was written, what was
measured, and where the fix landed.

ENVIRONMENT — this matters, and getting it wrong wastes a lot of time
- The quality gate and every benchmark run ONLY in WSL2 Ubuntu. Windows Python
  lacks the dependencies.
- Use `wsl -d Ubuntu` explicitly. The default distro is docker-desktop and has
  no bash. The default user is already `astra`; do not pass `-u astra`, that
  user is not found.
- The WSL checkout is ~/astra. Edit on Windows, then sync:
    wsl -d Ubuntu -- bash -lc "cd ~/astra && rsync -a --delete --exclude 'var/' --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' --exclude '.mypy_cache/' --exclude '.pytest_cache/' --exclude '.ruff_cache/' --exclude 'A-Z/' /mnt/c/Users/Dell/Documents/ASTRA/ ~/astra/"
- Exclude var/ from the sync. It holds the twin, corpus and policy, is gitignored,
  and a fresh clone has none of them — check `make artifacts-check` first and run
  `make artifacts` if it refuses.
- Write benchmark output under $HOME, not /tmp. WSL restarts wipe /tmp mid-session.
- Invoke benchmarks as `uv run python -m benchmarks.<name>`, never by path —
  `training` is deliberately not installed.
- Quote carefully: run WSL commands through PowerShell with double quotes. Single
  quotes via the Bash tool get mangled.

RUN ALL OF THIS
  make check                              # gate: tests, xfails, mypy, contracts, coverage
  make artifacts-check                    # must say the vehicle DRIVES, not merely that files exist
  python -m benchmarks.gate_census
  python -m benchmarks.exchangeability
  python -m benchmarks.degradation
  python -m benchmarks.fault_study
  python -m benchmarks.ablation
  python -m benchmarks.comparison
  python -m benchmarks.effectiveness
  python -m benchmarks.platform_transfer
  python -m benchmarks.commissioning
  python -m benchmarks.whiteness
  python -m benchmarks.redundancy
  python benchmarks/latency.py
  python -m benchmarks.soak -n 100000 -o var/soak/verify
  python -m benchmarks.flake_hunt --repeats 6 --focus-repeats 15
  pytest tests/integration/test_closed_loop_faults.py -v
  pytest tests/unit/test_l8_failsafe.py -k recovery_is_bounded

  `envelope` needs a log argument and refuses every log in var/ (all are audit
  schema v1; it needs v7+). To exercise it, drive a fresh log and call its main
  in the SAME process — the loop writes to a temp dir that is cleaned on exit.

  `detectors` has no main. It is a library; its output is the shadow-detector
  table inside fault_study.

WRITE YOUR OWN PROBES FOR THESE — no benchmark produces them
- Full-tick latency: TickSample carries `pipeline_duration_ns`. benchmarks/latency.py
  times only the L1+L2+L7a+L8 subset. Run the full-tick measurement at least FIVE
  times; the tail is unstable and one run is not a result.
- Single-channel vs redundant: drive_closed_loop(..., single_channel=True/False).
- Peak estimator error: the estimate is record.fast_state.mean[1] (position_y in
  FAST_STATE_FIELDS). TickSample.lane_deviation_m is the signed truth.

TRAPS THAT HAVE ALREADY BITTEN — check for each
- Field names. TickSample has NO estimated/true lateral fields, and
  ProposedCommand has no `proposed_command` — it is `.command`. Two probes
  silently returned nan before this was noticed. If a probe returns nan or an
  empty result, STOP and introspect the object; do not report around it.
- E-152 cites `python -m benchmarks.redundancy` for figures that script does not
  produce. It prints the shadow residual table. The figures come from
  drive_closed_loop with single_channel toggled.
- Historical vs current. Figures from before 15 August 2026 were superseded by
  ADR-0032 (sigma-point redraw) and ADR-0033 (redundancy on the driven path).
  Keep them as dated history; do not present them as current behaviour.
- Guards go stale like numbers. Every refusal a benchmark raises should be
  checked for whether it is refusing the right thing. One guard spent a day
  blocking its own benchmark because a later ADR made a correct safety stop look
  like a dead loop.
- A zero is not automatically good news. A zero veto rate, a silent gate and a
  benchmark that prints nothing all look like health.

EXPECTED VALUES AS OF 16 AUGUST 2026 — a mismatch is a finding, not an error
  gate                3,047 passed + 3 xfailed; mypy over 167 files; 12 contracts,
                      0 broken; coverage 97.47%; per-file floor green
  gate census         STATISTICAL 2800/0/0 · PHYSICAL 2651/149/0, all
                      LATERAL_JERK_EXCEEDS_LIMIT · DETERMINISTIC 2800/0/0
  exchangeability     URBAN_CLEAR live 3.3648-3.4083 vs corpus 3.8758-5.4312,
                      0.0% inside; DEGRADED_SENSOR n=1, too few to judge
  fault study         control 0.017 m · imu_dropout 0.062 m (final speed 0.0000,
                      DEGRADED +5, LIMP +15, HALT never, peak phi 40) ·
                      position_bias and position_drift both 0.017 m ·
                      lateral_noise 1.307 m with 126 vetoes
  ablation            L6 off and L7a off identical to governed in every cell;
                      L7b off zeroes every veto and takes lateral_noise
                      1.307 m -> 0.138 m
  comparison          ASTRA better on every fault except lateral_noise, where
                      ungoverned Core-A is 0.148 m against ASTRA's 1.307 m
  redundancy figures  single/clean 0.1034 · single/1 m bias 0.8387 ·
                      redundant/clean 0.0168 · redundant/1 m bias 0.0168
  peak est error      1.1805 m single-channel vs 0.1323 m redundant
  whiteness           position_drift does NOT alarm; it matches the control to
                      every printed digit; imu_dropout reports 41 live ticks
  degradation         5 modalities, all critical, all HALT at phi 40
  platform transfer   no platform HALTs; sharp_steer ends 53.756 m off at LIMP
  commissioning       only urban_clear CERTIFIED; four contexts BOUNDED
  latency             full tick p50 ~2.2 ms stable; p99 2.768-10.460 ms across
                      runs; max 7.7-47.0 ms; 0-31 ticks per 2,000 over the 10 ms
                      budget
  soak 100k           all ten criteria pass, STABLE, resident +0.1 MiB,
                      p99 8.599 -> 7.757 ms
  recovery bound      91 ticks = 4.6 s, asserted by a passing test
  counts              34 ADRs · 10 SIs · 10 assumptions · 30 credibility rows,
                      [M-ext] 0 of 30 · 21 register rows (16 closed, 1
                      reclassified, 1 partly closed, 3 open) · audit schema 10

WHAT CANNOT BE VERIFIED — say so rather than implying coverage
- Historical figures whose defect is closed and cannot be reproduced: OD-1's
  2,883 m, OD-5's 1,508, OD-6's 99,808/100,000, OD-4's 2.9e6 m, FB2's 40%,
  FB3's 5.02%. Trace these to CREDIBILITY_MATRIX.md and label them history.
- Every [INTERPRETATION] in the folder. Those are arguments; running code says
  nothing about whether they are right.

FINISH BY
1. Updating the verification record in A-Z/00_START_HERE/README.md: what you ran,
   what reproduced, what did not, and where each correction landed.
2. Updating this file's expected-values table to what you measured.
3. Reporting honestly what fraction of the folder you actually verified. Do not
   claim 100%.
```
