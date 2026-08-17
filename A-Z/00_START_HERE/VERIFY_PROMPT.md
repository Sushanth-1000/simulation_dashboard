# The re-verification prompt

Paste the block below into a fresh session to re-verify this folder from scratch.
It is self-contained: environment quirks, the exact commands, the expected values,
and the traps that have already cost time.

**Re-run it whenever** the code changes, an ADR lands, or more than a week has
passed. Two ADRs once moved a headline safety number with nothing announcing it,
which is the whole reason this file exists.

**It proposes; it does not edit.** The verifying session writes its findings to a
new `CORRECTIONS.md` and changes nothing else. That separation is deliberate — a
session that measures *and* rewrites can quietly talk itself into agreeing with
the document, and there is then no artefact showing what disagreed. Applying the
corrections is a second, reviewed step.

**Related:** [`REPRODUCE.md`](REPRODUCE.md) is the same command list organised by
*result* rather than by run order — use it when you want one number, not the whole
sweep.

---

```
Re-verify the A-Z folder in this repository by RUNNING the code, not by reading
the documents the claims came from.

YOUR OUTPUT IS A FILE, NOT AN EDIT
Write A-Z/00_START_HERE/CORRECTIONS.md and change nothing else. Do NOT edit any
A-Z section, any file under docs/, or this prompt. Propose; do not apply.

If you find a defect in the CODE (a benchmark that refuses wrongly, a guard that
has gone stale, a crash), say so in CORRECTIONS.md under "Code defects" and still
do not fix it in this session. A measurement pass that also changes the thing
being measured cannot be audited.

THE RULE
Every quantitative claim in A-Z/ must trace to a command you ran in this session.
Never quote a figure from EVIDENCE.md, CREDIBILITY_MATRIX.md or any A-Z section as
verification of itself — those are what you are checking. If a number cannot be
reproduced, say so plainly and classify it (see the format below) rather than
softening it.

A zero is not automatically good news. A zero veto rate, a silent gate and a
benchmark that prints nothing all look like health.

ENVIRONMENT — getting this wrong wastes a lot of time
- The gate and every benchmark run ONLY in WSL2 Ubuntu. Windows Python lacks the
  dependencies.
- Use `wsl -d Ubuntu` explicitly. The default distro is docker-desktop and has no
  bash. The default user is already `astra`; do NOT pass `-u astra`, that user is
  not found.
- The WSL checkout is ~/astra. Edit on Windows, then sync:
    wsl -d Ubuntu -- bash -lc "cd ~/astra && rsync -a --delete --exclude 'var/' --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' --exclude '.mypy_cache/' --exclude '.pytest_cache/' --exclude '.ruff_cache/' --exclude 'A-Z/' /mnt/c/Users/Dell/Documents/ASTRA/ ~/astra/"
- Exclude var/ from the sync. It holds the twin, corpus and policy, is gitignored,
  and a fresh clone has none of them.
- Write benchmark output under $HOME, not /tmp. WSL restarts wipe /tmp mid-session.
- Invoke benchmarks as `uv run python -m benchmarks.<name>`, never by path —
  `training` is deliberately not installed.
- Run WSL commands through PowerShell with double quotes. Single quotes via a
  bash-style tool get mangled.

STEP 0 — BEFORE ANYTHING ELSE
  make artifacts-check
Must print "twin, corpus and policy present; the vehicle drives". Presence is not
the check; DRIVING is. Run `make artifacts` if it refuses — order is load-bearing,
the corpus is generated through the twin and the policy is trained against both.

RUN ALL OF THIS
  make check                       # tests, xfails, mypy, contracts, coverage
  python -m benchmarks.gate_census
  python -m benchmarks.exchangeability
  python -m benchmarks.degradation
  python -m benchmarks.fault_study
  python -m benchmarks.ablation
  python -m benchmarks.comparison
  python -m benchmarks.arms                     # single channel vs three
  python -m benchmarks.redundancy               # the shadow monitor, a different thing
  python -m benchmarks.effectiveness
  python -m benchmarks.platform_transfer
  python -m benchmarks.commissioning
  python -m benchmarks.whiteness
  python -m benchmarks.whiteness --sweep
  python benchmarks/latency.py                  # four-layer subset
  python -m benchmarks.tick_latency             # full assembled tick, five runs
  python -m benchmarks.soak -n 100000 -o var/soak/verify
  python -m benchmarks.flake_hunt --repeats 6 --focus-repeats 15
  pytest tests/integration/test_closed_loop_faults.py -v
  pytest tests/unit/test_l8_failsafe.py -k recovery_is_bounded

  `envelope` needs a log argument and refuses every log in var/ (all are audit
  schema v1; it needs v7+). To exercise it, drive a fresh log and call its main in
  the SAME process — the loop writes to a temp dir cleaned on exit.

  `detectors` has no main. It is a library; its output is the shadow-detector
  table inside fault_study.

THE ONE THING NO BENCHMARK PRINTS
The lateral_noise mechanism. To re-derive it, drive the lateral_noise scenario
from benchmarks.fault_study.SCENARIOS with an observer and read, per tick,
`record.issued.origin` and both command vectors. Expected: RATE_LIMITED on ~122
of 200 post-fault ticks, and the rate limiter substituting throttle 0 / brake 1.0
while the steering axis barely moves.

TRAPS THAT HAVE ALREADY BITTEN — check each
- Field names. TickSample has NO estimated/true lateral fields, and
  ProposedCommand has no `proposed_command` — it is `.command`. The estimate is
  `record.fast_state.mean[1]` (position_y) and it is OPTIONAL, so handle None.
  Two probes silently returned nan before this was noticed. If anything returns
  nan or an empty result, STOP and introspect the object; do not report around it.
- EVIDENCE.md's E-152 and E-153 still cite `benchmarks.redundancy`, which does
  NOT produce their figures — it prints the shadow residual monitor.
  `benchmarks.arms` is the command that does. If those rows still cite the wrong
  one, that is a finding.
- Historical vs current. Figures from before 15 August 2026 were superseded by
  ADR-0032 (sigma-point redraw) and ADR-0033 (redundancy on the driven path), and
  ADR-0030's health-level ceiling changed the dropout escalation. Keep them as
  dated history; do not present them as current behaviour.
- Guards go stale like numbers. Check every refusal a benchmark raises for whether
  it is refusing the right thing. One guard spent a day blocking its own benchmark
  because a later ADR made a correct safety stop look like a dead loop.
- One run is not a tail statistic. tick_latency defaults to five runs for that
  reason; do not quote a max from a single run.

EXPECTED VALUES AS OF 16 AUGUST 2026 — a mismatch is a finding, not an error
  gate                3,065 passed + 3 xfailed; mypy over 169 files; 12 contracts,
                      0 broken; coverage 97.47%; per-file floor green
  gate census         STATISTICAL 2800/0/0 · PHYSICAL 2651/149/0, all
                      LATERAL_JERK_EXCEEDS_LIMIT · DETERMINISTIC 2800/0/0
  exchangeability     URBAN_CLEAR live 3.3648-3.4083 vs corpus 3.8758-5.4312,
                      0.0% inside; DEGRADED_SENSOR n=1, too few to judge
  fault study         control 0.017 m · imu_dropout 0.062 m (final speed 0.0000,
                      DEGRADED +5, LIMP +15, HALT never, peak phi 40) ·
                      position_bias and position_drift both 0.017 m ·
                      speed_stuck 0.024 m · speed_bias 0.059 m ·
                      lateral_noise 1.307 m with 126 vetoes
  ablation            L6 off and L7a off identical to governed in every cell;
                      L7b off zeroes every veto and takes lateral_noise
                      1.307 m -> 0.138 m
  comparison          ASTRA better on every fault except lateral_noise, where
                      ungoverned Core-A is 0.148 m against ASTRA's 1.307 m
  arms                single/clean 0.1034 · single/1 m bias 0.8387 ·
                      redundant/clean 0.0168 · redundant/1 m bias 0.0168;
                      peak estimator error 1.1805 -> 0.1323; verdict says
                      INDISTINGUISHABLE
  redundancy          faulted channel leaves every clean band at +41 (IMU) and
                      +28 (GPS) ticks
  whiteness           position_drift does NOT alarm and matches the control to
                      every printed digit; imu_dropout reports 41 live ticks
  effectiveness       from estimate 117.929 (true 112) and 164.443 (true 168);
                      from sensor 114.986 and 167.702. E-63's "140.000 on every
                      platform" does NOT reproduce
  degradation         5 modalities, all critical, all HALT at phi 40, no INERT row
  platform transfer   no platform HALTs; sharp_steer ends 53.756 m off at LIMP
  commissioning       only urban_clear CERTIFIED; four contexts BOUNDED
  latency subset      four-layer hot path p99 0.442 ms
  tick_latency        p50 ~2.2 ms stable across runs; p99 2.768-10.460 ms;
                      max 4.2-61.1 ms; 0-31 ticks per 2,000 over the 10 ms budget
  soak 100k           all ten criteria pass, STABLE, resident +0.1 MiB,
                      p99 8.599 -> 7.757 ms, PROPOSED on 99,958 ticks
  flake_hunt          6/6 full-suite and 15/15 threaded passes under stress-ng
                      with 32 workers; NO FLAKE OBSERVED. Full suite median
                      238.8 s under load against ~91 s clean
  recovery bound      91 ticks = 4.6 s, asserted by a passing test
  structural          ProposalWriter has send + a pending property, no read
                      method · Verdict.merge strips abstentions first, so
                      all-abstain => VETO as well as empty => VETO ·
                      AUDIT_SCHEMA_VERSION = 10 · 3 strict xfails, all NFR5 walls
  counts              34 ADRs · 10 SIs · 10 assumptions · 30 credibility rows,
                      [M-ext] 0 of 30 · 21 register rows (16 closed, 1
                      reclassified, 1 partly closed, 3 open)

WHAT CANNOT BE VERIFIED — say so rather than implying coverage
- Historical figures whose defect is closed and cannot be reproduced: OD-1's
  2,883 m, OD-5's 1,508, OD-6's 99,808/100,000, OD-4's 2.9e6 m, FB2's 40%,
  FB3's 5.02%. Trace these to CREDIBILITY_MATRIX.md and label them history.
- Every [INTERPRETATION] in the folder. Those are arguments; running code says
  nothing about whether they are right. Do not list them as verified OR as
  unverified findings — they are a different kind of claim.

WRITE A-Z/00_START_HERE/CORRECTIONS.md IN THIS FORMAT

  # Corrections proposed — <date>
  Session ran <N> of the commands above. Gate: <result>.

  ## Summary
  <one paragraph: how many claims checked, how many reproduced, how many did
  not, and the single most consequential finding>

  ## Corrections
  ### C1 · <short title> — <STALE | WRONG | UNREPRODUCIBLE | OVERSTATED>
  - **File** A-Z/NN_SECTION/README.md:LINE
  - **Says** <quote the exact text>
  - **Measured** <the figure> via `<the exact command>`
  - **Class** STALE (superseded by a dated change) / WRONG (never true) /
    UNREPRODUCIBLE (no command produces it) / OVERSTATED (true but claims more
    than the measurement supports)
  - **Proposed text** <the replacement, written in the folder's voice, keeping
    the old figure as dated history where it was once true>

  ## Code defects
  <anything wrong with the code rather than the documents. Do not fix them here.>

  ## Reproduced exactly
  <a list, so the pass is auditable in both directions. A corrections file that
  only lists failures cannot be distinguished from a shallow pass.>

  ## Not verified this pass
  <what you did not run and why, including anything that timed out>

  ## Expected-values table
  <the full table above, updated to what you measured, ready to paste into
  VERIFY_PROMPT.md when these corrections are applied>

RULES FOR THAT FILE
- Quote the document text exactly. A correction a reader cannot locate is a
  claim, not a correction.
- Give the command for every measured figure. No command, no correction.
- Keep an old figure as dated history when it was true on its date. Most
  discrepancies here are staleness, not error, and deleting the old number
  destroys the audit trail.
- Rank the corrections by how much they should change a reader's view, not by
  the order you found them.
- If nothing needs correcting, still write the file with an empty Corrections
  section and a full "Reproduced exactly" list. A pass that finds nothing is a
  result and must leave the same evidence as one that finds something.
- Do not claim 100%. State the fraction you actually verified.
```
