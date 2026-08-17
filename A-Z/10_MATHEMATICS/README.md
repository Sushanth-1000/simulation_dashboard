# 10 · Mathematical Foundations

**Read this before section 09.** Every concept is built from the ground up:
*intuition → equation → what each variable means → where it appears in ASTRA*.

No prior knowledge assumed beyond school algebra.

---

## 10.1 · Uncertainty as a distribution

### Intuition

You do not know where the vehicle is. You have a **best guess** and a **sense of
how wrong that guess might be**. Both are needed: *"we are at 0.03 m"* is much
less useful than *"we are at 0.03 m, give or take 0.1 m"*.

### The Gaussian

The distribution used throughout, because it is closed under the operations a
Kalman filter performs — combine two Gaussians and you get a Gaussian.

```
p(x) = (1 / √(2πσ²)) · exp( −(x − μ)² / (2σ²) )
```

| Variable | Meaning |
|---|---|
| `μ` (mu) | the **mean** — the best guess |
| `σ` (sigma) | the **standard deviation** — typical error size, in the same units as `x` |
| `σ²` | the **variance** — σ squared. What the maths carries |

**Rule of thumb:** ~68% of the probability lies within ±1σ, ~95% within ±2σ.

### In ASTRA

`POSITION_SIGMA = 0.1` — lateral position is measured to about 10 cm.

**And this is the number L6 divides by.** Hold that thought; it returns in §10.6.

---

## 10.2 · Many quantities at once — vectors and covariance

The vehicle has five fast-changing quantities, tracked together **[FACT** —
`FAST_STATE_FIELDS`**]**:

```
x = [ position_x, position_y, speed, heading, lateral_acceleration ]
```

### Why one matrix and not five numbers

Because the errors are **correlated**. If your heading estimate is wrong, your
position estimate becomes wrong *in a predictable direction*. Five independent
σ's cannot express that; a **covariance matrix** can.

```
      ┌ σ²(px)      cov(px,py)   cov(px,v)   …  ┐
  P = │ cov(py,px)  σ²(py)       …               │
      │ cov(v,px)   …            σ²(v)           │
      └ …                                        ┘
```

**How to read it.**

- **Diagonal** — the variance of each quantity on its own. `P[1][1]` is the
  variance of lateral position.
- **Off-diagonal** — how two errors move together. Positive means *"when this one
  is over-estimated, so is that one"*.
- **Symmetric** — `cov(a,b) = cov(b,a)`.

### Positive-definiteness, and why the code lets it crash

A covariance matrix must be **positive definite** — informally, every direction
must have positive uncertainty. Negative variance is meaningless.

Numerical error can destroy this. ASTRA's response **[FACT** — `unscented.py`**]**:

> `np.linalg.cholesky` raises `LinAlgError` on a covariance that has stopped
> being positive definite, and that exception is **allowed to propagate** … and
> therefore into a VETO. **A filter that quietly repaired its own covariance
> would return a state estimate nobody could justify**, and the layer above would
> have no way to know.

**[INTERPRETATION]** This is a small decision with a large lesson: silently
fixing a broken number destroys the evidence that it broke.

### Storage

`SymmetricMatrix` stores only the lower triangle — a symmetric 5×5 has 15
distinct entries, not 25. ADR-0011: **no NumPy in the kernel**, so the innermost
layer carries no third-party dependency at all.

---

## 10.3 · Bayesian estimation — the loop the filter runs

### Intuition

Two things tell you where you are:

1. **What you expected** — you were here, going this fast, so you should now be
   there. *Cheap, and drifts.*
2. **What you measured** — a sensor says you are here. *Noisy, and does not drift.*

**Neither alone is good.** Bayesian estimation combines them, weighted by how
much you trust each.

### The cycle

```
        ┌──────────► PREDICT ──────────┐
        │   push the state forward      │
        │   uncertainty GROWS  (+Q)     │
        │                               ▼
     estimate                       prior estimate
        ▲                               │
        │           UPDATE              │
        │   fold in the measurement     │
        └───  uncertainty SHRINKS  (R) ◄┘
```

