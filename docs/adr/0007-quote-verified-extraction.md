# 0007. Classify per role, extract once, and keep only quote-verified items

- Status: accepted
- Date: 2026-10-31

## Context

Skill statistics are only as good as what the model extracts from each posting. Models can invent plausible requirements ("Kubernetes") that a posting never mentions, and the same posting is relevant to several roles. Cost matters too: re-running research should not pay for the same work twice.

## Decision

1. **Two separate model steps, each validated against a contract.**
   - *Classify* (`RoleMatch`, small model): is this posting the role, judged against the role's definition? Role-specific, stored in `posting_role_matches`.
   - *Extract* (`PostingExtraction`, mid model): skills, tools, responsibilities and seniority. Role-independent, so each posting is extracted once and reused by every role.
2. **Every item needs a verbatim quote.** After extraction, each item's quote is searched for in the posting text. Matching forgives only typography, whitespace and case, never wording. Items whose quote is not found are dropped and counted in `extraction_runs.items_dropped`; that count is our measured fabrication rate.
3. **Taxonomy-first labels.** The extractor sees the taxonomy's labels and is asked to reuse them. A label then maps to a skill by exact name or alias, or by a near-identical spelling (similarity ≥ 92, names of 5+ characters only). Anything else stays unmapped in a review queue (`make review-skills`), never forced onto the nearest skill. The taxonomy also corrects skill versus tool ("Python" listed as a skill becomes a tool).
4. **Caching by version.** A posting is never re-classified for the same role and classifier version, or re-extracted for the same extractor version. Prompts are versioned files (`classify-role.v1.md`, `extract-posting.v1.md`); changing a prompt means a new version, which re-runs only that step.
5. **A strict sample for statistics:** postings in the country, not duplicates, full text (never Adzuna snippets), judged to be the role with confidence ≥ 0.5, and extracted with the current extractor. Each share carries a 95% Wilson interval, which stays honest for small samples (2 of 2 postings is 100%, but the interval runs from 34% to 100%).

## Consequences

- Re-running research costs nothing for postings already processed; on 2026-10-31 data, a first run for all three golden roles is estimated at under $2.10.
- Quote verification cannot catch an item whose quote is real but whose label misreads it. The labelled evaluation set (100 postings checked by a person) measures that.
- Duplicate copies of one job keep a stable canonical copy (ties broken by id), so cached work stays valid across runs.

## Alternatives considered

- **One combined call per posting and role:** simpler, but pays for extraction once per role and mixes two judgements in one prompt.
- **Trusting extracted items without quotes:** cheaper to build, but fabricated skills would flow straight into the statistics.
- **Free-text labels clustered afterwards:** flexible, but harder to explain and to check than a reviewed taxonomy with a queue for new terms.
