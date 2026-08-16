# 20 · Alternatives

Each major component against realistic competitors, compared on the dimensions
that actually decided it.

**Scoring key:** ●●● strong · ●●○ adequate · ●○○ weak.

---

## 20.1 · State estimation

| | **UKF** *(chosen)* | EKF | Particle filter | Complementary filter |
|---|---|---|---|---|
| Accuracy on non-linear models | ●●● | ●●○ | ●●● | ●○○ |
| Runtime | ●●○ `O(n³)`, n=5 | ●●● | ●○○ | ●●● |
| Memory | ●●● | ●●● | ●○○ | ●●● |
| **Produces a covariance** | **●●●** | ●●● | ●●● | **○○○ none** |
| Implementation difficulty | ●●○ | ●○○ Jacobians by hand | ●●○ | ●●● |
| Explainability | ●●● | ●●● | ●●○ | ●●● |
| Failure behaviour | Cholesky raises → **VETO** | Silent linearisation error | Particle depletion | Silent |

**Why the UKF won.** Two decisive columns.

**No Jacobian.** An EKF needs one derived by hand, re-derived whenever the model
changes, and it is a first-order approximation whose error grows with curvature.

**It produces the covariance.** This is not a nicety — **L6 divides by it**. A
complementary filter is cheaper and faster and would leave the statistical gate
with no denominator, deleting a whole layer.

**What would reopen it.** A platform whose posterior is genuinely multi-modal —
two plausible positions rather than one uncertain one. A Kalman filter of any
kind assumes unimodality; a particle filter does not.

---

## 20.2 · The uncertainty / anomaly layer

