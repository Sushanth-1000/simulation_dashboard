"""The replay tape format: what a recorded run consists of.

Design constraint that shapes everything here
----------------------------------------------
A replayed run must produce a **byte-identical** event stream to the run it
reproduces. That is not a nice-to-have; it is what makes a diff between two runs
meaningful, and a diff is the entire debugging technique the Demo Plan is
protecting.

Two consequences follow, and both are load-bearing:

1. **The tape contains no wall-clock reading.** Not a creation timestamp, not a
   "recorded at", nothing. Any such field would differ on every recording and
   make byte-comparison useless in exactly the artefact whose purpose is
   byte-comparison. Instants on the tape are timeline-tagged offsets, which are
   reproduced exactly.

2. **Serialisation is canonical.** Fixed separators, keys emitted in a fixed
   order, no incidental whitespace. Two tapes of the same inputs are the same
   bytes.

The payload problem, and the codec
-----------------------------------
Sensor metadata -- modality, acquisition instant, quality -- is architectural
and identical in every domain, so it serialises here. The payload is not: a
LiDAR return, a camera frame and a CAN word have nothing in common, and the
pipeline is deliberately generic over them (NFR5).

A tape therefore cannot serialise a payload without help. :class:`PayloadCodec`
is that help: the adapter that knows what a payload *is* supplies the pair of
functions that move it to and from JSON. The core stays domain-independent and
the tape stays complete -- which matters because L2 consumes payloads, so a tape
without them could not re-drive the filter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from astra.contracts.sensing import FusedSensorFrame, SensorSample
from astra.kernel.enums import SensorModality
from astra.kernel.errors import ContractViolationError, SchemaVersionError
from astra.kernel.identifiers import RunId, TickId
from astra.kernel.time import Instant, Timeline
from astra.kernel.validation import require_probability

if TYPE_CHECKING:
    from astra.contracts.audit import JsonValue

__all__ = [
    "TAPE_SCHEMA_VERSION",
    "IdentityPayloadCodec",
    "PayloadCodec",
    "TapeHeader",
    "decode_frame",
    "encode_frame",
]

TAPE_SCHEMA_VERSION: Final = 1
"""Schema version of the tape format. A tape from another version is refused.

Separate from the audit schema version because the two artefacts serve different
consumers and move on different schedules: an evidence archive must stay
readable for years, whereas a tape only has to outlive the investigation that
produced it.
"""


@runtime_checkable
class PayloadCodec[PayloadT](Protocol):
    """Moves a domain-specific sensor payload to and from JSON.

    Supplied by the adapter that owns the payload type. The codec must be a true
    round-trip -- ``decode(encode(x))`` must equal ``x`` for every payload the
    adapter produces -- because replay fidelity is exactly that property.
    """

    def encode(self, payload: PayloadT) -> JsonValue:
        """Render a payload as a JSON value.

        Args:
            payload: The payload to encode.

        Returns:
            A JSON-serialisable representation.
        """
        ...

    def decode(self, raw: JsonValue) -> PayloadT:
        """Reconstruct a payload from its JSON representation.

        Args:
            raw: A value previously produced by :meth:`encode`.

        Returns:
            The reconstructed payload.
        """
        ...


class IdentityPayloadCodec:
    """A codec for payloads that are already JSON values.

    Sufficient for tests, for synthetic scenarios, and for any adapter whose
    measurements are plain numbers or mappings. An adapter delivering binary
    frames supplies its own codec instead; the identity codec makes no attempt
    to guess.
    """

    __slots__ = ()

    def encode(self, payload: JsonValue) -> JsonValue:
        """Return the payload unchanged.

        Args:
            payload: A payload that is already a JSON value.

        Returns:
            The same value.
        """
        return payload

    def decode(self, raw: JsonValue) -> JsonValue:
        """Return the value unchanged.

        Args:
            raw: The encoded value.

        Returns:
            The same value.
        """
        return raw


@dataclass(frozen=True, slots=True)
class TapeHeader:
    """The first line of a tape: what run it reproduces, and on what timeline.

    Carries no wall-clock field, deliberately. See the module docstring.

    Attributes:
        run: The identity of the recorded run. Replay adopts it, so replayed
            records carry the identity of the run being reproduced rather than a
            fresh one -- which is what makes the two event streams comparable.
        timeline: The timeline every instant on the tape is measured against.
        config_hash: The configuration hash the recorded run ran under. Replay
            under a different operating point is still useful, but it is no
            longer a reproduction, and the header is what lets that be detected.
        schema_version: The tape format version.
    """

    run: RunId
    timeline: Timeline
    config_hash: str
    schema_version: int = TAPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate the header.

        Raises:
            ContractViolationError: If the configuration hash is empty.
            SchemaVersionError: If the schema version is not supported.
        """
        if not self.config_hash:
            message = "a replay tape must record the configuration hash of the run it reproduces"
            raise ContractViolationError(message)
        if self.schema_version != TAPE_SCHEMA_VERSION:
            message = (
                f"replay tape declares schema version {self.schema_version}, "
                f"this build reads version {TAPE_SCHEMA_VERSION}"
            )
            raise SchemaVersionError(message, context={"declared": self.schema_version})

    def to_payload(self) -> dict[str, JsonValue]:
        """Render the header as a canonical JSON mapping.

        Returns:
            The header payload, key order fixed.
        """
        return {
            "record_type": "header",
            "schema_version": self.schema_version,
            "run": self.run.value,
            "timeline": self.timeline.value,
            "config_hash": self.config_hash,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, JsonValue]) -> TapeHeader:
        """Reconstruct a header from a parsed tape line.

        Args:
            payload: The parsed JSON object.

        Returns:
            The header.

        Raises:
            ContractViolationError: If a required field is missing or malformed.
            SchemaVersionError: If the tape was written by another version.
        """
        try:
            return cls(
                run=RunId(str(payload["run"])),
                timeline=Timeline(str(payload["timeline"])),
                config_hash=str(payload["config_hash"]),
                schema_version=int(str(payload["schema_version"])),
            )
        except KeyError as error:
            message = f"replay tape header is missing the field {error.args[0]!r}"
            raise ContractViolationError(message, context={"field": error.args[0]}) from error
        except ValueError as error:
            message = f"replay tape header is malformed: {error}"
            raise ContractViolationError(message) from error


