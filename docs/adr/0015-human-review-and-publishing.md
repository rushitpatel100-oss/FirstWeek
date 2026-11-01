# ADR 0015: Human review, spot-check and publishing

Status: accepted (2026-11-01)

## Context

A verified report is still a model's work checked by another model. The plan asks for a person to accept it and to spot-check 50 verified claims by hand before anything is published. The Home and report screens are not built yet.

## Decision

A terminal tool first; the screens will read the same stored data.

- `make review-report role="..."` shows each undecided claim of the latest stored report with its confidence, the verifier's verdict and the quotes it cites. The reviewer accepts, rejects (with a one-line reason) or skips. Decisions are saved at once, so the review can stop and resume. Editing a claim's text is deliberately not offered: an edited sentence would no longer be the one the quotes and the verifier were checked against. Reject it and let the next run write it better.
- `make spot-check [n=10]` draws random claims nobody has spot-checked, across all stored reports, hides the verifier's verdict, and asks one question: do the quotes back the whole claim? The answer is stored as `ok` or `wrong`, apart from the accept/reject decision.
- `make publish-report role="..."` publishes the latest report only when every claim has a decision, at least one is accepted, 50 claims have been spot-checked, and no more than 10% of those were judged wrong. Rejected claims are removed from the stored report and listed in its provenance with stage `review` and the reviewer's reason. A published report is frozen.

Status moves `draft` -> `reviewed` (every claim decided) -> `published`. The gate and the 10% limit live in `review.py` as named constants.

## Consequences

- The 50 checks are counted across reports, not per report: they measure the verifier, not one document. A new verifier model or prompt should start a new count (`UPDATE report_claims SET spot_check = NULL` for now; a versioned count comes with the screens).
- The summary restates findings from the other sections. Rejecting a claim does not remove a summary line built on it; reject that line too. A later step can link them.
- Low-confidence claims can be accepted. Whether the product hides or flags them is a screen decision, not a publishing one.
- The 10% limit is a first guess and is Rushit's to change.

## Also in this change

- `synthesise-section.v4`: vendors, training providers and career-guide sites are named as the source, never called practitioners; a number must be in a quote, with the sentence that holds it cited when it sits apart from the point.
