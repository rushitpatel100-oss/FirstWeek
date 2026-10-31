# Handoff: where FirstWeek stands

Start a new conversation with: **"Continue FirstWeek: read `docs/handoff.md`."** This page, `CLAUDE.md`, the ADRs, the learning log and the plan doc hold everything a new conversation needs. Update this page at the end of every step.

Last updated: 2026-10-31.

## Where we are

- **M0 and M1 are done** (PRs #1 to #10): monorepo, contracts, LLM gateway, local stack and CI; job collection from 80 boards and Adzuna, role classification, quote-verified extraction, skills taxonomy (ESCO-linked), statistics, the daily Temporal run, and hand-labelled evaluations for the classifier and the extraction.
- **M2 is under way:**
  - Evidence passages with free local embeddings and hybrid search: #11 to #13, ADR 0012.
  - The report writer: #14, ADR 0013. The first real GenAI Engineer draft (statistics version 9, $0.44) was reviewed and the fixes merged in #15 (ADR 0013 addendum).
- **Nothing is open.** `main` is green.

## Next step: the claim verifier and confidence scoring

From the plan doc's M2 checklist:

- A model from another family (the gateway's `judge` tier) labels every draft claim **supported**, **partial** or **unsupported** against the passages it cites.
- Each claim gets a confidence score from source-tier weights (capped at 3 strong sources) × recency × agreement. High is 0.75 or more; Medium is 0.5 to 0.75. Read the plan doc for the exact weights before building.
- Verified reports are then stored in `role_reports` and `report_claims`. Nothing is stored until this step exists.

After that, the rest of M2: the skill-gap section driven by background, the admin review and publish flow, the Home, progress and report screens, and the practitioner interviews.

## Waiting on Rushit

- Run `make index-evidence` (removes the newly excluded sites' passages), then `make report role="GenAI Engineer"`, and send the draft from `reports/genai-engineer.md`.
- Book 3 to 5 practitioner interviews. They fill "day to day" and bring back "A typical week".
- Open question: the first draft cited no forum posts at all. Worth checking whether any forum pages are collected and indexed.

## How we work

- Claude builds, Rushit reviews. Each step is one PR with tests and a walkthrough: What, Why, Decisions needed, Try it. Calls Claude makes on its own are flagged as such.
- Rushit runs things on his machine (WSL2 Ubuntu, Docker Desktop, `~/code/firstweek`) and replies "next", "go", "agree" or pastes output.
- After each step: an ADR if the decision is notable, one line in `docs/learning-log.md`, the plan doc checklist, and this page.
- To make usage limits last: one new conversation per step, Sonnet by default, Opus only for design-heavy steps.

## Links

- Plan doc: https://claude.ai/artifact/FAq86BNqUZTYUSLBUwfuhK (M2 checklist list `mbtr61qmkxy.27120`; status paragraph `mbtr61qmkxy.43393`).
- Repo: https://github.com/rushitpatel100-oss/FirstWeek

## Notes for Claude's workspace

- Attach the repo `rushitpatel100-oss/FirstWeek` and clone it before anything else.
- `gh pr create` fails there (GraphQL is blocked). Open PRs through the REST API:
  `jq -n --arg title "..." --arg head BRANCH --arg base main --rawfile body BODY.md '{title:$title,head:$head,base:$base,body:$body}' | gh api repos/rushitpatel100-oss/FirstWeek/pulls --input -`
- Database tests need Postgres: run `service postgresql start` before `make check`, or about 30 tests are skipped.
- There are no API keys in the workspace, so runs on real data (`make research`, `make report`) happen on Rushit's machine.
