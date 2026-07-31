"""Persisted calibration corpora: what a conformal guarantee is made of.

Why a corpus is a first-class artefact rather than a list of numbers
---------------------------------------------------------------------
Conformal prediction promises coverage *relative to a calibration set*. The
promise is only as meaningful as the answer to "which set, produced how?", and
that answer has to survive into the evidence archive: a quantile with no
provenance is a threshold somebody chose.

So a corpus carries what it was made from -- the twin's weights digest, the
configuration hash, the generator's seed, the score definition -- alongside the
scores themselves. A reader years later can then tell whether the coverage
number in a report describes the system that produced it.

The exchangeability caveat, stated where it bites
---------------------------------------------------
The coverage guarantee assumes the calibration and test scores are
**exchangeable**. Scores harvested from a control loop are not: consecutive
ticks are autocorrelated, because the vehicle's state moves continuously and the
twin's prediction moves with it.

That is not a defect in this module -- it is the reason ASTRA has more than one
gate, and it is honesty boundary #4. What this module does about it is refuse to
hide it: :func:`coverage_report` measures coverage both ways, on shuffled splits
(exchangeable by construction, so they test the *quantile arithmetic*) and on a
sequential split (autocorrelated, so it tests what the live system actually
faces). A corpus that covers well shuffled and badly sequentially has a real
problem, and reporting only the first number would conceal it.

Why coverage is averaged over many splits
------------------------------------------
A single calibration/validation split is a **noisy estimator**. Measured by
Monte-Carlo on iid data, one split at 500 calibration points has a standard
deviation of about 1.5 percentage points around the nominal 95%. So a single
split landing at 92.6% is an unremarkable 1.6-sigma draw, and reporting it as
"below target" would be a false alarm -- while a single split landing at 96%
would be an equally meaningless pass.

:func:`coverage_report` therefore repeats the split many times and reports the
mean, together with the spread and the worst split seen. The mean is what the
target is applied to; the spread is printed so nobody mistakes a tight result
for a loose one.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

from astra.kernel.enums import ContextClass, LayerId
from astra.kernel.errors import ContractViolationError
from astra.layers.l3_trust.quantile import conformal_quantile

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from astra.layers.l3_trust.mondrian import MondrianCalibration

__all__ = [
    "CORPUS_SCHEMA_VERSION",
    "CalibrationCorpus",
    "ClassCoverage",
    "coverage_report",
]

CORPUS_SCHEMA_VERSION = 1
"""Schema version of the persisted corpus. A corpus from another version is refused."""

SCORE_DEFINITION = "euclidean_departure_over_sqrt_fast_covariance_lateral_acceleration"
"""How the scores were computed, recorded so a corpus cannot be silently reused
under a different definition. A calibration set built from one score definition
says nothing about a gate that computes a different one."""


@dataclass(frozen=True, slots=True)
class CalibrationCorpus:
    """Non-conformity scores per context class, with the provenance to defend them.

    Attributes:
        scores: The scores, keyed by context class.
        twin_weights_digest: Which twin produced the predictions the scores were
            measured against.
        config_hash: The operating point the generating run used.
        seed: The generator's random seed, so the corpus is reproducible.
        score_definition: How a score was computed.
        schema_version: The corpus format version.
    """

    scores: Mapping[ContextClass, tuple[float, ...]]
    twin_weights_digest: str
    config_hash: str
    seed: int
    score_definition: str = SCORE_DEFINITION
    schema_version: int = CORPUS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate the corpus.

        Raises:
            ContractViolationError: If provenance is missing, or any score is
                non-finite or negative. A score is a normalised distance; a
                negative one means the normalisation was wrong, not that the
                proposal was unusually close.
        """
        if not self.twin_weights_digest or not self.config_hash:
            message = "a calibration corpus must record the twin digest and configuration hash"
            raise ContractViolationError(message, layer=LayerId.L3_CONFORMAL_TRUST)
        for context, values in self.scores.items():
            for index, score in enumerate(values):
                if not (score >= 0.0) or score == float("inf"):
                    message = (
                        f"{context.value} score at index {index} is {score!r}; scores are "
                        f"normalised distances and must be finite and non-negative"
                    )
                    raise ContractViolationError(
                        message,
                        layer=LayerId.L3_CONFORMAL_TRUST,
                        context={"context_class": context.value, "index": index},
                    )

    @property
    def calibrated_classes(self) -> tuple[ContextClass, ...]:
        """Return the classes carrying at least one score, in declaration order."""
        return tuple(context for context in ContextClass if self.scores.get(context))

    def sample_count(self, context: ContextClass) -> int:
        """Return how many scores a class carries.

        Args:
            context: The class to count.

        Returns:
            The number of scores, zero if the class is absent.
        """
        return len(self.scores.get(context, ()))

    def seed_into(self, calibration: MondrianCalibration) -> None:
        """Load this corpus into a Mondrian calibration.

        Args:
            calibration: The calibration to seed.
        """
        for context, values in self.scores.items():
            if values:
                calibration.seed(context, values)

    def to_payload(self) -> dict[str, object]:
        """Render the corpus as a JSON-serialisable mapping.

        Returns:
            The payload, with classes in declaration order so two corpora of the
            same content serialise identically.
        """
        return {
            "schema_version": self.schema_version,
            "score_definition": self.score_definition,
            "twin_weights_digest": self.twin_weights_digest,
            "config_hash": self.config_hash,
            "seed": self.seed,
            "scores": {
                context.value: list(self.scores[context])
                for context in ContextClass
                if context in self.scores
            },
        }

    def write(self, path: Path) -> None:
        """Persist the corpus to a JSON file.

        Args:
            path: Where to write it. Parent directories are created.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_payload(), indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: Path) -> CalibrationCorpus:
        """Load a corpus from a JSON file.

        Args:
            path: The file to read.

        Returns:
            The corpus.

        Raises:
            ContractViolationError: If the file is malformed or was written by
                an unsupported schema version, or under a different score
                definition.
        """
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = int(payload.get("schema_version", -1))
        if version != CORPUS_SCHEMA_VERSION:
            message = (
                f"calibration corpus at {path} declares schema version {version}, "
                f"this build reads version {CORPUS_SCHEMA_VERSION}"
            )
            raise ContractViolationError(message, layer=LayerId.L3_CONFORMAL_TRUST)
        definition = str(payload.get("score_definition", ""))
        if definition != SCORE_DEFINITION:
            message = (
                f"calibration corpus at {path} was built under score definition "
                f"{definition!r}, but this build computes {SCORE_DEFINITION!r}; a "
                f"quantile from one definition says nothing about the other"
            )
            raise ContractViolationError(message, layer=LayerId.L3_CONFORMAL_TRUST)
        return cls(
            scores={
                ContextClass(name): tuple(float(value) for value in values)
                for name, values in payload["scores"].items()
            },
            twin_weights_digest=str(payload["twin_weights_digest"]),
            config_hash=str(payload["config_hash"]),
            seed=int(payload["seed"]),
        )


@dataclass(frozen=True, slots=True)
class ClassCoverage:
    """Measured empirical coverage for one context class.

    Attributes:
        context: The class measured.
        calibration_count: How many scores fitted each quantile.
        validation_count: How many held-out scores each was tested against.
        splits: How many random splits the mean was taken over.
        quantile: The median conformal threshold across the splits.
        shuffled_coverage: **Mean** coverage over the shuffled splits.
            Exchangeable by construction, so this measures whether the quantile
            arithmetic is right. This is the figure the target applies to.
        shuffled_spread: Standard deviation of coverage across those splits.
            Printed so a mean is never read without knowing how noisy it is.
        worst_split: The lowest coverage any single split produced. A mean that
            passes with a very low worst split is a different situation from one
            that passes tightly.
        sequential_coverage: Coverage on the single chronological split.
            Autocorrelated, so this is what a live run actually experiences and
            the conformal guarantee does **not** cover it.
        target: The nominal coverage ``1 - epsilon``.
    """

    context: ContextClass
    calibration_count: int
    validation_count: int
    splits: int
    quantile: float
    shuffled_coverage: float
    shuffled_spread: float
    worst_split: float
    sequential_coverage: float
    target: float

    @property
    def meets_target(self) -> bool:
        """Return whether the mean shuffled coverage reaches the target.

        The shuffled figure is the one held to the nominal target, because it is
        the only one the conformal guarantee actually promises: the guarantee is
        conditional on exchangeability, which the sequential split violates by
        construction.

        Returns:
            ``True`` if mean shuffled coverage is at or above the target.
        """
        return self.shuffled_coverage >= self.target


def _coverage(threshold: float, held_out: Sequence[float]) -> float:
    """Return the fraction of held-out scores at or below a threshold.

    Args:
        threshold: The conformal quantile.
        held_out: The validation scores.

    Returns:
        The empirical coverage, or ``0.0`` if there is nothing to measure.
    """
    if not held_out:
        return 0.0
    covered = sum(1 for score in held_out if score <= threshold)
    return covered / len(held_out)


def coverage_report(
    corpus: CalibrationCorpus,
    *,
    epsilon: float,
    splits: int = 200,
    seed: int = 0,
) -> tuple[ClassCoverage, ...]:
    """Measure per-class empirical coverage, averaged over many random splits.

    For each split the scores are shuffled, halved, the conformal quantile is
    fitted on the first half, and the fraction of the second half at or below it
    is recorded. The mean of those fractions is the reported coverage.

    Args:
        corpus: The corpus to measure.
        epsilon: The conformal significance level. The nominal target is
            ``1 - epsilon``.
        splits: How many random splits to average over. One split has a standard
            deviation of roughly 1.5 percentage points at 500 calibration
            points, which is wide enough to produce both false alarms and false
            passes, so the default is generous.
        seed: Seed for the split permutations, so a report is reproducible.

    Returns:
        One :class:`ClassCoverage` per calibrated class, in declaration order.
    """
    results: list[ClassCoverage] = []
    for context in corpus.calibrated_classes:
        values = list(corpus.scores[context])
        midpoint = len(values) // 2
        if midpoint == 0:
            continue

        # Seeded per class so that adding a class cannot change another's
        # numbers -- a report whose figures move when an unrelated class is
        # added is a report nobody can diff.
        # Not a security control: this shuffles a calibration set to estimate
        # coverage. Seeded per class so that adding a class cannot move another
        # class's figures -- a report whose numbers shift when an unrelated
        # class appears is a report nobody can diff.
        shuffler = random.Random(f"{seed}:{context.value}")  # noqa: S311
        coverages: list[float] = []
        thresholds: list[float] = []
        for _ in range(max(1, splits)):
            shuffler.shuffle(values)
            threshold = conformal_quantile(values[:midpoint], epsilon)
            thresholds.append(threshold)
            coverages.append(_coverage(threshold, values[midpoint:]))

        sequential = list(corpus.scores[context])
        results.append(
            ClassCoverage(
                context=context,
                calibration_count=midpoint,
                validation_count=len(values) - midpoint,
                splits=len(coverages),
                quantile=statistics.median(thresholds),
                shuffled_coverage=statistics.fmean(coverages),
                shuffled_spread=statistics.pstdev(coverages) if len(coverages) > 1 else 0.0,
                worst_split=min(coverages),
                sequential_coverage=_coverage(
                    conformal_quantile(sequential[:midpoint], epsilon), sequential[midpoint:]
                ),
                target=1.0 - epsilon,
            )
        )
    return tuple(results)
