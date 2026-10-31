# Learning log

One line per session: what was built and the one idea worth remembering.

| Date | Milestone | Built | Worth remembering |
| --- | --- | --- | --- |
| 2026-10-30 | M0 | Monorepo, contracts, 23-table schema, LLM gateway, Temporal smoke workflow, CI | Check the budget against the worst case before calling a model; record the real cost after. |
| 2026-10-30 | M0 | Fixed first real-model call: Claude 5.5 and GPT-6 Sol reject a custom temperature | Fakes do not know provider rules; also test through LiteLLM mock mode, which runs the real parameter checks. |
| 2026-10-31 | M1 | Role resolution, job-board/Adzuna/web collectors, cleaning, MinHash dedup; 94 unique UK AI jobs from 21 employers | Check pipelines on real data early: it exposed missed boilerplate headings and tests that could wipe the dev database. |
| 2026-10-31 | M1 | Role classification, quote-verified extraction, 117-entry skills taxonomy, Wilson-interval statistics, `make research` | A tie-break nobody thinks about (which duplicate is canonical) silently re-bills cached work; make every choice deterministic. |
| 2026-10-31 | M1 | First live research run (GenAI Engineer: $0.11, 5 of 63 counted); fixed cut-off classifier replies; `make review-matches` | Claude 5.5 thinks by default and thinking counts towards max_tokens: a tight limit cuts the JSON, not the thinking. Retry cut-offs with more room, never as "fix your JSON". |
| 2026-10-31 | M1 | 80 job boards; GenAI Engineer sample 5 -> 15; progress lines; results saved as they arrive; repeat postings counted once | Read the classifier's reasons, not just its counts: they exposed a double-counted posting and an unclear boundary (customer-facing "Applied AI" roles). |
| 2026-10-31 | M1 | Daily research on Temporal (schedule, heartbeats, per-role isolation), 6-month window on `last_seen_at`, decisions tied to the definition's wording | A cache key must include every input that changes the answer: the role definition was missing, so editing it would have silently reused old decisions. |
| 2026-10-31 | M1 | 112 hand-labelled postings (336 role judgements, 38 unsure), `make eval-classifier` with precision/recall and a stability check | Labels drafted by a model measure agreement, not accuracy, until a person checks them; say which one a score is. "Unsure" labels are the cheapest map of where a definition is vague. |
| 2026-10-31 | M1 | First scores (Agentic 97%, GenAI 97%, AI Software 80% agreement); one broad title filter; role boundaries reworded; labels revised | Instability clusters where definitions are vague: 5 of 8 answer flips were postings already labelled "unsure". Fix the wording, not the model. |
| 2026-10-31 | M1 | Extraction labels (37 postings, 642 taxonomy items, 28 seniority) and `make eval-extraction` against the plan's targets | Score at the level the statistics use (taxonomy entries), and keep "not in the taxonomy" separate: it is a vocabulary gap, not an extraction error. |
