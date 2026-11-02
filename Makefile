.DEFAULT_GOAL := help
ALEMBIC := uv run alembic -c packages/core/alembic.ini

.PHONY: seed-demo autopilot export-reports artifacts blueprint sandbox-image sandbox-smoke need-role help setup up down logs migrate migration lint format typecheck test check smoke smoke-llm web resolve collect research review-skills esco-suggest review-matches research-now eval-classifier eval-extraction index-evidence search report review-report spot-check publish-report skill-gap

need-role:
	@test -n "$(role)" || (echo 'Add the role, for example: make $(MAKECMDGOALS) role="GenAI Engineer"' && exit 1)

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## First-time setup: Python deps, web deps, .env, git hooks
	uv sync --all-packages
	cd apps/web && pnpm install
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example. Add your API keys.")
	uv run pre-commit install

up: ## Start the whole stack in Docker (web :3000, API :8000, Temporal UI :8233)
	docker compose up --build

down: ## Stop the stack
	docker compose down

logs: ## Follow logs from every service
	docker compose logs -f

migrate: ## Apply database migrations
	$(ALEMBIC) upgrade head

migration: ## Create a migration from model changes: make migration m="add x"
	$(ALEMBIC) revision --autogenerate -m "$(m)"

lint: ## Lint Python and web code
	uv run ruff check .
	uv run ruff format --check .
	cd apps/web && pnpm lint

format: ## Auto-format Python code
	uv run ruff check . --fix
	uv run ruff format .

typecheck: ## Strict type checks for Python and TypeScript
	uv run mypy packages/core/src packages/core/tests apps/api/src services/research/src services/research/tests services/simulation/src services/simulation/tests services/worker/src
	cd apps/web && pnpm exec next typegen && pnpm typecheck

test: ## Run all Python tests (database tests need a migrated Postgres)
	uv run pytest

check: lint typecheck test ## Everything CI runs, locally

smoke: ## End-to-end check: API -> Temporal -> worker -> database
	curl -s -X POST "http://localhost:8000/system/smoke?name=$$(whoami)" && echo

smoke-llm: ## One real, traced model call (needs ANTHROPIC_API_KEY)
	uv run python scripts/smoke_llm.py

web: ## Run the web app with hot reload (API must be running)
	cd apps/web && pnpm dev

resolve: ## Map a job title to a known role: make resolve title="Senior LLM Engineer"
	uv run python -m firstweek_research resolve "$(title)"

collect: need-role ## Collect UK postings and web sources for a role: make collect role="GenAI Engineer"
	uv run python -m firstweek_research collect --role "$(role)"

research: need-role ## Collect, classify, extract and summarise a role: make research role="GenAI Engineer"
	uv run python -m firstweek_research research --role "$(role)"

review-skills: ## List extracted skill labels that the taxonomy does not know yet
	uv run python -m firstweek_research review-skills

esco-suggest: ## Suggest ESCO links for taxonomy entries that have none (a person picks)
	uv run python -m firstweek_research esco-suggest

review-matches: ## Show each posting's classifier decision and reason: make review-matches role="GenAI Engineer"
	uv run python -m firstweek_research review-matches --role "$(role)"

eval-classifier: ## Score the classifier against hand labels; add repeats=2 to measure stability (costs ~$0.06)
	uv run python -m firstweek_research eval-classifier --repeats $(or $(repeats),0)

eval-extraction: ## Score skill, tool and seniority extraction against hand labels (free)
	uv run python -m firstweek_research eval-extraction

research-now: ## Run the daily research workflow for every golden role now (needs make up)
	uv run python -m firstweek_worker.run_research_now

index-evidence: ## Split postings and articles into passages and embed them (free, runs locally)
	uv run python -m firstweek_research index-evidence

search: ## Search the evidence: make search q="how is LLM output evaluated" [role="GenAI Engineer"]
	uv run python -m firstweek_research search "$(q)" $(if $(role),--role "$(role)")

report: need-role ## Write, verify and store a Role Reality Report: make report role="GenAI Engineer" (verify=no for a draft only)
	uv run python -m firstweek_research report --role "$(role)" --out "reports/$$(echo '$(role)' | tr 'A-Z ' 'a-z-').md" $(if $(filter no,$(verify)),--no-verify,)

review-report: need-role ## Accept or reject each claim of the latest report: make review-report role="GenAI Engineer"
	uv run python -m firstweek_research review-report --role "$(role)"

spot-check: ## Check the verifier by hand on random claims: make spot-check [n=10]
	uv run python -m firstweek_research spot-check --count $(or $(n),10)

publish-report: need-role ## Publish the reviewed report (needs every claim decided and 50 spot-checks)
	uv run python -m firstweek_research publish-report --role "$(role)"

skill-gap: need-role ## Compare your background with a role: make skill-gap role="GenAI Engineer" background="I was a mechanical engineer ..."
	uv run python -m firstweek_research skill-gap --role "$(role)" --background "$(background)"

blueprint: need-role ## Design a draft project blueprint (scenario, tickets, rubric): make blueprint role="GenAI Engineer" (costs ~$0.06)
	uv run python -m firstweek_simulation blueprint --role "$(role)"

seed-demo: need-role ## Store the hand-written practice project for a role, no model call: make seed-demo role="GenAI Engineer"
	uv run python -m firstweek_simulation seed-demo --role "$(role)"

autopilot: need-role ## Design, build and gate a project unattended, free by default (needs make sandbox-image and GEMINI_API_KEY)
	uv run python -m firstweek_simulation autopilot --role "$(role)"

export-reports: ## Write each role's newest stored report to data/reports/*.json (for the cloud pipeline)
	@for r in "GenAI Engineer" "Agentic AI Engineer" "AI Software Engineer"; do \
	  f="data/reports/$$(echo $$r | tr 'A-Z ' 'a-z-').json"; \
	  uv run python -m firstweek_simulation export-report --role "$$r" --out "$$f" || true; done

artifacts: need-role ## Build the starter repo, data and reference solution for the latest draft blueprint (needs make sandbox-image; ~$0.20)
	uv run python -m firstweek_simulation artifacts --role "$(role)"

sandbox-image: ## Build the code sandbox image (Docker)
	docker build -f infra/docker/sandbox.Dockerfile -t firstweek-sandbox:py infra/docker

sandbox-smoke: ## Run real jobs in the sandbox: make sandbox-smoke (backend from SANDBOX_BACKEND, default docker)
	uv run python -m firstweek_core.sandbox.smoke
