# ADR 0016: Skill gap from a person's background

Status: accepted (2026-11-01)

## Context

The plan has a career-switcher feature: a background field ("I was a mechanical engineer") drives a skill-gap section of the report. The `GapItem` contract (skill, have / transferable / missing, reason) already exists. A person's background is private to them, so it must not end up in the shared, published report.

## Decision

- **Skills and shares come from the stored report** (`asked_for`, from collected postings), never from the model: every skill asked for by 20% of postings or more, at most 25, most asked first.
- **The model only judges the match** (`skill-gap.v1`, mid tier, temperature 0): for each skill, `have`, `transferable` or `missing`, plus the exact words from the background that show it.
- **Code keeps a `have` or `transferable` only if those words are really in the background** (same quote matching as the report checks). Otherwise the skill is `missing`. Skills the model skipped are `missing` ("Not assessed"); unknown ids and repeats are ignored. The kept reason ends with the person's own words.
- **Coverage is computed by code**: the share-weighted portion of asked-for skills the person has, a close match counting half.
- The output is labelled as the model's judgement of the person's own words.
- **Nothing is stored yet.** `make skill-gap role="..." background="..."` prints the result. `role_reports.user_background` and `user_id` exist for the personal report, but storing a person's text waits for accounts and the screens, and for a retention decision.

## Consequences

- Cost is one call, a few cents. The background text goes to the model provider (Claude), as the report's own writing does for public data; the screens must say so before asking for it.
- The check stops invented credit, but not a generous reading: `transferable` is a judgement. The reason must say what carries over and what is new, and the wording is tagged as judgement.
- The gap is only as good as the skills list, which rests on the postings sample (15 for GenAI Engineer so far).
