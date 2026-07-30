"""Dependency-free primitives shared by every ASTRA component.

The kernel is the bottom of the dependency graph. It imports nothing from
``astra`` outside itself and nothing from the third-party ecosystem, which is
what allows an offline evidence-analysis tool or a certification script to
import ASTRA's vocabulary without installing the numerical or simulation stack.

Nothing that makes a decision belongs here. The kernel supplies the words the
decisions are expressed in: units, identifiers, time, error taxonomy,
validation guards, enumerations and architectural constants.
"""
