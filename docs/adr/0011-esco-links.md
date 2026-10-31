# 0011. Link the skills taxonomy to ESCO only where a true equivalent exists

- Status: accepted
- Date: 2026-10-31

## Context

The build plan asks for the 117-entry AI skills taxonomy to be linked to ESCO, the EU's public classification of skills, competences and occupations (v1.2.0). Links let FirstWeek's skill names line up with an official reference, and they make clear which entries are FirstWeek's own additions. The schema already had `taxonomy_skills.esco_uri` and `origin` ('esco' or 'ai_extension'), but nothing filled them.

ESCO's search is fuzzy. Searching "RAG" returns "clean ink rollers", "Rust" returns rust-proofing car bodies, and "machine learning" ranks "data mining" first.

## Decision

- **Never link automatically.** `make esco-suggest` searches ESCO for each entry's label and first aliases, and puts candidates with the same name first. A person picks, and the chosen URI goes into `ai_skills.yaml` as `esco_uri`, where it is reviewed like any other change.
- **Link only true equivalents, never a broader or neighbouring concept.** For example, ESCO's "communicate with stakeholders" is about suppliers and shareholders, so it isn't linked to our "Stakeholder communication", which is about product and engineering colleagues. "Speech recognition" isn't linked to "Speech and audio ML", which is broader.
- **18 of 117 entries are linked (2026-10-31):** machine learning, deep learning, NLP, computer vision, recommender systems, statistics, data analysis, system design, data engineering, mentoring, Python, TypeScript, JavaScript, Java, C++, Scala, SQL and PostgreSQL.
- **The other 99 form FirstWeek's AI extension** (`origin = 'ai_extension'`). ESCO has no concepts yet for RAG, prompt engineering, LLM evaluation, agents, MLOps or most AI tooling (LangChain, vLLM, Kubernetes, AWS).
- Each link is unique: two entries can't point at the same ESCO skill (checked on load), and seeding sets `origin` from the link.

## Consequences

- Reports can say which skills are recognised in an official framework and which are new AI practice, itself a useful signal for career switchers.
- ESCO releases change over time. The links name v1.2.0, and `make esco-suggest --all` re-checks every entry against a newer release.
- New taxonomy entries start unlinked. Running `make esco-suggest` is part of adding them.
