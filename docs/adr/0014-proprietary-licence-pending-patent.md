# ADR-0014: Proprietary licence while the patent filing is pending

- **Status:** Accepted
- **Date:** 2026-07-29
- **Phase:** 1 (Foundation)

## Context

One of the four source documents is a patent-oriented restatement of the architecture. Its existence
is the point: the work is intended to be the subject of a patent filing, and the Prototype & Demo
Plan gates external demonstrations on the filing's status.

Public disclosure before filing can prejudice patentability. Jurisdictions differ — some provide a
grace period after the inventor's own disclosure, others treat any public availability as
disqualifying prior art — and the project cannot rely on which regime will apply. A public
repository, a conference demo, a paper preprint or a package on PyPI are all disclosures.

The default in academic and open-source software is a permissive licence, and there are real reasons
to want one here: reviewability, collaboration, the ability to cite the implementation alongside the
paper. Those reasons do not go away. They are simply not available yet.

The relevant asymmetry: **relicensing open later is always possible; the reverse is not.** Code
released under Apache-2.0 cannot be recalled. Patent rights forfeited by disclosure cannot be
recovered.

## Decision

**Proprietary, all rights reserved, private repository, until the filing status is confirmed.**

`LICENSE` states that the software and its associated documentation, design records, calibration
schemas and test artefacts are confidential and proprietary; that the work is unpublished; that no
right to use, copy, modify, distribute, publicly perform or display, or create derivative works is
granted except under a separate signed agreement; and that receipt or possession conveys no right to
reproduce or disclose its contents or to manufacture, use or sell anything it describes. It carries
an explicit **PATENT NOTICE** stating that the architecture is the subject of an intended filing.

`NOTICE` carries the confidentiality statement. `README.md` opens with a do-not-distribute banner.

Two mechanical guards support the policy:

- **`"Private :: Do Not Upload"`** in `pyproject.toml`'s classifiers. PyPI rejects any distribution
  carrying that classifier, so an accidental `twine upload` fails rather than publishing a
  patent-pending architecture.
- **`detect-private-key`** in `.pre-commit-config.yaml`, running on every commit. A private,
  patent-pending repository must never grow a committed credential, and this is cheap insurance.

There is no `[project.urls]` entry pointing at a public package index; `Documentation` and `Source`
point at a repository URL that is expected to remain private.

**The standing operational rule until the filing is confirmed:** no external demonstration, no
publication, no public repository, NDA before any demo. This is assumption A-7, and it is the one
assumption in the register that engineering cannot resolve.

*This ADR records an engineering decision made to preserve an option. It is not legal advice, and it
must be confirmed with whoever handles the filing.*

## Alternatives considered

**Apache-2.0.** The strongest candidate among the open licences, because its explicit patent grant
and its defensive-termination clause are a good fit for patent-adjacent work. Rejected as
**premature**, not as wrong: applying it now means public disclosure and an irrevocable grant of the
very rights the filing exists to secure. Apache-2.0 remains the most likely destination if and when
the filing completes.

**MIT or BSD.** Rejected for the same disclosure reason, and additionally because neither says
anything about patents — which in a project whose central artefact is a patent application leaves
the most important question unanswered.

**A source-available licence** (BUSL, PolyForm, Elastic). Rejected. These solve a commercial
problem — preventing a competitor from operating your software as a service — and this project's
problem is disclosure. Source-available still means the source is available, and availability is the
thing that must not happen yet.

**Dual licensing.** Rejected as premature for the same reason, and it presupposes a commercial
strategy that does not exist.

**No licence file at all.** Rejected. Absence of a licence technically means all rights reserved by
default, but it communicates carelessness rather than intent, and it leaves a recipient with no
statement of what they may not do. An explicit licence with a patent notice is a document a
recipient has read.

**Publish now, file later under a grace period.** Rejected. It depends on which jurisdictions apply
and on a timeline nobody controls, and getting it wrong is unrecoverable. The upside — earlier
visibility — is not worth an irreversible risk to the project's central asset.

## Consequences

### Positive

- Patentability is preserved. The option to file remains open, which is the entire point.
- The optionality runs one way and the right way: relicensing to Apache-2.0 later costs a commit;
  un-publishing costs the patent.
- The `LICENSE` and `NOTICE` files make the constraint explicit to every recipient, so a
  collaborator does not have to infer it.
- The PyPI classifier and the pre-commit hook make accidental disclosure and accidental credential
  leakage harder in the two most likely ways they would happen.
- The Demo Plan's filing gate is honoured rather than improvised at the moment someone asks for a
  demo.

### Negative / accepted trade-offs

- **No external contributions, no external review.** A safety-critical architecture benefits
  enormously from outside eyes, and this decision closes that door for the duration. It is a genuine
  loss and not a small one.
- **The academic cost is real.** The implementation cannot be cited, linked, or reproduced by a
  reviewer of the paper. "Available on request under NDA" is materially weaker than a repository
  URL, and some venues treat artefact availability as a review criterion.
- **Demonstrations require NDAs**, which is friction at exactly the moments — a guide review, an
  industry conversation, a competition — where the project most wants to show what it built.
- **The constraint has no defined end date.** A-7 is resolved by a person, not a commit, and there
  is no mechanism in the repository that will notice if the filing question goes unanswered for a
  year. The likeliest failure mode of this decision is not disclosure; it is drift — the repository
  staying private long past the point where it needed to.
- **The guards are partial.** The PyPI classifier and `detect-private-key` protect against two
  specific accidents. Nothing prevents someone pushing to a public remote, pasting source into a
  public issue tracker, or screenshotting a file in a talk.
- **A proprietary licence complicates future dependency choices.** Some libraries this project may
  want in later phases carry copyleft terms that interact badly with a closed distribution, and that
  constraint now has to be checked at each addition.
