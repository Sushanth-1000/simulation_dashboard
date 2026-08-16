# 08 · Internal Mechanics

Where §06 says *"L2 fuses the readings"*, this section says **exactly what
happens, line by line**.

All code quoted is **[FACT]**, read from the tree.

---

## 8.1 · The UKF predict step — and the bug that lived in it

```python
def predict(self) -> None:
    sigmas     = self._points.sigma_points(self.x, self.P)
    propagated = np.array([self._fx(point, self._dt) for point in sigmas])
    self.x, self.P = unscented_transform(
        propagated, self._mean_weights, self._covariance_weights, self.Q
    )
    self._sigmas_f = self._points.sigma_points(self.x, self.P)   # ← ADR-0032
```

**Line by line.**

1. **Draw 11 sigma points** from the current `(x, P)`. Cholesky of `(n+λ)P`,
   then ± each row.
2. **Push every point through the true process model** `fx`. No linearisation.
3. **Reconstruct** the mean and covariance, **adding `Q`** — the covariance grows,
   because a prediction is less certain than what it came from.
4. **Redraw the sigma points from the `Q`-inflated `P`.**

### Why line 4 exists — the whole of ADR-0032

Without it, `_sigmas_f` holds the points *propagated through `fx`*, whose spread
is the covariance **before** `Q` was added. `update` then observes that stale set:

```
S = H(P − Q)Hᵀ + R          short by exactly H·Q·Hᵀ
```

**Every Mahalanobis distance the filter ever reported was inflated.** Inherited
from FilterPy, reproduced deliberately, and **pinned by a unit test** so that
changing it *"had to be a decision rather than a drift"*. On 15 August it became
one — and the test fired.

**Why redrawing rather than adding the term.** A UKF has **no `H`**. Not having
one is the entire point of the formulation. Redrawing is how the textbook carries
the term: the process noise goes into the measurement sigma set, where the
transform can find it.

**And it changes the gain, correctly.** The cross-covariance is accumulated from
the *same* points, so it becomes `P·Hᵀ` against the predicted covariance — which
is what a Kalman gain is defined against. Correcting `S` alone would have left
the two inconsistent.

**Cost:** a second Cholesky per tick — trivial on 5×5 — and **control quality**:
final lane deviation went **0.0122 m → 0.1218 m**, because a correct filter
trusts each measurement less.

---

## 8.2 · The update step

```python
sigmas_h = np.array([observe(point) for point in self._sigmas_f])
predicted, innovation_covariance = unscented_transform(
    sigmas_h, self._mean_weights, self._covariance_weights, noise
)

cross = np.zeros((self._dim_x, sigmas_h.shape[1]))
for index in range(self._sigmas_f.shape[0]):
    cross += self._covariance_weights[index] * np.outer(
        self._sigmas_f[index] - self.x, sigmas_h[index] - predicted
    )

gain  = cross @ np.linalg.inv(innovation_covariance)
self.y = measurement - predicted
self.S = innovation_covariance
self.K = gain
self.x = self.x + gain @ self.y
```

**What each step is doing.**

- **`sigmas_h`** — push the state sigma points through the *observation* function.
  *"If the state were each of these, what would the sensor read?"*
- **`predicted, S`** — the expected measurement and how much it should vary.
- **`cross`** — the cross-covariance `Pxz`: how state error and measurement error
  move together. **This is what makes the correction possible.**
- **`gain = Pxz · S⁻¹`** — how far to move toward the measurement. Large when
  the state is uncertain relative to the sensor; small when the reverse.
- **`y = z − predicted`** — the **innovation**. The surprise.
- **`x += K·y`** — move the estimate toward the measurement, in proportion to `K`.

### Three deliberate details

**The loop, not a matrix product.** *"Accumulated as a sum of weighted outer
products, in index order … a matrix product sums in a different order and lands a
nanosecond of state away."* Bit-comparable replay (A-5) needs summation order
fixed.

**`inv` not `solve`.** `solve` would be better conditioned. Kept because
*"replacing a library and improving its numerics in the same change makes any
difference unattributable to either"*.

