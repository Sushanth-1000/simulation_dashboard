# CARLA.md — the remote handover

**You are a fresh Claude session on a GPU machine. This file is everything you
need.** Nothing here assumes you have seen the conversation that produced it.

**Read this whole file before running anything.** It is ordered so that the two
decisions which cannot be un-made come before the work that depends on them.

---

## 0 · Orientation, in ninety seconds

**ASTRA** is a nine-layer runtime governance system that sits between an
untrusted AI controller and an actuator. It judges every proposed command before
it is issued, degrades in graduated steps instead of halting, and writes an
evidence record for every decision.

**Core-A** is the untrusted half — the proposer, and nothing else. **Core-B** is
everything that decides: estimation, uncertainty, three gates, arbitration,
fail-safe, actuation, the audit log.

**Why you are here.** One number governs this entire project:

> **Rows at `[M-ext]`: 0 of 30.**

Every measurement ASTRA has is `[M-syn]` — taken on a plant it also wrote. The
digital twin, the calibration corpus and the trained policy all descend from the
**same kinematic bicycle model**, so the generator and the judge agree by
construction. That is the largest single thing a reviewer can hold against the
work.

**CARLA is the only thing that can move a row from "this machinery runs" to
"this machinery is correct against something we did not author."** Three of the
four remaining open register rows wait on it.

**What CARLA is NOT for: making the numbers better.** Several will get worse.
Section 7 predicts which, in advance, on purpose. **A prediction that comes true
is a result; a prediction that is refuted is a better one.** Do not quietly drop
a prediction that turns out wrong.

### Where the code is

| | |
|---|---|
| **Repository** | `https://github.com/huddartanay/Major-Project.git` |
| **Branch you want** | `phase4-l5-twin-l7b-physical` |
| **Commit this file was written at** | `7ac73c3` |
| **Owner** | Sushanth C · `sushanthc.cs23@bmsce.ac.in` |

**`main` is 92 commits behind and is not what you want.** A default clone lands
on `main` and gives you a repository from before all nine layers were finished,
before redundancy landed, and before the entire A-Z knowledge base existed. It
will look plausible and nothing will match this file.

```bash
git clone https://github.com/huddartanay/Major-Project.git astra
cd astra
git checkout phase4-l5-twin-l7b-physical
git log --oneline -1        # expect 7ac73c3 or later
```

If the repository is private you will need a GitHub token or an SSH key on the
remote box — a browser-based remote session cannot complete an interactive
credential prompt, so set that up before the clone rather than during it.

**Push your CARLA work to a branch off `phase4-l5-twin-l7b-physical`**, not to
`main` and not directly onto the phase branch while someone may still be working
on it:

```bash
git checkout -b carla-adapter
```

### What is NOT settled, and will block you

Two decisions belong to the project owner, not to you, and one component does not
exist. **Raise all three before starting §5.**

| | State |
|---|---|
| **`RAIN_NIGHT`** (Gate A, §4.1) | **Undecided.** Blocks CALIBRATE generation |
| **`partition.json`** (Gate B, §4.2) | **Not written.** Blocks the first frame |
| **Phase 6, FGSM** (§5.6) | **Not built.** No implementation exists in this repository |

Everything else in this file you can act on.

### The documents that own the detail

| File | What it owns |
|---|---|
| `docs/CARLA_PLAN.md` | The full argument for every decision below. **Read it after this file** |
| `docs/DATA_SPLIT_PROTOCOL.md` | The train / calibrate / test discipline |
| `A-Z/00_START_HERE/REPRODUCE.md` | Every existing number, with the command that produces it |
| `A-Z/00_START_HERE/README.md` | Map of a 31-section knowledge base covering every component |

---

## 1 · The machine, and how not to lose four hours to it

You are on a remote box over a Chrome extension. That shapes several things.

### 1.1 · Find out what you actually have

```bash
nvidia-smi; nproc; free -g; df -h .; python3 --version
```

