"""Boundary guards: the single place where "this value is impossible" is decided.

Why guards are functions rather than assertions
-----------------------------------------------
``assert`` is removed by ``python -O``. Any safety check written as an assertion
is a check that disappears in exactly the deployment configuration where it
matters most. Every guard here is an ordinary ``if`` that raises a typed
:class:`~astra.kernel.errors.ContractViolationError` subclass, so the behaviour
is identical in every interpreter mode.

Where guards run, and where they must not
-----------------------------------------
Guards run at *boundaries*: when a value enters the system from a sensor, a
configuration file, a calibration profile or an adapter. They do not run
between internal layers on the hot path. Re-validating a value that a frozen
record already validated at construction buys nothing and spends the tick
budget; the type system carries the guarantee from there.

The one deliberate exception is :func:`require_finite`. NaN is checked more
often than the rest because it is the only value that defeats a comparison
rather than failing it: ``nan > threshold`` is ``False``, so a NaN
non-conformity score turns a VETO into a PASS. That is a fail-*open* mode, and
it is the specific reason this function exists as its own error class.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

from astra.kernel.errors import (
    DimensionMismatchError,
    NonFiniteValueError,
    RangeViolationError,
)
from astra.kernel.units import Probability

if TYPE_CHECKING:
    from astra.kernel.enums import LayerId

__all__ = [
    "require_dimension",
    "require_finite",
    "require_non_decreasing",
    "require_non_negative",
    "require_positive",
    "require_probability",
    "require_range",
]


def require_finite(value: float, *, name: str, layer: LayerId | None = None) -> float:
    """Reject NaN and infinity.

    Args:
        value: The value to check.
        name: Field name, used verbatim in the error message and audit record.
        layer: The layer performing the check, when known.

    Returns:
        The value, unchanged, so the guard can be used inline.

    Raises:
        NonFiniteValueError: If the value is NaN or infinite.
    """
    if not math.isfinite(value):
        message = f"{name} must be finite, got {value!r}"
        raise NonFiniteValueError(message, layer=layer, context={"field": name})
    return value


def require_range(
    value: float,
    *,
    minimum: float,
    maximum: float,
    name: str,
    layer: LayerId | None = None,
) -> float:
    """Require a finite value within an inclusive interval.

    Args:
        value: The value to check.
        minimum: Inclusive lower bound.
        maximum: Inclusive upper bound.
        name: Field name for diagnostics.
        layer: The layer performing the check, when known.

    Returns:
        The value, unchanged.

    Raises:
        NonFiniteValueError: If the value is NaN or infinite.
        RangeViolationError: If the value lies outside the interval.
    """
    require_finite(value, name=name, layer=layer)
    if not minimum <= value <= maximum:
        message = f"{name} must lie in [{minimum}, {maximum}], got {value!r}"
        raise RangeViolationError(
            message,
            layer=layer,
            context={"field": name, "value": value, "minimum": minimum, "maximum": maximum},
        )
    return value


def require_probability(value: float, *, name: str, layer: LayerId | None = None) -> Probability:
    """Require a value in the closed unit interval.

    Used for the Trust Index, conformal coverage levels, the Calibration
    Divergence Index, per-profile validation fractions and every normalised
    component of the Runtime Context Signature.

    Args:
        value: The value to check.
        name: Field name for diagnostics.
        layer: The layer performing the check, when known.

    Returns:
        The value as a :data:`~astra.kernel.units.Probability`.

    Raises:
        NonFiniteValueError: If the value is NaN or infinite.
        RangeViolationError: If the value lies outside ``[0, 1]``.
    """
    return Probability(require_range(value, minimum=0.0, maximum=1.0, name=name, layer=layer))


def require_non_negative(value: float, *, name: str, layer: LayerId | None = None) -> float:
    """Require a finite value greater than or equal to zero.

    Args:
        value: The value to check.
        name: Field name for diagnostics.
        layer: The layer performing the check, when known.

    Returns:
        The value, unchanged.

    Raises:
        NonFiniteValueError: If the value is NaN or infinite.
        RangeViolationError: If the value is negative.
    """
    require_finite(value, name=name, layer=layer)
    if value < 0.0:
        message = f"{name} must be non-negative, got {value!r}"
        raise RangeViolationError(message, layer=layer, context={"field": name, "value": value})
    return value


def require_positive(value: float, *, name: str, layer: LayerId | None = None) -> float:
    """Require a finite value strictly greater than zero.

    Distinct from :func:`require_non_negative` because the difference matters:
    a zero variance in the ICP normalisation term ``sigma(x) = sqrt(P_f[dim])``
    produces a division by zero, so that field needs strict positivity while a
    distance or a counter does not.

    Args:
        value: The value to check.
        name: Field name for diagnostics.
        layer: The layer performing the check, when known.

    Returns:
        The value, unchanged.

    Raises:
        NonFiniteValueError: If the value is NaN or infinite.
        RangeViolationError: If the value is zero or negative.
    """
    require_finite(value, name=name, layer=layer)
    if value <= 0.0:
        message = f"{name} must be strictly positive, got {value!r}"
        raise RangeViolationError(message, layer=layer, context={"field": name, "value": value})
    return value


def require_dimension(
    values: Sequence[float],
    *,
    expected: int,
    name: str,
    layer: LayerId | None = None,
) -> tuple[float, ...]:
    """Require a sequence of exactly the expected length, and materialise it.

    Returning a tuple is deliberate: it both fixes the length that was checked
    and makes the result immutable, so a caller cannot validate a list and then
    mutate it before use.

    Args:
        values: The sequence to check.
        expected: The required length, normally a constant from
            :mod:`astra.kernel.constants`.
        name: Field name for diagnostics.
        layer: The layer performing the check, when known.

    Returns:
        The values as an immutable tuple.

    Raises:
        DimensionMismatchError: If the length differs from ``expected``.
    """
    materialised = tuple(values)
    if len(materialised) != expected:
        message = f"{name} must have {expected} elements, got {len(materialised)}"
        raise DimensionMismatchError(
            message,
            layer=layer,
            context={"field": name, "expected": expected, "actual": len(materialised)},
        )
    return materialised


def require_non_decreasing(
    values: Sequence[float],
    *,
    name: str,
    layer: LayerId | None = None,
) -> tuple[float, ...]:
    """Require a monotonically non-decreasing sequence.

    This is the quantile-monotonicity sanity bound the architecture requires
    Core-B to apply to any calibration table before activation. A quantile
    table that is not monotonic is either corrupt or adversarial: a
    non-monotonic table can make a *higher* non-conformity score map to a
    *lower* rejection threshold, which is the shape a calibration-poisoning
    attack would take.

    Args:
        values: The sequence to check.
        name: Field name for diagnostics.
        layer: The layer performing the check, when known.

    Returns:
        The values as an immutable tuple.

    Raises:
        NonFiniteValueError: If any element is NaN or infinite.
        RangeViolationError: If any element is smaller than its predecessor.
    """
    materialised = tuple(values)
    for index, value in enumerate(materialised):
        require_finite(value, name=f"{name}[{index}]", layer=layer)
    for index in range(1, len(materialised)):
        if materialised[index] < materialised[index - 1]:
            message = (
                f"{name} must be non-decreasing, but element {index} "
                f"({materialised[index]!r}) is below element {index - 1} "
                f"({materialised[index - 1]!r})"
            )
            raise RangeViolationError(
                message,
                layer=layer,
                context={"field": name, "index": index},
            )
    return materialised