**`K @ (S @ K.T)`, not `(K @ S) @ K.T`.** Same identity, different rounding, and
the right-associated form is the one being replaced.

**[INTERPRETATION]** Three separate places where *"reproduce exactly, improve
separately"* was chosen over *"make it better now"*. That discipline is what
makes the FilterPy removal defensible as a like-for-like swap.

---

## 8.3 · The non-conformity score, end to end

```python
departure = math.dist(proposed, predicted)
sigma     = math.sqrt(max(variance, _MINIMUM_SIGMA))
score     = departure / sigma
```

Then, in the gate:

```
threshold = quantile(context_class, 1 − effective_epsilon)
verdict   = VETO if score > threshold else PASS
```

**`_MINIMUM_SIGMA` is a floor, and it exists for a stated reason:** without it, a
near-zero variance produces *"an enormous score — arithmetically a VETO, which is
the right answer, but by way of an overflow rather than a decision."* The floor
makes the veto **explicit** and keeps the number in the evidence log finite and
readable.

**`effective_epsilon`** tightens when the covariate-shift detector fires — so the
*threshold* moves even though the calibration distribution does not.

---

## 8.4 · The fail-safe counters

```python
def _advanced_counter(self, *, blocking: bool, exploring: bool = False) -> int:
    if exploring:
        return self._counter                       # frozen — ADR-0023
    if not blocking:
        return max(0, self._counter - 1)
    return min(self._settings.ood_threshold_halt, self._counter + 1)
```

**Four behaviours in five lines.**

- **Freeze during exploration** (ADR-0023). While L9 owns the out-of-envelope
  condition, counting it again escalates one event twice. Measured: the counter
  climbed 0 → 100 and halted a vehicle L9 was correctly holding in a narrowed
  envelope.
- **Floor at 0.** A long clean run must not build *credit* that lets a later
  burst pass unnoticed.
- **Ceiling at the HALT threshold.** A soak recorded **1,508 by tick 2,000** and
  climbing, consulted by nothing. An integer that grows without bound and
  influences nothing is noise — and it is written into every audit row.
- **The ceiling also bounds recovery.** Outside HALT the counter cannot exceed
  `θ_halt`, so the longest walk back to NOMINAL is
  `θ_halt − θ_degraded + hysteresis` = **91 ticks = 4.6 s at 20 Hz**. Recovery is
  automatic **and bounded**.

### The integrity counter

```python
critical = self._settings.critical_modalities
unhealthy = sum(
    1 for modality, health in frame_health
    if health is not StreamHealth.HEALTHY and modality in critical
)
if unhealthy <= self._settings.integrity_tolerated_faults:
    return max(0, self._integrity - 1)
return min(self._settings.integrity_threshold_halt, self._integrity + 1)
```

Three decisions compressed into one condition:

| Element | ADR | Why |
|---|---|---|
| `modality in critical` | 0028 | A camera failure halted the vehicle exactly as an IMU failure did, on a build whose extractor reads the IMU alone |
| `<= tolerated_faults` | 0027 | One faulted channel of three HALTed a vehicle driving at 0.042 m on the other two |
| Does **not** freeze during exploration | 0024 | *"A vehicle exploring a tunnel with a dead IMU is in more trouble than one doing either alone, not less"* |

---

## 8.5 · Capability withdrawal — the second axis

```python
unhealthy = {m for m, h in frame_health if h is not StreamHealth.HEALTHY}
withdrawn = tuple(
    name for name, required in self._settings.capabilities
    if unhealthy.intersection(required)
)
```

**No counter. No threshold. No hysteresis.** Three properties make it safe:

**It can only subtract.** The posture and the capability set compose by
**intersection**. A set able to *grant* what the posture forbids would be a
fourth gate with veto-override authority — SI-3 forbids it, and intersection
makes it **unrepresentable rather than merely untested**.

**It ignores `critical_modalities` entirely.** The critical set decides whether a
modality moves the *posture*; this decides which *functions* it carries. A camera
can be no reason to slow down and still be the only thing a lane change needs.

