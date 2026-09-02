# Phase 5 - OD-8 Calibration -> H7 Monitor Placement -> Lying-Sensor Verification

Gated research stage opened **1 September 2026**, following the E17 audit.

## Why this phase exists

E17 established that fault observability is heterogeneous and that one fault-policy pair shows a
well-posed absorption point. It also established that the L6 statistical gate was miscalibrated
(OD-8): unreachable on P1/P3, permanently tripped on P2.

That made monitor **calibration**, not monitor **placement**, the binding constraint. H7 cannot be
run against a monitor that cannot operate. Phase 5 therefore fixes calibration first and treats
everything downstream as gated on it.

## Gates

    E18  OD-8 calibration      ->  must PASS before E19 starts
    E19  H7 monitor placement  ->  gated on E18
    E20  Lying sensor          ->  after E18, preferably after E19

A stage is not entered because it exists in the plan.

## Standing integrity rule, carried from E17

> A sweep result cannot be trusted unless the faulted arm is demonstrated to differ from the clean
> arm **at the delivered signal**.

Four measurement/audit defects were found during E17, three by self-audit. Every experiment here
runs the delivered-signal check before its results are accepted.

## Relationship to `research/`

`research/` holds the E17 audit history and stays authoritative for it. This directory holds Phase 5
only. Neither supersedes the other.

## Data management

Source and experiment configuration are version-controlled. Large raw artifacts are recorded by
location, generation command and experiment ID rather than committed by default -- see
`DATA_MANAGEMENT.md`. The repository carries a confidentiality and intended-patent notice, so
distribution decisions rest with the project owner.
