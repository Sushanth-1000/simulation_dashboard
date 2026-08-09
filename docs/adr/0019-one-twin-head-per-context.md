# ADR-0019 — One twin output head per context, instead of a consolidation penalty

**Status:** Accepted
**Date:** 6 August 2026
**Supersedes:** [ADR-0018](0018-ewc-anchors-on-context-not-on-every-update.md),
whose anchoring rule this removes the need for. ADR-0018's *findings* stand and
are the reason this decision exists; its *mechanism* is deleted.

## Context

ADR-0018 repaired elastic weight consolidation in the twin: the anchor had been
re-taken after every buffer flush, so the penalty resisted the last fifty
samples' movement and permitted unlimited total drift. With the anchor held
across a context, the response became monotone across six orders of magnitude
instead of a one-decade window with a cliff.

That fix was real, and it was not enough. Measuring the repaired mechanism
against what a consolidation penalty actually *claims* — that it is **selective**,
protecting the old context more than it blocks the new — gave this:

| λ | forgetting | fraction of the new context learned | forgetting ÷ learning |
|---|---|---|---|
| 0 | 0.0390 | 21.2 % | 0.00184 |
| 10² | 0.0334 | 18.2 % | 0.00184 |
| 10³ | 0.0117 | 6.3 % | 0.00186 |
| 10⁴ | 0.0032 | 1.7 % | 0.00186 |
| 10⁵ | 0.0018 | 0.9 % | 0.00194 |

The last column is constant. Every unit of retention was bought with a
proportional unit of plasticity, at every strength tested. The penalty was a
speed dial, not a consolidator, and it bought nothing that lowering the learning
rate would not have bought equally.

**This could not have been otherwise, and that is the important part.** EWC
protects an old task by holding the parameters *that task depends on* while
leaving the rest free, which requires the two tasks to use partially disjoint
subspaces. FB2 adapts a single 16→2 linear readout, and both contexts use all of
it. There was no disjointness to exploit, so no setting of λ could have produced
selectivity. RK-5 anticipated the possibility in as many words: *EWC may fail to
prevent catastrophic forgetting.*

## Decision

**`TwinNetwork` holds one output head per
:class:`~astra.kernel.enums.ContextClass` over a shared trunk.** FB2 adapts the
head for the context the outcome was observed in. `ewc_lambda`,
`fisher_sample_count`, the Fisher estimation and the elastic penalty are deleted.

Three rules make it work:

- **The trunk is frozen during adaptation**, as it already was. Moving it would
  silently re-specify the features every *other* head was fitted against, and
  reintroduce cross-context interference through the back door.
- **`UNCLASSIFIED` is never adapted.** Its head is the pristine offline-trained
  twin, and it is what answers when the context is unknown. A twin that rewrote
  itself while it could not tell where it was would be the failure mode the whole
  architecture exists to prevent.
- **A context change discards the partial buffer.** An update spanning a
  boundary teaches one head the average of a highway and a rainstorm, which is a
  worse answer than either and belongs to neither.

`predict` also takes the context, and the tick loop now passes it.

## The second reason, which would justify this on its own

The non-conformity score is

    alpha = |pi_prop - pi_hat| / sigma(x)

compared against a **per-context** conformal quantile. But `pi_hat` came from a
**context-blind** twin. L3's Mondrian calibration, L6's quantile table and L9's
seed profiles are all conditioned on `ContextClass`; L5 was the only component in
the chain that was not, so the score's two operands were conditioned on different
partitions. Per-context heads make them agree. This is a correctness fix that
would be worth making even if forgetting were not a problem, and it is the reason
this ADR is not merely damage control for ADR-0018.

## Options considered

| Option | Benefit | Drawback | |
|---|---|---|---|
| **A. One head per context** | Forgetting is impossible rather than discouraged, so the test can assert *exact* equality instead of a tolerance. Deletes a safety-relevant tuning number nobody could set correctly. Fixes the score's conditioning mismatch. 5 heads × 34 parameters | No transfer between contexts — learning rain teaches nothing about urban. Needs an `UNCLASSIFIED` rule | **chosen** |
| B. Keep the mechanism; rename `ewc_lambda` to what it is, an adaptation rate limiter | Cheapest, and honest about the measurement | Abandons forgetting entirely. FB2 could still destroy the twin, just slowly, and "slowly" is not a safety property |
| C. Adapt the hidden trunk too, giving EWC disjoint subspaces to find | Would make the penalty theoretically capable of selectivity | Contradicts the twin's design — small, hot-path, output-only. Nothing guarantees disjointness actually appears; it would have to be measured after paying for it. Most expensive and least certain |
| D. Leave the strict xfail and move on | Zero cost now | Blocks FB2, FB3 and FB4, and an xfail nobody acts on decays into noise |

**On A's drawback.** Losing transfer between contexts is a real cost and it is
accepted deliberately: transfer is what *causes* interference. The trunk still
carries whatever is common to all contexts, because it is shared and frozen; what
the heads give up is the ability to generalise a *newly learned* context onto an
unvisited one, which is not a property any part of the safety argument relies on.

## Consequences

Good:

- `test_l5_forgetting.py` asserts `highway_after == highway_before` — exact, not
  approximate. An approximate assertion would leave room for a future change to
  reintroduce interference and still pass.
- Its control feeds the same rain through the *highway* head, reproducing the
  pre-ADR-0019 behaviour by mislabelling the context rather than by keeping dead
  code around. It still destroys the highway: 0.85 units of highway lost per unit
  of rain gained.
- Separation costs nothing in plasticity. The rain head sees exactly the gradients
  it would have seen as the only head, which is precisely what the penalty could
  not manage.
- Coverage rose from 97.90 % to 98.13 % — deleting the Fisher machinery removed
  more lines than the heads added.

Costs and follow-ups:

- **A defect this uncovered in shipping code.** `training/train_twin.py` fits the
  trunk and one head; the others would have kept their random initialisation, so
  a twin loaded from such a checkpoint would predict noise in every context but
  one. `TwinNetwork.seed_heads_from` now broadcasts, and offline training calls
  it. Caught by the forgetting test refusing to agree that the offline twin knew
  the highway — which is the argument for writing the test first, made again.
- **Checkpoints written before this ADR still load.** `_with_heads` migrates a
  single `output` layer by copying it into every head. That is the semantically
  right migration and not just a convenience: the offline twin *is* the common
  starting point each context adapts away from.
- **FB2 is still slow and still unwired**, and neither is addressed here. 4,000
  samples — 200 s at 20 Hz — closes about a fifth of a large context change.
  Whether that is fit for purpose is measured next, by running FB2 in shadow.
- **`ContextClass` now has a fourth consumer.** Adding a class means adding a
  head, and a head with no training data is the offline twin until it gets some
  — which is the right default but should be stated when the enumeration grows.

## Compliance

- **SI-3** untouched: the twin's prediction feeds two gates; neither gains nor
  loses authority.
- **NFR5** untouched: `ContextClass` is a core enumeration, not a platform fact.
- **A-4** (no defaults for empirical safety parameters): improved. There is one
  fewer empirical parameter to default, because there is no longer a penalty
  strength to choose.
- **A-5** (byte-reproducible runs): head selection is driven by a classification
  already recorded in the evidence row, so a replayed run reads the same heads.
- **RK-5** is now answered rather than deferred: the risk was that EWC might fail
  to prevent forgetting. It did fail, it was measured failing, and it has been
  replaced by something that cannot.