**No debounce, unlike the counters.** A counter exists to distinguish a glitch
from a fault, because escalating the *posture* on one bad frame is intolerable.
**Withdrawing a function costs almost nothing** — so paying a detection delay
would be the wrong trade, and would mean granting a lane change during ticks the
camera had already gone dark.

---

## 8.6 · Sensor decay — measuring what the counter cancels

```python
alpha = 2.0 / (self._settings.decay_window_ticks + 1.0)
for modality, health in frame_health:
    unhealthy = 0.0 if health is StreamHealth.HEALTHY else 1.0
    previous  = self._decay.get(modality, 0.0)
    self._decay[modality] = previous + alpha * (unhealthy - previous)
```

**An exponential moving average of a 0/1 indicator**, which converges to exactly
the **duty cycle** of the fault.

### The blind spot it fills

The integrity counter moves **+1 unhealthy, −1 healthy**, so **any duty cycle at
or below 50% nets to zero and never escalates, however long it runs.**

Measured over a full minute at 20 Hz:

| pattern | ticks dark | peak counter | posture |
|---|--:|--:|---|
| 1 dark / 1 clean | 600 / 1200 | **1** | **NOMINAL** |
| 3 dark / 10 clean | 279 / 1200 | 3 | NOMINAL |

A camera dropping a quarter of its frames reported perfect health.

**The counter is not wrong.** It answers *"am I in trouble now?"* and the answer
really is no — the estimator had a fresh reading a tick ago. It is **memoryless
by design**, which is the same property that makes recovery bounded.

**So the fix was not to change it, but to measure the quantity it cancels.**

**And decay drives nothing** — no posture, no veto, no command. *A decaying sensor
is a service condition, and a vehicle that stopped for maintenance would be the
nuisance stop ADR-0028 removed, through a different door.*

**And `reset` does not clear it.** Otherwise halt → reset → halt → reset would
launder a failing sensor clean. *A reset clears what the machine decided; it does
not make the camera younger.*

---

## 8.7 · Verdict merge

```
merge([PASS, PASS, PASS]) → PASS
merge([PASS, VETO, PASS]) → VETO        any veto wins
merge([])                 → VETO        absence is refusal
ABSTAIN dropped before the fold
```

Not a vote, not a weighted score, not a majority. **A fold with `VETO` as the
absorbing element and as the identity for the empty case.**

**Why empty ⇒ VETO.** If no gate reported, something upstream failed. Treating
that as permission would make a crashed gate indistinguishable from an approving
one.

---

## 8.8 · Errors as verdicts

```
LinAlgError (covariance not PD)
   → SafetyPathError
      → VETO
```

**No component repairs itself.** A filter that quietly fixed its own covariance
would return a state estimate nobody could justify, and the layer above would
have no way to know it had happened.

**[INTERPRETATION]** The general rule visible across the codebase: **an error
becomes a refusal, never a repair.** Repair destroys the evidence that something
broke.

---

## 8.9 · You should know this before moving on

**Mechanisms you must be able to describe**

1. The four lines of `predict`, and why line 4 exists
2. `Pxz · S⁻¹` — what the cross-covariance is *for*
3. `departure / sigma`, and the floor under sigma
4. The counter's four behaviours: freeze, floor, ceiling, bounded recovery
5. Why capability withdrawal has no debounce and the counters do
6. Why decay drives nothing and survives `reset`

**Questions you should be able to answer**

1. Why does redrawing the sigma points fix `S` when adding `H·Q·Hᵀ` cannot?
2. Why is the cross-covariance accumulated in a loop rather than as a matrix
   product?
3. What does an unbounded counter cost, given nothing reads the excess?
4. Why does the *integrity* counter not freeze during exploration when the OOD
   counter does?
5. Why does composing posture and capabilities by **intersection** make an SI-3
   violation unrepresentable rather than merely untested?

**Misconception to avoid**

> *"The floor under sigma is defensive programming."*
>
> It is a **legibility** decision. Without it the veto still happens — by
> overflow. The floor makes it *"explicit rather than by way of an overflow"* and
> keeps the evidence-log number finite and readable. The behaviour barely changes;
> the audit trail changes completely.

---

**Next:** `23_RUNTIME_BEHAVIOR/`.