def encode_frame[PayloadT](
    frame: FusedSensorFrame[PayloadT], codec: PayloadCodec[PayloadT]
) -> dict[str, JsonValue]:
    """Render one fused frame as a canonical JSON mapping.

    Samples are emitted in :class:`~astra.kernel.enums.SensorModality`
    declaration order rather than in the frame's own tuple order. The frame does
    not guarantee an order, so recording whichever order fusion happened to
    produce would make two tapes of identical inputs differ -- defeating
    byte-comparison for no benefit.

    Args:
        frame: The frame to record.
        codec: The payload codec supplied by the adapter.

    Returns:
        The frame payload, key order fixed.
    """
    by_modality = {sample.modality: sample for sample in frame.samples}
    return {
        "record_type": "frame",
        "tick": frame.tick.value,
        "fused_at": frame.fused_at.nanoseconds,
        "samples": [
            {
                "modality": modality.value,
                "observed_at": by_modality[modality].observed_at.nanoseconds,
                "quality": float(by_modality[modality].quality),
                "payload": codec.encode(by_modality[modality].payload),
            }
            for modality in SensorModality
            if modality in by_modality
        ],
    }


def decode_frame[PayloadT](
    payload: dict[str, JsonValue], codec: PayloadCodec[PayloadT], timeline: Timeline
) -> FusedSensorFrame[PayloadT]:
    """Reconstruct a fused frame from a parsed tape line.

    Args:
        payload: The parsed JSON object.
        codec: The payload codec supplied by the adapter.
        timeline: The timeline from the tape header, applied to every instant.

    Returns:
        The reconstructed frame, equal to the one recorded.

    Raises:
        ContractViolationError: If a required field is missing or malformed.
    """
    try:
        raw_samples = payload["samples"]
        if not isinstance(raw_samples, list):
            message = "replay tape frame has a malformed sample list"
            raise ContractViolationError(message)
        samples = tuple(
            SensorSample(
                modality=SensorModality(str(entry["modality"])),
                observed_at=Instant(int(str(entry["observed_at"])), timeline),
                quality=require_probability(
                    float(str(entry["quality"])), name="recorded_sample.quality"
                ),
                payload=codec.decode(entry["payload"]),
            )
            for entry in raw_samples
            if isinstance(entry, dict)
        )
        return FusedSensorFrame.build(
            tick=TickId(int(str(payload["tick"]))),
            fused_at=Instant(int(str(payload["fused_at"])), timeline),
            samples=samples,
        )
    except KeyError as error:
        message = f"replay tape frame is missing the field {error.args[0]!r}"
        raise ContractViolationError(message, context={"field": error.args[0]}) from error
    except ValueError as error:
        message = f"replay tape frame is malformed: {error}"
        raise ContractViolationError(message) from error


def render_line(payload: dict[str, JsonValue]) -> str:
    """Serialise one tape record to its canonical single-line form.

    Args:
        payload: The record payload.

    Returns:
        A compact JSON document with no trailing newline. Fixed separators and
        no key sorting -- the payloads are built in a fixed order already -- so
        the output is byte-stable.
    """
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
