# FirstWeek

**Live your first week in a new AI role.** Type any job title, such as GenAI Engineer or Agentic AI Engineer, and FirstWeek shows what the job really involves, backed by evidence from real job postings and practitioner sources. Then you do the job: a five-day simulated project with tickets, a codebase, and AI colleagues (a Tech Lead who reviews your pull requests, a PM who changes priorities mid-week) who react to your work. You leave with a portfolio repo and a skill matrix where every score links to evidence.

> Status: **M1 Research pipeline, part 2.** Postings are collected, classified against role definitions, and mined for skills with quote-verified extraction, giving skill shares with 95% intervals. See the [roadmap](#roadmap).

## Try it (free demo)

[45-second walkthrough video](docs/img/firstweek-demo.mp4) · [live demo](https://rushitpatel100-oss.github.io/FirstWeek/)

The [demo page](apps/demo) is a static site: a week at a made-up insurer, with a team chat, tickets
arriving day by day, and a real Python project you edit and test. The tests run for real in your
browser (pytest through Pyodide). Colleague replies, the code review and the end-of-week verdict
are recorded samples; the full app answers with a live model. See [ADR 0025](docs/adr/0025-static-portfolio-demo.md).
Run it locally: `cd apps/demo && pnpm install && pnpm dev`.

![The demo page](docs/img/demo.png)

## Why

New AI roles are hard to understand from the outside. Career switchers can learn the tools, but cannot see what the work looks like day to day, so their projects often miss what employers need. FirstWeek makes these roles visible, then lets people try them.

## How it works

| Layer | What you get |
| --- | --- |
| **Discover** | A Role Reality Report: responsibilities, tools, a typical week and pain points. Every claim cites sources and carries a confidence level. |
| **Experience** | A simulated project over five days, with tickets, a sandbox that runs real code, and AI colleagues. |
| **Prove** | An evaluation with deterministic checks plus an independent AI judge, a skill matrix, a GitHub repo of your work, and CV bullets drawn only from verified results. |

Accuracy comes from evidence, not model memory: job postings are de-duplicated and counted, every report sentence is checked against the passages it cites, and three "golden" roles are reviewed by people. Any other role is researched on demand and clearly labelled as not yet reviewed.

## Architecture

```
Web app (Next.js) ──► API (FastAPI)
                          │
         ┌────────────────┼─────────────────┐
         ▼                ▼                 ▼
 Temporal workflows   Sandbox runner   LangGraph agents
 (research, blueprint, (E2B; Docker     (router, Tech Lead,
  evaluation)           for dev)         PM, Teammate)
         │                │                 │
         └──────► Postgres + pgvector, Redis, object storage
         │
         └──────► LLM gateway (LiteLLM + Langfuse) ──► Claude, OpenAI judge
```

Key decisions are recorded in [docs/adr](docs/adr).

## Run it locally

You need Docker, [uv](https://docs.astral.sh/uv/), Node.js 22 and pnpm. On Windows, use WSL2.

```bash
make setup        # installs Python and web dependencies, creates .env
make up           # starts Postgres, Redis, Temporal, migrations, API, worker and web
```

Then open:

- Web app: http://localhost:3000 (shows live status of every service)
- API docs: http://localhost:8000/docs
- Temporal UI: http://localhost:8233

Collect real UK job postings for a role (company job boards need no key; add Adzuna and Firecrawl keys to `.env` for the other sources):

```bash
make resolve title="Senior LLM Engineer"   # which known role does a title map to?
make collect role="GenAI Engineer"         # fetch, clean, de-duplicate and store
make research role="GenAI Engineer"        # collect, classify, extract, then skill statistics
make review-skills                         # extracted labels the taxonomy does not know yet
```

`make research` needs `ANTHROPIC_API_KEY`. Re-runs only pay for new postings.

Check the whole path works (API → Temporal → worker → database):

```bash
make smoke
```

With `ANTHROPIC_API_KEY` (and optionally Langfuse keys) in `.env`, make one real, traced model call:

```bash
make smoke-llm
```

## Develop

```bash
make check        # lint, strict type checks and tests: the same as CI
                  # database tests use a separate <name>_test database, never your data
make migration m="describe the change"   # after editing database models
make migrate
```

| Path | What lives there |
| --- | --- |
| `packages/core` | Typed contracts, database models and migrations, the LLM gateway |
| `services/research` | Role definitions, collectors, cleaning, de-duplication, classification, extraction, statistics; prompts in `firstweek_research/prompts` |
| `apps/api` | FastAPI service |
| `services/worker` | Temporal worker and workflows |
| `apps/web` | Next.js frontend |
| `docs/adr` | Architecture decision records |
| `prompts`, `evals` | Versioned prompts and evaluation datasets (from M1) |

## Roadmap

| Milestone | Outcome |
| --- | --- |
| M0 Foundations ✅ | Monorepo, local stack, contracts, data model, LLM gateway, CI |
| **M1 Research pipeline** | Postings and sources collected, cleaned, extracted and counted (collection, extraction and statistics done; workflow next) |
| M2 Role Reality Report | Evidence-backed reports with verified claims |
| M3 Blueprints and sandbox | Generated projects that pass a validation gate |
| M4 Workspace and Tech Lead | Real code review in the browser |
| M5 Full simulation | Five playable days with PM and Teammate |
| M6 Evaluation and portfolio | Skill matrix, GitHub export, CV bullets |
| M7 Deploy and write-up | Public demo on AWS, eval report |

## License

[MIT](LICENSE) © 2026 Rushit Patel