**Record the output in `docs/CARLA_ENVIRONMENT.md`.** Every timing number you
produce is host-dependent and meaningless without it — the existing figures were
taken on a 16-core laptop under WSL2 and are labelled as such.

**You do not need a huge GPU for this.** CARLA at 20 Hz with one vehicle and a
few sensors is not demanding. A large GPU means you can run **headless at higher
throughput**, not that you should raise the tick rate. **Keep 20 Hz** — the whole
evidence pack is at 20 Hz and a different rate makes nothing comparable.

### 1.2 · Run everything long inside tmux

A remote browser session **will** drop, and a dropped session mid-TEST-run is a
real problem, because TEST may only be run once.

```bash
tmux new -s carla        # Ctrl-b d to detach, tmux attach -t carla to return
```

**Every generation run, every soak, every TEST run goes in tmux.** Not optional.

### 1.3 · Run CARLA headless

```bash
./CarlaUE4.sh -RenderOffScreen -quality-level=Epic -carla-rpc-port=2000
```

`-RenderOffScreen` because there is no display. Keep `-quality-level=Epic` unless
GPU-bound — quality affects sensor realism, which is the point of being here.

**Do not use `-benchmark -fps=N`.** You want **synchronous mode** driven by
`world.tick()` from the ASTRA loop, so the simulator's clock and ASTRA's injected
clock are the same clock. See §5.2.

---

## 2 · Setup

### 2.1 · Repository

Cloned and checked out per §0. Then:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --all-groups --all-extras
```

Python **3.12** is the floor (ADR-0003). Prefix commands with `uv run`.

### 2.2 · CARLA itself

**Version 0.9.16.** Settled by ADR-0015 and it matters: 0.9.16 ships an official
**`cp312`** wheel. That is what dissolved the project's highest-rated risk — the
source documents mandated 0.9.14, whose client supported only CPython 2.7/3.7/3.8
against a 3.12 floor, so *as written the two requirements admitted no
interpreter*.

**Do not install a different version to make something work.** Silently dropping
to 0.9.14 would reintroduce a closed risk and would be invisible in every result.
If 0.9.16 will not install, stop and report it.

CARLA is **Linux-only** — no macOS build. That constraint is real and recorded.

**Getting it onto the box.** The packaged release is the one you want; building
from source costs hours and buys nothing here.

```bash
# 1. The simulator itself (~20 GB unpacked -- check `df -h .` first)
wget https://tiny.carla.org/carla-0-9-16-linux -O CARLA_0.9.16.tar.gz
mkdir -p ~/carla && tar -xzf CARLA_0.9.16.tar.gz -C ~/carla

# 2. The Python client, into the project's venv
uv pip install carla==0.9.16

