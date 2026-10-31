# Learning log

One line per session: what was built and the one idea worth remembering.

| Date | Milestone | Built | Worth remembering |
| --- | --- | --- | --- |
| 2026-10-30 | M0 | Monorepo, contracts, 23-table schema, LLM gateway, Temporal smoke workflow, CI | Check the budget against the worst case before calling a model; record the real cost after. |
| 2026-10-30 | M0 | Fixed first real-model call: Claude 5.5 and GPT-6 Sol reject a custom temperature | Fakes do not know provider rules; also test through LiteLLM mock mode, which runs the real parameter checks. |
| 2026-10-31 | M1 | Role resolution, job-board/Adzuna/web collectors, cleaning, MinHash dedup; 94 unique UK AI jobs from 21 employers | Check pipelines on real data early: it exposed missed boilerplate headings and tests that could wipe the dev database. |
| 2026-10-31 | M1 | Role classification, quote-verified extraction, 117-entry skills taxonomy, Wilson-interval statistics, `make research` | A tie-break nobody thinks about (which duplicate is canonical) silently re-bills cached work; make every choice deterministic. |
| 2026-10-31 | M1 | First live research run (GenAI Engineer: $0.11, 5 of 63 counted); fixed cut-off classifier replies; `make review-matches` | Claude 5.5 thinks by default and thinking counts towards max_tokens: a tight limit cuts the JSON, not the thinking. Retry cut-offs with more room, never as "fix your JSON". |
