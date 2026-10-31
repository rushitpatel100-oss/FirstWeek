# 0001. One monorepo: a uv workspace for Python, a pnpm app for the web

- Status: accepted
- Date: 2026-10-30

## Context

FirstWeek has several Python services (API, Temporal worker, later research and simulation code) that share contracts and database models, plus a TypeScript frontend. It is built by one person, and reviewers should see the whole system in one place.

## Decision

- One Git repository.
- Python packages live in a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/): `packages/core` holds shared contracts, models and the LLM gateway; `apps/api` and `services/worker` depend on it. One lockfile (`uv.lock`) pins everything.
- The Next.js app in `apps/web` is managed by pnpm with its own lockfile.
- One Docker recipe builds every Python service, selected by a `PACKAGE` build argument.

## Consequences

- A contract change and every caller of it land in the same pull request.
- `uv sync --all-packages` gives a working environment in one step.
- Python and TypeScript tooling stay separate, which keeps each simple.

## Alternatives considered

- Separate repos per service: more ceremony, contracts drift.
- Poetry or pip-tools: slower and no native workspaces.
