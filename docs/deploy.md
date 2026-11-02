# Deploying FirstWeek

A guide for putting the practice project (the virtual internship) online. Nothing here is done for
you until you have the accounts listed under "What you need". Rushit does those steps; Claude
prepared the code and the start scripts (ADR 0024).

## Shape of it

```
visitor -> web app (Next.js) -> API (FastAPI) -> Postgres (with pgvector)
                                      |-> code runner (E2B)
                                      |-> models (Gemini, Groq; Claude if you switch tiers)
```

- The web app calls the API from the server, never from the browser, so no CORS setup is needed.
- The API runs the learner's tests in **E2B** (a hosted sandbox). Docker is for your machine only;
  a hosted API cannot reach a Docker engine.
- Postgres must offer the **pgvector** extension: the first migration runs `CREATE EXTENSION
  vector`. Check that your host supports it before choosing one.

## What you need

1. **A host for the API** that runs a Docker image (any host that does; the image is built from
   `infra/docker/python.Dockerfile` with `PACKAGE=firstweek-api`) and a **Postgres with pgvector**.
2. **A host for the web app**: a Node host or the image in `apps/web/Dockerfile`.
3. **An E2B key** (https://e2b.dev) for running learners' tests.
4. **The model keys** you already use: `GEMINI_API_KEY` and `GROQ_API_KEY`. Turn on billing for the
   Gemini key before a public launch (see ADR 0020).
5. A long random value for `INTERNAL_API_KEY` (for example `openssl rand -hex 32`).

## API settings

Start command: `sh /app/api-start.sh` (it migrates the database, seeds the demo and serves on
`$PORT`, default 8000). Health check: `GET /health`.

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://user:password@host:5432/dbname` |
| `SANDBOX_BACKEND` | `e2b` |
| `E2B_API_KEY` | your E2B key |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | model keys |
| `SIMULATION_TIER` | `judge` (free chain) or `mid` with `ANTHROPIC_API_KEY` |
| `INTERNAL_API_KEY` | the shared secret |
| `ARTIFACTS_DIR` | a folder on the container's disk, for example `/app/var/artifacts` |
| `SEED_DEMO_ROLE` | `GenAI Engineer` (seeds the Northwind demo; skipped when unset) |

The demo's files live on the container's disk, which a restart wipes. The start script restores
them each time from the database, so nothing is lost.

## Web app settings

| Variable | Value |
|---|---|
| `API_URL` | the API's address, for example `https://firstweek-api.example.com` |
| `INTERNAL_API_KEY` | the same secret as the API |

## Getting the data in

The practice page needs the role to exist in the database (`role_archetypes` and
`archetype_versions`); the demo project itself is seeded by the start script. To copy those rows
from your local database (run on your machine, with the local Postgres up):

```
pg_dump --data-only --inserts -t role_archetypes -t archetype_versions \
  "postgresql://firstweek:firstweek@localhost:5432/firstweek" > roles.sql
psql "$PRODUCTION_DATABASE_URL" -f roles.sql
```

Run the API once first so the migrations create the tables. The role list on the home page shows
only **published** reports, which need your review and spot-checks (ADR 0015). Until then the
practice page is reached by its address: `/roles/genai-engineer/practice`.

## Checks after deploying

1. `GET <api>/health` answers `{"status": "ok"}`.
2. `GET <api>/roles/genai-engineer/internship` returns the colleagues and events.
3. Open `<web>/roles/genai-engineer/practice`: "Virtual internship", Day 1 and the inbox.
4. Press **Run tests**: the failing output should come from E2B.
5. Send a message in chat. Then **Finish the week** on day 5.

## Known limits

- Rate limits are counted in memory, so run **one API instance**. More instances each count alone.
- The week's progress is saved in the visitor's browser only (no accounts).
- Free model tiers run out (about 20 calls per day per Gemini model). Turn on billing on the Gemini
  key for anything public.
- `make seed-demo` stays the way to refresh the demo by hand; the start script only restores it.
