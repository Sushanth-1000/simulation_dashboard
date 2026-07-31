"""Unit tests for the L3 calibration corpus and its coverage report."""

from __future__ import annotations

import json
import math
import random
from typing import TYPE_CHECKING, cast

import pytest

from astra.kernel.enums import ContextClass
from astra.kernel.errors import ContractViolationError
from astra.layers.l3_trust.corpus import (
    CORPUS_SCHEMA_VERSION,
    CalibrationCorpus,
    ClassCoverage,
    coverage_report,
)
from astra.layers.l3_trust.mondrian import MondrianCalibration

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

DIGEST = "twin-weights-0123456789abcdef"
CONFIG_HASH = "config-fedcba9876543210"
SEED = 7
EPSILON = 0.05
TARGET = 0.95

# 600 iid scores split in half gives 300 calibration points, where the
# conformal rank is ceil(301 * 0.95) = 286 and the expected coverage is
# 286 / 301 = 0.9502 -- comfortably inside the 0.02 band asserted below.
CORPUS_SIZE = 600
SPLITS = 100


def _corpus(
    scores: Mapping[ContextClass, tuple[float, ...]],
    *,
    twin_weights_digest: str = DIGEST,
    config_hash: str = CONFIG_HASH,
    seed: int = SEED,
) -> CalibrationCorpus:
    return CalibrationCorpus(
        scores=scores,
        twin_weights_digest=twin_weights_digest,
        config_hash=config_hash,
        seed=seed,
    )


def _uniform(count: int, *, seed: int) -> tuple[float, ...]:
    # A local generator: the module-level `random` state is shared with every
    # other test in the process and would make these numbers order-dependent.
    generator = random.Random(seed)
    return tuple(generator.random() for _ in range(count))


def _ramp(count: int) -> tuple[float, ...]:
    return tuple(float(value) / 10.0 for value in range(count))


class _RecordingCalibration:
    """Records every seed call, so a class the corpus skipped is observable."""

    def __init__(self) -> None:
        self.seeded: list[tuple[ContextClass, tuple[float, ...]]] = []

    def seed(self, context: ContextClass, scores: Sequence[float]) -> None:
        self.seeded.append((context, tuple(scores)))


# --------------------------------------------------------------------------- #
# Construction: provenance and admissible scores
# --------------------------------------------------------------------------- #


def test_a_corpus_without_a_twin_digest_is_refused() -> None:
    with pytest.raises(ContractViolationError):
        _corpus({ContextClass.HIGHWAY_CLEAR: (1.0,)}, twin_weights_digest="")


def test_a_corpus_without_a_configuration_hash_is_refused() -> None:
    with pytest.raises(ContractViolationError):
        _corpus({ContextClass.HIGHWAY_CLEAR: (1.0,)}, config_hash="")


def test_a_negative_score_is_refused() -> None:
    # A score is a normalised distance. A negative one means the normalisation
    # was wrong, not that the proposal was unusually close.
    with pytest.raises(ContractViolationError):
        _corpus({ContextClass.HIGHWAY_CLEAR: (1.0, -0.5, 2.0)})


def test_a_nan_score_is_refused() -> None:
    with pytest.raises(ContractViolationError):
        _corpus({ContextClass.URBAN_CLEAR: (1.0, math.nan)})


def test_an_infinite_score_is_refused() -> None:
    with pytest.raises(ContractViolationError):
        _corpus({ContextClass.URBAN_CLEAR: (math.inf,)})


def test_the_rejection_names_the_class_and_the_offending_index() -> None:
    with pytest.raises(ContractViolationError) as raised:
        _corpus({ContextClass.DEGRADED_SENSOR: (0.0, 1.0, -3.0)})

    assert raised.value.context["context_class"] == ContextClass.DEGRADED_SENSOR.value
    assert raised.value.context["index"] == 2


# --------------------------------------------------------------------------- #
# Reading the corpus back
# --------------------------------------------------------------------------- #


def test_calibrated_classes_are_ordered_by_declaration_not_by_insertion() -> None:
    # Insertion order is whatever the generating run happened to encounter
    # first; declaration order is a property of the enumeration, so two corpora
    # of the same content enumerate identically.
    corpus = _corpus(
        {
            ContextClass.DEGRADED_SENSOR: (1.0,),
            ContextClass.URBAN_CLEAR: (2.0,),
            ContextClass.HIGHWAY_CLEAR: (3.0,),
        }
    )

    assert corpus.calibrated_classes == (
        ContextClass.HIGHWAY_CLEAR,
        ContextClass.URBAN_CLEAR,
        ContextClass.DEGRADED_SENSOR,
    )