**Predict** — apply the motion model. You know less than before, so **`P` grows**
by the process noise `Q`.

**Update** — a measurement arrives. You know more, so **`P` shrinks**, by an
amount governed by the measurement noise `R`.

### The variables you will meet everywhere

| Symbol | Name | Means |
|---|---|---|
| `x` | state | best estimate |
| `P` | covariance | uncertainty in `x` |
| `Q` | **process noise** | how much the *model* is wrong per step |
| `R` | **measurement noise** | how noisy the *sensor* is |
| `z` | measurement | what the sensor said |
| `y` | **innovation** | `z − (what we predicted)` — **the surprise** |
| `S` | innovation covariance | how surprised we *should* expect to be |
| `K` | Kalman gain | how much to trust the measurement |

### The innovation is the most important one

> `y` is the difference between what the sensor said and what the model expected.

If the model and the sensor agree, `y ≈ 0`. Persistent non-zero `y` means
something is wrong — **and that is why the innovation is the natural place to
look for sensor faults**. It is also why four separate fault detectors in this
project were built on it, and why all four failed against a slow drift (§09).

---

## 10.4 · Why *unscented* — the problem with linearising

### The problem

A Kalman filter's maths assumes **linear** relationships. Vehicle motion is not
linear: heading feeds into position through sine and cosine.

**The classical fix (EKF):** linearise — compute a Jacobian, a matrix of partial
derivatives, at the current estimate and pretend the model is linear nearby.

**Why that is unattractive.** You must derive the Jacobian by hand, it must be
re-derived whenever the model changes, and it is a *first-order* approximation of
a curved function — the error grows with curvature and with uncertainty.

### The unscented idea

Do not approximate the *function*. Approximate the **distribution**, then push it
through the **true** function.

```
   Gaussian (μ, P)
        │
        │  pick 2n+1 carefully-placed points
        ▼
   sigma points  X_0 … X_2n
        │
        │  push each through the TRUE non-linear f()
        ▼
   transformed points Y_0 … Y_2n
        │
        │  weighted mean and covariance
        ▼
   Gaussian (μ', P')
```

**No Jacobian. No derivatives. The real model, evaluated at points.**

### The equations, exactly as implemented

