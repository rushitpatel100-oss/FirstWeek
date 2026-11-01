# ADR 0019: Starter repository, data and reference solution

Status: accepted (2026-11-01)

## Context

A blueprint is words until there is something to work on: a repository with the planted issues in it, data, and a solution that proves the issues are fixable. The rubric's checks quote numbers (a corrected accuracy, a count of lost records). A model must not invent those numbers.

## Decision

- **Two model calls on the mid tier** (`build-starter.v1`, `build-reference.v1`), no escalation: the cost target is a few cents per project. The first writes the starter repository (with target tests), a hidden `key/` side, and the list of files the generator writes. The second writes the reference solution as full replacement files, given the starter.
- **Hidden side**: `key/make_data.py --seed N` writes the datasets, logs and ground truth; `key/metrics.py` writes `metrics.json` for a fixed repository. Both run from the repository root as modules (`python -m key.make_data`), so they can import the repository. Nothing under `key/` ever goes into what the person receives.
- **Seeds**: the shared blueprint uses seed 1. Per-user variation (a later step) is the same generator with another seed.
- **Code runs everything in the sandbox** (ADR 0017, no network): the generator, the starter's tests (must run and fail: pytest exit 1, not a crash and not a pass), the reference's tests (must pass), and the metrics script. Every check is recorded, pass or fail.
- **Measured numbers replace guesses**: `expected_metrics` in the answer key is whatever `metrics.json` reports for the reference solution. Only numbers are accepted.
- **Checks before running**: allowed file types (text and data only), well-formed key side, target tests present, the reference may not touch `key/` or change existing tests.
- **Where it lives**: `var/artifacts/<blueprint id>/{starter,reference,key}` (git-ignored; `ARTIFACTS_DIR`). The answer key's `reference_solution_uri` points at the reference folder. An object store replaces this on deploy.
- `make artifacts role="..."` builds for the latest draft blueprint and prints the checks.

## Consequences

- A failed check does not regenerate. The validation gate (next step) will retry a failed piece up to three times, check that acceptance criteria map to checks, and flag the blueprint for approval. Until then a blueprint stays unvalidated.
- The generator is model-written code that runs in the sandbox; the sandbox limits (time, memory, no network, no secrets) are what make that safe.
- The mid tier may write repositories that fail checks; the check list says exactly why, which is what the gate's retry will feed back.

## Addendum: one file per call (2026-11-01)

Two real runs failed with the starter reply cut off at 32,000 tokens, even after the prompt asked for a small repository and the schema capped file sizes. Claude 5.5 thinks before it answers and thinking counts towards the limit, and a whole repository inside one JSON reply (every quote and newline escaped) is the worst case for it. We could not see where the tokens went, so the design now makes the problem impossible instead of tuning it:

- **Plan, then write each file** (`plan-starter.v1`, `write-file.v1`, `plan-reference.v1`, `write-reference-file.v1`; the earlier all-in-one prompts stay as released, unused). A small structured plan holds shared notes (names, signatures, data formats, which file holds which flaw) and one line per file. Each file is then a separate plain-text call (8,000-token limit) that sees the plan and the files before it.
- A cut-off or empty file is reported by name as a failed check, and nothing runs. A surrounding code fence is stripped. File contents are still validated by the `FileDraft` contract (path, size).
- Cost is about the same output in total plus the plan and the repeated context (small at these prices), spread over roughly 10 to 15 cheap calls; a bad file costs one call instead of the whole answer.