def test_a_class_carrying_no_scores_is_not_calibrated() -> None:
    corpus = _corpus(
        {
            ContextClass.HIGHWAY_CLEAR: (1.0,),
            ContextClass.RAIN_NIGHT: (),
        }
    )

    assert corpus.calibrated_classes == (ContextClass.HIGHWAY_CLEAR,)


def test_sample_count_is_zero_for_a_class_the_corpus_never_saw() -> None:
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: (1.0, 2.0)})

    assert corpus.sample_count(ContextClass.RAIN_NIGHT) == 0
    assert corpus.sample_count(ContextClass.UNCLASSIFIED) == 0


def test_sample_count_reports_how_many_scores_a_class_carries() -> None:
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _ramp(37)})

    assert corpus.sample_count(ContextClass.HIGHWAY_CLEAR) == 37


# --------------------------------------------------------------------------- #
# Seeding a Mondrian calibration
# --------------------------------------------------------------------------- #


def test_seed_into_loads_every_class_that_carries_scores() -> None:
    corpus = _corpus(
        {
            ContextClass.HIGHWAY_CLEAR: _ramp(30),
            ContextClass.URBAN_CLEAR: _ramp(12),
            ContextClass.DEGRADED_SENSOR: _ramp(5),
        }
    )
    calibration = MondrianCalibration(window=500)

    corpus.seed_into(calibration)

    assert calibration.sample_count(ContextClass.HIGHWAY_CLEAR) == 30
    assert calibration.sample_count(ContextClass.URBAN_CLEAR) == 12
    assert calibration.sample_count(ContextClass.DEGRADED_SENSOR) == 5
    assert calibration.scores(ContextClass.URBAN_CLEAR) == _ramp(12)


def test_seed_into_skips_a_class_with_no_scores_rather_than_seeding_nothing() -> None:
    corpus = _corpus(
        {
            ContextClass.HIGHWAY_CLEAR: (1.0, 2.0),
            ContextClass.RAIN_NIGHT: (),
            ContextClass.URBAN_CLEAR: (3.0,),
        }
    )
    recorder = _RecordingCalibration()

    corpus.seed_into(cast("MondrianCalibration", recorder))

    assert [context for context, _ in recorder.seeded] == [
        ContextClass.HIGHWAY_CLEAR,
        ContextClass.URBAN_CLEAR,
    ]


def test_an_uncalibrated_class_stays_uncalibrated_after_seeding() -> None:
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _ramp(30)})
    calibration = MondrianCalibration(window=500)

    corpus.seed_into(calibration)

    assert calibration.sample_count(ContextClass.RAIN_NIGHT) == 0


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def test_a_corpus_survives_a_write_and_read_round_trip(tmp_path: Path) -> None:
    corpus = _corpus(
        {
            ContextClass.HIGHWAY_CLEAR: _uniform(50, seed=1),
            ContextClass.URBAN_CLEAR: _uniform(20, seed=2),
        }
    )
    path = tmp_path / "nested" / "corpus.json"

    corpus.write(path)
    restored = CalibrationCorpus.read(path)

    assert restored.scores == corpus.scores
    assert restored.twin_weights_digest == corpus.twin_weights_digest
    assert restored.config_hash == corpus.config_hash
    assert restored.seed == corpus.seed
    assert restored.score_definition == corpus.score_definition
    assert restored.schema_version == CORPUS_SCHEMA_VERSION
    assert restored == corpus


def test_reading_a_corpus_from_another_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "corpus.json"
    CalibrationCorpus(
        scores={ContextClass.HIGHWAY_CLEAR: (1.0,)},
        twin_weights_digest=DIGEST,
        config_hash=CONFIG_HASH,
        seed=SEED,
        schema_version=CORPUS_SCHEMA_VERSION + 1,
    ).write(path)

    with pytest.raises(ContractViolationError):
        CalibrationCorpus.read(path)


