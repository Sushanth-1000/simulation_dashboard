"""Are the live non-conformity scores exchangeable with the corpus that judges them?

The assumption the whole statistical gate rests on
----------------------------------------------------
Inductive conformal prediction gives a distribution-free coverage guarantee, and
it buys that guarantee with **exactly one** assumption: the calibration scores
and the test score are *exchangeable* — drawn from the same distribution, in any
order. Break it and the quantile is a number computed from the wrong sample. The
gate still emits verdicts; they just do not mean what the theory says.

OD-8 is that assumption already violated, in-house, on synthetic data, before
any external dataset is involved. Measured 6 August (E-41): the running scores
sat at **1.156**, *below the corpus minimum of 1.158*, with the whole
``HIGHWAY_CLEAR`` distribution spanning 1.158-1.189 over 1,000 samples. Not a
tail-probability disagreement — **no overlap at all.**

Why it is being re-measured
-----------------------------
Two changes on 15 August moved everything the score is built from:

- **ADR-0032** corrected the innovation covariance, which changed the Kalman
  gain and therefore the estimate the score's ``sigma`` is read from.
- **ADR-0033** made redundancy the driven path, which changed the estimate
  itself — the clean run's lane deviation improved six-fold.

The corpus was regenerated through both. So the question is open again in a way
it has not been since August: **does the live loop now sit inside the
distribution it is judged against?**

What this does *not* establish
--------------------------------
Exchangeability holding here would be necessary, not sufficient. The corpus and
the live loop share a plant, a twin and a policy, so agreement between them is
agreement between two things this project wrote — the ``[M-syn]`` boundary that
the whole credibility matrix turns on. A pass says the machinery is
self-consistent. It says nothing about coverage on real driving, which is what
Phase 9's CARLA drives exist for.

It also cannot be settled by the veto rate. A gate whose scores sit below the
corpus minimum vetoes almost nothing and *looks* healthy, which is precisely how
OD-8 stayed invisible: **0.089% was the mismatch, not discrimination.**
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from astra.layers.l3_trust.corpus import CalibrationCorpus
from astra.layers.l4_proposer.learned import LearnedPolicy
from astra.layers.l6_statistical_gate.gate import CONTROL_DIMENSION, non_conformity_score
from training.closed_loop import CORPUS, drive_closed_loop

if TYPE_CHECKING:
    from collections.abc import Sequence

    from astra.kernel.enums import ContextClass

__all__ = ["Comparison", "compare", "render"]

_DEFAULT_TICKS: Final = 1000
_DEFAULT_SEED: Final = 20260731
_DEFAULT_POLICY: Final = Path("var/policy/synthetic.pt")
_DEFAULT_OUTPUT: Final = Path("var/exchangeability")

_MINIMUM_LIVE_SAMPLES: Final = 30
"""Below this a containment fraction is reported as thin rather than as a
number. The first run of this benchmark printed **100% inside** for a context
with **one** live sample, beside a genuine 0% from 999 -- and the two sat in the
same column looking equally weighed. A fraction from n=1 is not a weaker
measurement, it is a different kind of thing, and the honest rendering says so
rather than letting a reader average them."""


@dataclass(frozen=True, slots=True)
class Comparison:
    """One context class's live scores against its calibration scores.

    Attributes:
        context: The class both samples belong to.
        corpus_count: How many calibration scores back the quantile.
        corpus_low: The corpus minimum.
        corpus_high: The corpus maximum.
        live_count: How many live scores were observed.
        live_low: The live minimum.
        live_median: The live median.
        live_high: The live maximum.
        inside: Fraction of live scores within the corpus support.
        overlaps: Whether the two ranges intersect at all.
    """

    context: str
    corpus_count: int
    corpus_low: float
    corpus_high: float
    live_count: int
    live_low: float
    live_median: float
    live_high: float
    inside: float
    overlaps: bool


def compare(*, ticks: int, seed: int, policy_path: Path) -> list[Comparison]:
    """Drive the loop and compare its scores against the corpus, per context.

    The score is recomputed from the record rather than read from a gate
    evidence field, using the **same public function the gate calls**. A
    reimplementation would measure the reimplementation; this measures the gate's
    arithmetic against the gate's corpus.

    Args:
        ticks: How long to drive.
        seed: The plant seed.
        policy_path: The trained proposer.

    Returns:
        One comparison per context class that both samples contain.
    """
    corpus = CalibrationCorpus.read(CORPUS)
    live: dict[ContextClass, list[float]] = {}

    def observe(sample: object) -> None:
        record = sample.record  # type: ignore[attr-defined]
        proposal, prediction, state, trust = (
            record.proposal,
            record.prediction,
            record.fast_state,
            record.trust,
        )
        if proposal is None or prediction is None or state is None or trust is None:
            return
        score, _, _ = non_conformity_score(
            proposed=proposal.command.values,
            predicted=prediction.command.values,
            variance=state.variance_of(CONTROL_DIMENSION),
        )
        live.setdefault(trust.context_class, []).append(score)

    drive_closed_loop(
        policy=LearnedPolicy.load(policy_path), ticks=ticks, seed=seed, observer=observe
    )

    comparisons: list[Comparison] = []
    for context, calibration in corpus.scores.items():
        observed = live.get(context)
        if not observed or not calibration:
            continue
        low, high = min(calibration), max(calibration)
        within = sum(1 for score in observed if low <= score <= high)
        comparisons.append(
            Comparison(
                context=context.value,
                corpus_count=len(calibration),
                corpus_low=low,
                corpus_high=high,
                live_count=len(observed),
                live_low=min(observed),
                live_median=statistics.median(observed),
                live_high=max(observed),
                inside=within / len(observed),
                overlaps=not (max(observed) < low or min(observed) > high),
            )
        )
    return comparisons


def render(comparisons: Sequence[Comparison]) -> list[str]:
    """Return the comparison table and the verdict it supports.

    Args:
        comparisons: One entry per context class.

    Returns:
        Printable lines.
    """
    lines = [
        "",
        "Exchangeability -- do the live scores sit inside the corpus that judges them?",
        "=" * 88,
        f"{'context':<18}{'corpus range':<24}{'live range':<24}{'median':<10}{'inside'}",
        "-" * 88,
    ]
    for entry in comparisons:
        corpus_range = f"{entry.corpus_low:.4f} - {entry.corpus_high:.4f}"
        live_range = f"{entry.live_low:.4f} - {entry.live_high:.4f}"
        thin = entry.live_count < _MINIMUM_LIVE_SAMPLES
        inside = f"n={entry.live_count}" if thin else f"{entry.inside:.1%}"
        flag = "  <-- too few to judge" if thin else ("" if entry.overlaps else "  <-- NO OVERLAP")
        lines.append(
            f"{entry.context:<18}{corpus_range:<24}{live_range:<24}"
            f"{entry.live_median:<10.4f}{inside:<8}{flag}"
        )
    lines.append("-" * 88)

    judged = [entry for entry in comparisons if entry.live_count >= _MINIMUM_LIVE_SAMPLES]
    disjoint = [entry for entry in judged if not entry.overlaps]
    if not judged:
        lines.extend(["", "No context produced enough live samples to judge."])
        return lines
    if disjoint:
        lines.extend(
            [
                "",
                f"OD-8 STANDS. {len(disjoint)} context(s) have no overlap at all -- the live",
                "  loop is judged against a distribution it does not belong to, so the",
                "  conformal guarantee does not hold and the veto rate measures the",
                "  mismatch rather than the gate's discrimination.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Every context overlaps. Necessary, and NOT sufficient: the corpus and the",
                "  live loop share a plant, a twin and a policy, so this is agreement",
                "  between two things this project wrote. It says the machinery is",
                "  self-consistent; it says nothing about coverage on real driving.",
            ]
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments, or ``None`` for ``sys.argv``.

    Returns:
        Zero always. A violated assumption is a finding, not a build failure.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticks", "-n", type=int, default=_DEFAULT_TICKS)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument("--output", "-o", type=Path, default=_DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)

    comparisons = compare(ticks=arguments.ticks, seed=arguments.seed, policy_path=arguments.policy)
    for line in render(comparisons):
        print(line)

    arguments.output.mkdir(parents=True, exist_ok=True)
    (arguments.output / "exchangeability.json").write_text(
        json.dumps(
            {
                "ticks": arguments.ticks,
                "seed": arguments.seed,
                "contexts": [asdict(entry) for entry in comparisons],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