**[FACT** — verbatim from `unscented.py`'s module docstring.**]**

**Sigma points** (van der Merwe's scaled form):

```
lambda = alpha² (n + kappa) − n
U      = chol( (n + lambda) P )        upper triangular
X_0    = x
X_k    = x + U_k       for k in 1..n   (U_k is the k-th ROW of U)
X_n+k  = x − U_k
```

**Weights:**

```
Wm_0 = lambda / (n + lambda)
Wc_0 = lambda / (n + lambda) + (1 − alpha² + beta)
Wm_i = Wc_i = 1 / (2(n + lambda))      for i > 0
```

**The transform, with additive noise `N`:**

```
mean = Σ_i Wm_i · Y_i
cov  = Σ_i Wc_i (Y_i − mean)(Y_i − mean)ᵀ + N
```

### Every variable

| Symbol | Meaning |
|---|---|
| `n` | state dimension — **5** for the fast filter |
| `2n+1` | number of sigma points — **11**. One at the mean, one either side per dimension |
| `alpha` | how far the points spread. Small keeps them near the mean. **1e-3** here |
| `kappa` | secondary scaling, usually 0 |
| `beta` | incorporates prior knowledge of the distribution. **2 is optimal for a Gaussian** |
| `lambda` | the composite scaling factor |
| `chol` | **Cholesky decomposition** — the "square root" of a matrix. It is how you spread points in proportion to uncertainty in *every* direction, including correlated ones |
| `Wm` | weights for reconstructing the **mean** |
| `Wc` | weights for reconstructing the **covariance**. Note `Wc_0 ≠ Wm_0` |

**Why two weight sets.** The mean and the covariance are different statistics;
`beta` corrects the covariance using knowledge about the distribution's shape,
and that correction has no business in the mean.

**Complexity.** `O(n³)` per step, dominated by the Cholesky. `n = 5`, so this is
trivial in absolute terms.

---

## 10.5 · Conformal prediction — a guarantee without a model

### The idea, in one sentence

> Rank the new thing against a pile of past things. If it is more extreme than
> 95% of them, call it unusual.

**And that is a real, provable guarantee** — no assumption that your model is
correct, no assumption of Gaussianity.

### What it buys, and the one thing it costs

It buys **distribution-free coverage**: if you flag the top ε fraction, you will
be wrong at most ε of the time.

It costs **exactly one assumption**:

> **Exchangeability** — the calibration scores and the new score are drawn from
> the same population, and their *order* does not matter.

Break it and the quantile is a number computed from the wrong sample. **The
method does not fail loudly. It just stops being true.**

### Mondrian — class-conditional

A single global population would compare highway driving against urban driving
and call both mildly unusual. **Mondrian** conformal prediction keeps a *separate*
calibration population per context class, so the comparison is against
*situations like this one*.

### The quantile index — and a subtlety the project got right

Naïvely you take the ⌈n(1−ε)⌉-th smallest calibration score. **That is wrong**,
and `quantile.py` says why **[FACT]**:

> The guarantee holds only if the threshold is the **⌈(n+1)(1−ε)⌉**-th smallest
> score.

The `+1` accounts for the test point itself joining the population. Dropping it
makes the interval **too tight** and the guarantee false — subtly, and only
visibly at small `n`.

**And a second subtlety.** When ⌈(n+1)(1−ε)⌉ > n there is **no finite threshold**
that achieves the coverage — you simply do not have enough calibration data. The
correct answer is **infinity** (never veto), not "clamp to the largest score".

> An infinite threshold is honest: *"I cannot make this guarantee yet."*
> Clamping would silently promise coverage it cannot deliver.

The smallest usable `n` is `⌈(1−ε)/ε⌉` — at ε = 0.05, that is **19 samples**
before any finite threshold exists.

**[INTERPRETATION]** These two details are worth dwelling on because they are
exactly the kind of thing that is wrong in most implementations and never
noticed: both failure modes produce plausible numbers.

---

## 10.6 · The non-conformity score

**[FACT** — verbatim from `gate.py`.**]**

```python
departure = math.dist(proposed, predicted)
sigma = math.sqrt(max(variance, _MINIMUM_SIGMA))
score = departure / sigma
```

| Term | Meaning |
|---|---|
| `departure` | Euclidean distance between what the proposer asked for and what the twin predicts |
| `variance` | `P_f` at the **control dimension** — the filter's own uncertainty in lateral acceleration |
| `sigma` | its square root — an uncertainty in the same units as the departure |
| `score` | departure measured **in units of the filter's own uncertainty** |

### Why divide by sigma — the elegant part

A departure of 0.5 m/s² means something very different when the filter is
confident (σ = 0.05) than when it is not (σ = 0.5).

```
confident filter:  0.5 / 0.05 = 10.0   → very unusual
uncertain filter:  0.5 / 0.50 =  1.0   → unremarkable
```

**The gate automatically becomes more permissive exactly when the state is least
certain.** This is the behaviour the paper describes, and it **arises from the
arithmetic** rather than being special-cased.

### And the failure mode that follows from it

A **self-consistent lie shrinks σ**, because the filter treats a consistent
reading as informative. So the denominator falls, and the estimate is further
from truth while the gate is more confident.

> **Confidence and correctness move in opposite directions.** That is OD-9, in one
> line of arithmetic.

### Why the function returns three values

It returns `(score, departure, sigma)`, not just the score — because *"a score
alone cannot be told apart from a large departure and a large sigma"*. The
evidence log needs the parts.

---

## 10.7 · Mahalanobis distance

### Intuition

*"How many standard deviations away is this, accounting for the fact that the
dimensions are correlated?"*

Euclidean distance treats every direction alike. If your uncertainty is a long
thin ellipse, a point far along the thin axis is much more surprising than one
equally far along the long axis. Mahalanobis distance accounts for that.

```
d = √( yᵀ S⁻¹ y )
```

| Term | Meaning |
|---|---|
| `y` | the innovation — the surprise |
| `S` | the innovation covariance — how surprised we expected to be |
| `S⁻¹` | its inverse — "divide by" the expected surprise |

If `d` is 1, you were exactly as surprised as expected. If 7.5 (the configured
gate), something is badly off.

### The bug that lived here — ADR-0032

`S` should be `H·P·Hᵀ + R`, where `P` **includes** the process noise `Q`. The
implementation observed sigma points whose spread was `P` **before** `Q` was
added, so:

```
S = H(P − Q)Hᵀ + R          ← short by exactly H·Q·Hᵀ
```

**Every Mahalanobis distance the filter ever reported was inflated.** Measured:
**1.34× at the median**, and **1.02× at the maximum** — the correction is
largest where innovations are small and nearly absent in the tail, *which is
where vetoes are decided*.

**Why it could not be patched.** You cannot simply add `H·Q·Hᵀ`, because **a UKF
has no `H`** — not having one is the entire point of the sigma-point formulation.
The fix was to **redraw the sigma points from the `Q`-inflated covariance**,
which is how the textbook formulation carries the term.

---

## 10.8 · Maximum Mean Discrepancy (MMD)

Used by L6's shift detector.

**Intuition.** *"Do these two piles of numbers come from the same distribution?"*
— answered without assuming what the distribution is, by mapping both into a
feature space and comparing their means.

**Role here:** compare a rolling window of live scores against the calibration
reference. When they diverge, the covariate-shift detector fires and tightens ε.

**[UNVERIFIED]** The kernel and window details are in
`src/astra/layers/l6_statistical_gate/mmd.py` and were not read in detail while
writing this. Treat the role as correct and the internals as a lead.

---

## 10.9 · Constrained optimisation — the CMDP

**The problem.** Maximise driving performance subject to *"lane deviation ≤ 0.875
m"*, *"acceleration ≤ 4 m/s²"*, *"collision rate = 0"*.

**The naïve approach — fold constraints into the reward as penalties.** It works
badly: the weights are arbitrary, and it is **exactly the failure of C-3**, where
`action_rate_weight` was 6.0 against a task reward capping at 2.0, making a step
at the jerk limit cost **one part in ten thousand**. The result was a policy that
**stopped the vehicle** — the constraint had effectively vanished.

**The Lagrangian dual.** Keep the constraints separate with their own multipliers,
and *adapt* the multipliers from the costs the current policy actually realises.
A constraint that is being violated gets a rising multiplier until it is not.

**Why it matters for legibility:** the constraint budgets stay readable as
budgets — 0.875 m, 4 m/s², zero collisions — rather than disappearing into a
weighted sum nobody can audit.

---

## 10.10 · You should know this before moving on

**Equations you must be able to read**

1. `cov = Σ Wc_i (Y_i − mean)(Y_i − mean)ᵀ + N` — the unscented transform
2. `score = departure / sigma` — and why the division is the clever part
3. `d = √(yᵀ S⁻¹ y)` — Mahalanobis
4. `⌈(n+1)(1−ε)⌉` — the conformal index, **and why not `⌈n(1−ε)⌉`**

**Variables you must know cold:** `x`, `P`, `Q`, `R`, `y`, `S`, `K`, `σ`, `ε`.

**Questions you should be able to answer**

1. Why one covariance matrix rather than five variances?
2. Why does the UKF avoid Jacobians, and what does it do instead?
3. What is the *one* assumption conformal prediction buys its guarantee with?
4. Why is `⌈n(1−ε)⌉` wrong, and what goes wrong at small `n`?
5. Why does dividing by σ make the gate permissive when uncertain — and how does
   that become the OD-9 failure mode?
6. Why can `H·Q·Hᵀ` not simply be added to `S` in a UKF?

**Misconception to avoid**

> *"Conformal prediction gives a guarantee, so the gate is sound."*
>
> The guarantee is conditional on exchangeability, and this project has
> **measured that condition violated** — zero overlap between live and
> calibration scores (`E-159`). The maths is fine. The precondition is not met,
> and the gate's zero veto rate is the symptom.

---

**Next:** `09_ALGORITHMS/`.
