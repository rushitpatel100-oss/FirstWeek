# 0010. Where the three AI roles' boundaries sit, and one broad title filter

- Status: accepted
- Date: 2026-10-31

## Context

The first evaluation against hand labels (ADR 0009) gave:

| Role | Agreement | Precision | Recall |
|---|---|---|---|
| Agentic AI Engineer | 97% | 89% | 94% |
| GenAI Engineer | 97% | 100% | 79% |
| AI Software Engineer | 80% | 50% | 50% |

A stability check found 8 of 175 postings changing answer across three runs, 5 of them on postings labelled "unsure". The 24 disagreements and the unstable postings came from four gaps:

1. **Title filters dropped real matches.** 9 disagreements were postings the model never saw. For example, "Senior Software Engineer, GenAI Platform" failed AI Software Engineer's filter because "GenAI" doesn't contain "AI" as a separate word.
2. **AI Software Engineer overlapped the other roles.** The model counted LLM product builders as AI Software Engineers, because the definition didn't say where the line was.
3. **Managers and advisers.** These were sometimes counted, for example an engineering manager and a consultancy's pre-sales principal.
4. **Vendor teams building for clients.** A vendor's public-sector team building custom applications for government clients sat between "vendor customer delivery" (excluded) and "consultancy building" (counted). The answer changed between runs.

## Decision

Rushit agreed all four on 2026-10-31:

1. **One broad AI title filter for every golden role** (`data/title_filters.yaml`, referenced as `title_filter: ai`). Any title mentioning AI, GenAI, LLMs, agents, ML or inference is read by the classifier. The model decides from the posting text; the title only rules out jobs that are clearly unrelated.
2. **AI Software Engineer is general software engineering where AI is a component**: services that call models, platforms for serving and operating models, and the pipelines and product code around them. When the core is model-specific craft (prompts, context, retrieval quality, evaluating model output, agent behaviour), the posting is a GenAI or Agentic AI Engineer instead. Building classical ML models is not this role either.
3. **A shared rule in every definition: hands-on building must be the main job.** People managers, advisory, strategy and pre-sales roles don't count, at consultancies too.
4. **Vendor customer delivery includes building for the customer.** Forward-deployed, applied-AI, solutions and agent-delivery roles at AI vendors are excluded even when they build custom applications or agents for the vendor's customers. They will become a role of their own. Consultancy engineers who build for clients still count.

Also clarified: platforms that agents run on count for Agentic AI Engineer, and reinforcement-learning policies for robots or vehicles do not.

## Consequences

- Candidates per role on 2026-10-31 rise from 76–96 to about 246. The extra classification costs about $0.30 once, then a few cents a day for new postings.
- The definitions changed, so every stored decision is re-made on the next run (ADR 0008's `definition_hash`).
- The labels were revised to match, and "unsure" fell from 38 to 28. The 118 newly caught titles aren't in the labelled set; the next labelling round should sample them.
- The before and after scores, from the same labels, show whether the wording helped. That is the check to repeat for every future definition change.

## Alternatives considered

- **Keep per-role title patterns and add the missed words:** this would keep losing recall to the next unexpected title, for savings of fractions of a penny.
- **Let the roles overlap freely:** fewer disagreements, but AI Software Engineer and GenAI Engineer reports would show nearly the same postings, which tells a career switcher nothing.
- **Classify into exactly one role per posting:** clean, but some jobs genuinely are two roles (for example, building an agent platform is both agentic and software work).

## Result (2026-10-31, after re-classifying every posting)

Same labels, revised to the new wording before the run:

| Role | Agreement | Precision | Recall | Counted postings |
|---|---|---|---|---|
| Agentic AI Engineer | 97% → 100% | 89% → 100% | 94% → 100% | 21 → 18 |
| GenAI Engineer | 97% → 98% | 100% → 100% | 79% → 85% | 17 → 15 |
| AI Software Engineer | 80% → 98% | 50% → 100% | 50% → 89% | 25 → 33 |

Re-classifying cost $0.68 for 243 postings per role. Four disagreements remained. Rushit settled them: two labels were wrong under the agreed boundaries, so they changed to "no", and two are genuinely unsure. They are the first labels a person has confirmed (`checked: [role]`). Extraction scores against its own labels were 86% precision and 87% recall (targets 85% and 75%).