# 3. Prove both halves work before writing any adapter code
~/carla/CarlaUE4.sh -RenderOffScreen -carla-rpc-port=2000 &
uv run python -c "import carla; c=carla.Client('localhost',2000); c.set_timeout(10.0); print(c.get_server_version(), c.get_client_version())"
```

**Server and client version must match.** A mismatch produces confusing
timeouts rather than a clear error, and it is the most common way to lose an
afternoon here. If `uv pip install carla==0.9.16` fails, the wheel also ships
inside the tarball under `PythonAPI/carla/dist/`.

Town04 is needed and ships with the standard release — no additional map
download.

### 2.3 · The artefacts — the first place people lose a day

**`var/` is gitignored.** A fresh clone has **no** twin, **no** calibration corpus
and **no** trained policy, and every existing measurement runs through all three.

```bash
uv run make artifacts-check
```

Must print `artefact check: twin, corpus and policy present; the vehicle drives`.

**Presence is not the check — DRIVING is.** If it refuses, run `make artifacts`.
**Order is load-bearing:** the corpus is generated *through* the twin and the
policy is trained against both, so running them out of order produces a
mismatched set that loads cleanly and measures nothing. The policy is the long
pole; budget time.

---

## 3 · Prove the port before you trust anything

**Do this before writing a line of adapter code.** You have moved the project to a
new machine and OS. If a baseline has shifted you need to know *now*, not after a
CARLA result disagrees with the record.

```bash
make check
python -m benchmarks.gate_census
python -m benchmarks.fault_study
python -m benchmarks.arms
python -m benchmarks.exchangeability
```

### Expected baseline — measured 17 August 2026

A mismatch is a **finding about the port**, not an error. Record it.

| | Expected |
|---|---|
| `make check` | 3,065 passed + 3 xfailed · `mypy --strict` over 169 files · 12 contracts, 0 broken · coverage 97.47% · **`quality gate: PASSED`** |
| `gate_census` | `STATISTICAL` 2800/0/0 · `PHYSICAL` 2651/**149**/0, all `LATERAL_JERK_EXCEEDS_LIMIT` · `DETERMINISTIC` 2800/0/0 |
| `fault_study` | control 0.017 m · `imu_dropout` 0.062 m (DEGRADED +5, LIMP +15, **HALT never**, peak φ 40) · `position_bias` and `position_drift` both 0.017 m · `speed_stuck` 0.024 m · `speed_bias` 0.059 m · `lateral_noise` 1.307 m with 126 vetoes |
| `arms` | single/clean 0.1034 · single/1 m bias 0.8387 · redundant/clean **0.0168** · redundant/1 m bias **0.0168** · peak estimator error 1.1805 → 0.1323 · verdict `INDISTINGUISHABLE` |
| `exchangeability` | `URBAN_CLEAR` live 3.3648–3.4083 vs corpus 3.8758–5.4312, **0.0% inside** |

The three `XFAIL`s are the NFR5 walls and are **supposed to fail**. If one flips
to `XPASS` the suite goes red on purpose — that is how a fix is forced to
announce itself.

**Timing will differ, and that is expected.** Re-measure rather than reuse:

```bash
python -m benchmarks.tick_latency     # full assembled tick, five runs
python benchmarks/latency.py          # four-layer subset
```

---

## 4 · Two decision gates — settle both before generating a single frame

### 4.1 · GATE A — `RAIN_NIGHT`. A blocker, not a nicety

**The problem.** L3's context classifier cannot decide `RAIN_NIGHT`. Precipitation
and ambient light are not in the fast state vector, and the classifier's own
docstring **refuses to guess** from a friction proxy it cannot see.

**Why it bites here.** The demo drive has a rain/night phase. Run it unfixed and
every wet-night tick classifies as `HIGHWAY_CLEAR`, gets compared against a dry
population, and produces degraded coverage that **looks like a gate failure and is
actually a classifier gap** — an inversion of exactly the kind this project's
register exists to catch, walked into deliberately.

**Two acceptable answers. Not both, and not neither.**

| Option | What it means |
|---|---|
| **A1 — fix the classifier's input** | Weather is a *settable simulator parameter*, so the adapter can publish it as a modality and it reaches the classifier honestly. **CARLA is what makes this option possible at all** |
| **A2 — drop the rain/night phase** | Record why in an ADR, and state that the context class is unusable rather than pretending it works |

**Write an ADR either way, then proceed.** A1 is genuinely cheaper here than
anywhere else, because the simulator already knows the weather. A2 is defensible
on the grounds that adding a rain input answers it for rain and not for the
general question of unobservable contexts. **Decide with whoever owns the project
and record the decision — do not defer it into the work.**

### 4.2 · GATE B — commit `var/carla/partition.json` before the first frame

**This is the single most important instruction in this file.**

`DATA_SPLIT_PROTOCOL.md` is written for a fixed corpus, where the risk is
*accidental overlap*. **CARLA is a generator, and that inverts the risk.** You
cannot accidentally reuse a segment, because you can always make more. What you
can do — easily, invisibly, and with the best intentions — is **generate TEST
again after seeing the result.** Nothing in the data catches it, nothing in the
code catches it, the numbers stay plausible, and the guarantee quietly stops being
true.

So: **commit the route manifest and the seed to git before the first frame is
rendered.** `var/carla/partition.json` is committed, **not gitignored**, unlike
every other artefact.

> ### The trap that will bite you here
>
> **`.gitignore` line 20 is `var/`, so `git add var/carla/partition.json` does
> nothing and says nothing.** It exits zero, prints nothing, and the file is not
> staged. You will believe you committed the partition and you will not have.
>
> That is Gate B failing silently, through the back door, which is precisely the
> shape this project's register exists to catch.
>
> **Fix it permanently, not with a flag.** Add a negation to `.gitignore` so the
> exception is visible to everyone rather than depending on someone remembering
> `-f`:
>
> ```gitignore
> var/
> !var/carla/
> !var/carla/partition.json
> ```
>
> Then verify it actually worked, rather than assuming:
>
> ```bash
> git check-ignore -v var/carla/partition.json   # must print nothing
> git add var/carla/partition.json && git status --short
> ```

```json
{
  "seed": 20260816,
  "town": "Town04",
  "train":     [{"route": "hw-loop-a", "weather": "ClearNoon",      "traffic_seed": 11}],
  "calibrate": [{"route": "hw-loop-b", "weather": "ClearSunset",    "traffic_seed": 21}],
  "test":      [{"route": "hw-loop-c", "weather": "WetCloudyNight", "traffic_seed": 31}]
}
```

**The partition unit is a `route × weather × traffic seed`.** Not ticks —
consecutive CARLA ticks are as autocorrelated as consecutive real ones. **And not
laps of the same route:** two laps of `hw-loop-a` in `ClearNoon` differ only by
traffic, so putting one in CALIBRATE and the other in TEST is a tick-level split
wearing a costume. **The road geometry itself must differ.** Town04 has enough
distinct highway and urban stretches for three disjoint route sets.

| set | routes | ≈ duration | purpose |
|---|--:|--:|---|
| **TRAIN** | 6 | ≈ 60 min | Fit the L5 twin on CARLA dynamics — suspension, tyre slip, drivetrain lag, none of which the bicycle model has |
| **CALIBRATE** | 4 | ≈ 40 min | The Mondrian corpus and the MMD reference. Sized by sufficiency, **not by a percentage** |
| **TEST** | 4 | ≈ 40 min | The seven-phase drive. **Touched once** |

**Generate more TRAIN freely** if the twin underfits — it costs nothing and
contaminates nothing. **Do not generate more TEST.**

---

## 5 · What to build

Four things, and only the first is large. Each has an acceptance check; do not
move on without it.

### 5.1 · The adapter — `src/astra/adapters/carla/`

`.importlinter` has forbidden the name `carla` anywhere in `astra` since Phase 1
and **that contract stays**. The adapter is the one place the name may appear.

It supplies ports that already exist:

| Port | What CARLA gives it |
|---|---|
| `SensorSource` | IMU, GNSS, and a lidar/camera-derived lateral position, per modality, with real timestamps |
| `MeasurementExtractor` | the three position channels ADR-0033 fuses by median |
| `IntegrityMonitor` | the same residual monitor, unchanged |
| `CommandProjector` | throttle / brake / steer, real steering effectiveness |
| `ActuationSpace` | the automotive space, which is genuinely correct here |

ADR-0034 makes this possible and names the four coordinated things an adapter
must bring: **space, projector, policy, and a matching
`twin.control_effectiveness` row.** CARLA needs all four plus a profile.

> **Acceptance:** `make contracts` still prints `12 kept, 0 broken`, and
> `src/astra/` is unchanged beyond what ADR-0034 already made injectable. **If the
> core has to change, NFR5 was weaker than believed — and that finding is worth
> more than the adapter.** Record it; do not quietly patch the core.

### 5.2 · The driver — `training/carla_loop.py`

`drive_closed_loop` **owns its plant**: it constructs `SyntheticDrivingEnv`, steps
it, and reads truth back. CARLA cannot be dropped into that — the simulator owns
the clock, the tick is `world.tick()`, and ground truth arrives as an actor
transform rather than a state vector.

So this is a **sibling, not a parameter.** It must reproduce three properties or
the evidence is not comparable to anything already recorded:

1. **The injected `Clock`** (ADR-0010), driven from CARLA's *simulation* time, not
   wall time.
2. **Faults at the sensor boundary, never inside the core** (ADR-0022) — the same
   `FaultInjector`, applied to CARLA payloads.
3. **The same audit sink**, so a CARLA run and a synthetic run produce records a
   single reader can compare.

> **Acceptance:** a CARLA run's `DecisionRecord` rows load in `astra explain`
> beside a synthetic run's, and `benchmarks.envelope` reads the log without
> refusing.

### 5.3 · The profile — `config/environments/carla.toml`

**Every A-4 threshold declared afresh.** They are operating points, and the
synthetic ones were tuned against a different plant. There are **no defaults** — a
missing threshold is a startup failure, and so is a typo (`extra="forbid"`).

`failsafe.capabilities` and `failsafe.integrity_ceiling` **carry over unchanged**:
they are statements about the vehicle, not about the simulator.

### 5.4 · The run guard — not optional, and built *before* the first evidence run

Three times on 15 August 2026 a number was assembled correctly from an observation
nobody had checked was adequate: a detector measured on a vehicle that never
moved, a file declared missing from a truncated listing, and `100% inside`
reported from **one** sample.

The guard must **refuse to report** from a drive where:

- the vehicle did not move,
- every tick was vetoed,
- **or the simulator dropped frames.**

That third has no synthetic equivalent. A dropped frame is a missing tick, and a
missing tick in a closed loop is not a gap in the data — **it is a different
experiment.**

> **Acceptance:** point it at a stationary run deliberately and confirm it
> refuses. **A guard nobody has seen fire is a guard nobody has tested.**

### 5.5 · TEST-once, made mechanical

In a fixed dataset, re-running TEST leaves a trace. **In a simulator it leaves
none**, which makes *"we only looked once"* an assertion a reviewer must simply
believe.

Stamp the TEST manifest's digest into the run record **and** into an append-only
`var/carla/test-runs.log`. **A second evidence run against the same digest must
refuse**, exactly as `artifacts-check` refuses a policy that does not drive.

It is not tamper-proof — anyone can delete the log — **and that is not the
point.** The point is that re-running TEST becomes a deliberate act someone has to
perform on purpose, rather than a thing that happens because a number looked
disappointing on a Friday.

---

## 5.6 · The seven-phase drive — what TEST actually is

**This is the deliverable.** Four sections of this file refer to it; here is what
it is. Source: `docs/ROADMAP.md` and `docs/WORK_PLAN.md` §7.5.

**Town04, one continuous run, ≈ 21 minutes, and the vehicle never stops:**

| # | Phase | What it is there to exercise |
|:--:|---|---|
| 1 | **Highway** | The certified baseline. Everything later is a difference from this |
| 2 | **Urban** | A second certified context, and the profile switch between them |
| 3 | **Rain / night** | `RAIN_NIGHT` — **and this is the phase Gate A is about** |
| 4 | **Tunnel** | No certified profile matches ⇒ **bounded safe exploration**, the architecture's distinguishing behaviour |
| 5 | **Sensor fault** | IMU corruption, injected at the sensor boundary |
| 6 | **Adversarial (FGSM)** | An attack on the proposer, not on the sensors |
| 7 | **Recovery** | The walk back to `NOMINAL`, bounded at 91 ticks = 4.6 s |

### Why phases 5 and 6 carry the whole independence claim

Straight from `WORK_PLAN.md` §7.5, and it is the most important sentence in this
file after Gate B:

> **The independence evidence lives here and nowhere else.** Phase 6 (FGSM) is
> designed so that **exactly one** gate fires; Phase 5 (IMU corruption) so that
> **two fire for different reasons**. Until those run, *"three structurally
> independent gates"* is architecture rather than evidence.

That is the direct link to **P3 and P4** in §7. Today two of three gates judge
every tick and never object, so this drive is the first thing that could support
the central claim — or refute it.

**Report what happens, not what was predicted.** If two gates fire under FGSM, or
none do, **that is the finding.**

### It is one continuous run, and that has a cost

A failure in phase 6 costs a **full re-run** to reproduce — and TEST may only be
run once. Two consequences:

- **Rehearse the whole drive on TRAIN routes first.** TRAIN is regenerable and
  contaminates nothing; use it to shake out the adapter, the sensor mounts and
  the phase transitions until the run completes end to end.
- **Then run TEST once**, in tmux, with the guard armed.

### Phase 6 is NOT BUILT — scope it before you start

**There is no FGSM implementation in this repository.** `grep -ri fgsm src/
training/ benchmarks/` returns nothing but incidental mentions. Evidence row
**N-12** records the position honestly: *"the paper's §5 validation drive — 21
minutes, seven phases, 47 evidence tuples — **never run**."*

So phase 6 needs building, and it needs a decision first:

| Option | What it means |
|---|---|
| **Build FGSM against the policy network** | A gradient attack on `LearnedPolicy`'s observation. Faithful to the paper, and the only version that tests what §7.5 claims |
| **Substitute a simpler perturbation** | Cheaper, and **it does not test the same thing** — say so explicitly rather than letting it read as FGSM |
| **Drop phase 6** | Acceptable **only** if recorded, and it costs the independence evidence above |

**Whichever you choose, the attack goes at the proposer, not the sensors.** Phase
5 already attacks the sensors; the point of phase 6 is that a *different* failure
mode should light a *different* gate. An FGSM that perturbs sensor readings tests
phase 5 twice and proves nothing about independence.

### The ablation study runs alongside it

`ROADMAP.md` scopes it with the drive and it is not in §5's build list because
the harness already exists: `python -m benchmarks.ablation`. Point it at the
CARLA loop. Disarm L6, L7a and L7b in turn and re-measure — the synthetic result
is that `L6 off` and `L7a off` are **identical to governed in every cell**, and
whether that survives CARLA is P3/P4 seen from the other side.

### Route definitions

`hw-loop-a` and friends in the `partition.json` example are **placeholders**. You
have to define real Town04 routes as waypoint lists, and §4.2's rule governs
them: **the road geometry itself must differ between TRAIN, CALIBRATE and TEST.**
Town04 has a highway loop, urban streets and a tunnel — enough for three disjoint
sets, but you must pick them deliberately and write them into the manifest before
committing it.

---

## 6 · Order of operations

Do not reorder. Each gate must pass before the next step.

| # | Step | Gate before proceeding |
|:--:|---|---|
| 0 | Commit `partition.json` | **It is in git, before any frame is rendered** |
| 0b | Decide `RAIN_NIGHT` | An ADR exists either way. **Decided, not deferred** |
| 1 | Generate TRAIN | The run guard: the vehicle actually drove |
| 2 | Fit the twin on TRAIN **only** | Weights digest recorded |
| 3 | Generate the corpus from CALIBRATE, twin from step 2, FB1 on | Corpus SHA-256 recorded |
| 4 | **Per-class sufficiency check** | **Abort if any reachable class is short** |
| 5 | Run TEST **once** | Steps 0–4 recorded and unchanged |

**Any change to step 2 invalidates step 3.** This project has paid for that lesson
**four times.** Most recently on 15 August, when a corrected innovation covariance
put **400 of 400 ticks** into a veto until the corpus was regenerated — and
`make artifacts-check` caught it on its first day.

**Step 4 in detail.** `minimum_calibration_samples = 500`;
`generate_calibration.py` targets **1,000 per class**. At 20 Hz that is 50 seconds
of ticks classified into that class — trivially achievable *if the class is
reachable at all*. `RAIN_NIGHT` is the one that is not, which is why Gate A comes
first.

---

## 7 · The six predictions — written down before you measure

Dated and falsifiable **on purpose**, so they cannot be rationalised afterwards.
Mark each **confirmed** or **refuted**, with numbers. **Keep the refutations.**

| # | Prediction | Why | If wrong, that is the finding |
|---|---|---|---|
| **P1** | **OD-8 gets worse, not better** — L6's live scores land outside the CARLA corpus | The synthetic corpus is from another plant; even a CARLA corpus faces a policy that transfers badly | Exchangeability is more robust than in-house measurement suggested |
| **P2** | **The twin is badly wrong** — non-conformity scores rise sharply | The PINN learned bicycle kinematics; CARLA has suspension, tyre slip, drivetrain lag | The bicycle model is a better approximation than assumed |
| **P3** | **L7a finally fires** — the corridor bound is reachable in real driving | It vetoed once in ~500,000 synthetic ticks because nothing ever left the corridor | L7a's thresholds are wrong, not its traffic |
| **P4** | **The gate census inverts** — L6 stops being silent and vetoes constantly | Its silence today is OD-8, scores below the corpus. Out-of-distribution driving moves them the other way | The gate is insensitive rather than mis-calibrated |
| **P5** | **Wall 3 does not bite** — the bicycle process model is adequate | CARLA drives a car; the model is wrong for a warehouse AGV, not for this | A road vehicle needs more than a bicycle model, which is a real finding |
| **P6** | **The fail-safe halts more often** | Real sensors are noisier and drop frames; `integrity_tolerated_faults = 0` in every profile | The integrity thresholds transfer, which would be a genuine result |

**P3 and P4 are the ones worth caring about.** Today two of three gates judge
every tick and never object. If CARLA makes them object, the three-gate
independence claim gets its **first real support**. If it does not, the paper's
contribution 2 needs rewriting.

---

## 8 · Exit criteria

1. The adapter satisfies its ports with **no change to `src/astra/`** beyond what
   ADR-0034 made injectable.
2. `lint-imports` still passes — `carla` appears nowhere outside `adapters/`.
3. `partition.json` was committed **before the first frame**; TRAIN / CALIBRATE /
   TEST are disjoint **by route**; `test-runs.log` holds exactly one entry for the
   TEST manifest's digest.
4. The seven-phase continuous drive (**§5.6**) completes without the vehicle
   stopping — **or it stops and the reason is in the audit log, named, with the
   posture that produced it.**
5. Every P1–P6 prediction is marked confirmed or refuted, with numbers.
6. The register's `[M-syn]` rows carry a second column: what the same measurement
   said in CARLA.

**Criterion 4 is the right shape for a governance system.** It does not require
success; it requires that failure be **legible**. A stop with a named reason and a
posture is a passing result.

---

## 9 · Traps this project has already paid for

Every one cost real time. They are listed because they will recur.

**The working copy is not what shipped.** On 17 August the quality gate passed
locally while the committed branch was **red** — formatting had been applied on
one side of a file sync and the commit came from the other. **Lint from a fresh
`git clone`, not from your working tree.**

**One run is not a tail statistic.** A single latency run reported "one tick in
2,000 over budget"; five runs said 0–31, and ten the next day said 0–2. The p99
was not reproducible across days; **the maximum was.** `tick_latency` defaults to
five runs for exactly this reason.

**A zero is not good news by default.** A zero veto rate, a silent gate, and a
benchmark that prints nothing all look like health. Two of three gates have veto
counts of zero and it is a **defect**, not a result.

**Guards go stale exactly like numbers do.** A guard added after a retraction
later began blocking its own benchmark, because a subsequent ADR gave the
fail-safe a response that brings the vehicle to rest — which the guard read as a
dead loop. It produced nothing for a day and nobody noticed. **Check every refusal
for whether it is refusing the right thing.**

**Read the origin together with the value.** The `lateral_noise` mechanism was
explained wrongly **twice** because a command substitution was attributed to the
majority origin without reading `record.issued.origin` on that tick. When you
trace anything per tick, print the label and the number together.

**Field names.** `TickSample` has **no** estimated/true lateral fields. The
estimate is `record.fast_state.mean[1]` (`position_y`) and it is **optional** —
handle `None`. `ProposedCommand` has `.command`, not `.proposed_command`. **If a
probe returns `nan` or an empty result, stop and introspect the object — do not
report around it.** Two probes silently returned `nan` before anyone noticed.

**A number whose command cannot be re-run is not evidence.** Two evidence rows
cited a command that printed a different measurement entirely, and it stood for a
day because nobody ran it.

---

## 10 · What must never be claimed

Each line has already cost a retraction or a register row.

| Never say | Because |
|---|---|
| a "false-positive" or "false-negative rate" of any gate | None has been measured. **One CARLA result does not create one either** — that needs a distribution of *normal* driving, and fault injection cannot manufacture it |
| "the gates are independent" | All three read L2's estimate; OD-9 is a measured common cause. And two of three never object |
| "three layers of defence" | Measured: **one**. Disarming L7b takes every veto to zero |
| "validated on real driving" | CARLA is a simulator. `[M-ext]` earned here means **this simulator, this town, this seed** |
| "1.25 µs intercept latency" | An analytical bound for hardware that does not exist |
| "real-time" | p50 ~2.2 ms, but individual ticks have reached 44–55 ms against a 10 ms budget, and **there is no deadline monitor** |
| "ASIL-D" | A design target. An ASIL is the outcome of an assessed safety case |
| "tamper-proof evidence log" | Tamper-**evident** |

**The highest-rated risk on this plan is rhetorical, not technical.** It is
presenting CARLA numbers as though they validated the architecture, when they
validate a prototype on **one simulator, in one town, on one seed.** Every row
keeps its marker, and `[M-ext]` means *this simulator* — say so in the row, not in
a footnote.

---

## 11 · How to record what you find

**A number lives in exactly one place, and that place is `docs/EVIDENCE.md`.**
Everything else cites it as `E-n`. If a figure appears in two documents, one is
stale — that has happened, and the convention exists because of it.

Every row needs the claim, the figure, **the command that reproduces it**, and the
date. Mark CARLA rows `[M-ext]` **and name the simulator, town and seed.**

**When a measurement contradicts a document, the document is usually wrong — but
say which, in public.** This project keeps its retractions: `E-143`, `E-145` and
`E-161` are withdrawn rows that stayed on the record with the reason. That is the
house style, not an embarrassment.

**If you are verifying rather than building**,
`A-Z/00_START_HERE/VERIFY_PROMPT.md` is a self-contained prompt that proposes
corrections into a `CORRECTIONS.md` without editing anything. **The session that
measures should not be the session that rewrites** — that separation exists
because a session doing both corrected its own corrections twice in one afternoon.

---

## 12 · Your first six commands

```bash
nvidia-smi; nproc; free -g; df -h .
git clone https://github.com/huddartanay/Major-Project.git astra && cd astra
git checkout phase4-l5-twin-l7b-physical && git checkout -b carla-adapter
uv sync --all-groups --all-extras
make artifacts-check          # regenerate with `make artifacts` if it refuses
make check                    # expect 3,065 passed + 3 xfailed, gate PASSED
python -m benchmarks.gate_census && python -m benchmarks.arms
tmux new -s carla             # everything long goes in here
```

Then read `docs/CARLA_PLAN.md` in full, settle **Gate A** and **Gate B**, and only
then start §5.

**If anything in §3's baseline does not reproduce, stop and report it before
building.** A porting difference found now is a paragraph. Found after a CARLA
result, it is a retraction.
