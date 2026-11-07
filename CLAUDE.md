# FirstWeek: notes for Claude

FirstWeek turns any job title into an evidence-backed Role Reality Report and a five-day simulated project with AI colleagues. Portfolio project, built to production standards. The full build plan lives in the "AI Job Simulator: Portfolio Build Plan" doc. In a new conversation, read `docs/handoff.md` first: where the project stands and what comes next.

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
- `make report role="..."` writes a Role Reality Report from the latest statistics and the evidence (ADR 0013), has a model from another family check every claim and scores its confidence (ADR 0014), then stores it in `role_reports`. Numbers come from code, prose from Opus over checked citations. The markdown goes to `reports/` (git-ignored); `verify=no` gives a draft only. The verifier is a free Gemini model: needs `GEMINI_API_KEY` (free, https://aistudio.google.com/apikey).
- `make review-report role="..."` (accept or reject each claim), `make spot-check [n=10]` (check the verifier by hand, verdict hidden) and `make publish-report role="..."` (needs every claim decided, 50 spot-checks, at most 10% wrong; ADR 0015). Rejected claims leave the stored report; a published report is frozen.
- `make seed-reports` stores the researched report of each golden role as published, no key and no model call (ADR 0027). The files are `firstweek_research/data/static_reports/<slug>.{sample,report}.json`: skill shares are recounted from the sample by code, every quote is exact. `make check-reports` fetches every source again and confirms each quote is still there.
- `make skill-gap role="..." background="..."` compares a person's background with the stored report's skills (ADR 0016). Nothing is stored; the background is private.
- `make sandbox-image` builds the code sandbox image (Python 3.12 with pytest, numpy, pandas and requests; `make autopilot` and `make artifacts` build it first); `make sandbox-smoke` runs real jobs against the backend in `SANDBOX_BACKEND` (`docker` or `e2b`, needs `E2B_API_KEY`; ADR 0017). Code from people or models runs only through `firstweek_core.sandbox`, never `subprocess`.
- `make blueprint role="..."` designs a draft project blueprint (scenario, tickets, rubric) from the stored report and saves it unvalidated (ADR 0018). The answer key never goes to colleague agents: use `public_view()`.
- `make artifacts role="..."` builds the starter repo, data and reference solution for the latest draft blueprint, runs them in the sandbox and records the measured metrics (ADR 0019; needs `make sandbox-image`). Output goes to `var/artifacts/` (git-ignored).
- To use the practice project locally run Postgres in Docker (`docker compose up -d postgres`) and the API and web on the host (`make api`, `make web`): the API container in `make up` can reach neither the sandbox's Docker nor `var/artifacts`.
- `make seed-demo role="..."` stores a hand-written practice project (Agentic AI Engineer and AI Software Engineer have their own, ADR 0026; other roles get the GenAI one) (no model call, ADR 0022) so the workspace works at once; the newest approved project wins. It also writes a hand-made five-day internship (`internship.json`) beside the project (ADR 0023).
- `make autopilot role="..."` designs, builds and gates a project unattended, retrying failures up to 3 times; it first checks today's free quota covers the worst case (`make autopilot-check role="..."` shows it, no model call) and saves progress to resume if the quota runs out; free by default (`SIMULATION_TIER=judge`, needs `GEMINI_API_KEY`, or set `MODEL_LOCAL=ollama/<model>` for a model on this machine with no daily limit: it writes the files and repairs failing checks, hosted models design and plan) (ADR 0020). `make export-reports` writes `data/reports/*.json` so the manual `Autopilot` workflow can run it in the cloud from the `--report-file`.
- The API serves the approved project (`GET /roles/{slug}/project`), runs a learner's tests in the sandbox (`POST .../project/tests`) and returns a Tech Lead review (`POST .../project/review`) (ADR 0021). Learners never receive the answer key. The virtual internship adds `GET /roles/{slug}/internship` (colleagues and the week's events, no personas), `POST .../internship/chat` (a colleague answers in character) and `POST .../internship/verdict` (the supervisor's end-of-week review) (ADR 0023).
- `make eval-classifier` and `make eval-extraction` score stored decisions and extractions against the hand labels in `data/eval/` (ADR 0009). Run them before and after any change to a role definition, a prompt or the taxonomy.

## Layout

- `packages/core`: contracts, models, migrations, LLM gateway (strict mypy)
- `apps/api`: FastAPI
- `services/research`: role definitions (`data/roles/*.yaml`), taxonomy (`data/taxonomy/ai_skills.yaml`), collectors, cleaning, dedup, classification, quote-verified extraction, stats. Prompts are versioned files in `firstweek_research/prompts/`: never edit a released version, add `.v2`.
- `services/simulation`: task-type library, blueprint design (later: dataset, starter repo, validation gate). Prompts are versioned files in `firstweek_simulation/prompts/`.
- `services/worker`: Temporal worker; workflows in their own modules
- `apps/demo`: free static portfolio demo (Vite + React, Pyodide, recorded replies; ADR 0025). `python scripts/export_demo_data.py` refreshes `src/data.json`; `pnpm build` there; GitHub Pages deploys it.
- `apps/web`: Next.js 16 with Cache Components. Read `apps/web/AGENTS.md` first: its APIs differ from older Next.js.

## Working style

Each milestone step ships as one pull request with tests and a short walkthrough (what, why, decisions needed). Record notable decisions as ADRs in `docs/adr` and one line per session in `docs/learning-log.md`.
