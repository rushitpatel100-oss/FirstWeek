# ADR 0020: Autopilot, the validation gate and the free model tier

Status: accepted (2026-11-02)

## Context

The project needs to be finished quickly and almost free, with as little hand-holding as possible. Up to now each step was run by Rushit on his machine and pasted back, and design and build used the paid mid tier.

## Decision

- **Free by default**: `SIMULATION_TIER` (default `judge`, the free Gemini model) picks the tier that designs and builds projects. `mid` or `frontier` is a one-line change. A weaker free model will get more things wrong, so:
- **The gate decides, and retries**: `run_pipeline` designs a blueprint, builds the project (ADR 0019) and, if any check fails, builds again up to three times with the failures written into the planner's prompt (`plan-starter.v2`). A blueprint is approved only if the starter runs and fails its target tests, the reference solution passes them, and the reference's measured numbers exist. Approval is automatic and labelled so: `validated=true`, `status='approved'` in the database, "APPROVED (automatic)" in the report. Nobody has looked at it; a person can still review it later.
- **One command**: `make autopilot role="..."` (database) or `python -m firstweek_simulation autopilot --report-file data/reports/<slug>.json` (no database). The output folder holds the blueprint with its answer key, the checks of every attempt, the measured metrics and the starter, reference and key files.
- **Cloud run**: `.github/workflows/autopilot.yml` (manual) does the same on a GitHub runner, which has Docker, so the pipeline runs without anyone's terminal. It needs the repository secret `GEMINI_API_KEY` and a report snapshot from `make export-reports`. The result is uploaded as a private workflow artifact.

## Consequences

- Cost is zero on the free tier (rate limits apply; the gateway already retries). Free-tier prompts and replies may be used by the provider to improve its models: only public report text and invented project material go in, never personal data or keys.
- The gate checks that the material runs and that the numbers are measured. It does not check that the tickets are good or the flaws are interesting; that is still a human's call, now after the fact.
- Not yet checked: that every acceptance criterion maps to a check, and that the dataset matches the brief. Those are cheap to add once real runs show which failures actually happen.

## Addendum: the free tier waits out overload

The first real autopilot run died on a Gemini 503 ("high demand") after LiteLLM's two quick retries. Free models are overloaded in bursts, so for tier `judge` only the gateway now tries the models in `model_judge_fallbacks` in turn, and if all are busy waits 20, 40 and 80 seconds between four passes before giving up. Only overload, rate limit and connection errors count (`is_transient`); a bad request fails at once. Paid tiers never fall back or wait: silently swapping a model you pay for would hide cost and quality changes. The result records the model that actually answered.

Second real run: the first call hung 10 minutes (LiteLLM's default timeout is 600s), and `gemini-2.5-flash` answered 404 (retired for new users). Free-tier calls now time out after 120s with LiteLLM's own retries off (the gateway does the retrying), a 404 skips to the next model, and the dead model left the fallback list.

Third real run: the pipeline got through design and one full build attempt, then hit the free tier's hard cap of 20 requests per day per model (`GenerateRequestsPerDayPerProject`). The gateway now recognises a per-day 429, stops asking that model, and fails at once when every free model is spent instead of waiting minutes for a quota that returns tomorrow. Consequence: one autopilot run needs roughly 20 to 30 calls, so the free tier finishes about one run per day at best; paying for the same Gemini flash models (cents per run) is the cheap way past it.
