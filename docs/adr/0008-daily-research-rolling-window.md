# 0008. Collect daily and keep a 6-month window of postings

- Status: accepted
- Date: 2026-10-31

## Context

On a single day, the UK full-text sample for a role is small: 15 GenAI Engineer postings from 80 job boards on 2026-10-31, so each share in the report is uncertain by roughly ±20 percentage points. The employers that use titles such as "GenAI Engineer" most (banks, consultancies, large companies) have no public posting API. The ways to grow the sample were:

1. **Collect daily and keep a rolling window.** Postings stay open for weeks, so daily collection keeps finding new ones, and the window keeps the statistics current. The sample stays UK-only.
2. **Add international postings** for the skills and day-to-day work, keeping pay and demand UK-only.
3. **Read Workday career sites**, which have no official public API, so their terms of use would need a judgement call.

Rushit chose (1) now, with (2) later as a clearly labelled comparison.

## Decision

- **Postings record when they were seen.** `job_postings.first_seen_at` is set once; `last_seen_at` is refreshed by every collection that finds the posting still open.
- **Statistics use a 183-day window on `last_seen_at`.** A posting counts if it was open at any point in the last 6 months, whatever its original publish date. Postings outside the window are not sent to a model at all.
- **A Temporal workflow runs the research.** `DailyResearchWorkflow` runs two activities for each golden role in turn: `collect_role`, then `analyse_role` (classify, extract and compute statistics). One role failing never stops the others. Progress messages are Temporal heartbeats, so a stuck step is detected and retried. Retries are cheap because every paid result is saved as soon as it arrives.
- **A Temporal schedule starts the workflow daily** (07:17 Europe/London by default). Development Temporal runs in memory, so the worker recreates the schedule each time it starts. A laptop is often off at 07:17, so if the last collection is over 20 hours old the worker also starts a run straight away.
- **A spend cap of $1 per role per run** (`RESEARCH_BUDGET_USD_PER_ROLE`). Typical daily cost is a few cents, because only new postings are paid for.
- **Off in CI.** `RESEARCH_DAILY_ENABLED=false` in the full-stack job, so the smoke test never starts a real research run.

## Consequences

- The sample grows only while the stack is running. For now this is Rushit's machine; the same workflow runs unchanged on a hosted worker later.
- A posting that closes stays in the sample until 6 months after it was last seen. Short-lived spikes in demand therefore count for months, which suits "what does this job involve" better than "how many jobs are open today". Live demand still comes from Adzuna counts.
- Collection runs once per role, so job boards are downloaded three times a day. That takes about 10 to 15 seconds per role; sharing one download is an easy optimisation if more roles are added.

## Alternatives considered

- **Only today's postings:** current, but too small to report shares meaningfully.
- **Window on the original publish date:** evergreen postings published in 2024 but still open today would wrongly drop out.
- **A cron job on the host:** simpler, but it gives none of Temporal's retries, heartbeats or run history, and the plan already uses Temporal for pipelines (ADR 0002).
