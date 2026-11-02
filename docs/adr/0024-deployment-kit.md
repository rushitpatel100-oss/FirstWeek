# ADR 0024: Deployment kit for the practice project

Date: 2026-11-02. Status: accepted.

## Context

The practice project (ADR 0021, 0023) works on Rushit's machine. Putting it online raises three
problems the local setup hides: the API cannot reach a Docker engine, a hosted disk is wiped on
restart, and the API sees every visitor as the web server.

## Decision

- Hosted code runs use the existing E2B backend (`SANDBOX_BACKEND=e2b`, ADR 0017).
- `infra/docker/api-start.sh` migrates, runs `ensure-demo` (seed once, or restore the files when the
  database has the project but the disk does not) and serves. `SEED_DEMO_ROLE` turns seeding on.
- The web app forwards the visitor's address in `X-Forwarded-For`, and the API believes it only when
  the request also carries `X-Internal-Key` equal to `INTERNAL_API_KEY`. Without the key it uses the
  real peer address, so a caller cannot choose its own address to dodge a limit.
- No host is chosen here. `docs/deploy.md` lists what any host must offer (Docker, Postgres with
  pgvector) and the settings to give it.

## Consequences

- Rate limits stay in memory: run one API instance. A shared store (Redis) is the step after that.
- Nothing is deployed until Rushit creates the accounts and keys listed in `docs/deploy.md`.
