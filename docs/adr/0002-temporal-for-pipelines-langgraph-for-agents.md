# 0002. Temporal runs the pipelines; LangGraph runs the colleagues

- Status: accepted
- Date: 2026-10-30

## Context

Two very different kinds of work happen in FirstWeek:

1. **Long, multi-step pipelines**: researching a role (collect, clean, extract, verify, score), building and validating a blueprint, evaluating a submission. These take minutes, call flaky external APIs, and must survive crashes and retries without redoing paid work.
2. **Live conversation**: colleague agents (Tech Lead, PM, Teammate) reacting to the user, pausing while the user works, and resuming later.

## Decision

- **Temporal** owns the macro workflow: each pipeline is a Temporal workflow and each stage an activity, with retry policies and a visible run history.
- **LangGraph** owns the micro behaviour inside a simulation: a router plus agent subgraphs, checkpointed in Postgres so a simulation resumes exactly where the user left off.
- Neither does the other's job: agents do not run pipelines, and Temporal does not hold conversation state.

## Consequences

- A failed research stage retries only that stage, so paid LLM calls are not repeated.
- Temporal adds one service to run, which Docker Compose handles (`temporal server start-dev`).
- The boundary is easy to explain in interviews, and is the most common mistake in agent systems to get wrong.

## Alternatives considered

- Celery: retries exist but no durable workflow history or resumable multi-step state.
- LangGraph for everything: possible, but long pipelines would hold expensive state in agent checkpoints and lose Temporal's run visibility.
