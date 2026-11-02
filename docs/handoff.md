# Handoff: where FirstWeek stands

Start a new conversation with: **"Continue FirstWeek: read `docs/handoff.md`."** This page, `CLAUDE.md`, the ADRs, the learning log and the plan doc hold everything a new conversation needs. Update this page at the end of every step.

Last updated: 2026-11-01 (M3 autopilot and gate).

## Where we are

- **M0 and M1 are done** (PRs #1 to #10): monorepo, contracts, LLM gateway, local stack and CI; job collection from 80 boards and Adzuna, role classification, quote-verified extraction, skills taxonomy (ESCO-linked), statistics, the daily Temporal run, and hand-labelled evaluations for the classifier and the extraction.
- **M2 is under way:**
  - Evidence passages with free local embeddings and hybrid search: #11 to #13, ADR 0012.
  - The report writer: #14, ADR 0013. The first real GenAI Engineer draft (statistics version 9, $0.44) was reviewed and the fixes merged in #15 (ADR 0013 addendum).
  - The claim verifier and confidence scores, with verified reports stored: ADR 0014, merged as #17. Free Gemini judge, merged with it.
  - Report evidence fixes: #18 (ADR 0013 addendum): number and wording checks, writer prompt v3, forum-only searches per role, judge preflight.

## Next step: run autopilot, then M4

M3 gate and autopilot: `make autopilot role=...` (ADR 0020), free tier, retries, auto-approves; cloud workflow `Autopilot`. M3 step 3 builds the starter repo, data and reference solution (ADR 0019, `make artifacts role=...`, measured metrics, no retries yet). M3 step 2 is the blueprint generator (ADR 0018, `services/simulation`, `make blueprint role=...`, drafts only). M3 step 1 is the code sandbox (ADR 0017, `firstweek_core.sandbox`): Docker for development, E2B for demos. Real isolation is checked with `make sandbox-image && make sandbox-smoke` on Rushit's machine. Next: a dataset/starter repo with planted issues and a reference solution, the validation gate that runs it in the sandbox, and per-user seeds.

The report screen has the skill-gap form ("How do you compare?", `POST /roles/{slug}/skill-gap`, ADR 0016 addendum): rate limited, nothing stored. Left in M2: the progress screen (needs the simulation to exist, so it moves to M3), practitioner interviews, and Rushit's review and publish of the first reports. Then M3: the simulation (blueprint, tickets, AI colleagues). Read the plan doc's M3 checklist before starting.

Known gaps: the stored report does not keep each section's "not covered" notes; a missing role renders Next's 404 content with status 200; the rate limits are in memory (one API process); the form clears after submitting (React resets it), the result stays.

Small follow-ups: record pages' publication dates when collecting (undated pages count as old); settle whether interviews may be cited or only validate; link summary claims to the claims they restate so rejecting one removes the other; the label question for GitLab's "Senior Backend Engineer, AI Engineering: Chat"; storing a personal report once accounts exist.

## Waiting on Rushit

- Run `make review-report role="GenAI Engineer"`, then `make spot-check n=20` a few times; `make report` for the other two roles gives enough claims for 50 checks.
- Book 3 to 5 practitioner interviews. They fill "day to day" and bring back "A typical week".
- Check that `make search` now shows `[forum]` hits after the new collection. Forum pages from Hacker News may scrape as table noise; if so, the chunker needs a filter.

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
