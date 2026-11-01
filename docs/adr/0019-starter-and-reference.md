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

## Addendum: size (2026-11-01)

The first real run failed: the starter reply was cut off at the 32,000-token ceiling (thinking counts towards it), after a first try at 16,000 that was paid for and thrown away. Fixes: `build-starter.v2` asks for a small repository (about 700 lines in all) and the schema limits it (14 starter files, 6 key files, 12,000 characters each); the first try now uses the ceiling directly, so a long answer is paid for once.
