"""The interfaces each ASTRA layer implements.

Ports are ``typing.Protocol`` classes: structural, not nominal. A Phase 2 UKF
implementation satisfies ``StateEstimator`` by having the right methods, with
no inheritance and no import of this package at runtime. That keeps the
dependency arrow pointing inward -- implementations depend on the architecture,
never the reverse -- and makes a test double a five-line class rather than a
mocking-framework exercise.
"""
