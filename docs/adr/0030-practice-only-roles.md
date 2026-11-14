# 0030: Show roles that have a practice project but no published report

Status: accepted, 2026-11-14

## Context
The seven roles added in ADR 0029 each have a hand-written practice project, but a Role Reality
Report needs a research run, a verifier and a human review before it is published (ADR 0015).
`GET /roles` listed only roles with a published report, so those projects were unreachable.

## Decision
`GET /roles` lists roles with a published report first, then roles with an approved project and
no published report. The second group has `has_report: false` and no country, sample size or
date. The home page shows them with only "Start your first week" and says the report is not
published yet. `GET /roles/{slug}/report` still returns 404 for them: no report is invented.

## Consequences
- `RoleSummary.country`, `sample_size` and `published_at` are now nullable; the web type changed.
- A role appears once `make research` has created it and `make seed-demo` has approved a project.
- Not checked on the machine that wrote it: the web change (no node_modules) and the database
  test (no Docker). CI runs the database test.