| | **Mondrian ICP** *(chosen)* | Global conformal | Fixed threshold | Bayesian credible interval | EnbPI *(the paper's claim)* |
|---|---|---|---|---|---|
| Guarantee | **Distribution-free** | Distribution-free | None | Requires a well-specified model | Distribution-free |
| Context sensitivity | **●●●** per class | ●○○ | ●○○ | ●●○ | ●●○ |
| Runtime | ●●● `O(log n)` | ●●● | ●●● | ●○○ | ●○○ ensemble |
| Explainability | ●●● *"above the 95th percentile for this context"* | ●●● | ●●● | ●●○ | ●●○ |
| Assumptions | **Exchangeability** | Exchangeability | — | Model correctness | Exchangeability |
| Failure behaviour | **Silent** — a stale corpus vetoes nothing | Silent | Silent | Silent | Silent |

**Why Mondrian ICP won.** It is the only option offering a coverage guarantee
**without trusting the model** — and not trusting the model is the whole premise.

**Why not global conformal.** It would compare highway against urban and call
both mildly unusual, flagging neither.

**Why not EnbPI** — the paper's stated contribution: it needs an ensemble, and
**no ensemble was ever built**. The claim was withdrawn and `ensemble_size`
deleted.

**The honest caveat.** Every option in that table shares a **silent** failure
mode, and ICP's precondition is currently **violated** (`OD-8`). *The chosen
option is not currently delivering the property it was chosen for.*

---

## 20.3 · The consequence model

| | **PINN twin** *(chosen)* | Analytical model | Plain neural net | Lookup table | No twin |
|---|---|---|---|---|---|
| Accuracy in-distribution | ●●● | ●●○ | ●●● | ●●○ | — |
| Accuracy out-of-distribution | ●●○ physics regularises | ●●● *if the model is right* | ●○○ | ○○○ | — |
| Runtime | ●●○ | ●●● | ●●○ | ●●● | ●●● |
| Explainability | ●○○ | **●●●** | ●○○ | ●●● | — |
| Failure behaviour | Wrong prediction, **no uncertainty attached** | Wrong where the model is wrong | Confidently wrong | Undefined off-table | Two gates lose their input |

**Why the PINN won.** It generalises where an analytical model would not, and the
physics term keeps it honest where data is thin.

**The strongest argument against it** — and worth taking seriously: an
**analytical** model would be far more explainable, and this is a vehicle whose
dynamics are well understood. **[INTERPRETATION]** For a safety case, an
analytical twin might be the better engineering choice; the learned one buys
generality the prototype has not yet needed.

**And a limitation shared by nothing else here:** the twin produces a **point
prediction with no uncertainty**, so a twin error is indistinguishable from a
proposer anomaly.

---

## 20.4 · The proposer

| | **Constrained PPO** *(chosen)* | Unconstrained RL + penalties | Classical MPC | Hand-written controller |
|---|---|---|---|---|
| Performance | ●●● | ●●● | ●●○ | ●●○ |
| Constraint legibility | **●●● budgets stay budgets** | **○○○ — see C-3** | ●●● | ●●● |
| Needs a good model | No | No | **Yes** | No |
| **Is it a real adversary for the governance?** | **●●●** | ●●● | ●●○ | **○○○** |

**Why constrained PPO won.** Two reasons, and the second is easy to miss.

**Constraints stay legible.** C-3 is the measured failure of the alternative:
`action_rate_weight` at 6.0 against a task reward capping at 2.0 made a jerk-limit
step cost **one part in ten thousand**, and the policy **stopped the vehicle**.

**It is genuinely untrusted.** A hand-written controller would be well-behaved —
and would therefore **never test the governance**. The whole thesis is *"an
untrusted proposer can be governed"*; a trustworthy proposer proves nothing.

**[INTERPRETATION]** This is why the CARLA plan leads with the *transferred*
policy rather than a retrained one. A proposer that transfers badly is not an
embarrassment — it is the case the architecture exists for.

---

## 20.5 · Detecting a lying sensor

| | **Median + residual** *(chosen)* | Kalman-fuse all channels | Mean of channels | Pairwise cross-check | Single-chain detectors |
|---|---|---|---|---|---|
| Survives one liar | **●●●** outvoted | ●●○ weighted in | **○○○** unbounded pull | ●●○ | ○○○ |
| **Identifies which** | **●●●** largest residual | ○○○ | ○○○ | ○○○ knows *something* is wrong | ○○○ |
| Survives two coordinated | **○○○ inverts** | ○○○ | ○○○ | ○○○ | ○○○ |
| Cost | ●●● `O(1)` | ●●○ | ●●● | ●●○ | ●●● |
| Measured result | **bias never reaches the estimator** | — | — | **0.99× on drift** | **all five silent** |

**Why the median won.** It **outvotes** rather than *averages*. A mean is moved by
an outlier without bound; a median of three ignores it entirely.

**And the residual has a property nothing else had:** `reading − median`
**cancels the truth term exactly**, so it measures *sensor disagreement* and
nothing else. Verified at **5e-17** across true positions 0.0 m and 7.5 m.

That invariance is what the cross-channel candidate lacked — it measured a
*quantity*, so a large legitimate manoeuvre moved it and it **reported the
manoeuvre as a fault**.

**The column that should worry you:** every option fails against two coordinated
liars, and the chosen one fails **worst** — it inverts and names the honest
channel.

---

## 20.6 · The safety-argument mechanism

| | **Executable invariants** *(chosen)* | Prose + review | Tests only | Formal verification |
|---|---|---|---|---|
| Can drift from code | **No** | **Yes — measured, 4 weeks** | Partly | No |
| Coverage | 10 invariants | Anything writable | What you thought to test | What you can formalise |
| Cost to add one | ●●○ | ●●● | ●●○ | ●○○ |
| Assessor legibility | ●●● | ●●● | ●●○ | ●●○ |

**Why executable invariants won.** The claim about *how each is enforced* is
itself tested — *"an invariant cannot be quietly downgraded and keep claiming a
guarantee."*

**The evidence against the alternative is first-hand:** SI-6 was documented as
`REVIEW`-only and **stayed wrong for four weeks after the code changed**.

---

## 20.7 · The architecture as a whole

| | **ASTRA** | Simplex | Runtime shield alone | Formal verification | Lockstep |
|---|---|---|---|---|---|
| Catches semantic failure | ●●○ | ●●○ | ●●○ | ●●● *where formalisable* | **○○○** |
| Catches structural failure | ○○○ | ○○○ | ○○○ | ○○○ | **●●●** |
| Graduated response | **●●●** four postures + capability axis | ●○○ binary | ○○○ | — | ●○○ |
| Keeps driving when uncertified | **●●●** | ●○○ | ●●○ | — | ●●● |
| Evidence per decision | **●●●** | ●●○ | ●●○ | ●●● proof | ●○○ |
| Maturity | **●○○ prototype** | ●●● deployed | ●●● | ●●○ | ●●● shipping |

**The row to read honestly is the last one.** Lockstep and simplex architectures
are **deployed in production vehicles today**. ASTRA is a prototype with zero
external validation.

**And the first two rows are why it is not a competitor to lockstep** — they are
orthogonal. A vehicle needs both.

---

## 20.8 · You should know this before moving on

**The four decisive arguments**

1. **UKF** — it produces the covariance L6 divides by
2. **Mondrian ICP** — the only guarantee that does not require trusting the model
3. **Constrained PPO** — a hand-written controller would never *test* the
   governance
4. **Median** — it outvotes rather than averages, and the residual cancels truth

**Questions you should be able to answer**

1. Which alternative to the UKF would delete an entire layer, and how?
2. Why would global conformal prediction flag neither highway nor urban driving?
3. Why is a *well-behaved* proposer the wrong choice for this project?
4. What property does `reading − median` have that cross-channel consistency
   lacked?
5. Why is ASTRA not an alternative to lockstep redundancy?

**Misconception to avoid**

> *"The chosen option won on every dimension."*
>
> None did. The UKF is slower than a complementary filter; the PINN twin is far
> less explainable than an analytical model; the median inverts under two liars
> where simpler schemes merely fail. Each won on **one decisive column**, and the
> others were paid.

---

**Next:** `21_BENEFITS/`.