def test_reading_a_corpus_built_under_another_score_definition_is_refused(
    tmp_path: Path,
) -> None:
    # This is the one that matters most: a quantile fitted to one score
    # definition says nothing about a gate that computes a different one, and
    # nothing about the file's shape would reveal the mismatch.
    path = tmp_path / "corpus.json"
    CalibrationCorpus(
        scores={ContextClass.HIGHWAY_CLEAR: (1.0, 2.0)},
        twin_weights_digest=DIGEST,
        config_hash=CONFIG_HASH,
        seed=SEED,
        score_definition="mahalanobis_departure_over_slow_covariance",
    ).write(path)

    with pytest.raises(ContractViolationError):
        CalibrationCorpus.read(path)


def test_the_payload_orders_classes_by_declaration(tmp_path: Path) -> None:
    del tmp_path
    corpus = _corpus(
        {
            ContextClass.DEGRADED_SENSOR: (1.0,),
            ContextClass.HIGHWAY_CLEAR: (2.0,),
            ContextClass.URBAN_CLEAR: (3.0,),
        }
    )

    payload = cast("dict[str, list[float]]", corpus.to_payload()["scores"])

    assert list(payload) == [
        ContextClass.HIGHWAY_CLEAR.value,
        ContextClass.URBAN_CLEAR.value,
        ContextClass.DEGRADED_SENSOR.value,
    ]


def test_two_corpora_of_the_same_content_serialise_byte_identically() -> None:
    scores = {
        ContextClass.HIGHWAY_CLEAR: _uniform(8, seed=3),
        ContextClass.URBAN_CLEAR: _uniform(4, seed=4),
        ContextClass.DEGRADED_SENSOR: _uniform(2, seed=5),
    }
    forward = _corpus(dict(scores))
    backward = _corpus({context: scores[context] for context in reversed(list(scores))})

    assert json.dumps(forward.to_payload()) == json.dumps(backward.to_payload())


# --------------------------------------------------------------------------- #
# coverage_report -- RK-2, the risk that a wrong quantile is silently invalid
# --------------------------------------------------------------------------- #


def test_the_report_carries_one_entry_per_calibrated_class_in_declaration_order() -> None:
    corpus = _corpus(
        {
            ContextClass.DEGRADED_SENSOR: _uniform(40, seed=1),
            ContextClass.HIGHWAY_CLEAR: _uniform(40, seed=2),
            ContextClass.URBAN_CLEAR: _uniform(40, seed=3),
        }
    )

    report = coverage_report(corpus, epsilon=EPSILON, splits=10, seed=0)

    assert [result.context for result in report] == [
        ContextClass.HIGHWAY_CLEAR,
        ContextClass.URBAN_CLEAR,
        ContextClass.DEGRADED_SENSOR,
    ]


@pytest.mark.parametrize("splits", [1, 3, 25])
def test_the_report_takes_the_number_of_splits_it_was_asked_for(splits: int) -> None:
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _uniform(60, seed=9)})

    (result,) = coverage_report(corpus, epsilon=EPSILON, splits=splits, seed=0)

    assert result.splits == splits


def test_the_split_counts_partition_the_class(tmp_path: Path) -> None:
    del tmp_path
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _uniform(61, seed=9)})

    (result,) = coverage_report(corpus, epsilon=EPSILON, splits=5, seed=0)

    assert result.calibration_count == 30
    assert result.validation_count == 31
    assert result.target == pytest.approx(TARGET)


def test_mean_shuffled_coverage_on_exchangeable_scores_reaches_the_nominal_level() -> None:
    # RK-2. On iid scores the splits are exchangeable by construction, so this
    # measures the quantile arithmetic itself: an implementation that dropped
    # the `+1` in ceil((n+1)(1-epsilon)) under-covers, and nothing else in the
    # pipeline would raise or fail while it did.
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _uniform(CORPUS_SIZE, seed=17)})

    (result,) = coverage_report(corpus, epsilon=EPSILON, splits=SPLITS, seed=0)

    assert result.shuffled_coverage == pytest.approx(TARGET, abs=0.02)
    assert result.meets_target


def test_the_spread_is_positive_over_many_splits_and_zero_over_one() -> None:
    # The mean is never to be read without it: one split at 300 calibration
    # points is a noisy enough estimator to produce both false alarms and
    # false passes.
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _uniform(CORPUS_SIZE, seed=17)})

    many = coverage_report(corpus, epsilon=EPSILON, splits=SPLITS, seed=0)[0]
    single = coverage_report(corpus, epsilon=EPSILON, splits=1, seed=0)[0]

    assert many.shuffled_spread > 0.0
    assert single.shuffled_spread == 0.0
    assert single.worst_split == single.shuffled_coverage


