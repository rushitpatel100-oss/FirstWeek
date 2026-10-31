# FirstWeek: notes for Claude

FirstWeek turns any job title into an evidence-backed Role Reality Report and a five-day simulated project with AI colleagues. Portfolio project, built to production standards. The full build plan lives in the "AI Job Simulator: Portfolio Build Plan" doc.

## Ground rules

- Every model call goes through `firstweek_core.llm.LLMGateway`. Never call a provider SDK directly.
- Every LLM output is validated against a Pydantic contract in `firstweek_core.contracts`.
- Facts about real roles or companies come only from collected evidence, never model memory.
- Schema changes: edit `firstweek_core/db/models.py`, then `make migration m="..."`. Never hand-edit tables.
- Colleague agents never see `AnswerKey`. Use `ProjectBlueprint.public_view()`.
- Secrets live in `.env` (git-ignored). Never commit keys or print them.

## Commands

- `make check`: ruff, strict mypy, pytest (what CI runs)
- `make up` / `make down`: Docker stack
- Database tests run against `<DATABASE_URL name>_test` (root `conftest.py` creates and migrates it). Never point tests at the dev database.
- `make collect role="..."` fills the dev database with real postings.
- `make research role="..."` collects, classifies, extracts and prints statistics; `make review-matches role="..."` shows each classifier decision and its reason.
- The worker runs `DailyResearchWorkflow` on a daily Temporal schedule (ADR 0008); `make research-now` starts it at once.
- `make index-evidence` cuts postings and articles into passages and embeds them with a free local model; `make search q="..." role="..."` runs the hybrid (meaning + keyword) search reports cite from (ADR 0012).
- `make eval-classifier` and `make eval-extraction` score stored decisions and extractions against the hand labels in `data/eval/` (ADR 0009). Run them before and after any change to a role definition, a prompt or the taxonomy.

## Layout

- `packages/core`: contracts, models, migrations, LLM gateway (strict mypy)
- `apps/api`: FastAPI
- `services/research`: role definitions (`data/roles/*.yaml`), taxonomy (`data/taxonomy/ai_skills.yaml`), collectors, cleaning, dedup, classification, quote-verified extraction, stats. Prompts are versioned files in `firstweek_research/prompts/`: never edit a released version, add `.v2`.
- `services/worker`: Temporal worker; workflows in their own modules
- `apps/web`: Next.js 16 with Cache Components. Read `apps/web/AGENTS.md` first: its APIs differ from older Next.js.

## Working style

Each milestone step ships as one pull request with tests and a short walkthrough (what, why, decisions needed). Record notable decisions as ADRs in `docs/adr` and one line per session in `docs/learning-log.md`.
