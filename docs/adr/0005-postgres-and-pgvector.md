# 0005. Postgres with pgvector is the single datastore

- Status: accepted
- Date: 2026-10-30

## Context

FirstWeek stores relational data (roles, sources, simulations, tickets), JSON documents (reports, blueprints, project state), embeddings for evidence retrieval, and LangGraph checkpoints.

## Decision

- One Postgres database holds all of it, with the pgvector extension for embeddings (1536 dimensions, HNSW index with cosine distance).
- Schema changes go through SQLAlchemy models and Alembic migrations only. CI applies every migration, checks the models match the schema, downgrades to empty and upgrades again.
- Research data is shared and versioned; simulation data belongs to one user. Every report claim links to passages, and every passage to its source.

## Consequences

- One system to back up, migrate and reason about.
- Joins between claims, passages and sources are plain SQL, which keeps traceability simple.

## Alternatives considered

- A separate vector database (Pinecone, Qdrant): another service and another consistency problem, with no benefit at this data size.