def test_the_worst_split_bounds_the_mean_from_below() -> None:
    corpus = _corpus(
        {
            ContextClass.HIGHWAY_CLEAR: _uniform(CORPUS_SIZE, seed=17),
            ContextClass.URBAN_CLEAR: _uniform(120, seed=18),
        }
    )

    for result in coverage_report(corpus, epsilon=EPSILON, splits=SPLITS, seed=0):
        assert 0.0 <= result.worst_split <= result.shuffled_coverage <= 1.0
        assert math.isfinite(result.quantile)


@pytest.mark.parametrize(
    ("shuffled", "expected"),
    [(0.96, True), (TARGET, True), (0.9499, False), (0.0, False)],
)
def test_meets_target_compares_the_shuffled_mean_against_the_nominal_level(
    shuffled: float, expected: bool
) -> None:
    # The shuffled figure, not the sequential one: the guarantee is conditional
    # on exchangeability, which a chronological split violates by construction.
    result = ClassCoverage(
        context=ContextClass.HIGHWAY_CLEAR,
        calibration_count=300,
        validation_count=300,
        splits=SPLITS,
        quantile=0.95,
        shuffled_coverage=shuffled,
        shuffled_spread=0.01,
        worst_split=0.9,
        sequential_coverage=0.5,
        target=TARGET,
    )

    assert result.meets_target is expected


def test_a_class_with_fewer_than_two_scores_is_skipped_rather_than_reported() -> None:
    # One score cannot be split, and a coverage figure computed from an empty
    # validation half would be a number with no content.
    corpus = _corpus(
        {
            ContextClass.HIGHWAY_CLEAR: (0.5,),
            ContextClass.URBAN_CLEAR: _uniform(40, seed=21),
        }
    )

    report = coverage_report(corpus, epsilon=EPSILON, splits=5, seed=0)

    assert [result.context for result in report] == [ContextClass.URBAN_CLEAR]


def test_the_same_corpus_and_seed_give_identical_figures() -> None:
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _uniform(200, seed=23)})

    assert coverage_report(corpus, epsilon=EPSILON, splits=20, seed=4) == coverage_report(
        corpus, epsilon=EPSILON, splits=20, seed=4
    )


def test_a_different_seed_generally_moves_the_figures() -> None:
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _uniform(200, seed=23)})

    first = coverage_report(corpus, epsilon=EPSILON, splits=20, seed=4)
    second = coverage_report(corpus, epsilon=EPSILON, splits=20, seed=5)

    assert first != second


def test_adding_a_class_does_not_move_another_class_figures() -> None:
    # The splits are seeded per class on purpose. A report whose numbers shift
    # when an unrelated class appears is a report nobody can diff between two
    # generating runs.
    shared = _uniform(120, seed=29)
    alone = _corpus({ContextClass.HIGHWAY_CLEAR: shared})
    accompanied = _corpus(
        {
            ContextClass.HIGHWAY_CLEAR: shared,
            ContextClass.URBAN_CLEAR: _uniform(80, seed=30),
        }
    )

    (only,) = coverage_report(alone, epsilon=EPSILON, splits=25, seed=6)
    highway, urban = coverage_report(accompanied, epsilon=EPSILON, splits=25, seed=6)

    assert highway == only
    assert urban.context is ContextClass.URBAN_CLEAR


def test_the_sequential_split_is_reported_separately_from_the_shuffled_mean() -> None:
    # Honesty boundary #4: consecutive ticks are autocorrelated, so the
    # chronological number is what a live run experiences and the conformal
    # guarantee does not cover it. Reporting only the shuffled figure would
    # conceal that.
    corpus = _corpus({ContextClass.HIGHWAY_CLEAR: _ramp(200)})

    (result,) = coverage_report(corpus, epsilon=EPSILON, splits=10, seed=0)

    # A monotone ramp is the worst case for a chronological split: every
    # held-out score is larger than every calibration score.
    assert result.sequential_coverage == 0.0
    assert result.shuffled_coverage > result.sequential_coverage
